# app.py
import requests
import streamlit as st
import os
from services.spotify import (
    get_spotify_token,
    fetch_available_genres,
    save_genres_csv,
    load_genres_csv,
    search_artists,
    fetch_all_albums,
    get_auth_header,
    fmt,
)
from services.enrichers import enrich_from_external
from services.wiki_styles import render_wikipedia_styles_panel

# ===============
# Page config
# ===============
st.set_page_config(page_title="Spotify Artist Search", page_icon="🎵", layout="wide")
# Small CSS tweaks for mobile spacing
st.markdown("""
<style>
@media (max-width: 700px){
  .block-container{padding-top:0.5rem; padding-bottom:3rem;}
}
</style>
""", unsafe_allow_html=True)
st.title("🎵 Spotify Artist Search")
st.markdown("Search artists by genre or name, with paging and rich biography.")

# Mobile mode toggle (affects layout choices)
if 'mobile_mode' not in st.session_state:
    st.session_state['mobile_mode'] = False
mobile = st.sidebar.checkbox("📱 Mobile mode", value=st.session_state['mobile_mode'], help="Optimizes layout for small screens")
st.session_state['mobile_mode'] = mobile

# Apply any deferred page change **before** widgets are instantiated
if 'pending_page' in st.session_state:
    st.session_state['page_input'] = st.session_state.pop('pending_page')
    st.session_state['page'] = st.session_state.get('page_input', 1)

# ===============
# Credentials (use Streamlit Secrets if available)
# ===============
# Bridge Streamlit Cloud secrets -> environment variables
for _k in ["SPOTIFY_CLIENT_ID","SPOTIFY_CLIENT_SECRET","DISCOGS_USER_AGENT","DISCOGS_TOKEN"]:
    try:
        if _k in st.secrets and st.secrets[_k]:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# ===============
# Auth
# ===============
TOKEN = get_spotify_token(CLIENT_ID, CLIENT_SECRET)
if not TOKEN:
    st.error("❌ Could not authenticate with Spotify API.")
    st.stop()

# ===============
# UI helpers
# ===============

def render_albums_dialog(artist_name, albums, singles, compilations):
    """Show albums in a modal if available, else inline panel (compat fallback)."""
    def _render_body():
        st.write("**Albums (by year, desc)**")
        for alb in albums:
            y = (alb.get('release_date') or '')[:4]
            st.write(f"• {alb['name']} ({y})")
        if singles or compilations:
            st.markdown("---")
            if singles:
                st.write("**Singles/EPs (latest 30)**")
                for s in singles:
                    y = (s.get('release_date') or '')[:4]
                    st.write(f"• {s['name']} ({y})")
            if compilations:
                st.write("**Compilations (latest 20)**")
                for c in compilations:
                    y = (c.get('release_date') or '')[:4]
                    st.write(f"• {c['name']} ({y})")
    if hasattr(st, "modal"):
        with st.modal(f"Albums — {artist_name}"):
            _render_body()
            if st.button("Close"):
                for k in ["albums_open","albums_artist_name","albums_list","singles_list","comps_list"]:
                    st.session_state.pop(k, None)
                st.rerun()
    else:
        st.markdown(f"### Albums — {artist_name}")
        st.info("Your Streamlit version does not support st.modal; showing inline panel instead.")
        _render_body()
        if st.button("Close"):
            for k in ["albums_open","albums_artist_name","albums_list","singles_list","comps_list"]:
                st.session_state.pop(k, None)
            st.rerun()

# ===============
# Deep genre search (improve artist list)
# ===============

def deep_fetch_artists_by_genre_core(token: str, genre: str, per_bucket: int = 50, use_decades: bool = False):
    """Core fetch without UI side-effects. Splits search into buckets and deduplicates."""
    letters = [f"artist:{chr(c)}" for c in range(ord('a'), ord('z')+1)]
    digits = [f"artist:{d}" for d in list("0123456789")]
    buckets = letters + digits
    if use_decades:
        decades = [f"year:{y}-{y+9}" for y in (1960,1970,1980,1990,2000,2010,2020)]
        buckets += decades
    seen = {}
    for b in buckets:
        for offset in range(0, per_bucket, 50):
            q = f'genre:"{genre}" {b}'
            data = search_artists(token, q, limit=50, offset=offset)
            items = data.get('items', []) if data else []
            if not items:
                break
            for it in items:
                if it and it.get('id'):
                    seen[it['id']] = it
    return sorted(seen.values(), key=lambda a: a.get('followers',{}).get('total',0), reverse=True)

@st.cache_data(ttl=86400, show_spinner=False)
def deep_fetch_artists_by_genre_cached(genre: str, per_bucket: int = 50, use_decades: bool = False):
    # Use global TOKEN to avoid cache-busting by short-lived tokens
    return deep_fetch_artists_by_genre_core(TOKEN, genre, per_bucket, use_decades)

def safe_fetch_all_albums(artist_id: str):
    releases = fetch_all_albums(TOKEN, artist_id)
    if not releases:
        # token may have expired — try fresh
        fresh = get_spotify_token(CLIENT_ID, CLIENT_SECRET)
        if fresh:
            releases = fetch_all_albums(fresh, artist_id)
    return releases

@st.cache_data(ttl=86400, show_spinner=False)
def cached_fetch_all_albums(artist_id: str):
    return safe_fetch_all_albums(artist_id)

@st.cache_data(ttl=86400, show_spinner=False)
def cached_enrich(name: str):
    return enrich_from_external(name)

# ========= Playlist-driven discovery for free-text genres =========

def search_playlists_api(query: str, limit: int = 50, offset: int = 0) -> dict:
    headers = get_auth_header(TOKEN)
    r = requests.get(
        "https://api.spotify.com/v1/search",
        headers=headers,
        params={"q": query, "type": "playlist", "limit": limit, "offset": offset},
        timeout=15,
    )
    if r.status_code == 401:
        fresh = get_spotify_token(CLIENT_ID, CLIENT_SECRET)
        if fresh:
            r = requests.get(
                "https://api.spotify.com/v1/search",
                headers=get_auth_header(fresh),
                params={"q": query, "type": "playlist", "limit": limit, "offset": offset},
                timeout=15,
            )
    return r.json().get("playlists", {}) if r.status_code == 200 else {}


def fetch_playlist_tracks_api(playlist_id: str, max_items: int = 200) -> list[dict]:
    if not playlist_id:
        return []
    items = []
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    params = {"limit": 100}
    headers = get_auth_header(TOKEN)
    while url and len(items) < max_items:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code == 401:
            fresh = get_spotify_token(CLIENT_ID, CLIENT_SECRET)
            if fresh:
                headers = get_auth_header(fresh)
                r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code != 200:
            break
        j = r.json() or {}
        items.extend(j.get("items") or [])
        url = j.get("next")
        params = None
    return items[:max_items]


def fetch_artists_batch_api(ids: list[str]) -> list[dict]:
    out = []
    ids = [i for i in ids if i]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        r = requests.get(
            "https://api.spotify.com/v1/artists",
            headers=get_auth_header(TOKEN),
            params={"ids": ",".join(chunk)},
            timeout=12,
        )
        if r.status_code == 200:
            out.extend(r.json().get("artists", []))
    return out


@st.cache_data(ttl=86400, show_spinner=False)
def discover_artists_by_playlist_theme_cached(term: str, playlists_to_scan: int = 10, tracks_per_playlist: int = 100) -> list[dict]:
    # 1) Find playlists for the theme
    pls = []
    for offset in (0, 50):  # up to 100 playlists
        pl_page = search_playlists_api(term, limit=50, offset=offset) or {}
        items = pl_page.get("items") or []
        for p in items:
            if isinstance(p, dict) and p.get("id"):
                pls.append(p)
    # dedupe by playlist id & cap
    seen_pl = set()
    uniq_pls = []
    for p in pls:
        pid = p.get("id")
        if pid and pid not in seen_pl:
            seen_pl.add(pid)
            uniq_pls.append(p)
    pls = uniq_pls[:playlists_to_scan]

    # 2) Harvest artists from playlist tracks
    artist_ids = set()
    for pl in pls:
        pid = (pl or {}).get("id")
        if not pid:
            continue
        for item in (fetch_playlist_tracks_api(pid, max_items=tracks_per_playlist) or []):
            tr = (item or {}).get("track") or {}
            for a in (tr.get("artists") or []):
                aid = (a or {}).get("id")
                if aid:
                    artist_ids.add(aid)

    if not artist_ids:
        return []

    # 3) Fetch artist objects and sort by followers
    artists = fetch_artists_batch_api(list(artist_ids))
    artists = [a for a in artists if a and a.get("id")]
    artists.sort(key=lambda a: (a.get("followers", {}).get("total", 0)), reverse=True)
    return artists[:1000]


def deep_fetch_artists_by_genre(token: str, genre: str, per_bucket: int = 50, use_decades: bool = False, progress_label: str = ""):
    """UI wrapper with progress bar that calls the cached core."""
    with st.spinner(progress_label or f"Scanning genre '{genre}'…"):
        # We keep a small visual progress by chunking buckets, but rely on cache for speed
        return deep_fetch_artists_by_genre_cached(genre, per_bucket=per_bucket, use_decades=use_decades)

# ===============
# Actions (top bar)
# ===============

def update_genres_with_diagnostics():
    """Fetch Spotify genre seeds with detailed UI diagnostics and save to CSV."""
    tok = get_spotify_token(CLIENT_ID, CLIENT_SECRET)
    if not tok:
        st.error("Could not get a fresh Spotify token.")
        return
    try:
        r = requests.get(
            "https://api.spotify.com/v1/recommendations/available-genre-seeds",
            headers=get_auth_header(tok), timeout=12
        )
    except Exception as e:
        st.error("Network error while calling Spotify genre-seeds endpoint.")
        st.code(str(e))
        return
    if r.status_code == 200:
        try:
            genres = sorted(set(r.json().get("genres", [])))
        except Exception:
            genres = []
        if not genres:
            st.error("Spotify returned 200 but no genres array.")
            st.code(r.text[:2000])
            return
        save_genres_csv(genres, "spotify_genres.csv")
        st.success(f"Saved {len(genres)} genres to spotify_genres.csv")
        st.rerun()
        return
    # Non-200 → show diagnostics
    try:
        msg = r.json()
    except Exception:
        msg = r.text
    st.error(f"Spotify genre-seeds HTTP {r.status_code}")
    st.code(str(msg))


# Callbacks to auto-refresh on change

def _do_deep_scan_if_applicable():
    g = _current_genre()
    name = st.session_state.get('name_input')
    if st.session_state.get('deep_scan', True) and g and not name:
        st.session_state['page'] = 1
        if _is_free_text_genre():
            items = discover_artists_by_playlist_theme_cached(g)
        else:
            items = deep_fetch_artists_by_genre_cached(g, per_bucket=st.session_state.get('ds_per_bucket',50), use_decades=st.session_state.get('ds_decades', False))
        st.session_state['deep_items'] = items
        st.session_state.pop('query', None)

def on_genre_change():
    _do_deep_scan_if_applicable()

def on_genre_free_change():
    _do_deep_scan_if_applicable()

def _current_genre() -> str:
    g1 = (st.session_state.get('genre_input') or '').strip()
    g2 = (st.session_state.get('genre_free_input') or '').strip()
    return g2 or g1

def _is_free_text_genre() -> bool:
    return bool((st.session_state.get('genre_free_input') or '').strip())

def on_page_change():
    st.session_state['page'] = st.session_state.get('page_input', 1)

def on_deep_toggle():
    _do_deep_scan_if_applicable()

# Primary actions at top (Search prominent)

def on_search():
    st.session_state['page'] = st.session_state.get('page_input', 1)
    st.session_state['use_deep'] = st.session_state.get('deep_scan', True)
    name = st.session_state.get('name_input', '')
    current_genre = _current_genre()
    st.session_state['selected_name'] = name
    st.session_state['selected_genre'] = current_genre

    if name:
        parts = [f'artist:"{name}"']
        if current_genre:
            parts.append(f'genre:"{current_genre}"')
        st.session_state['query'] = " ".join(parts)
        st.session_state.pop('deep_items', None)
    elif current_genre:
        st.session_state.pop('query', None)
        if _is_free_text_genre():
            st.info("Discovering artists from themed playlists…")
            items = discover_artists_by_playlist_theme_cached(current_genre)
        else:
            st.info("Running deep scan… this may take a few seconds.")
            items = deep_fetch_artists_by_genre(TOKEN, current_genre, per_bucket=50, use_decades=False, progress_label=f"Genre: {current_genre}")
        st.session_state['deep_items'] = items
        st.success(f"Found {len(items)} artists for '{current_genre}'.")
    else:
        st.warning("Please set at least a name or a genre.")

col_actions1, col_actions2 = st.columns([1,1])
with col_actions1:
    if st.button("🔎 Search", use_container_width=True):
        on_search()
with col_actions2:
    if st.button("🧹 Reset filters", use_container_width=True):
        st.session_state['name_input'] = ""
        st.session_state['genre_input'] = ""
        st.session_state['genre_free_input'] = ""
        st.session_state['page_input'] = 1
        for k in [
            'query','deep_items','use_deep','albums_open','albums_artist_name',
            'albums_list','singles_list','comps_list','open_albums_for','albums_data']:
            st.session_state.pop(k, None)
        st.rerun()

# ===============
# Filters
# ===============
genres = load_genres_csv()
# show source of genres list
if os.path.exists("spotify_genres.csv"):
    st.caption(f"Loaded {len(genres)} genres from spotify_genres.csv")
elif os.path.exists("generos.csv"):
    st.caption(f"Loaded {len(genres)} genres from generos.csv (fallback)")
if mobile:
    name = st.text_input("🎤 Artist/Band Name", key="name_input")
    genre = st.selectbox("🎸 Genre (Spotify)", options=[""] + genres, key="genre_input", on_change=on_genre_change)
    genre_free = st.text_input("…or type a genre (free text)", key="genre_free_input", on_change=on_genre_free_change, placeholder="e.g., progressive rock", help="Use this even if the seed isn't in Spotify's list.")
    page = st.number_input("Page", min_value=1, value=1, key="page_input", on_change=on_page_change)
else:
    col1, col2, col3 = st.columns([2,2,1])
    with col1:
        name = st.text_input("🎤 Artist/Band Name", key="name_input")
    with col2:
        genre = st.selectbox("🎸 Genre (Spotify)", options=[""] + genres, key="genre_input", on_change=on_genre_change)
        genre_free = st.text_input("…or type a genre (free text)", key="genre_free_input", on_change=on_genre_free_change, placeholder="e.g., progressive rock", help="Use this even if the seed isn't in Spotify's list.")
    with col3:
        page = st.number_input("Page", min_value=1, value=1, key="page_input", on_change=on_page_change)

# Deep scan controls
if 'ds_per_bucket' not in st.session_state:
    st.session_state['ds_per_bucket'] = 50
if 'ds_decades' not in st.session_state:
    st.session_state['ds_decades'] = False

deep = st.checkbox("Improve artist list for genre (deep scan)", value=True, key='deep_scan', on_change=on_deep_toggle, help="Runs multiple searches (A–Z, 0–9) and deduplicates.")
with st.expander("Deep scan options"):
    st.session_state['ds_per_bucket'] = st.slider("Per bucket results", 50, 200, st.session_state['ds_per_bucket'], step=50, help="Max artists to request per bucket (50 per API page).")
    st.session_state['ds_decades'] = st.checkbox("Also split by decades (1960s…2020s)", value=st.session_state['ds_decades'])

# ===============
# Wikipedia styles — Top 50 by followers
render_wikipedia_styles_panel(TOKEN)

# ===============
# Results
# ===============
items = []
total = 0
from_deep = False

if st.session_state.get('deep_items') and not st.session_state.get('query'):
    # Use deep scan results
    all_items = st.session_state['deep_items']
    total = len(all_items)
    from_deep = True
    # paginate
    start = (st.session_state['page']-1)*20
    end = start + 20
    items = all_items[start:end]
    total_pages = (total-1)//20 + 1 if total else 0
    st.subheader(f"Page {st.session_state['page']}/{total_pages} — deep scan")
elif 'query' in st.session_state:
    # Normal search path
    artists_data = search_artists(
        TOKEN,
        st.session_state['query'],
        limit=20,
        offset=(st.session_state['page']-1)*20
    )
    total = artists_data.get('total', 0)
    items = artists_data.get('items', [])
    total_pages = (total-1)//20 + 1 if total else 0
    st.subheader(f"Page {st.session_state['page']}/{total_pages}")

# Render items (both paths)
for artist in items:
    with st.expander(f"{artist['name']} ({fmt(artist['followers']['total'])} followers)"):
        col_a, col_b = st.columns([2,1])
        with col_a:
            st.write(f"**Popularity:** {artist['popularity']}/100")
            genres_list = artist.get('genres') or []
            st.write(f"**Genres:** {', '.join(genres_list) if genres_list else '—'}")
            followers_fmt = fmt(artist['followers']['total'])
            if spotify_url := artist['external_urls'].get('spotify'):
                st.markdown(f"[Open in Spotify]({spotify_url}) • Followers: {followers_fmt}")
        with col_b:
            if images := artist.get('images'):
                st.image(images[0]['url'], width=120)

        # Overview (Spotify releases)
        releases = cached_fetch_all_albums(artist['id'])
        def _atype(it):
            return it.get('album_group') or it.get('album_type') or ''
        albums = [x for x in releases if _atype(x) == 'album']
        singles = [x for x in releases if _atype(x) == 'single']
        compilations = [x for x in releases if _atype(x) == 'compilation']
        def _year(it):
            d = it.get('release_date') or ''
            return d[:4] if len(d)>=4 else None
        years = sorted([y for y in {_year(x) for x in releases} if y])

        st.markdown("**📖 Overview (Spotify releases):**")
        if years:
            st.write(f"• First release on Spotify: {years[0]}")
            st.write(f"• Latest release on Spotify: {years[-1]}")
        st.write(f"• Releases: {len(releases)}  |  Albums: {len(albums)}  |  Singles/EPs: {len(singles)}  |  Compilations: {len(compilations)}")
        st.caption("Note: Dates reflect releases available on Spotify (reissues/remasters included).")

        # Enrichment (external sources)
        if st.button("📚 Enrich (Wikidata / MusicBrainz / Wikipedia / Discogs)", key=f"enrich_{artist['id']}"):
            st.session_state[f'enrich_data_{artist["id"]}'] = cached_enrich(artist['name'])
            st.rerun()

        ext = st.session_state.get(f'enrich_data_{artist["id"]}')
        if ext:
            mb = ext.get('musicbrainz', {})
            wd = ext.get('wikidata', {})
            wp = ext.get('wikipedia', {})
            dg = ext.get('discogs', {})
            st.markdown("**📚 Biography & Facts:**")
            if mb.get('begin') or mb.get('end'):
                st.write(f"• Career (MusicBrainz): {mb.get('begin','—')} — {mb.get('end','—')}")
            line = []
            if wd.get('inception'): line.append(f"Founded: {wd['inception']}")
            if wd.get('dissolved'): line.append(f"Dissolved: {wd['dissolved']}")
            if wd.get('members_count') is not None: line.append(f"Members: {wd['members_count']}")
            if line:
                st.write("• Wikidata: " + " | ".join(line))
            if wp:
                label = wp.get('title') or 'Wikipedia'
                if wp.get('url'):
                    st.write(f"• Wikipedia: [{label}]({wp['url']})")
                if wp.get('extract'):
                    st.write("**Summary (Wikipedia):**")
                    st.write(wp['extract'])
            if dg:
                if dg.get('members'):
                    st.write("• Discogs — Members: " + ", ".join(dg['members'][:20]) + ("…" if len(dg['members'])>20 else ""))
                if dg.get('profile'):
                    st.write("**Profile (Discogs):**")
                    st.write(dg['profile'])

        # Albums UI (mobile uses modal; desktop shows side panel)
        if mobile:
            if st.button(f"🗂 Albums ({len(albums)})", key=f"alb_btn_{artist['id']}"):
                if hasattr(st, "modal"):
                    with st.modal(f"Albums — {artist['name']}"):
                        st.write("**Albums (by year, desc)**")
                        for alb in sorted(albums, key=lambda x: x.get('release_date',''), reverse=True):
                            y = (alb.get('release_date') or '')[:4]
                            url = (alb.get('external_urls') or {}).get('spotify')
                            if url: st.markdown(f"- [{alb['name']}]({url}) ({y})")
                            else: st.markdown(f"- {alb['name']} ({y})")
                        if singles or compilations:
                            st.markdown('---')
                            if singles:
                                st.write("**Singles/EPs (latest 30)**")
                                for s in sorted(singles, key=lambda x: x.get('release_date',''), reverse=True)[:30]:
                                    y = (s.get('release_date') or '')[:4]
                                    url = (s.get('external_urls') or {}).get('spotify')
                                    if url: st.markdown(f"- [{s['name']}]({url}) ({y})")
                                    else: st.markdown(f"- {s['name']} ({y})")
                            if compilations:
                                st.write("**Compilations (latest 20)**")
                                for c in sorted(compilations, key=lambda x: x.get('release_date',''), reverse=True)[:20]:
                                    y = (c.get('release_date') or '')[:4]
                                    url = (c.get('external_urls') or {}).get('spotify')
                                    if url: st.markdown(f"- [{c['name']}]({url}) ({y})")
                                    else: st.markdown(f"- {c['name']} ({y})")
                else:
                    # Fallback inline (scrollable)
                    st.markdown("#### Albums")
                    html = "<div style='height: 60vh; overflow-y: scroll; padding-right: 8px; border: 1px solid #ddd; border-radius: 6px; padding: 10px; background: #fafafa; scrollbar-gutter: stable;'>"
                    for alb in sorted(albums, key=lambda x: x.get('release_date',''), reverse=True):
                        y = (alb.get('release_date') or '')[:4]
                        url = (alb.get('external_urls') or {}).get('spotify')
                        name = alb.get('name','—')
                        if url: html += f"<div><a href='{url}' target='_blank'>{name}</a> ({y})</div>"
                        else: html += f"<div>{name} ({y})</div>"
                    html += "</div>"
                    st.markdown(html, unsafe_allow_html=True)
        else:
            # Desktop: keep side-by-side panel
            cbtn, calist = st.columns([1,2])
            with cbtn:
                if st.button(f"🗂 Albums ({len(albums)})", key=f"alb_btn_{artist['id']}"):
                    st.session_state['open_albums_for'] = artist['id']
                    st.session_state['albums_data'] = {
                        'artist_name': artist['name'],
                        'albums': sorted(albums, key=lambda x: x.get('release_date',''), reverse=True),
                        'singles': sorted(singles, key=lambda x: x.get('release_date',''), reverse=True)[:30],
                        'comps': sorted(compilations, key=lambda x: x.get('release_date',''), reverse=True)[:20],
                    }
                    st.rerun()
            with calist:
                if st.session_state.get('open_albums_for') == artist['id']:
                    ad = st.session_state.get('albums_data', {})
                    st.markdown(f"#### Albums — {ad.get('artist_name', artist['name'])}")
                    # scrollable list to save vertical space
                    def _make_list(items):
                        out = []
                        for it in items:
                            y = (it.get('release_date') or '')[:4]
                            url = (it.get('external_urls') or {}).get('spotify')
                            name = it.get('name', '—')
                            if url:
                                out.append(f"<li><a href='{url}' target='_blank'>{name}</a> ({y})</li>")
                            else:
                                out.append(f"<li>{name} ({y})</li>")
                        return "\n".join(out)
                    parts = []
                    if ad.get('albums'):
                        parts.append("<strong>Albums (by year, desc)</strong><ul>" + _make_list(ad['albums']) + "</ul>")
                    if ad.get('singles'):
                        parts.append("<strong>Singles/EPs (latest 30)</strong><ul>" + _make_list(ad['singles']) + "</ul>")
                    if ad.get('comps'):
                        parts.append("<strong>Compilations (latest 20)</strong><ul>" + _make_list(ad['comps']) + "</ul>")
                    if not parts:
                        parts.append("<em>No releases available from Spotify for this artist (or token expired). Try Search again.</em>")
                    html = "<div style='height: 380px; overflow-y: scroll; padding-right: 8px; border: 1px solid #ddd; border-radius: 6px; padding: 10px; background: #fafafa; scrollbar-gutter: stable;'>" + "".join(parts) + "</div>"
                    st.markdown(html, unsafe_allow_html=True)
                    if st.button("Close albums", key=f"close_albums_{artist['id']}_panel"):
                        st.session_state.pop('open_albums_for', None)
                        st.session_state.pop('albums_data', None)
                        st.rerun()

# Sidebar
st.sidebar.header("🔧 Tools")
st.sidebar.info("Tip: on phones, enable 📱 Mobile mode for a slimmer layout. You can also type any genre in the free-text box and enable Deep Scan to broaden results.")
