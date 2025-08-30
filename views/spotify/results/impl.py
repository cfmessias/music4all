# views/spotify/results/impl.py
# UI dos resultados (artist-first) com:
#   • sem falsos positivos quando não há '*'
#   • conjunção Artist ∩ Genre quando ambos são fornecidos
#   • About (Wikipédia em EN) ao lado do Overview

from __future__ import annotations

import requests
import streamlit as st

from services.spotify import fetch_all_albums, fmt, get_auth_header
from services.spotify.lookup import embed_spotify
from services.spotify.radio import (
    find_artist_this_is_playlist,
    find_artist_radio_playlist,
)
from services.ui_helpers import ui_mobile, ui_audio_preview, ms_to_mmss
from services.playlist import list_playlists, add_tracks_to_playlist

from .search import (
    parse_wildcard,
    search_artists_strict,
    search_artists_wildcard,
    search_artists_by_genre,
    filter_artists_by_genre,
)
from .wiki import artist_blurb


# ---------- API auxiliar (tracks de um álbum) ----------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_album_tracks_api(token: str, album_id: str) -> list[dict]:
    if not album_id:
        return []
    items = []
    url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
    params = {"limit": 50, "offset": 0}
    headers = get_auth_header(token)
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code != 200:
            break
        j = r.json() or {}
        items.extend(j.get("items") or [])
        url = j.get("next")
        params = None
    return items


# -------------------- Render principal --------------------

def render_spotify_results(token: str):
    mobile = ui_mobile()

    # Inputs básicos do estado
    name_typed = (st.session_state.get("query") or "").strip()
    seed = (st.session_state.get("genre_input") or "").strip()
    free = (st.session_state.get("genre_free_input") or "").strip()
    genre_term = free or seed

    if not name_typed and not genre_term:
        return  # nada a pesquisar ainda

    # 1) Artist tem prioridade SEMPRE
    results = []
    mode_caption = ""
    if name_typed:
        core, mode = parse_wildcard(name_typed)
        if mode == "exact":
            # sem '*' → match estrito (sem falsos positivos)
            results = search_artists_strict(token, core) or []
            mode_caption = "🔎 Mode: artist name (exact)"
        else:
            # com '*' → pesquisa alargada (pode devolver parecidos)
            results = search_artists_wildcard(token, name_typed, max_pages=4) or []
            mode_caption = "🔎 Mode: artist name (wildcard)"

        # Conjunção com género, se fornecido
        if genre_term:
            before = len(results)
            results = filter_artists_by_genre(results, genre_term)
            mode_caption += f" ∩ genre «{genre_term}» ({len(results)}/{before})"

    else:
        # 2) Sem Artist → usar género
        results = search_artists_by_genre(token, genre_term, max_pages=4) or []
        # Afinar com o filtro por tokens (aumenta precisão)
        results = filter_artists_by_genre(results, genre_term)
        mode_caption = f"🔎 Mode: genre «{genre_term}»"

    # Ordenar por followers
    results.sort(key=lambda a: -((a.get("followers") or {}).get("total", 0)))

    if mode_caption:
        st.caption(mode_caption)
    if not results:
        if name_typed:
            st.info(f'No artists found for "{name_typed}".')
        else:
            st.info(f'No artists found for genre "{genre_term}".')
        return

    # Paginação
    per_page = 10
    total = len(results)
    total_pages = (total - 1) // per_page + 1
    page = max(1, min(int(st.session_state.get("page", 1) or 1), total_pages))
    st.session_state["page"] = page
    start, end = (page - 1) * per_page, (page - 1) * per_page + per_page
    items = results[start:end]

    # Render de cada artista
    for artist in items:
        followers_fmt = fmt((artist.get("followers") or {}).get("total", 0))
        with st.expander(f"{artist.get('name','—')} ({followers_fmt} followers)"):

            # colunas topo do cartão
            colA, colB = st.columns([2, 1]) if not mobile else st.columns([1, 1])

            # -------- coluna A: meta/links/ações
            with colA:
                st.write(f"**Popularity:** {artist.get('popularity', 0)}/100")
                gl = artist.get("genres") or []
                st.write(f"**Genres:** {', '.join(gl) if gl else '—'}")

                sp_url = (artist.get("external_urls") or {}).get("spotify")
                if sp_url:
                    st.markdown(f"[Open in Spotify]({sp_url}) • Followers: {followers_fmt}")
                else:
                    st.write(f"Followers: {followers_fmt}")

                # Ações básicas
                c1, c2, c3 = st.columns([1, 1, 1])
                with c1:
                    if st.button("▶", key=f"play_{artist['id']}"):
                        st.session_state[f"embed_{artist['id']}"] = True
                    if st.session_state.get(f"embed_{artist['id']}"):
                        try:
                            embed_spotify("artist", artist["id"], height=80)
                        except Exception:
                            pass
                with c2:
                    if st.button("⭐ This Is", key=f"thisis_{artist['id']}"):
                        try:
                            pl = find_artist_this_is_playlist(token, artist.get("name", ""), artist.get("id"))
                        except Exception:
                            pl = None
                        if pl and pl.get("id"):
                            try:
                                embed_spotify("playlist", pl["id"], height=80)
                            except Exception:
                                pass
                        elif pl and pl.get("url"):
                            st.markdown(f"[Open on Spotify]({pl['url']})")
                        else:
                            st.info("No 'This Is' playlist found.")
                with c3:
                    if st.button("📻 Radio", key=f"radio_{artist['id']}"):
                        try:
                            pl = find_artist_radio_playlist(token, artist.get("name", ""), artist.get("id"))
                        except Exception:
                            pl = None
                        if pl and pl.get("id"):
                            try:
                                embed_spotify("playlist", pl["id"], height=80)
                            except Exception:
                                pass
                        elif pl and pl.get("url"):
                            st.markdown(f"[Open on Spotify]({pl['url']})")
                        else:
                            st.info("No radio playlist found.")

            # -------- coluna B: imagem
            with colB:
                imgs = artist.get("images") or []
                if imgs:
                    st.image(imgs[0].get("url"), width=120 if not mobile else 96)

            # -------- Overview + About lado a lado
            releases = fetch_all_albums(token, artist["id"]) or []

            def _atype(x):
                return (x.get("album_group") or x.get("album_type") or "").lower()

            albums = [x for x in releases if _atype(x) == "album"]
            singles = [x for x in releases if _atype(x) == "single"]
            comps = [x for x in releases if _atype(x) == "compilation"]

            def _year(x):
                d = x.get("release_date") or ""
                return d[:4] if len(d) >= 4 else None

            years = sorted([y for y in {_year(x) for x in releases} if y])

            col_over, col_about = st.columns([1.8, 1])
            with col_over:
                st.markdown("**📖 Overview (Spotify releases):**")
                if years:
                    st.write(f"• First release on Spotify: {years[0]}")
                    st.write(f"• Latest release on Spotify: {years[-1]}")
                else:
                    st.write("• First/Latest release: —")
                st.write(
                    f"• Releases: {len(releases)} | "
                    f"Albums: {len(albums)} | Singles/EPs: {len(singles)} | Compilations: {len(comps)}"
                )

            with col_about:
                st.markdown("**ℹ️ About**")
                txt, url = artist_blurb(artist.get("name", ""), hints=gl)
                if txt:
                    st.write(txt)
                    if url:
                        st.caption(f"[Wikipedia]({url})")
                else:
                    st.caption("—")

            # -------- (opcional) painel de álbuns com add-to-playlist
            if albums:
                if st.button(f"🗂 Albums ({len(albums)})", key=f"btn_alb_{artist['id']}"):
                    st.session_state["open_albums_for"] = artist["id"]
                    st.session_state["albums_of"] = sorted(
                        albums, key=lambda x: x.get("release_date", ""), reverse=True
                    )

            if st.session_state.get("open_albums_for") == artist["id"]:
                alist = st.session_state.get("albums_of") or []
                left, right = st.columns([1.2, 1.8])
                with left:
                    labels = [f"{a.get('name','—')} ({(a.get('release_date') or '')[:4]})" for a in alist]
                    ids = [a.get("id") for a in alist]
                    if ids:
                        idx = st.selectbox(
                            "Select album",
                            options=list(range(len(ids))),
                            format_func=lambda i: labels[i],
                            key=f"selalb_{artist['id']}"
                        )
                        st.session_state[f"selalb_id_{artist['id']}"] = ids[idx]
                    if st.button("Close albums", key=f"close_alb_{artist['id']}"):
                        st.session_state.pop("open_albums_for", None)
                        st.session_state.pop("albums_of", None)

                with right:
                    aid = st.session_state.get(f"selalb_id_{artist['id']}")
                    if not aid:
                        st.info("Select an album to view its tracks.")
                    else:
                        rows = fetch_album_tracks_api(token, aid) or []
                        if not rows:
                            st.info("No tracks.")
                        else:
                            names = list_playlists() or []
                            dest = st.selectbox(
                                "Target playlist",
                                options=(names + ["➕ Create new…"]) if names else ["➕ Create new…"],
                                key=f"dest_{aid}",
                            )
                            if dest == "➕ Create new…":
                                newn = st.text_input("New playlist name", key=f"new_{aid}")
                                target = (newn or "").strip() or "My Playlist"
                            else:
                                target = dest

                            if st.button("➕ Add ALL tracks", key=f"addall_{aid}"):
                                to_add = []
                                for tr in rows:
                                    to_add.append({
                                        "id": tr.get("id"),
                                        "uri": tr.get("uri"),
                                        "name": tr.get("name"),
                                        "artists": ", ".join(a.get("name", "") for a in (tr.get("artists") or [])),
                                        "album": "",
                                        "album_id": aid,
                                        "album_url": (tr.get("external_urls") or {}).get("spotify"),
                                        "disc_number": tr.get("disc_number"),
                                        "track_number": tr.get("track_number"),
                                        "duration_ms": tr.get("duration_ms"),
                                        "preview_url": tr.get("preview_url"),
                                        "external_url": (tr.get("external_urls") or {}).get("spotify"),
                                    })
                                add_tracks_to_playlist(target, to_add)
                                st.success(f"Added {len(to_add)} tracks to '{target}'.")

                            st.markdown("<div style='max-height:50vh; overflow:auto;'>", unsafe_allow_html=True)
                            for tr in rows:
                                base = f"#{tr.get('track_number')} — {tr.get('name')} "\
                                       f"({ms_to_mmss(tr.get('duration_ms'))})"
                                link = (tr.get("external_urls") or {}).get("spotify")
                                label = f"[{base}]({link})" if link else base
                                st.write(label)
                                if tr.get("preview_url") and ui_audio_preview():
                                    st.audio(tr["preview_url"])
                            st.markdown("</div>", unsafe_allow_html=True)
