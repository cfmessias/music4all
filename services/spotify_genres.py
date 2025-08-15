# services/spotify_genres.py
import requests
import streamlit as st

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_spotify_genre_seeds(token: str) -> list[str]:
    """
    Devolve a lista de 'available genre seeds' a partir da API do Spotify.
    Se falhar, devolve [] (o caller pode fazer fallback para CSV).
    """
    if not token:
        return []
    try:
        url = "https://api.spotify.com/v1/recommendations/available-genre-seeds"
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return []
        items = (r.json() or {}).get("genres") or []
        # normaliza/ordena
        return sorted({str(x).strip() for x in items if x})
    except Exception:
        return []
