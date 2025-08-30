# views/genres/spotify_widgets.py
import streamlit as st
from services.spotify.lookup import (
    get_spotify_token_cached, embed_spotify
)
from services.spotify.radio import find_artist_radio_playlist

def render_artist_list(artists, play_prefix: str):
    if not artists:
        st.caption("no data"); return
    for idx, a in enumerate(artists):
        cimg, cmain, cact = st.columns([1, 6, 3])
        with cimg:
            if a.get("image"): st.image(a["image"], width=56)
            else: st.empty()
        with cmain:
            st.markdown(f"**{a.get('name','—')}**")
            st.caption(f"Followers: {a.get('followers','—')} • Popularity: {a.get('popularity','—')}")
        with cact:
            a1, a2 = st.columns([1, 1])
            with a1:
                state_key = f"{play_prefix}_artist_{idx}_embed"
                if st.button("▶", key=f"{play_prefix}_art_btn_{idx}", help="Embed artist player"):
                    st.session_state[state_key] = True
                if st.session_state.get(state_key):
                    _id = (a or {}).get("id", "")
                    if _id: embed_spotify("artist", _id, height=80)
            with a2:
                radio_state = f"{play_prefix}_artist_{idx}_radio"
                if st.button("📻", key=f"{play_prefix}_art_radio_{idx}", help="Open artist radio"):
                    token = get_spotify_token_cached()
                    try:
                        pl = find_artist_radio_playlist(token, (a or {}).get("name", ""))
                    except Exception:
                        pl = None
                    st.session_state[radio_state] = pl or {"id": "", "external_url": ""}
                _pl = st.session_state.get(radio_state) or {}
                if _pl.get("id"):
                    if _pl.get("external_url"): st.markdown(f"[Open radio in Spotify]({_pl['external_url']})")
                    else: st.caption("radio found")
                elif _pl != {}:
                    st.caption("radio not found")

def render_playlist_list(playlists, play_prefix: str):
    if not playlists:
        st.caption("no data"); return
    for idx, p in enumerate(playlists):
        cimg, cmain, cact = st.columns([1, 7, 2])
        with cimg:
            if p.get("image"): st.image(p["image"], width=56)
            else: st.empty()
        with cmain:
            st.markdown(f"**{p.get('name','—')}**")
            st.caption(f"Owner: {p.get('owner','—')}")
        with cact:
            if p.get("url"): st.markdown(f"[Open in Spotify]({p['url']})")
            btn_key   = f"{play_prefix}_pl_btn_{p.get('id') or idx}"
            state_key = f"{play_prefix}_pl_played_{p.get('id') or idx}"
            if st.button("▶", key=btn_key, help="Embed playlist"):
                st.session_state[state_key] = True
            if st.session_state.get(state_key):
                from services.spotify.lookup import embed_spotify
                embed_spotify("playlist", p["id"], height=380)
