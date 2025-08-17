# views/genres_page.py
import streamlit as st
from services.ui_helpers import ui_mobile  # mantido, mas layout é forçado a "mobile"
from services.spotify_radio import find_artist_radio_playlist
from services.genre_csv import (
    load_hierarchy_csv, build_indices, norm,
    make_key as _key, build_context_keywords
)
from services.spotify_lookup import (
    get_spotify_token_cached, spotify_genre_top_artists,
    spotify_genre_playlists, embed_spotify
)

# -------------------------------------------------
# Renders auxiliares (listas Spotify)
# -------------------------------------------------
def _render_spotify_artist_list(artists: list[dict], play_prefix: str):
    if not artists:
        st.caption("sem informação"); return
    for idx, a in enumerate(artists):
        cimg, cmain, cact = st.columns([1, 6, 3])   # layout compacto “mobile”
        with cimg:
            if a.get("image"): st.image(a["image"], width=56)
            else: st.empty()
        with cmain:
            st.markdown(f"**{a.get('name','—')}**")
            st.caption(f"Followers: {a.get('followers','—')} • Popularity: {a.get('popularity','—')}")

        with cact:
            a1, a2 = st.columns([1, 1])

            # ▶ tocar/embutir o artista
            with a1:
                state_key = f"{play_prefix}_artist_{idx}_embed"
                if st.button("▶", key=f"{play_prefix}_art_btn_{idx}", help="Embed artist player"):
                    st.session_state[state_key] = True
                if st.session_state.get(state_key):
                    _id = (a or {}).get("id", "")
                    if _id:
                        embed_spotify("artist", _id, height=80)

            # 📻 procurar e mostrar a playlist "Artist Radio"
            with a2:
                radio_state = f"{play_prefix}_artist_{idx}_radio"
                if st.button("📻", key=f"{play_prefix}_art_radio_{idx}", help="Open artist radio"):
                    token = get_spotify_token_cached()
                    pl = None
                    try:
                        pl = find_artist_radio_playlist(token, (a or {}).get("name", ""))
                    except Exception:
                        pl = None
                    if pl and pl.get("id"):
                        st.session_state[radio_state] = pl
                    else:
                        st.session_state[radio_state] = {"id": "", "external_url": ""}

                _pl = st.session_state.get(radio_state) or {}
                if _pl.get("id"):
                    if _pl.get("external_url"):
                        st.markdown(f"[Open radio in Spotify]({_pl['external_url']})")
                    embed_spotify("playlist", _pl["id"], height=80)
                elif _pl != {} and not _pl.get("id"):
                    st.caption("Radio not available")


def _render_spotify_playlist_list(playlists: list[dict], play_prefix: str):
    if not playlists:
        st.caption("sem informação"); return
    for idx, p in enumerate(playlists):
        cimg, cmain, cact = st.columns([1, 6, 3])   # layout compacto “mobile”
        with cimg:
            if p.get("image"): st.image(p["image"], width=56)
            else: st.empty()
        with cmain:
            st.markdown(f"**{p.get('name','—')}**")
            st.caption(f"Owner: {p.get('owner','—')}")
        with cact:
            if p.get("url"): st.markdown(f"[Open in Spotify]({p['url']})")
            btn_key   = _key(f"{play_prefix}_pl_btn",   [p.get('id') or str(idx)])
            state_key = _key(f"{play_prefix}_pl_played",[p.get('id') or str(idx)])
            if st.button("▶", key=btn_key, help="Embed playlist"):
                st.session_state[state_key] = True
            if st.session_state.get(state_key):
                embed_spotify("playlist", p["id"], height=380)


# -------------------------------------------------
# Helpers de pesquisa
# -------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def _flatten_all_paths(df):
    """
    Extrai todos os caminhos possíveis:
      - todos os prefixos de H1..H7
      - caminhos completos incluindo 'Texto' (quando existir)
    Devolve:
      - paths: list[tuple[str,...]] (sem duplicados)
      - url_by_path: dict[path_tuple] -> url (quando este path é folha nalgum registo)
    """
    children, leaves, roots, leaf_url = build_indices(df)
    paths_set = set()

    level_cols = [c for c in df.columns if c.startswith("H")]
    level_cols.sort(key=lambda x: int(x[1:]) if x[1:].isdigit() else 99)

    for _, r in df.iterrows():
        levels = [norm(r.get(c, "")) for c in level_cols]
        levels = [x for x in levels if x]

        for i in range(1, len(levels) + 1):
            p = tuple(levels[:i])
            if p:
                paths_set.add(p)

        txt = norm(r.get("Texto", ""))
        if txt:
            full = tuple(levels + [txt]) if levels and levels[-1] != txt else tuple(levels)
            if full:
                paths_set.add(full)

    paths = sorted(paths_set, key=lambda t: " / ".join(t).lower())
    return paths, leaf_url


def _normlower(s: str) -> str:
    return norm(s).lower()


def _search_paths(paths, query: str, max_results: int = 200):
    q = _normlower(query)
    if not q:
        return []
    out = []
    for p in paths:
        hay = " / ".join(p).lower()
        if q in hay:
            out.append(p)
            if len(out) >= max_results:
                break
    return out


# -------------------------------------------------
# Página
# -------------------------------------------------
def render_generos_page():
    st.subheader("🧭 Genre hierarchy")

    try:
        df, used_path = load_hierarchy_csv()

        # --- Top action buttons ---
        top_btn_1, top_btn_2 = st.columns([0.12, 0.18])

        with top_btn_1:
            if st.button("🔎 Search", key="genres_top_search"):
                q = (st.session_state.get("genres_search_q") or "").strip()
                if not q:
                    st.warning("Type something to search.")
                else:
                    all_paths, url_by_path = _flatten_all_paths(df)
                    hits = _search_paths(all_paths, q, max_results=300)
                    st.session_state["genres_search_results"] = {"query": q, "hits": hits}
                    st.session_state["genres_search_page"] = 1  # começa na 1.ª página

        with top_btn_2:
            if st.button("🧹 Reset filters", key="genres_top_reset"):
                # limpa input e resultados/paginação
                st.session_state["genres_search_q"] = ""
                st.session_state.pop("genres_search_results", None)
                st.session_state.pop("genres_search_page", None)
                # volta à raiz da hierarquia
                st.session_state["genres_path"] = []
                # apaga quaisquer resíduos antigos
                for k in list(st.session_state.keys()):
                    if k.endswith(("_artists", "_playlists")) or k.startswith(("sr_spotify", "list_spotify")):
                        st.session_state.pop(k, None)

    except Exception as e:
        st.error(str(e)); return

    children, leaves, roots, leaf_url = build_indices(df)

    # estado do caminho atual
    if "genres_path" not in st.session_state:
        st.session_state["genres_path"] = []
    path = st.session_state["genres_path"]
    prefix = tuple(path)

    # ---------------------------
    # PESQUISA
    # ---------------------------
    st.text_input("Search genres/styles", key="genres_search_q", placeholder="e.g., art rock")

    # Mostrar resultados de pesquisa (se houver)
    sr = st.session_state.get("genres_search_results")
    if sr:
        q = sr.get("query", "")
        hits = sr.get("hits") or []
        st.markdown(f"**Search results for _{q}_** ({len(hits)} paths)")
        if not hits:
            st.info("No matches.")
        else:
            # paginação simples
            page = int(st.session_state.get("genres_search_page", 1))
            page_size = 50
            total_pages = (len(hits) - 1) // page_size + 1
            top, _p, _n = st.columns([6, 2, 2])
            with _p:
                if st.button("◀ Prev", key="genres_search_prev") and page > 1:
                    st.session_state["genres_search_page"] = page - 1
            with _n:
                if st.button("Next ▶", key="genres_search_next") and page < total_pages:
                    st.session_state["genres_search_page"] = page + 1
            st.caption(f"Page {page}/{total_pages}")

            start = (page - 1) * page_size
            chunk = hits[start : start + page_size]

            for idx, p in enumerate(chunk):
                label = " / ".join(p)
                row = st.columns([6, 2, 1])     # label | wiki | Go

                # label
                with row[0]:
                    st.markdown(f"`{label}`")

                # wiki (se existir)
                with row[1]:
                    url = leaf_url.get(tuple(p))
                    if url:
                        st.markdown(f"[🔗]({url})", help="Wikipedia")
                    else:
                        st.caption(" ")

                # Go → faz lookup Spotify (comportamento antigo do 🎧)
                with row[2]:
                    gkey = _key("sr_go", p, idx=idx)
                    if st.button(
                        "Go",
                        key=gkey,
                        use_container_width=True,
                        help="List Spotify artists/playlists for this path",
                    ):
                        token = get_spotify_token_cached()
                        if not token:
                            st.warning("No Spotify token disponível.")
                        else:
                            # Fecha qualquer outro bloco aberto desta área (pesquisa)
                            for k in list(st.session_state.keys()):
                                if k.startswith("sr_spotify"):
                                    st.session_state.pop(k, None)

                            leaf = p[-1] if p else ""
                            ctx = build_context_keywords(list(p), leaf)

                            artists = spotify_genre_top_artists(token, ctx[0], ctx, limit=10)
                            playlists = spotify_genre_playlists(token, ctx[0], ctx, limit=10) if not artists else []

                            base = _key("sr_spotify", p, idx=idx)
                            st.session_state[f"{base}_artists"] = artists
                            st.session_state[f"{base}_playlists"] = playlists


                # render dos resultados logo abaixo deste item (se já houver)
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

    # ---------------------------
    # Navegação normal por ramos
    # ---------------------------
    # breadcrumbs
    bc_cols = st.columns(max(len(path), 1) + 1)
    with bc_cols[0]:
        if st.button("🏠 Home", use_container_width=True, key=_key("home", [])):
            st.session_state["genres_path"] = []
    for i, label in enumerate(path, start=1):
        with bc_cols[i]:
            if st.button(f"{label} ⤴", use_container_width=True, key=_key("bc", path[:i])):
                st.session_state["genres_path"] = path[:i]

    # Se o próprio nó atual tiver página wiki (folha nalguma linha), mostra link
    cur_url = leaf_url.get(prefix)
    if cur_url:
        row = st.columns([7, 3])  # texto | link
        with row[0]:
            st.markdown(f"**This node has a Wikipedia page:** [🔗]({cur_url})")
        with row[1]:
            st.markdown(f"[🔗]({cur_url})", help="Wikipedia")

    st.markdown("### Current branch")

    # próximos ramos
    next_children = sorted(x for x in children.get(prefix, set()) if norm(x))
    if next_children:
        st.write("Select a branch to drill down:")
        for idx, label in enumerate(next_children):
            child_path = path + [label]
            row = st.columns([7, 1])  # nome | wiki
            with row[0]:
                if st.button(label, key=_key("branch", child_path, idx=idx), use_container_width=True):
                    st.session_state["genres_path"] = list(child_path)
            with row[1]:
                url = leaf_url.get(tuple(child_path))
                if url: st.markdown(f"[🔗]({url})", help="Wikipedia")
                else:   st.caption(" ")
    else:
        # nó terminal → folhas (Texto + URL)
        rows = leaves.get(prefix, [])
        if rows:
            st.write("Leaves in this branch:")
            for idx, (txt, url, p) in enumerate(rows[:1000]):
                row = st.columns([7, 1])
                with row[0]:
                    st.markdown(f"**{txt}**  \n`{' / '.join(p)}`")
                with row[1]:
                    if url: st.markdown(f"[Wikipedia]({url})")
                    else:   st.caption("—")
        else:
            st.info("No leaves under this node.")


# ----- Alias para compatibilidade -----
def render_genres_page():
    return render_generos_page()
