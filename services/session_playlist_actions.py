# services/session_playlist_actions.py
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional

import streamlit as st


# ----------------------------
# Estado e utilitários
# ----------------------------

_PLAYLIST_KEY = "session_playlist_state"


def _ensure_state(default_name: str = "Music4all – Session") -> Dict[str, Any]:
    """Garante que existe estado para a session playlist."""
    if _PLAYLIST_KEY not in st.session_state:
        st.session_state[_PLAYLIST_KEY] = {
            "name": default_name,
            "tracks": [],  # cada item: {"title": str, "artist": str, "uri": str|None, "id": str|None}
        }
    return st.session_state[_PLAYLIST_KEY]


def add_track_to_session(title: str, artist: str, uri: Optional[str] = None, id_: Optional[str] = None) -> None:
    """API simples para outros módulos adicionarem faixas à session playlist."""
    state = _ensure_state()
    state["tracks"].append(
        {"title": title or "", "artist": artist or "", "uri": uri, "id": id_}
    )


def clear_session_playlist() -> None:
    """Esvazia as faixas, mantém o nome."""
    state = _ensure_state()
    state["tracks"] = []


def _human_count(n: int) -> str:
    return f"{n} track(s)" if n != 1 else "1 track"


# ----------------------------
# Integrações opcionais (hook)
# ----------------------------

def _try_send_to_spotify(tracks: List[Dict[str, Any]], name: str) -> None:
    """
    Tenta enviar para o Spotify chamando um 'hook' se existir.
    Procura por uma função `send_session_playlist_to_spotify(tracks, name)`
    em módulos conhecidos do projeto.
    """
    send_func = None
    # 1) Tentativa: services.spotify_playlists
    try:
        from services.spotify_playlists import send_session_playlist_to_spotify as _send  # type: ignore
        send_func = _send
    except Exception:
        send_func = None

    # 2) Tentativa: services.playlists_page (alguns projetos expõem lá)
    if send_func is None:
        try:
            from views.playlists_page import send_session_playlist_to_spotify as _send2  # type: ignore
            send_func = _send2
        except Exception:
            send_func = None

    if send_func is None:
        st.info("Não encontrei a integração de envio para o Spotify neste projeto.")
        return

    try:
        send_func(tracks, name)
        st.success("Playlist enviada para o Spotify.")
    except Exception as e:
        st.error(f"Falha ao enviar para o Spotify: {e}")


# ----------------------------
# Import via CSV
# ----------------------------

CSV_HINT = "CSV com cabeçalhos: title, artist, (opcional) uri/id"


def _import_csv(file) -> int:
    """Lê CSV e adiciona à session playlist. Retorna nº de linhas importadas."""
    if file is None:
        return 0
    content = file.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    rows = 0
    for row in reader:
        title = (row.get("title") or "").strip()
        artist = (row.get("artist") or "").strip()
        uri = (row.get("uri") or "").strip() or None
        id_ = (row.get("id") or "").strip() or None
        if not title and not uri and not id_:
            continue
        add_track_to_session(title, artist, uri, id_)
        rows += 1
    return rows


# ----------------------------
# UI principal (com expander)
# ----------------------------

def _render_inner_ui(
    default_name: str = "Music4all – Session",
    on_goto_playlists=None,
) -> None:
    state = _ensure_state(default_name)
    name = state.get("name") or default_name
    tracks = state.get("tracks", [])

    # Linha com nome + atalho para página de playlists
    c1, c2 = st.columns([0.7, 0.3])
    with c1:
        # Mantemos selectbox para compatibilidade visual (pode ser só uma opção)
        name = st.selectbox(
            "Playlist",
            options=[name],
            index=0,
            key="sess_pl_name",
        )
        state["name"] = name

    with c2:
        if st.button("Go to Playlists", use_container_width=True):
            if callable(on_goto_playlists):
                on_goto_playlists()
            else:
                # Pequena âncora informativa se não houver callback
                st.session_state["active_tab"] = "Playlists"
                st.experimental_rerun()

    # Botão enviar (em toda a largura)
    can_send = len(tracks) > 0
    if st.button("Send to Spotify", use_container_width=True, disabled=not can_send):
        if not can_send:
            st.warning("A playlist está vazia.")
        else:
            _try_send_to_spotify(tracks, name)

    # Uploader CSV
    up = st.file_uploader(
        "Drag and drop a CSV to create a new playlist",
        type=["csv"],
        help=CSV_HINT,
    )
    if up is not None:
        n = _import_csv(up)
        if n > 0:
            st.success(f"Importadas {n} linhas do CSV para **{name}**.")
        else:
            st.info("Não foram detectadas linhas válidas no CSV.")

    # Resumo atual (sem listar faixas individualmente para manter leve)
    st.caption(f"Current: **{name or 'unnamed'}** — {_human_count(len(tracks))}")
    if not tracks:
        st.info("This playlist has no tracks yet.")


def render_session_playlist_actions(
    *,
    default_name: str = "Music4all – Session",
    expanded: bool = False,
    title: str = "🎛️ Session playlist",
    on_goto_playlists=None,
) -> None:
    """
    Desenha a Session playlist **dentro de um expander**.
    - expanded=False → recolhido por defeito.
    - default_name   → nome inicial se o estado ainda não existir.
    - on_goto_playlists → callback opcional quando o utilizador clica em 'Go to Playlists'.
    """
    state = _ensure_state(default_name)
    st.caption(f"Current: **{state['name'] or 'unnamed'}** — {_human_count(len(state['tracks']))}")
    with st.expander(title, expanded=expanded):
        _render_inner_ui(default_name=default_name, on_goto_playlists=on_goto_playlists)


# Alias para compatibilidade (alguns projetos usam o singular)
def render_session_playlist_action(
    *args, **kwargs
) -> None:  # pragma: no cover - simples alias
    render_session_playlist_actions(*args, **kwargs)


# Wrapper explícito (se quiseres chamar directamente noutras páginas)
def render_session_playlist_expander(
    collapsed: bool = True, title: str = "🎛️ Session playlist", **kwargs
) -> None:
    render_session_playlist_actions(expanded=not collapsed, title=title, **kwargs)
