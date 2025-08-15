# views/spotify_results.py
from __future__ import annotations

import re
import requests
import streamlit as st

from services.spotify_lookup import embed_spotify
from services.spotify_radio import (
    find_artist_this_is_playlist,
    find_artist_radio_playlist,
)
from services.spotify import get_auth_header, fetch_all_albums, fmt
from services.ui_helpers import ui_mobile, ui_audio_preview, ms_to_mmss
from services.playlist import list_playlists, add_tracks_to_playlist

# =========================
#   Wikipedia helpers
# =========================
WIKI_API = "https://{lang}.wikipedia.org/w/api.php"


@st.cache_data(ttl=86400, show_spinner=False)
def _wiki_api_search(title: str, lang: str = "en") -> str | None:
    try:
        r = requests.get(
            WIKI_API.format(lang=lang),
            params={
                "action": "query",
                "list": "search",
                "srsearch": title,
                "format": "json",
                "srlimit": 1,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        hits = (r.json().get("query") or {}).get("search") or []
        return hits[0]["title"] if hits else None
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_wikipedia_title(
    artist_name: str, lang: str = "en"
) -> tuple[str | None, str | None]:
    if not artist_name:
        return None, None
    for cand in (f"{artist_name} (band)", f"{artist_name} (music group)", artist_name):
        title = _wiki_api_search(cand, lang=lang)
        if title:
            url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
            return title, url
    return None, None


# =========================
#   Wildcards & Search
# =========================
def _parse_wildcard(raw: str) -> tuple[str, str]:
    """Return (core, mode) from input with '*' at start/end."""
    s = (raw or "").strip()
    if not s:
        return "", "all"
    starts = s.startswith("*")
    ends = s.endswith("*")
    core = s.strip("*").strip()
    if not core:
        return "", "all"
    if starts and ends:
        return core, "contains"
    if starts:
        return core, "suffix"
    if ends:
        return core, "prefix"
    return core, "exact"


def _match_name(name: str, core: str, mode: str) -> bool:
    n = (name or "").strip().casefold()
    c = (core or "").strip().casefold()
    if not c:
        return True
    if mode == "exact":
        return n == c
    if mode == "prefix":
        return n.startswith(c)
    if mode == "suffix":
        return n.endswith(c)
    if mode == "contains":
        return c in n
    return True


@st.cache_data(ttl=900, show_spinner=False)
def _search_artists_api(token: str, q: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Single page call to /v1/search for artists."""
    if not token or not q:
        return []
    headers = get_auth_header(token)
    params = {"q": q, "type": "artist", "limit": limit, "offset": offset}
    try:
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params=params,
            timeout=12,
        )
        if r.status_code != 200:
            return []
        return ((r.json().get("artists") or {}).get("items") or [])
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def search_artists_wildcard(token: str, raw_query: str, max_pages: int = 4) -> list[dict]:
    """
    Search artists honoring user wildcards.
    - Scans up to 4 pages (offsets 0/50/100/150).
    - For 'exact', try artist:"<name>" first and then fallback.
    - Dedup by id and filter locally.
    """
    core, mode = _parse_wildcard(raw_query)
    if not core:
        return []

    seen, out = set(), []
    primary_q = core
    exact_q = f'artist:"{core}"' if mode == "exact" else None

    # 1) Exact first (if applicable)
    if exact_q:
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, exact_q, limit=50, offset=off):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                if _match_name(a.get("name", ""), core, mode):
                    out.append(a)

    # 2) Normal / fallback
    if (not exact_q) or (exact_q and not out):
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, primary_q, limit=50, offset=off):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                if _match_name(a.get("name", ""), core, mode):
                    out.append(a)

    return out


def _extract_user_query() -> str:
    """
    Read the user's query from common keys to avoid UI mismatches.
    """
    for k in [
        "query",
        "artist",
        "artist_query",
        "search",
        "artist_name",
        "spotify_artist",
        "spotify_search",
        "name_input",
    ]:
        v = st.session_state.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


# ======== NEW: genre-only support ========
def _parse_genre_only(raw_q: str) -> str | None:
    """
    If raw_q is exactly of the form genre:"<value>", return <value>; else None.
    """
    if not isinstance(raw_q, str):
        return None
    m = re.match(r'^\s*genre\s*:\s*"([^"]+)"\s*$', raw_q.strip(), flags=re.IGNORECASE)
    return (m.group(1).strip() if m else None)


@st.cache_data(ttl=900, show_spinner=False)
def search_artists_by_genre(token: str, genre: str, max_pages: int = 4) -> list[dict]:
    """
    Genre-first search: query Spotify for artists, then filter locally by artist.genres.
    This is robust even when the API's 'genre:' operator doesn't behave consistently.
    """
    if not (token and genre):
        return []
    g = genre.strip().casefold()
    seen, out = set(), []
    # Use the plain genre as search text to broaden recall, then local-filter
    for off in (0, 50, 100, 150)[:max_pages]:
        for a in _search_artists_api(token, genre, limit=50, offset=off):
            if not isinstance(a, dict):
                continue
            aid = a.get("id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            glist = [str(x).casefold() for x in (a.get("genres") or [])]
            # Accept 'contains' both ways (handles cases like "symphonic prog" vs "symphonic progressive rock")
            if any((g in gg) or (gg in g) for gg in glist):
                out.append(a)
    return out
# ========================================


# =========================
#   Albums / Tracks
# =========================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_album_tracks_api(token: str, album_id: str) -> list[dict]:
    """Fetch album tracks via Spotify API."""
    if not album_id:
        return []
    items = []
    url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
    params = {"limit": 50, "offset": 0}
    headers = get_auth_header(token)
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code == 401:
            return []
        if r.status_code != 200:
            break
        j = r.json() or {}
        items.extend(j.get("items") or [])
        url = j.get("next")
        params = None
    return items


@st.cache_data(ttl=86400, show_spinner=False)
def cached_fetch_all_albums(token: str, artist_id: str):
    return fetch_all_albums(token, artist_id)


# =========================
#   UI
# =========================
def render_spotify_results(token: str):
    """
    Artist search with user-controlled wildcards:
      'Genesis'   (exact) | '*Genesis' (suffix) | 'Genesis*' (prefix) | '*Genesis*' (contains)
    Scans multiple API pages before applying local filter.
    """
    mobile = ui_mobile()

    # 1) Query from top search box (no fallback input here)
    raw_q = _extract_user_query()
    if not raw_q:
        # st.info("Type the artist in the search box at the top. You can use * at the start and/or end.")
        return

    # 1b) Detect genre-only query: genre:"<value>"
    genre_only = _parse_genre_only(raw_q)
    # 2) Search
    per_page = 20
    if genre_only:
        all_matched = search_artists_by_genre(token, genre_only, max_pages=4) or []
        core_q, mode_q = "", "genre"
    else:
        all_matched = search_artists_wildcard(token, raw_q, max_pages=4) or []
        core_q, mode_q = _parse_wildcard(raw_q)

        # Optional homonym collapse (exact mode only)
        if mode_q == "exact" and all_matched:
            best_by_name = {}
            for a in all_matched:
                if not isinstance(a, dict):
                    continue
                name_key = (a.get("name") or "").strip().casefold()
                followers = ((a.get("followers") or {}).get("total") or 0)
                cur_best = best_by_name.get(name_key)
                if cur_best is None or followers > ((cur_best.get("followers") or {}).get("total") or 0):
                    best_by_name[name_key] = a
            all_matched = list(best_by_name.values())
            all_matched.sort(key=lambda x: -((x.get("followers") or {}).get("total") or 0))
    #-----------------------------------
    # ---- PAGINAÇÃO ----
    # mantém per_page=20 definido acima; aqui só fazemos override para género
    # ---- PAGINAÇÃO (10 por página para todos os casos) ----
    per_page_local = 10

    total_filtered = len(all_matched)
    total_pages = (total_filtered - 1) // per_page_local + 1 if total_filtered else 0

    # página atual segura + sincronizada em session_state
    page = int(st.session_state.get("page", 1) or 1)
    if total_pages == 0:
        page = 0
    else:
        page = max(1, min(page, total_pages))
        st.session_state["page"] = page

    st.subheader(f"Page {page}/{total_pages}")

    # Prev/Next local (acima da lista) — só quando há várias páginas
    if total_pages > 1:
        cprev, cnext = st.columns([0.15, 0.15])
        with cprev:
            if st.button("◀ Previous", key="local_prev", disabled=page <= 1, use_container_width=True):
                st.session_state["page"] = page - 1
                st.rerun()
        with cnext:
            if st.button("Next ▶", key="local_next", disabled=page >= total_pages, use_container_width=True):
                st.session_state["page"] = page + 1
                st.rerun()

    # fatia da página
    start = (page - 1) * per_page_local if total_filtered else 0
    end = start + per_page_local
    items = all_matched[start:end] if total_filtered else []


#----------------------------------------------------
    if not items:
        if genre_only:
            st.info(f'No artists found for genre "{genre_only}".')
        else:
            st.info("No artist matches your pattern. Try adjusting the * (e.g., Genesis, Yes*, *Yes).")
        return

    # ---- Artists list
    for artist in items:
        followers_fmt = fmt((artist.get("followers") or {}).get("total", 0))
        with st.expander(f"{artist.get('name','—')} ({followers_fmt} followers)"):

            # -------- First-level columns
            col_a, col_b = st.columns([2, 1]) if not mobile else st.columns([1, 1])

            # -------- Column A: meta + links + actions ▶ / ⭐ / 📻
            with col_a:
                st.write(f"**Popularity:** {artist.get('popularity', 0)}/100")
                genres_list = artist.get("genres") or []
                st.write(f"**Genres:** {', '.join(genres_list) if genres_list else '—'}")

                spotify_url = (artist.get("external_urls") or {}).get("spotify")
                wiki_title, wiki_url = resolve_wikipedia_title(artist.get("name"), lang="en")
                links = []
                if spotify_url:
                    links.append(f"[Open in Spotify]({spotify_url})")
                if wiki_url:
                    links.append(f"[Wikipedia]({wiki_url})")
                if links:
                    st.markdown(" • ".join(links) + f" • Followers: {followers_fmt}")
                else:
                    st.write(f"Followers: {followers_fmt}")

                # -------- Actions (one nesting level only)
                act_play, act_thisis, act_radio = st.columns([1, 1, 1])

                # ▶ Embed artist
                with act_play:
                    embed_key = f"artist_{artist['id']}_embed"
                    if st.button("▶", key=f"btn_{artist['id']}_embed", help="Embed artist player"):
                        st.session_state[embed_key] = True
                        st.rerun()
                    if st.session_state.get(embed_key):
                        try:
                            embed_spotify("artist", artist["id"], height=80)
                        except Exception:
                            pass

                # ⭐ This Is <Artist>
                with act_thisis:
                    thisis_key = f"artist_thisis_result_{artist['id']}"
                    if st.button("⭐ This Is", key=f"btn_thisis_{artist['id']}", help="Find 'This Is <artist>' playlist"):
                        try:
                            pl = find_artist_this_is_playlist(
                                token=token,
                                artist_name=artist.get("name", ""),
                                artist_id=artist.get("id"),   # track validation
                            )
                        except Exception:
                            pl = None
                        st.session_state[thisis_key] = pl if pl else {"type": "none"}
                        st.rerun()

                    if thisis_key in st.session_state:
                        _pl = st.session_state[thisis_key]
                        if _pl and _pl.get("type") == "playlist" and _pl.get("id"):
                            title = _pl.get("name") or f"This Is {artist.get('name','')}"
                            if _pl.get("external_url"):
                                st.markdown(f"[Open “{title}” on Spotify]({_pl['external_url']})")
                            try:
                                embed_spotify("playlist", _pl["id"], height=80)
                            except Exception:
                                pass
                        else:
                            st.caption("This Is playlist not available")

                # 📻 <Artist> Radio
                with act_radio:
                    radio_key = f"artist_radio_result_{artist['id']}"
                    if st.button("📻 Radio", key=f"btn_radio_{artist['id']}", help="Find '<artist> Radio' playlist"):
                        try:
                            pl = find_artist_radio_playlist(
                                token=token,
                                artist_name=artist.get("name", ""),
                                artist_id=artist.get("id"),   # track validation
                            )
                        except Exception:
                            pl = None
                        st.session_state[radio_key] = pl if pl else {"type": "none"}
                        st.rerun()

                    if radio_key in st.session_state:
                        _pl = st.session_state[radio_key]
                        if _pl and _pl.get("type") == "playlist" and _pl.get("id"):
                            title = _pl.get("name") or f"{artist.get('name','')} Radio"
                            if _pl.get("external_url"):
                                st.markdown(f"[Open “{title}” on Spotify]({_pl['external_url']})")
                            try:
                                embed_spotify("playlist", _pl["id"], height=80)
                            except Exception:
                                pass
                        else:
                            st.caption("Radio playlist not available")

            # -------- Column B: image
            with col_b:
                imgs = artist.get("images") or []
                if imgs:
                    st.image(imgs[0].get("url"), width=120 if not mobile else 96)

            # -------- Releases (albums/singles/compilations)
            releases = cached_fetch_all_albums(token, artist["id"]) or []

            def _atype(it):
                return (it.get("album_group") or it.get("album_type") or "").lower()

            albums = [x for x in releases if _atype(x) == "album"]
            singles = [x for x in releases if _atype(x) == "single"]
            compilations = [x for x in releases if _atype(x) == "compilation"]

            def _year(it):
                d = it.get("release_date") or ""
                return d[:4] if len(d) >= 4 else None

            years = sorted([y for y in {_year(x) for x in releases} if y])

            st.markdown("**📖 Overview (Spotify releases):**")
            if years:
                st.write(f"• First release on Spotify: {years[0]}")
                st.write(f"• Latest release on Spotify: {years[-1]}")
            else:
                st.write("• First/Latest release: —")
            st.write(
                f"• Releases: {len(releases)}  |  "
                f"Albums: {len(albums)}  |  "
                f"Singles/EPs: {len(singles)}  |  "
                f"Compilations: {len(compilations)}"
            )

            # -------- Albums panel (top-level columns inside expander)
            cbtn, calist = st.columns([1, 2]) if not mobile else st.columns([1, 1])
            with cbtn:
                if st.button(f"🗂 Albums ({len(albums)})", key=f"alb_btn_{artist['id']}"):
                    st.session_state["open_albums_for"] = artist["id"]
                    st.session_state["albums_data"] = {
                        "artist_name": artist["name"],
                        "albums": sorted(
                            albums, key=lambda x: x.get("release_date", ""), reverse=True
                        ),
                        "singles": sorted(
                            singles, key=lambda x: x.get("release_date", ""), reverse=True
                        )[:30],
                        "comps": sorted(
                            compilations, key=lambda x: x.get("release_date", ""), reverse=True
                        )[:20],
                    }
                    st.rerun()

            with calist:
                if st.session_state.get("open_albums_for") == artist["id"]:
                    ad = st.session_state.get("albums_data", {})
                    artist_name = ad.get("artist_name", artist["name"])
                    st.markdown(f"#### Albums — {artist_name}")

                    # One nesting level of columns (allowed)
                    left, right = st.columns([1.2, 1.8], gap="large") if not mobile else st.columns([1, 1])

                    # LEFT: dropdown + all releases toggle
                    with left:
                        album_opts = []
                        for it in (ad.get("albums") or []):
                            y = (it.get("release_date") or "")[:4]
                            album_opts.append((f"{it.get('name', '—')} ({y})", it.get("id")))
                        if album_opts:
                            labels = [lbl for lbl, _ in album_opts]
                            ids = [aid for _, aid in album_opts]
                            sel = st.selectbox(
                                "Select album",
                                options=list(range(len(labels))),
                                format_func=lambda i: labels[i],
                                key=f"select_album_idx_{artist['id']}",
                            )
                            st.session_state[
                                f"selected_album_id_{artist['id']}"
                            ] = ids[sel]

                        show_all = st.toggle(
                            "All releases (albums / singles / compilations)",
                            value=False,
                            key=f"all_releases_{artist['id']}",
                        )
                        if show_all:
                            def _mk(items, title):
                                if not items:
                                    return ""
                                out = [f"<b>{title}</b><ul>"]
                                for it in items:
                                    y = (it.get("release_date") or "")[:4]
                                    url = (it.get("external_urls") or {}).get("spotify")
                                    name = it.get("name", "—")
                                    if url:
                                        out.append(
                                            f'<li><a href="{url}" target="_blank">{name}</a> ({y})</li>'
                                        )
                                    else:
                                        out.append(f"<li>{name} ({y})</li>")
                                out.append("</ul>")
                                return "\n".join(out)

                            html = "<div style='max-height:40vh; overflow:auto;'>"
                            html += _mk(ad.get("albums") or [], "Albums")
                            html += _mk(ad.get("singles") or [], "Singles / EPs")
                            html += _mk(ad.get("comps") or [], "Compilations")
                            html += "</div>"
                            st.markdown(html, unsafe_allow_html=True)

                        if st.button(
                            "Close albums", key=f"close_albums_{artist['id']}_panel"
                        ):
                            for k in [
                                "open_albums_for",
                                "albums_data",
                                f"selected_album_id_{artist['id']}",
                            ]:
                                st.session_state.pop(k, None)
                            st.rerun()

                    
                    
                    # RIGHT: tracks of selected album
                    with right:
                        aid = st.session_state.get(f"selected_album_id_{artist['id']}")
                        if not aid:
                            st.info("Select an album to view its tracks.")
                        else:
                            meta = next((a for a in ad.get("albums", []) if a.get("id") == aid), {})
                            album_name = meta.get("name", "Album")
                            album_url = (meta.get("external_urls") or {}).get("spotify")

                            st.markdown(f"**Tracks — {album_name}**")
                            if album_url:
                                st.markdown(f"[Open album in Spotify]({album_url})")

                            # ---------- TOP controls (target + Add ALL)
                            names = list_playlists() or []
                            dest_choice = st.selectbox(
                                "Target playlist",
                                options=(names + ["➕ Create new…"]) if names else ["➕ Create new…"],
                                key=f"pick_dest_{artist['id']}",
                            )
                            if dest_choice == "➕ Create new…":
                                newn = st.text_input("New playlist name", key=f"pick_dest_new_{artist['id']}")
                                target_name = (newn or "").strip() or "My Playlist"
                            else:
                                target_name = dest_choice

                            # (mantemos este botão; retirámos o 'Add selected')
                            if st.button("➕ Add ALL tracks", key=f"add_all_{aid}__top"):
                                rows_all = fetch_album_tracks_api(token, aid) or []
                                rows = []
                                for tr in rows_all:
                                    rows.append(
                                        {
                                            "id": tr.get("id"),
                                            "uri": tr.get("uri"),
                                            "name": tr.get("name"),
                                            "artists": ", ".join([a.get("name", "") for a in (tr.get("artists") or []) if a]),
                                            "album": album_name,
                                            "album_id": aid,
                                            "album_url": album_url,
                                            "disc_number": tr.get("disc_number"),
                                            "track_number": tr.get("track_number"),
                                            "duration_ms": tr.get("duration_ms"),
                                            "preview_url": tr.get("preview_url"),
                                            "external_url": (tr.get("external_urls") or {}).get("spotify"),
                                        }
                                    )
                                if rows:
                                    add_tracks_to_playlist(target_name, rows)
                                    st.success(f"Added {len(rows)} tracks to '{target_name}'.")
                                    # Marcar todas como selecionadas visualmente
                                    for r in rows:
                                        st.session_state[f"chk_{aid}_{r['id']}"] = True
                                else:
                                    st.info("No tracks to add.")

                            # ---------- Build rows for listing (once)
                            rows = []
                            for tr in (fetch_album_tracks_api(token, aid) or []):
                                rows.append(
                                    {
                                        "id": tr.get("id"),
                                        "uri": tr.get("uri"),
                                        "name": tr.get("name"),
                                        "artists": ", ".join([a.get("name", "") for a in (tr.get("artists") or []) if a]),
                                        "album": album_name,
                                        "album_id": aid,
                                        "album_url": album_url,
                                        "disc_number": tr.get("disc_number"),
                                        "track_number": tr.get("track_number"),
                                        "duration_ms": tr.get("duration_ms"),
                                        "preview_url": tr.get("preview_url"),
                                        "external_url": (tr.get("external_urls") or {}).get("spotify"),
                                    }
                                )

                            # Guarda simples para não duplicar adições ao alternar a checkbox
                            added_key = f"auto_added_ids__{target_name}"
                            if added_key not in st.session_state:
                                st.session_state[added_key] = set()

                            # Caixa scrollável + mensagem topo
                            st.markdown(
                                "<div style='max-height:50vh; overflow:auto; border:1px solid #ddd; padding:8px; border-radius:8px'>",
                                unsafe_allow_html=True,
                            )
                            st.markdown("**To play on Spotify, click the track name.**")

                            for r in rows:
                                base = f"#{r['track_number']} — {r['name']} — {r['artists']} ({ms_to_mmss(r['duration_ms'])})"
                                label_md = f"[{base}]({r['external_url']})" if r.get("external_url") else base

                                ckey = f"chk_{aid}_{r['id']}"
                                checked = st.checkbox(label_md, key=ckey)

                                # Auto-add when toggled on (once)
                                if checked and (r["id"] not in st.session_state[added_key]):
                                    add_tracks_to_playlist(target_name, [r])
                                    st.session_state[added_key].add(r["id"])

                                if r.get("preview_url") and ui_audio_preview():
                                    st.audio(r["preview_url"])

                                st.markdown("<hr style='margin:8px 0; opacity:0.15;'>", unsafe_allow_html=True)

                            st.markdown("</div>", unsafe_allow_html=True)
