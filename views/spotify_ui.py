# views/spotify_ui.py
import streamlit as st
from services.spotify import load_genres_csv
from services.ui_helpers import ui_mobile
from .spotify_helpers import reset_spotify_filters

# ============================================================
# Construção da query a partir do estado (não polui o campo Artist)
# ============================================================
def _compose_query_from_state() -> bool:
    s = st.session_state
    s.setdefault("page_input", 1)
    s["page"] = int(s.get("page_input", 1) or 1)

    # Artist separado da query para não aparecer genre:"..."
    name = (s.get("name_input") or "").strip()
    genre_free = (s.get("genre_free_input") or "").strip()
    genre_sel  = (s.get("genre_input") or "").strip()
    g = genre_free or genre_sel

    if name:
        # 🔧 Usar o texto do utilizador tal como está (ex.: yes, *yes*)
        #    e só acrescentar o género se existir
        parts = [name]
        if g:
            parts.append(f'genre:"{g}"')
        s["query"] = " ".join(parts)
        s.pop("deep_items", None)
        return True

    if g:
        s["query"] = f'genre:"{g}"'
        s.pop("deep_items", None)
        return True

    # Tudo vazio → avisar, sem esconder inputs
    st.warning("At least one of the fields must be filled in.")
    return False


def handle_spotify_search_click():
    if _compose_query_from_state():
        st.rerun()


def handle_spotify_reset_click():
    reset_spotify_filters()
    st.rerun()


# ============================================================
# Botões pequenos no topo (junto ao título)
# ============================================================
def render_top_action_buttons_spotify():
    """Mostra os dois botões pequenos junto ao título."""
    b1, b2 = st.columns([0.12, 0.18])
    with b1:
        if st.button("🔎 Search", key="sp_top_search"):
            handle_spotify_search_click()
    with b2:
        if st.button("🧹 Reset filters", key="sp_top_reset"):
            handle_spotify_reset_click()


# ============================================================
# Paginação (2ª linha): Pag: N  |  ◀ Previous  |  Next ▶
# ============================================================
def _ensure_page_state():
    s = st.session_state
    s.setdefault("page_input", 1)
    s.setdefault("page", 1)


def _goto_page(delta: int):
    _ensure_page_state()
    cur = int(st.session_state.get("page_input", 1) or 1)
    new = max(1, cur + delta)
    st.session_state["page_input"] = new
    st.session_state["page"] = new
    st.rerun()


def render_pagination_controls():
    """
    Segunda linha (display-only):
      [Pag: N]  |  [◀ Previous]  |  [Next ▶]
    """
    _ensure_page_state()
    pg = int(st.session_state.get("page_input", 1) or 1)

    cpage, cprev, cnext = st.columns([0.20, 0.14, 0.14])

    with cpage:
        st.markdown(
            f"<div style='height:38px;display:flex;align-items:center;'>"
            f"<strong>Pag:</strong>&nbsp;{pg}</div>",
            unsafe_allow_html=True,
        )

    with cprev:
        st.button(
            "◀ Previous",
            key="sp_page_prev",
            on_click=_goto_page,
            kwargs={"delta": -1},
            use_container_width=True,
        )

    with cnext:
        st.button(
            "Next ▶",
            key="sp_page_next",
            on_click=_goto_page,
            kwargs={"delta": 1},
            use_container_width=True,
        )


# ============================================================
# Filtros (1ª linha)
# ============================================================
def render_spotify_filters(genres=None):
    """Top filter bar for the Spotify page (Artist + genres)."""
    try:
        mobile = ui_mobile()
    except Exception:
        mobile = False

    # Conteúdo do selectbox:
    # 1) se vier por argumento, usa
    # 2) senão tenta session_state["genres_options"]
    # 3) fallback para load_genres_csv()
    if genres:
        genres_list = list(genres)
    else:
        genres_list = st.session_state.get("genres_options")
        if not genres_list:
            try:
                genres_list = load_genres_csv() or []
            except Exception:
                genres_list = []
        genres_list = list(genres_list)

    # Safety guard: se algum código externo tiver escrito genre:"..." no campo do artista, limpa
    if (st.session_state.get("name_input") or "").startswith('genre:"'):
        st.session_state["name_input"] = ""

    if mobile:
        new_q = st.text_input(
            "Artist",
            key="name_input",
            placeholder="Type in the artist. You can use * at the start and/or end.",
            help="Use * at the start and/or end: Genesis (exact), *Genesis (ends with), Genesis* (starts with), *Genesis* (contains).",
        )
        st.selectbox("Genre (Spotify seeds)", options=[""] + genres_list, key="genre_input")
        st.text_input("Genre (free text)", key="genre_free_input", placeholder="e.g., symphonic prog")
    else:
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            new_q = st.text_input(
                "Artist",
                key="name_input",
                placeholder="Type in the artist. You can use * at the start and/or end.",
                help="Use * at the start and/or end: Genesis (exact), *Genesis (ends with), Genesis* (starts with), *Genesis* (contains).",
            )
        with c2:
            st.selectbox("Genre (Spotify seeds)", options=[""] + genres_list, key="genre_input")
        with c3:
            st.text_input("Genre (free text)", key="genre_free_input", placeholder="e.g., symphonic prog")

    # Reset de página quando o campo Artist muda
    if new_q != st.session_state.get("_last_name_input", ""):
        st.session_state["_last_name_input"] = new_q
        st.session_state["page"] = 1

    # (Sem validação automática aqui; só no clique do Search.)
