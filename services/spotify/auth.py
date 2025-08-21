from __future__ import annotations
import os
import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE_DEFAULT = "playlist-modify-public playlist-modify-private user-read-private"

def _mk_auth() -> SpotifyOAuth:
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8501")
    scope = os.getenv("SPOTIFY_USER_SCOPES", SCOPE_DEFAULT)
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        cache_path=".cache-user",
        show_dialog=True,
    )

def clear_user_auth():
    """Limpa cache de autenticação."""
    st.session_state.pop("user_token_info", None)
    try:
        if os.path.exists(".cache-user"):
            os.remove(".cache-user")
    except Exception:
        pass

def ensure_user_spotify():
    """
    Devolve (spotipy_client, user_profile) autenticados via Authorization Code.
    Mostra botão de login se necessário. Faz refresh automático do token.
    """
    auth = _mk_auth()

    # Reusar/refresh se já houver token na sessão
    tok = st.session_state.get("user_token_info")
    if tok:
        try:
            if auth.is_token_expired(tok):
                tok = auth.refresh_access_token(tok["refresh_token"])
                st.session_state["user_token_info"] = tok
            sp = spotipy.Spotify(auth=tok["access_token"])
            me = sp.me()
            return sp, me
        except Exception:
            clear_user_auth()

    # Tentar obter "code" da URL (Streamlit moderno)
    code = None
    try:
        params = st.query_params
        code = params.get("code")
    except Exception:
        pass

    if not code:
        login_url = auth.get_authorize_url()
        st.link_button("🔑 Ligar à tua conta Spotify", login_url, use_container_width=False)
        return None, None

    # Troca code -> token
    try:
        tok = auth.get_access_token(code, as_dict=True)
        st.session_state["user_token_info"] = tok
        # Limpar o code da URL para não repetir
        try:
            st.query_params.clear()
        except Exception:
            pass
        sp = spotipy.Spotify(auth=tok["access_token"])
        me = sp.me()
        return sp, me
    except Exception:
        clear_user_auth()
        st.error("Falhou a autenticação. Clica no botão acima para tentar novamente.")
        return None, None

# --- Helpers de compatibilidade p/ chamadas HTTP diretas ---------------------

def get_user_access_token() -> str | None:
    """
    Devolve o access_token do utilizador (se já tiver feito login).
    """
    tok = st.session_state.get("user_token_info")
    if isinstance(tok, dict):
        return tok.get("access_token")
    return None


def get_auth_header(token: str | None = None) -> dict:
    """
    Devolve o header Authorization a partir de um token.
    Se token for None, tenta usar o token do utilizador em sessão.
    """
    if not token:
        token = get_user_access_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}
