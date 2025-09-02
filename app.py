# app.py — Music & Cinema menu with Radio integrated

from __future__ import annotations
import os
import streamlit as st

# ---------- Spotify token ----------
from services.spotify import get_spotify_token
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
TOKEN = get_spotify_token(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)

# ---------- Music pages ----------
from views.spotify.page import render_spotify_page
from views.wiki_page import render_wikipedia_page
from views.genres_roots_page import render_genres_page_roots as render_genres_page
from views.playlists_page import render_playlists_page
# from views.genealogy_page_up_down import render_genealogy_page
# from views.influence_map import render_influence_map_page

# >>> NEW: Radio page (root-level radio.py). If you place it under views/radio/page.py,
# change this import to:  from views.radio.page import render_radio_page
from views.radio.radio import render_radio_page

# ---------- Cinema ----------
def _resolve_cinema_runner():
    try:
        # tenta primeiro a função nova; se não existir, usa a antiga como alias
        try:
            from cinema.page import render_cinema_page as _cin
        except ImportError:
            from cinema.page import render_page as _cin

        def run(section="Movies"):
            # o teu app passa 'section' ("Movies"/"Series"/"Soundtracks")
            # se a função não aceitar o parâmetro, cai no fallback sem argumentos
            try:
                return _cin(section=section)
            except TypeError:
                return _cin()
        return run
    except Exception as e:
        def run(section="Movies", _e=e):
            st.error(f"Cinema page not available: {_e}")
        return run

render_cinema = _resolve_cinema_runner()

# ---------- Page setup ----------
st.set_page_config(page_title="Music & Cinema", page_icon="🎛️", layout="wide")
st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# =========================================================
# Row 1 — domain selector
# =========================================================
domain = st.radio(
    label="domain",
    options=["🎵 Music", "🎬 Cinema"],
    horizontal=True,
    key="ui_domain",
    label_visibility="collapsed",
)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# =========================================================
# Row 2 — submenu per domain
# =========================================================
if domain.endswith("Music"):
    music_labels = [
        "🎧 Spotify",
        "🎼 Playlists",
        "📻 Radio",          # <<< NEW
        "🧭 Genres",
        "📚 Wikipedia",
        # "🧬 Genealogy",
        # "🗺️ Influence map",
    ]
    music_choice = st.radio(
        label="music_submenu",
        options=music_labels,
        horizontal=True,
        key="ui_music_submenu",
        label_visibility="collapsed",
    )
    selected = music_choice.split(" ", 1)[1] if " " in music_choice else music_choice

    st.markdown("---")
    if selected == "Spotify":
        render_spotify_page(TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    elif selected == "Radio":          # <<< NEW
        render_radio_page()
    elif selected == "Wikipedia":
        render_wikipedia_page(TOKEN)
    elif selected == "Genres":
        render_genres_page()
    elif selected == "Playlists":
        render_playlists_page()
    # elif selected == "Genealogy":
    #     render_genealogy_page()
    # elif selected == "Influence map":
    #     render_influence_map_page()

else:
    cinema_labels = ["🍿 Movies", "📺 Series", "🎼 Soundtracks"]
    cinema_choice = st.radio(
        label="cinema_submenu",
        options=cinema_labels,
        horizontal=True,
        key="ui_cinema_submenu",
        label_visibility="collapsed",
    )
    section = cinema_choice.split(" ", 1)[1] if " " in cinema_choice else cinema_choice

    st.markdown("---")
    render_cinema(section=section)
