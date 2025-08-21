# views/playlists_page.py
from __future__ import annotations

import io
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
import streamlit as st

from services.ui_helpers import ms_to_mmss
from services.playlist import (
    list_playlists,
    get_current_playlist,
    set_current_playlist,
    ensure_playlist,
    add_tracks_to_playlist,
    remove_track_at,
)  # :contentReference[oaicite:0]{index=0}
from services.spotify_session_push import push_session_playlist
from services.page_help import show_page_help



# =========================
# Helpers
# =========================

CSV_COLS = ["PlaylistName", "Title", "Artists", "Album", "Duration", "TrackID", "TrackURI", "TrackURL"]
CSV_PATH = Path("playlist.csv")


def _normalize_row(r: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia colunas de CSV para o formato interno usado no buffer de sessão."""
    return {
        "id": r.get("TrackID") or r.get("id") or "",
        "uri": r.get("TrackURI") or r.get("uri") or "",
        "name": r.get("Title") or r.get("name") or "",
        "artists": r.get("Artists") or r.get("artists") or "",
        "album": r.get("Album") or r.get("album") or "",
        "duration_ms": r.get("duration_ms") or 0,
        "external_url": r.get("TrackURL") or r.get("external_url") or "",
    }


def _parse_csv_to_rows(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Aceita ; ou , como separador e devolve rows normalizados."""
    text = file_bytes.decode("utf-8", errors="ignore")
    # tenta ';' primeiro (é o que exportamos), depois ','
    try:
        df = pd.read_csv(io.StringIO(text), sep=";")
        if df.shape[1] == 1:
            raise ValueError
    except Exception:
        df = pd.read_csv(io.StringIO(text), sep=",")
    return [
        _normalize_row(
            {
                "Title": row.get("Title"),
                "Artists": row.get("Artists"),
                "Album": row.get("Album"),
                "Duration": row.get("Duration"),
                "TrackID": row.get("TrackID"),
                "TrackURI": row.get("TrackURI"),
                "TrackURL": row.get("TrackURL"),
            }
        )
        for _, row in df.iterrows()
    ]


def _load_playlists_from_csv(path: Path = CSV_PATH) -> Dict[str, List[Dict[str, Any]]]:
    """Lê playlist.csv → dict[name] = list[rows]. Tolerante a ; ou , e capitalização."""
    if not path.exists():
        return {}
    try:
        # tenta ';' e depois ','
        try:
            df = pd.read_csv(path, sep=";")
            if df.shape[1] == 1:
                raise ValueError
        except Exception:
            df = pd.read_csv(path, sep=",")
        # normalizar nomes de colunas
        cols = {c.lower(): c for c in df.columns}
        req = ["playlistname", "title"]
        if not all(c in cols for c in req):
            return {}
        # garantir restantes
        for c in ["artists", "album", "duration", "trackid", "trackuri", "trackurl"]:
            cols.setdefault(c, c)
        out: Dict[str, List[Dict[str, Any]]] = {}
        for _, r in df.iterrows():
            pl = (r.get(cols["playlistname"]) or "").strip() or "My Playlist"
            row = {
                "Title": r.get(cols["title"]),
                "Artists": r.get(cols["artists"]),
                "Album": r.get(cols["album"]),
                "Duration": r.get(cols["duration"]),
                "TrackID": r.get(cols["trackid"]),
                "TrackURI": r.get(cols["trackuri"]),
                "TrackURL": r.get(cols["trackurl"]),
            }
            out.setdefault(pl, []).append(_normalize_row(row))
        return out
    except Exception:
        return {}


def _get_session_playlists_dict() -> Dict[str, List[Dict[str, Any]]]:
    """Obtém todas as playlists em memória como dict[name] -> rows."""
    names = list_playlists() or []  # :contentReference[oaicite:1]{index=1}
    out: Dict[str, List[Dict[str, Any]]] = {}
    # percorre por nome usando get_current_playlist para não depender de implementação interna
    current_name, _ = get_current_playlist()  # :contentReference[oaicite:2]{index=2}
    for nm in names:
        set_current_playlist(nm)  # move o ponteiro; seguro porque é sessão
        _, pl = get_current_playlist()
        out[nm] = list(pl.get("tracks") or [])
    # repor seleção original
    set_current_playlist(current_name)
    return out


def _write_playlists_to_csv(playlists: Dict[str, List[Dict[str, Any]]], path: Path = CSV_PATH) -> None:
    """Escreve TODO o estado (memória ∪ CSV anterior) para playlist.csv (separador ';')."""
    rows = []
    for name, tracks in (playlists or {}).items():
        for t in tracks or []:
            rows.append(
                {
                    "PlaylistName": name,
                    "Title": t.get("name", ""),
                    "Artists": t.get("artists", ""),
                    "Album": t.get("album", ""),
                    "Duration": ms_to_mmss(t.get("duration_ms") or 0),
                    "TrackID": t.get("id", ""),
                    "TrackURI": t.get("uri", ""),
                    "TrackURL": t.get("external_url", ""),
                }
            )
    df = pd.DataFrame(rows, columns=CSV_COLS)
    # criar pasta se necessário
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, sep=";")


def _export_csv_bytes(playlist_name: str, tracks: List[Dict[str, Any]]) -> bytes:
    """Gera CSV (separador ';') da playlist atual — (botão comentado)."""
    recs = []
    for t in tracks or []:
        recs.append(
            {
                "PlaylistName": playlist_name,
                "Title": t.get("name", ""),
                "Artists": t.get("artists", ""),
                "Album": t.get("album", ""),
                "Duration": ms_to_mmss(t.get("duration_ms") or 0),
                "TrackID": t.get("id", ""),
                "TrackURI": t.get("uri", ""),
                "TrackURL": t.get("external_url", ""),
            }
        )
    df = pd.DataFrame(recs, columns=CSV_COLS)
    return df.to_csv(index=False, sep=";").encode("utf-8")


# =========================
# Page
# =========================

def render_playlists_page():
    show_page_help("playlists", lang="PT")

    st.header("Session playlist")

    # ---------- Nomes: memória ∪ CSV ----------
    mem_names = list_playlists() or []            # memória  :contentReference[oaicite:3]{index=3}
    csv_dict = _load_playlists_from_csv()         # CSV (se houver)
    csv_names = list(csv_dict.keys())
    all_names = sorted({*(mem_names or []), *csv_names} or {"My Playlist"})

    # Seleção atual (se não existir, usa o 1º)
    cur_name, _pl = get_current_playlist()        # :contentReference[oaicite:4]{index=4}
    if cur_name not in all_names:
        cur_name = all_names[0]
        set_current_playlist(cur_name)

    col_sel, col_send = st.columns([3, 1])
    with col_sel:
        sel = st.selectbox(
            "Playlist",
            options=all_names,
            index=all_names.index(cur_name) if cur_name in all_names else 0,
            key="ui_pl_sel",
        )
        if sel != cur_name:
            # Se veio só do CSV, importa para memória
            if sel not in (mem_names or []) and sel in csv_dict:
                ensure_playlist(sel)                                  # cria vazia em memória  :contentReference[oaicite:5]{index=5}
                add_tracks_to_playlist(sel, csv_dict[sel])            # carrega faixas       :contentReference[oaicite:6]{index=6}
            set_current_playlist(sel)                                  # passa a atual        :contentReference[oaicite:7]{index=7}
            cur_name, _pl = get_current_playlist()

    with col_send:
        if st.button("🚀 Send to Spotify", use_container_width=True):
            try:
                playlist_id, added, misses = push_session_playlist(playlist_name=cur_name)
                if playlist_id:
                    st.success(f"Sent {added} tracks to '{cur_name}'.")
                    if misses:
                        st.info(f"Couldn't resolve {len(misses)} track(s) without URI.")
                else:
                    st.info("Nothing to send.")
            except Exception as e:
                st.error(f"Failed to send: {e}")
            else:
                # ✅ AUTOSAVE: escrever playlist.csv com o estado completo (memória ∪ CSV antigo)
                state_mem = _get_session_playlists_dict()
                # merge: prioriza o que está em memória; mantém listas do CSV que não existirem na memória
                merged = dict(csv_dict)
                merged.update(state_mem)
                _write_playlists_to_csv(merged)

    # ---------- (Opcional) Export CSV — DESCOMENTA para ativar ----------
    # cur_n, pl_n = get_current_playlist()
    # csv_bytes = _export_csv_bytes(cur_n, list(pl_n.get("tracks") or []))
    # st.download_button(
    #     "💾 Export CSV",
    #     data=csv_bytes,
    #     file_name=f"{cur_n}.csv",
    #     mime="text/csv",
    # )

    # ---------- Linha 2: uploader isolado (cria nova playlist) ----------
    up = st.file_uploader(
        "Drag and drop a CSV to create a new playlist",
        type=["csv"],
        accept_multiple_files=False,
    )
    if up is not None:
        default_name = Path(up.name).stem.strip() or "Imported Playlist"
        new_name = st.text_input("New playlist name", value=default_name, key="ui_new_pl_name")
        if st.button("📥 Import CSV as playlist"):
            try:
                rows = _parse_csv_to_rows(up.getvalue())
                ensure_playlist(new_name)
                add_tracks_to_playlist(new_name, rows)
                set_current_playlist(new_name)
                st.success(f"Imported {len(rows)} tracks into '{new_name}'.")
            except Exception as e:
                st.error(f"Import failed: {e}")

    # ---------- Conteúdo da playlist selecionada + remoção ----------
    cur_name, pl = get_current_playlist()
    tracks = list(pl.get("tracks") or [])
    st.subheader(f"Current: {cur_name} — {len(tracks)} track(s)")

    if not tracks:
        st.info("This playlist has no tracks yet.")
        return

    # lista scrollável com checkboxes para remover
    st.markdown(
        "<div style='max-height:55vh; overflow:auto; border:1px solid #ddd; padding:8px; border-radius:8px'>",
        unsafe_allow_html=True,
    )

    to_remove: List[int] = []
    for idx, t in enumerate(tracks):
        title = t.get("name") or ""
        artists = t.get("artists") or ""
        dur = ms_to_mmss(t.get("duration_ms") or 0)
        label = f"#{idx+1} — {title} — {artists} ({dur})"
        if st.checkbox(label, key=f"rm_{cur_name}_{idx}"):
            to_remove.append(idx)

        url = t.get("external_url")
        if url:
            st.markdown(f"&nbsp;&nbsp;[▶ Play on Spotify]({url})", unsafe_allow_html=True)

        st.markdown("<hr style='margin:6px 0; opacity:0.15;'>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    col_r1, col_r2 = st.columns([1, 1])
    with col_r1:
        if st.button("🗑 Remove selected"):
            for i in sorted(to_remove, reverse=True):
                remove_track_at(i)  # atua sobre a playlist atual em memória  :contentReference[oaicite:8]{index=8}
                st.session_state.pop(f"rm_{cur_name}_{i}", None)
            st.rerun()

    with col_r2:
        if st.button("🧹 Clear all"):
            for i in range(len(tracks) - 1, -1, -1):
                remove_track_at(i)
            st.rerun()
