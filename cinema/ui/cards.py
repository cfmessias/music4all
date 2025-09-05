# cinema/ui/cards.py
from __future__ import annotations
import os
import requests
import pandas as pd
import streamlit as st

from cinema.providers.tmdb import tmdb_poster_url
from cinema.views.spotify_embed import render_player
from cinema.data import load_table
from .helpers import (
    key_for, title_match_score, artists_from_row_or_fetch, parse_date_like,
    on_click_play, safe_intlike, to_spotify_embed,
    save_watched_item_movies, save_watched_item_series
)

# === TMDb key (env ou secrets) ===
TMDB_API_KEY = (
    os.getenv("TMDB_API_KEY")
    or (st.secrets.get("TMDB_API_KEY") if hasattr(st, "secrets") else None)
    or ""
)
TMDB_API = "https://api.themoviedb.org/3"


# --- lookup watched no CSV (Movies/Series) ---
def _lookup_local_watched(section: str, title: str, year_val):
    base = load_table("Movies" if section == "Movies" else "Series").copy()
    if base.empty:
        return False, ""
    base["__t"] = base["title"].astype(str).str.strip().str.casefold()
    tnorm = (title or "").strip().casefold()
    ycol = "year" if section == "Movies" else "year_start"
    mask = base["__t"] == tnorm
    if ycol in base.columns and year_val not in (None, "", "nan"):
        try:
            want_y = int(str(year_val)[:4])
            base[ycol] = pd.to_numeric(base[ycol], errors="coerce")
            mask &= (base[ycol] == want_y)
        except Exception:
            pass
    row = base.loc[mask].head(1)
    if row.empty:
        return False, ""
    return bool(row.iloc[0].get("watched", False)), str(row.iloc[0].get("watched_date") or "")


# --- NEW: TMDb watch/providers por região (cacheado) ---
@st.cache_data(ttl=86400, show_spinner=False)
def _tmdb_watch_providers(media_type: str, tmdb_id: int, region: str) -> str:
    """
    media_type: 'movie' | 'tv'
    devolve providers (flatrate/ads/free/buy/rent) concatenados para a região dada.
    """
    if not tmdb_id or not TMDB_API_KEY:
        return ""
    url = f"{TMDB_API}/{ 'movie' if media_type=='movie' else 'tv' }/{int(tmdb_id)}/watch/providers"
    try:
        r = requests.get(url, params={"api_key": TMDB_API_KEY}, timeout=8)
        r.raise_for_status()
        data = r.json() or {}
        results = data.get("results") or {}
        region_data = results.get(region) or {}

        names: list[str] = []
        for key in ("flatrate", "ads", "free", "buy", "rent"):
            for p in (region_data.get(key) or []):
                n = p.get("provider_name")
                if n and n not in names:
                    names.append(n)

        if not names and region != "US":
            region_data = results.get("US") or {}
            for key in ("flatrate", "ads", "free", "buy", "rent"):
                for p in (region_data.get(key) or []):
                    n = p.get("provider_name")
                    if n and n not in names:
                        names.append(n)

        return ", ".join(names[:4])
    except Exception:
        return ""


def render_remote_results(section: str, remote: list[dict], query_title: str, region_code: str = "PT") -> None:
    if not remote:
        return
    st.subheader("Online results")

    if section not in ("Movies", "Series"):
        # Página Soundtracks simples
        df_sp = pd.DataFrame(remote)
        show_cols = [c for c in ["title", "artist", "year", "url"] if c in df_sp.columns]
        st.data_editor(
            df_sp[show_cols] if show_cols else df_sp,
            use_container_width=True, hide_index=True,
            key=key_for(section, "online_editor_sp"),
            column_config={"year": st.column_config.NumberColumn("year", format="%d", step=1)},
            disabled=show_cols,
        )
        return

    df_remote = pd.DataFrame(remote)
    if df_remote.empty:
        st.info("No results.")
        return
    #-----------------
    min_req = float(st.session_state.get(key_for(section, "minrating"), 0.0))
    if "rating" in df_remote.columns and min_req > 0:
        ratings = pd.to_numeric(df_remote["rating"], errors="coerce").fillna(0.0)
        df_remote = df_remote[ratings >= min_req].reset_index(drop=True)
        
    # Relevância permissiva: só ordena
    if (query_title or "").strip():
        df_remote["__ttl"] = df_remote.get("title", df_remote.get("name", ""))
        df_remote["__score"] = df_remote["__ttl"].apply(lambda s: title_match_score(str(s), query_title))
        df_remote = (
            df_remote
            .sort_values(["__score"], ascending=[False])
            .drop(columns=["__score", "__ttl"], errors="ignore")
            .reset_index(drop=True)
        )

    year_col = "year" if "year" in df_remote.columns else "year_start"
    if year_col not in df_remote.columns:
        df_remote[year_col] = ""

    # Normalizar colunas
    for c in [
        "id","title","name","director","creator","season",
        "genre","genres","streaming","rating","overview",
        "poster_url","poster","image","tmdb_id","poster_path",
        "web","play_url","notes","notes_text","watched","watched_date",
    ]:
        if c not in df_remote.columns:
            if c == "watched":
                df_remote[c] = False
            elif c == "watched_date":
                df_remote[c] = ""
            else:
                df_remote[c] = ""

    df_remote["notes_text2"] = df_remote.apply(
        lambda row: (str(row.get("notes_text") or "").strip()
                     or str(row.get("notes") or "").strip()
                     or str(row.get("overview") or "").strip()),
        axis=1
    )

    # Paginação
    per_page = 10
    total = len(df_remote)
    total_pages = max(1, (total - 1) // per_page + 1)
    page_key = key_for(section, "page")
    current = int(st.session_state.get(page_key, 1))
    current = max(1, min(current, total_pages))

    colp1, colp2, _ = st.columns([1, 1, 6])
    with colp1:
        if st.button("⟨ Prev", disabled=(current <= 1), key=key_for(section, "pg_prev")):
            current = max(1, current - 1)
            st.session_state.pop(key_for(section, "open_card_id"), None)
    with colp2:
        if st.button("Next ⟩", disabled=(current >= total_pages), key=key_for(section, "pg_next")):
            current = min(total_pages, current + 1)
            st.session_state.pop(key_for(section, "open_card_id"), None)

    st.session_state[page_key] = current
    st.caption(f"Page {current} / {total_pages} • {total} results")

    start, end = (current - 1) * per_page, min(current * per_page, total)
    page_rows = df_remote.iloc[start:end].reset_index(drop=True)

    # Cartões
    for i, r in page_rows.iterrows():
        row = r.to_dict()
        rid = safe_intlike(row.get("id")) or (start + i)
        title_i = row.get("title") or row.get("name") or "—"
        rating = row.get("rating")
        yv = row.get(year_col)

        # Header
        ytxt = ""
        if yv not in (None, "", "nan"):
            try:
                ytxt = f"{int(float(yv))}"
            except Exception:
                ytxt = str(yv)
        head_bits = [title_i]
        if ytxt:
            head_bits.append(f"({ytxt})")
        if pd.notna(rating) and str(rating).strip().lower() not in ("", "nan"):
            try:
                rating_val = float(str(rating).replace(",", "."))
                head_bits.append(f"— ★ {rating_val:.1f}")
            except Exception:
                head_bits.append(f"— ★ {rating}")
        header = " ".join(head_bits).strip()

        # Watched do CSV → badge + sufixo no título
        w_local, wd_local = _lookup_local_watched(section, title_i, yv)
        header2 = f"{header} • ✅ Watched" if w_local else header

        # Poster
        poster = row.get("poster_url") or row.get("poster") or row.get("image") or ""
        if not poster:
            ppath = row.get("poster_path") or ""
            if ppath:
                poster = f"https://image.tmdb.org/t/p/w185{ppath}"
        if not poster:
            y_try = None
            try:
                y_raw = row.get("year") if section == "Movies" else row.get("year_start")
                y_try = int(str(y_raw)[:4]) if y_raw not in (None, "", "nan") else None
            except Exception:
                pass
            poster = tmdb_poster_url(
                "movie" if section == "Movies" else "tv",
                row.get("tmdb_id") or row.get("id"),
                (row.get("title") or row.get("name") or ""),
                y_try,
            )

        # Streaming providers para a região escolhida
        providers_txt = ""
        tmdb_id_val = row.get("tmdb_id") or row.get("id")
        try:
            tid = int(tmdb_id_val) if tmdb_id_val is not None else None
        except Exception:
            tid = None
        if tid:
            mt = "movie" if section == "Movies" else "tv"
            providers_txt = _tmdb_watch_providers(mt, tid, region=region_code) or ""

        # Render cartão
        is_open = st.session_state.get(key_for(section, "open_card_id")) == rid
        with st.expander(header2, expanded=is_open):
            c_left, c_right = st.columns([1, 0.25], vertical_alignment="top")

            with c_left:
                who = row.get("director") if section == "Movies" else row.get("creator")
                gl = row.get("genres") or row.get("genre") or ""
                gl_txt = ", ".join(gl) if isinstance(gl, (list, tuple)) else str(gl)
                # usa providers por região se existir; senão, fallback ao campo remoto
                streaming = providers_txt or (row.get("streaming") or "")

                meta_parts = []
                if who:
                    meta_parts.append(f"**{'Director' if section=='Movies' else 'Creator'}:** {who}")
                if gl_txt.strip():
                    meta_parts.append(f"**Genres:** {gl_txt}")
                if streaming:
                    meta_parts.append(f"**Streaming ({region_code}):** {streaming}")
                if meta_parts:
                    st.markdown(" • ".join(meta_parts))

                # Badge “Watched”
                if w_local:
                    wd_badge = wd_local[:10] if wd_local else ""
                    st.markdown(
                        "<div style='margin:4px 0 8px 0'>"
                        "<span style='background:#E6F4EA;color:#0B6E3D;padding:2px 8px;"
                        "border-radius:999px;font-size:0.85rem;'>✓ Watched " + wd_badge + "</span>"
                        "</div>",
                        unsafe_allow_html=True,
                    )

                # Artistas + overview
                artists_txt = artists_from_row_or_fetch(row, section)
                if artists_txt:
                    st.markdown(f"**Artists:** {artists_txt}")

                st.markdown("**📖 Overview:**")
                st.write((row.get("notes_text2") or "").strip() or "—")

                # Botão Play + Player
                st.button(
                    "🎧 Play soundtrack",
                    key=key_for(section, f"play_{rid}"),
                    on_click=on_click_play,
                    kwargs={"section": section, "rid": rid, "title_i": title_i, "yv": yv, "tmdb_id": tmdb_id_val},
                )
                if st.session_state.get(key_for(section, "play_open_id")) == rid:
                    src = st.session_state.get(key_for(section, "play_src")) or ""
                    msg = st.session_state.get(key_for(section, "play_msg")) or ""
                    if src:
                        h = st.session_state.get(key_for(section, "play_height"), 380)
                        render_player(src, height=h)
                    else:
                        st.info(msg or "🎧 Soundtrack not found")

                # Watched line
                w_key = key_for(section, f"w_{rid}")
                d_key = key_for(section, f"wd_{rid}")
                default_w = w_local if isinstance(w_local, bool) else bool(row.get("watched"))
                default_d = parse_date_like(wd_local) or parse_date_like(row.get("watched_date"))

                cW, cLbl, cD, cSave = st.columns([0.18, 0.16, 0.28, 0.12])
                with cW:
                    w_val = st.checkbox("Watched", value=default_w, key=w_key)
                with cLbl:
                    st.markdown("<div style='padding-top:0.45rem; font-weight:600;'>Watched date</div>", unsafe_allow_html=True)
                with cD:
                    d_val = st.date_input(
                        "Watched date",
                        value=default_d, format="YYYY-MM-DD",
                        key=d_key, label_visibility="collapsed",
                    )
                with cSave:
                    if st.button("💾 Save", key=key_for(section, f"savew_{rid}")):
                        wd_str = str(d_val)[:10] if d_val else ""
                        if section == "Movies":
                            up, ins = save_watched_item_movies(row, w_val, wd_str)
                        else:
                            up, ins = save_watched_item_series(row, w_val, wd_str)
                        st.success(f"Saved: {up} update(s), {ins} new row(s).")

            with c_right:
                if poster:
                    st.image(poster, width=100)
