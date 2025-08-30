# views/spotify/page.py

import streamlit as st

# módulos existentes do teu projeto
from services.spotify import load_genres_csv
from services.spotify.genres import fetch_spotify_genre_seeds  # opcional: se existir
from .components.legacy_ui import (
    render_spotify_filters,
    render_top_action_buttons_spotify,
    render_pagination_controls,
)
from .results import render_spotify_results
from views.spotify.results import render_spotify_results


def render_spotify_page(token: str, client_id: str, client_secret: str):
    """
    Página Spotify.
    - Pré-carrega lista de géneros (Spotify API; fallback CSV) e guarda em st.session_state['genres_list'].
    - Desenha os filtros (que usam 'genres_list' no selectbox).
    - Mostra barra de paginação (Pag: N/M | Prev | Next) na mesma linha, estilo wiki.
    - Renderiza os resultados conforme st.session_state['query'].
    """
    st.subheader("🎧 Spotify")
    render_top_action_buttons_spotify()  # botões pequenos ao lado do título

    # 1) tentar buscar géneros à API do Spotify (se não tiveres, captura exceção e usa CSV)
    try:
        spotify_genres = fetch_spotify_genre_seeds(token) or (load_genres_csv() or [])
    except Exception:
        spotify_genres = load_genres_csv() or []
    st.session_state["genres_list"] = spotify_genres

    # 2) filtros (usa a lista acima)
    render_spotify_filters(genres=spotify_genres)

    # 3) paginação na MESMA linha (Pag: N/M | ◀ Previous | Next ▶)
    render_pagination_controls()

    # 4) resultados
    render_spotify_results(token)
