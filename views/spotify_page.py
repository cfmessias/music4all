# views/spotify_page.py
import streamlit as st

# módulos existentes do teu projeto
from services.spotify import load_genres_csv
from services.spotify_genres import fetch_spotify_genre_seeds  # novo ficheiro
from .spotify_ui import render_spotify_filters
from .spotify_results import render_spotify_results
from .spotify_ui import render_spotify_filters, render_top_action_buttons_spotify
from .spotify_results import render_spotify_results

def render_spotify_page(token: str, client_id: str, client_secret: str):
    """
    Página Spotify (assinatura mantida).
    - Pré-carrega lista de géneros (Spotify API; fallback CSV) e guarda em st.session_state['genres_list'].
    - Desenha os filtros (que usam 'genres_list' no selectbox).
    - Renderiza os resultados conforme st.session_state['query'].
    """
    st.subheader("🎧 Spotify")
    render_top_action_buttons_spotify()  # <- aparecem ao lado do título


    # 1) tentar buscar géneros diretamente à API do Spotify (recomendado)
    # 2) fallback para o CSV local (load_genres_csv) — mantém compatibilidade
    # 3) se tudo falhar, fica lista vazia (selectbox mostra opção vazia)
    spotify_genres = fetch_spotify_genre_seeds(token) or (load_genres_csv() or [])
    st.session_state["genres_list"] = spotify_genres

    # Ajuda rápida (podes comentar)
    # st.caption(f"Loaded {len(spotify_genres)} genres")

    # Render dos filtros (atualiza st.session_state['query'] ao carregar em Search)
    render_spotify_filters()

    # Resultados (usa token para chamadas à API)
    render_spotify_results(token)
