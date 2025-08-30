# views/genres_page.py
# Navegação “acordeão”: género selecionado visível + subgéneros por baixo (pílulas pequenas).

import streamlit as st
from services.ui_helpers import ui_mobile
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

# ---------- Query params ----------
def _qp_get():
    try:
        return dict(st.query_params)
    except Exception:
        return st.experimental_get_query_params()

def _qp_set(**kwargs):
    try:
        for k, v in kwargs.items():
            st.query_params[k] = v
    except Exception:
        st.experimental_set_query_params(**kwargs)

def _qp_path_read():
    qp = _qp_get()
    val = qp.get("set_path")
    if isinstance(val, list):
        val = val[0] if val else ""
    if not val:
        return None
    return [p for p in str(val).split("|") if p]

def _set_query_path(path):
    _qp_set(set_path="|".join(path) if path else "")

# ---------- CSS (sem indentação para não virar code block) ----------
def _write_css():
    st.markdown(
"""<style>
.current-node{
  display:inline-flex; align-items:center; gap:.5rem;
  border:1px solid rgba(128,128,128,.35);
  padding:.45rem .75rem; border-radius:999px; font-weight:600;
}
.crumbs a{ text-decoration:none; }
.crumbs .sep{ opacity:.6; margin:0 .25rem; }

.pill-tree{ margin:.35rem 0 .25rem .25rem; position:relative;}
.pill-tree .row{ display:flex; align-items:center; gap:.5rem; margin:.24rem 0;}
.pill-tree .stem{ width:18px; position:relative; align-self:stretch; }
.pill-tree .stem::before{ content:""; position:absolute; left:8px; top:0; bottom:0;
  width:2px; background:#3a3f44; opacity:.55;}
.pill-tree .dot{ position:absolute; left:2px; top:8px; width:12px; height:12px;
  border-radius:999px; background: var(--primary-color, #4B9CFF);
  border:2px solid rgba(0,0,0,.35);}
.pill-tree a.pill{ display:inline-block; text-decoration:none; border-radius:999px;
  padding:.25rem .6rem; font-size:.85rem; line-height:1.1;
  border:1px solid rgba(128,128,128,.35); }
.pill-tree a.pill:hover{ filter:brightness(1.08); }
.pill-tree .ext{ margin-left:.35rem; font-size:.9rem; opacity:.8; }

.root-btn{ font-size:0.95rem; padding:.5rem .8rem; }
@media (max-width:768px){
  .pill-tree a.pill{ font-size:.82rem; padding:.22rem .5rem; }
  .root-btn{ font-size:0.92rem; }
}
</style>""",
        unsafe_allow_html=True
    )

# ---------- HTML helpers ----------
def _breadcrumbs(path):
    if not path:
        return
    bits = []
    for i, label in enumerate(path):
        href = "?set_path=" + "|".join(path[: i + 1])
        if i < len(path) - 1:
            bits.append(f'<a href="{href}">{label}</a><span class="sep">/</span>')
        else:
            bits.append(f'<strong>{label}</strong>')
    st.markdown('<div class="crumbs">' + "".join(bits) + '</div>', unsafe_allow_html=True)

def _pill_tree(children_labels, base_path, leaf_url):
    rows = []
    for label in children_labels:
        href = "?set_path=" + "|".join(base_path + [label])
        wiki = leaf_url.get(tuple(base_path + [label]))
        ext = f'<a class="ext" href="{wiki}" target="_blank" title="Wikipedia">🔗</a>' if wiki else ""
        rows.append(
            f'<div class="row">'
            f'  <div class="stem"><span class="dot"></span></div>'
            f'  <div><a class="pill" href="{href}">{label}</a>{ext}</div>'
            f'</div>'
        )
    st.markdown('<div class="pill-tree">' + "".join(rows) + '</div>', unsafe_allow_html=True)

# ---------- Página ----------
def render_genres_page():
    st.title("Genres")
    _write_css()

    try:
        with st.expander("Ajuda", expanded=False):
            show_page_help()
    except Exception:
        pass

    _ = ui_mobile()  # mantido

    # Hierarquia REAL
    try:
        df, csv_path = load_hierarchy_csv()
        children, leaves, roots, leaf_url = build_indices(df)
    except Exception as e:
        st.error(f"Erro na hierarquia: {e}")
        return

    # Estado / query param
    if "genres_path" not in st.session_state:
        # ⚠️ Iniciar SEM caminho => mostra só as raízes
        st.session_state["genres_path"] = []

    qp_path = _qp_path_read()
    if qp_path is not None:
        st.session_state["genres_path"] = qp_path

    path = list(st.session_state["genres_path"])
    current = path[-1] if path else None

    # Pesquisa rápida
    with st.expander("Pesquisar género/subgénero", expanded=False):
        c1, c2 = st.columns([3, 1])
        with c1:
            q = st.text_input("Pesquisar género/subgénero", placeholder="e.g., art rock")
        with c2:
            if st.button("Ir", use_container_width=True):
                text = (q or "").strip().lower()
                if text:
                    # procurar no índice de folhas e nós
                    # (forma simples: percorrer chaves/valores de children/leaves/roots)
                    candidates = set(roots)
                    for k, v in children.items():
                        candidates.update(list(v))
                        candidates.update(list(k))
                    match = next((n for n in sorted(candidates, key=str.lower) if text in n.lower()), None)
                    if match:
                        # reconstruir um caminho através de um BFS pela estrutura children
                        from collections import deque
                        dq = deque([[r] for r in roots])
                        seen = set()
                        found = None
                        while dq:
                            p2 = dq.popleft()
                            if p2[-1].lower() == match.lower():
                                found = p2; break
                            t = tuple(p2)
                            if t in seen: continue
                            seen.add(t)
                            for ch in children.get(t, []):
                                dq.append(p2 + [ch])
                        st.session_state["genres_path"] = found or [match]
                        _set_query_path(st.session_state["genres_path"])
                        st.rerun()
                st.toast("Sem resultados.", icon="⚠️")

    # Toolbar básica
    col_up, col_top, _sp = st.columns([1, 1, 6])
    with col_up:
        if st.button("⬅️ Subir", use_container_width=True, disabled=(len(path) <= 0)):
            st.session_state["genres_path"] = path[:-1]
            _set_query_path(st.session_state["genres_path"])
            st.rerun()
    with col_top:
        if st.button("🏠 Topo", use_container_width=True, disabled=(len(path) == 0)):
            st.session_state["genres_path"] = []
            _set_query_path([])
            st.rerun()

    # --------- Vista raiz (mostra apenas a lista de géneros H1) ---------
    if not path:
        st.subheader("Current branch")
        st.write("Select a branch to drill down:")
        for i, label in enumerate(sorted(roots, key=str.lower)):
            if st.button(label, key=_key("root", [label], idx=i), use_container_width=True, help="Abrir ramo", type="secondary"):
                st.session_state["genres_path"] = [label]
                _set_query_path([label])
                st.rerun()
        return  # nada mais a mostrar neste estado

    # --------- Vista de ramo (acordeão) ---------
    _breadcrumbs(path)
    st.markdown(f'<span class="current-node">{current}</span>', unsafe_allow_html=True)

    st.divider()
    st.subheader("Subgéneros")

    next_children = sorted(list(children.get(tuple(path), set())), key=str.lower)
    if next_children:
        _pill_tree(next_children, path, leaf_url)
    else:
        st.write("Sem subgéneros neste nível.")

    st.divider()

    # (Opcional) Spotify/Wiki – mantidos mas protegidos
    try:
        token = get_spotify_token_cached()
    except Exception:
        token = None

    if token and current:
        st.subheader("Spotify · Artistas populares")
        try:
            arts = spotify_genre_top_artists(token, current) or []
            if arts:
                cols = st.columns(5)
                for i, a in enumerate(arts[:10]):
                    with cols[i % 5]:
                        st.write(a.get("name", "—"))
            else:
                st.caption("Sem dados.")
        except Exception:
            st.caption("Não foi possível obter artistas agora.")

        st.subheader("Spotify · Playlists do género")
        try:
            pls = spotify_genre_playlists(token, current) or []
            if pls:
                for pl in pls[:6]:
                    try:
                        uri = pl.get("uri") or pl.get("external_urls", {}).get("spotify")
                        if uri:
                            embed_spotify(uri)
                    except Exception:
                        pass
            else:
                st.caption("Sem playlists encontradas.")
        except Exception:
            st.caption("Não foi possível obter playlists agora.")

    try:
        title = resolve_wikipedia_title(current) if current else None
        if title:
            st.caption(f"Wikipedia: [{title}](https://en.wikipedia.org/wiki/{title.replace(' ', '_')})")
    except Exception:
        pass

# Execução direta (dev)
if __name__ == "__main__":
    render_genres_page()
