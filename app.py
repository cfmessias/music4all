# app.py — Music4all (views/ structure)
import os
import streamlit as st
from views.influence_map import render_influence_map_page
from services.spotify import get_spotify_token
from views.spotify_page import render_spotify_page
from views.wiki_page import render_wikipedia_page
from views.playlists_page import render_playlists_page
from views.genres_page import render_genres_page
# NOTA: não importamos radio_debug_page aqui; só importamos dentro do ramo se DEV_DEBUG=True

# ---------------------------
#  Modo de desenvolvimento
# ---------------------------
DEV_DEBUG = False  # <<< coloca True para mostrar a página "📻 Radio (debug)"

st.set_page_config(
    page_title="Music4all",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.title("🎵 Music4all")

# Toggles visíveis por baixo do título
c_mob, c_ap = st.columns([1, 1])
with c_mob:
    st.toggle("📱 Mobile layout", key="ui_mobile")
with c_ap:
    st.toggle("🔊 Audio previews", key="ui_audio_preview")

# Secrets -> env
for _k in ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "DISCOGS_USER_AGENT", "DISCOGS_TOKEN"]:
    try:
        if _k in st.secrets and st.secrets[_k]:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

TOKEN = get_spotify_token(CLIENT_ID, CLIENT_SECRET)
if not TOKEN:
    st.error("❌ Não foi possível autenticar na API do Spotify.")
    st.stop()

# ---------------------------
#  Top nav (radio horizontal)
# ---------------------------
# Lista de tabs (pode ser alterada dependendo do modo de desenvolvimento)
base_tabs = ['🎧 Spotify', '📚 Wikipedia', '🧭 Genres', '🎶 Playlists', '🗺️ Influence map', '🧩 Genre map']
tabs = base_tabs + ['📻 Radio (debug)'] if DEV_DEBUG else base_tabs

# garantir um valor inicial coerente
if 'active_tab' not in st.session_state:
    st.session_state['active_tab'] = tabs[0]
# se o valor antigo já não existir (p.ex. DEV_DEBUG desligado), forçar primeiro tab
if st.session_state['active_tab'] not in tabs:
    st.session_state['active_tab'] = tabs[0]

# escolher tab
prev = st.session_state.get('active_tab', tabs[0])
if prev not in tabs:
    prev = tabs[0]

active_tab = st.radio(
    'Sections',
    tabs,
    index=tabs.index(prev),
    horizontal=True,
    key='active_tab',
    label_visibility='collapsed',
)

# ---------------------------
#  Router
# ---------------------------
if active_tab == '🎧 Spotify':
    render_spotify_page(TOKEN, CLIENT_ID, CLIENT_SECRET)

elif active_tab == '📚 Wikipedia':
    render_wikipedia_page(TOKEN)

elif active_tab == '🧭 Genres':
    render_genres_page()

elif active_tab == '🗺️ Influence map':
    render_influence_map_page()

elif active_tab == '🧩 Genre map':
    from views.genre_map_auto import render_genre_map_page
    render_genre_map_page()

elif DEV_DEBUG and active_tab == '📻 Radio (debug)':
    from views.radio_debug_page import render_radio_debug_page
    render_radio_debug_page(TOKEN)

else:  # '🎶 Playlists'
    render_playlists_page()

