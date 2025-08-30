# views/genres_page.py
import streamlit as st
from services.ui_helpers import ui_mobile  # opcional
from services.spotify.radio import find_artist_radio_playlist
from services.genre_csv import (
    load_hierarchy_csv, build_indices, norm,
    make_key as _key, build_context_keywords
)
from services.spotify.lookup import (
    get_spotify_token_cached, spotify_genre_top_artists,
    spotify_genre_playlists, embed_spotify
)
from services.page_help import show_page_help
from services.wiki import resolve_wikipedia_title


# -------------------------
# Cache helpers (performance)
# -------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def _build_indices_cached(df):
    """Cache dos índices para acelerar cliques entre ramos."""
    return build_indices(df)

@st.cache_data(ttl=86400, show_spinner=False)
def _resolve_wiki_cached(term: str):
    """Resolve título/URL da Wikipedia com cache."""
    title_pt, url_pt = resolve_wikipedia_title(term, lang="pt")
    if url_pt:
        return title_pt, url_pt
    title_en, url_en = resolve_wikipedia_title(term, lang="en")
    return title_en, url_en


# -------------------------
# Listas Spotify
# -------------------------
def _render_spotify_artist_list(artists: list[dict], play_prefix: str):
    if not artists:
        st.caption("sem informação")
        return
    for idx, a in enumerate(artists):
        cimg, cmain, cact = st.columns([1, 6, 3])
        with cimg:
            if a.get("image"):
                st.image(a["image"], width=56)
            else:
                st.empty()
        with cmain:
            st.markdown(f"**{a.get('name','—')}**")
            st.caption(f"Followers: {a.get('followers','—')} • Popularity: {a.get('popularity','—')}")
        with cact:
            c1, c2 = st.columns([1, 1])
            with c1:
                state_key = f"{play_prefix}_artist_{idx}_embed"
                if st.button("▶", key=f"{play_prefix}_art_btn_{idx}", help="Embed artist player"):
                    st.session_state[state_key] = True
                if st.session_state.get(state_key):
                    _id = (a or {}).get("id", "")
                    if _id:
                        embed_spotify("artist", _id, height=80)
            with c2:
                radio_state = f"{play_prefix}_artist_{idx}_radio"
                if st.button("📻", key=f"{play_prefix}_art_radio_{idx}", help="Open artist radio"):
                    token = get_spotify_token_cached()
                    try:
                        pl = find_artist_radio_playlist(token, (a or {}).get("name", ""))
                    except Exception:
                        pl = None
                    st.session_state[radio_state] = pl or {"id": "", "external_url": ""}
                _pl = st.session_state.get(radio_state) or {}
                if _pl.get("id"):
                    if _pl.get("external_url"):
                        st.markdown(f"[Open radio in Spotify]({_pl['external_url']})")
                    else:
                        st.caption("radio encontrada")
                elif _pl != {}:
                    st.caption("radio não encontrada")


def _render_spotify_playlist_list(playlists: list[dict], play_prefix: str):
    if not playlists:
        st.caption("sem informação")
        return
    for idx, p in enumerate(playlists):
        cimg, cmain, cact = st.columns([1, 7, 2])
        with cimg:
            if p.get("image"):
                st.image(p["image"], width=56)
            else:
                st.empty()
        with cmain:
            st.markdown(f"**{p.get('name','—')}**")
            st.caption(f"Owner: {p.get('owner','—')}")
        with cact:
            if p.get("url"):
                st.markdown(f"[Open in Spotify]({p['url']})")
            btn_key   = _key(f"{play_prefix}_pl_btn",   [p.get('id') or str(idx)])
            state_key = _key(f"{play_prefix}_pl_played",[p.get('id') or str(idx)])
            if st.button("▶", key=btn_key, help="Embed playlist"):
                st.session_state[state_key] = True
            if st.session_state.get(state_key):
                embed_spotify("playlist", p["id"], height=380)


# -------------------------
# Pesquisa auxiliar
# -------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def _flatten_all_paths(df):
    children, leaves, roots, leaf_url = build_indices(df)
    paths_set = set()
    level_cols = [c for c in df.columns if c.startswith("H")]
    level_cols.sort(key=lambda x: int(x[1:]) if x[1:].isdigit() else 99)
    for _, row in df.iterrows():
        cur = []
        for col in level_cols:
            val = (row.get(col) or "").strip()
            if not val:
                break
            cur.append(val)
            paths_set.add(tuple(cur))
    url_by_path = {}
    for _, row in df.iterrows():
        cur = []
        for col in level_cols:
            val = (row.get(col) or "").strip()
            if not val:
                break
            cur.append(val)
        if cur:
            url = (row.get("URL") or "").strip()
            if url:
                url_by_path[tuple(cur)] = url
    return sorted(paths_set), url_by_path


def _search_paths(paths, q, max_results=300):
    qn = norm(q)
    if not qn:
        return []
    hits = []
    for p in paths:
        if qn in norm(" / ".join(p)):
            hits.append(p)
            if len(hits) >= max_results:
                break
    return hits


# -------------------------
# Página
# -------------------------
def render_generos_page():
    show_page_help("genres", lang="PT")
    st.subheader("🧭 Genre hierarchy")

    # --- CSS ---
    st.markdown("""
    <style>
      /* TOP (Home + breadcrumbs): largura total e fundo cinza */
      .breadcrumbs div.stButton > button {
          width: 100%;
          background-color: #f0f2f6 !important;
          border-color: #d9d9d9 !important;
          box-shadow: none !important;
      }
      /* Nó ATUAL (desativado/destacado) */
      .breadcrumbs div.stButton > button[disabled]{
          background-color: #e6e9ef !important;
          border-color: #bfc3c9 !important;
          font-weight: 600;
      }
      /* LISTA de ramos: botões mais pequenos */
      .branches div.stButton > button {
          padding: 0.35rem 0.6rem;   /* ⇦ ajusta aqui o tamanho dos botões da lista */
          font-size: 0.9rem;
      }
    </style>
    """, unsafe_allow_html=True)

    # Título/ligação wiki para o género "contexto"
    parent_genre = (
        st.session_state.get("selected_genre")
        or st.session_state.get("genres_search_q")
        or "Rock"
    )
    _title, _url = _resolve_wiki_cached(parent_genre)
    if _url:
        st.markdown(f"**{parent_genre}** · [{'Wikipédia' if 'wikipedia.org' in _url else 'Wikipedia'}]({_url})")
    else:
        st.markdown(f"**{parent_genre}**")

    # Carregar DF
    try:
        df, used_path = load_hierarchy_csv()
    except Exception as e:
        st.error(str(e))
        return

    # Barra de pesquisa
    c_query, c_btn_s, c_btn_r = st.columns([6, 1, 1])
    with c_query:
        st.text_input(
            "Search",
            key="genres_search_q",
            placeholder="Pesquisar género/caminho (ex.: Art Rock ou Rock / Progressive)"
        )
    with c_btn_s:
        if st.button("🔎 Search", key="genres_top_search"):
            q = (st.session_state.get("genres_search_q") or "").strip()
            if not q:
                st.warning("Type something to search.")
            else:
                all_paths, url_by_path = _flatten_all_paths(df)
                hits = _search_paths(all_paths, q, max_results=300)
                st.session_state["genres_search_results"] = {"query": q, "hits": hits}
                st.session_state["genres_search_page"] = 1
    with c_btn_r:
        if st.button("🧹 Reset", key="genres_top_reset"):
            st.session_state.pop("genres_search_q", None)
            st.session_state.pop("genres_search_results", None)
            st.session_state.pop("genres_search_page", None)
            st.session_state["genres_path"] = []
            for k in list(st.session_state.keys()):
                if k.endswith(("_artists", "_playlists")) or k.startswith(("sr_spotify", "list_spotify")):
                    st.session_state.pop(k, None)

    # Índices cacheados
    children, leaves, roots, leaf_url = _build_indices_cached(df)

    # Caminho atual
    if "genres_path" not in st.session_state:
        st.session_state["genres_path"] = []
    path = st.session_state["genres_path"]
    prefix = tuple(path)

    # ---------------- Resultados de pesquisa ----------------
    found = st.session_state.get("genres_search_results")
    if found:
        q = found["query"]
        hits = found["hits"]
        st.markdown(f"**Results for**: `{q}`  \nTotal: **{len(hits)}**")
        page_size = 15
        page = int(st.session_state.get("genres_search_page", 1))
        total_pages = max((len(hits) + page_size - 1) // page_size, 1)

        with st.container(border=True):
            top, _p, _n = st.columns([6, 2, 2])
            with _p:
                if st.button("◀ Prev", key="genres_search_prev") and page > 1:
                    st.session_state["genres_search_page"] = page - 1
            with _n:
                if st.button("Next ▶", key="genres_search_next") and page < total_pages:
                    st.session_state["genres_search_page"] = page + 1
            st.caption(f"Page {page}/{total_pages}")

            start = (page - 1) * page_size
            chunk = hits[start: start + page_size]

            for idx, p in enumerate(chunk):
                # Link wiki à ESQUERDA, como pedido
                row = st.columns([1, 6, 1])  # wiki | label | Go
                with row[0]:
                    url = leaf_url.get(tuple(p))
                    if url:
                        st.markdown(f"[🔗]({url})", help="Wikipedia")
                    else:
                        st.caption(" ")
                with row[1]:
                    st.markdown(f"`{' / '.join(p)}`")
                with row[2]:
                    go_key = _key("sr_spotify_go", p, idx=idx)
                    if st.button("Go", key=go_key, help="Search in Spotify"):
                        token = get_spotify_token_cached()
                        try:
                            leaf = p[-1] if p else ""
                            ctx = build_context_keywords(list(p), leaf)
                            artists = spotify_genre_top_artists(token, ctx[0], ctx, limit=10)
                            playlists = spotify_genre_playlists(token, ctx[0], ctx, limit=10) if not artists else []
                            base = _key("sr_spotify", p, idx=idx)
                            st.session_state[f"{base}_artists"] = artists
                            st.session_state[f"{base}_playlists"] = playlists
                        except Exception:
                            base = _key("sr_spotify", p, idx=idx)
                            st.session_state[f"{base}_artists"] = []
                            st.session_state[f"{base}_playlists"] = []
                base = _key("sr_spotify", p, idx=idx)
                artists   = st.session_state.get(f"{base}_artists")
                playlists = st.session_state.get(f"{base}_playlists")
                if artists is not None or playlists is not None:
                    if artists:
                        st.markdown("**Artists**")
                        _render_spotify_artist_list(artists, play_prefix=f"{base}_art")
                    elif playlists:
                        st.markdown("**Playlists**")
                        _render_spotify_playlist_list(playlists, play_prefix=f"{base}_pl")
                    else:
                        st.caption("sem informação")

        st.divider()
        return

    # ---------------- Navegação normal ----------------
    # Títulos acima do topo
    st.markdown("### Current branch")
    st.write("Select a branch to drill down:")

    # TOP: breadcrumbs com tamanho original e cinza
    st.markdown('<div class="breadcrumbs">', unsafe_allow_html=True)

    bc_cols = st.columns(max(len(path), 1) + 1)
    with bc_cols[0]:
        if st.button("🏠 Home", key=_key("home", []), use_container_width=True):
            st.session_state["genres_path"] = []

    for i, label in enumerate(path, start=1):
        with bc_cols[i]:
            is_last = (i == len(path))
            if is_last:
                # nó atual destacado (desativado)
                st.button(label, key=_key("bc_active", path[:i]), disabled=True, use_container_width=True)
            else:
                if st.button(f"{label} ⤴", key=_key("bc", path[:i]), use_container_width=True):
                    st.session_state["genres_path"] = path[:i]

    st.markdown('</div>', unsafe_allow_html=True)

    # Se o nó atual tiver página wiki, referência
    cur_url = leaf_url.get(prefix)
    if cur_url:
        row = st.columns([7, 3])
        with row[0]:
            st.markdown(f"**This node has a Wikipedia page:** [🔗]({cur_url})")
        with row[1]:
            st.markdown(f"[🔗]({cur_url})", help="Wikipedia")

    # Lista de próximos ramos
    next_children = sorted(x for x in children.get(prefix, set()) if norm(x))

    # Área de ramos com botões menores e link à ESQUERDA
    st.markdown('<div class="branches">', unsafe_allow_html=True)

    if next_children:
        for idx, label in enumerate(next_children):
            child_path = path + [label]
            row = st.columns([1, 7])  # wiki | botão
            with row[0]:
                url = leaf_url.get(tuple(child_path))
                if url:
                    st.markdown(f"[🔗]({url})", help="Wikipedia")
                else:
                    st.caption(" ")
            with row[1]:
                if st.button(label, key=_key("branch", child_path, idx=idx)):
                    st.session_state["genres_path"] = list(child_path)
    else:
        # Nó terminal → folhas (texto + URL) com link à esquerda
        rows = leaves.get(prefix, [])
        if rows:
            st.write("Leaves in this branch:")
            for idx, (txt, url, p) in enumerate(rows[:1000]):
                row = st.columns([1, 7])  # wiki | texto
                with row[0]:
                    if url:
                        st.markdown(f"[🔗]({url})")
                    else:
                        st.caption("—")
                with row[1]:
                    st.markdown(f"**{txt}**  \n`{' / '.join(p)}`")
        else:
            st.info("No leaves under this node.")

    st.markdown('</div>', unsafe_allow_html=True)


# ----- Alias para compatibilidade -----
def render_genres_page():
    return render_generos_page()
