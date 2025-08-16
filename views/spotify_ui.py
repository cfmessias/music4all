# views/spotify_ui.py
import streamlit as st
from services.ui_helpers import ui_mobile
from services.spotify import load_genres_csv
from .spotify_helpers import reset_spotify_filters

# ============================================================
# Compose query (sem “sujar” o campo Artist quando é só género)
# ============================================================
def _compose_query_from_state() -> bool:
    s = st.session_state
    s.setdefault("page_input", 1)
    s["page"] = int(s.get("page_input", 1) or 1)

    # O input “Artist” usa key="query" e mantém-se limpo
    name = (s.get("query") or "").strip()
    genre_free = (s.get("genre_free_input") or "").strip()
    genre_sel = (s.get("genre_input") or "").strip()

    if name:
        parts = [f'artist:"{name}"']
        g = genre_free or genre_sel
        if g:
            parts.append(f'genre:"{g}"')
        s["query_effective"] = " ".join(parts)
        s.pop("deep_items", None)
        return True

    if genre_free or genre_sel:
        s["query_effective"] = f'genre:"{genre_free or genre_sel}"'
        s.pop("deep_items", None)
        return True

    # Só avisa se tudo estiver vazio (não esconde inputs)
    if not name and not genre_sel and not genre_free:
        st.warning("At least one of the fields must be filled in.")
    return False


def handle_spotify_search_click():
    # Se não há filtros/artist, garantimos que limpamos a última pesquisa
    if not _compose_query_from_state():
        st.session_state.pop("query_effective", None)
        st.session_state["page"] = 1
        st.session_state["page_input"] = 1


def handle_spotify_reset_click():
    reset_spotify_filters()
    # Limpeza explícita do que pode manter resultados antigos visíveis
    for k in [
        "query_effective", "query",               # query final + input de artista
        "genre_input", "genre_free_input",        # géneros (seeds + free text)
        "page", "page_input", "sp_total_pages",   # paginação
        "_last_query",
    ]:
        st.session_state.pop(k, None)


def render_top_action_buttons_spotify():
    """Botões pequenos ao lado do título, iguais aos da página wiki."""
    b1, b2 = st.columns([0.12, 0.18])
    with b1:
        st.button("🔎 Search", key="sp_top_search", on_click=handle_spotify_search_click)
    with b2:
        st.button("🧹 Reset filters", key="sp_top_reset", on_click=handle_spotify_reset_click)


# ============================================================
# Paginação (mesma linha: Pag: N/M | ◀ Previous | Next ▶)
# ============================================================
def _ensure_page_state():
    s = st.session_state
    s.setdefault("page_input", 1)
    s.setdefault("page", 1)
    s.setdefault("sp_total_pages", 1)


def _goto_page(delta: int):
    _ensure_page_state()
    cur = int(st.session_state.get("page_input", 1) or 1)
    total = int(st.session_state.get("sp_total_pages", 1) or 1)
    new = max(1, min(total, cur + delta))
    st.session_state["page_input"] = new
    st.session_state["page"] = new
   


def render_pagination_controls():
    """Barra compacta (igual à wiki)."""
    _ensure_page_state()
    pg = int(st.session_state.get("page_input", 1) or 1)
    total = int(st.session_state.get("sp_total_pages", 1) or 1)

    cpage, cprev, cnext = st.columns([0.20, 0.14, 0.14])
    with cpage:
        st.markdown(
            f"<div style='height:38px;display:flex;align-items:center;'>"
            f"<strong>Pag:</strong>&nbsp;{pg}/{total}</div>",
            unsafe_allow_html=True,
        )
    with cprev:
        st.button(
            "◀ Previous",
            key="sp_page_prev",
            on_click=_goto_page,
            kwargs={"delta": -1},
            disabled=(pg <= 1),
            use_container_width=True,
        )
    with cnext:
        st.button(
            "Next ▶",
            key="sp_page_next",
            on_click=_goto_page,
            kwargs={"delta": 1},
            disabled=(pg >= total),
            use_container_width=True,
        )


# ============================================================
# Filtros (linha superior)
# ============================================================
def render_spotify_filters(genres=None):
    """Barra de filtros (Artist + Spotify seeds + free text)."""
    try:
        mobile = ui_mobile()
    except Exception:
        mobile = False

    # garantir lista de géneros
    if genres is None:
        genres = st.session_state.get("genres_list") or (load_genres_csv() or [])
    genres = list(genres)

    if mobile:
        new_q = st.text_input(
            "Artist",
            key="query",
            placeholder="Type the artist in the search box at the top. You can use * at the start and/or end.",
            help="Use * at the start and/or end: Genesis (exact), *Genesis (ends with), Genesis* (starts with), *Genesis* (contains).",
        )
        st.selectbox("Genre (Spotify seeds)", options=[""] + genres, key="genre_input")
        st.text_input("Genre (free text)", key="genre_free_input", placeholder="e.g., symphonic prog")
    else:
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            new_q = st.text_input(
                "Artist",
                key="query",
                placeholder="Type the artist in the search box at the top. You can use * at the start and/or end.",
                help="Use * at the start and/or end: Genesis (exact), *Genesis (ends with), Genesis* (starts with), *Genesis* (contains).",
            )
        with c2:
            st.selectbox("Genre (Spotify seeds)", options=[""] + genres, key="genre_input")
        with c3:
            st.text_input("Genre (free text)", key="genre_free_input", placeholder="e.g., symphonic prog")

    # reset da paginação quando o texto muda
    if new_q != st.session_state.get("_last_query", ""):
        st.session_state["_last_query"] = new_q
        st.session_state["page"] = 1
        st.session_state["page_input"] = 1
