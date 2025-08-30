# cinema/views/spotify_embed.py
import streamlit as st
import streamlit.components.v1 as components

# tenta usar a tua view (views/spotify)
_embed_fn = None
try:
    from views.spotify.embed import render_spotify_player as _embed_fn  # ex.: a tua função
except Exception:
    try:
        from views.spotify.player import render as _embed_fn
    except Exception:
        _embed_fn = None

def _to_embed_url(url_or_uri: str) -> str | None:
    s = (url_or_uri or "").strip()
    if not s:
        return None
    if s.startswith("spotify:"):
        # spotify:album:ID  → https://open.spotify.com/embed/album/ID
        parts = s.split(":")
        if len(parts) >= 3:
            return f"https://open.spotify.com/embed/{parts[1]}/{parts[2]}"
        return None
    # URL open.spotify.com → /embed/
    if "open.spotify.com/" in s and "/embed/" not in s:
        return s.replace("open.spotify.com/", "open.spotify.com/embed/")
    return s  # já deve ser embed

def render_player(url_or_uri: str, height: int = 152):
    """Mostra player embutido com a tua view se existir; senão iframe fallback."""
    if _embed_fn:
        try:
            return _embed_fn(url_or_uri, height=height)
        except TypeError:
            return _embed_fn(url_or_uri)
        except Exception:
            pass
    embed = _to_embed_url(url_or_uri)
    if not embed:
        st.info("Spotify item not playable.")
        return
    components.iframe(embed, height=height)
