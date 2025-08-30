# views/explore_page.py  — ECharts (EN + icon-only links)
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
from streamlit_echarts import st_echarts

from services.genre_csv import load_hierarchy_csv, build_indices, norm
from services.genres_kb import kb_neighbors, canonical_name, BLURBS
from services.page_help import show_page_help
import plotly.graph_objects as go

# Se não existirem já:
try:
    HILIGHT_COLOR
except NameError:
    HILIGHT_COLOR = "#2a66ff"
try:
    LINK_GREY
except NameError:
    LINK_GREY = "#9aa3a8"  # cinzento das arestas “normais”

def _plotly_sankey_figure(
    nodes,
    edges,                      # [(src, tgt, v)]
    highlight_edges,            # set([(src,tgt), ...])
    highlight_nodes,            # set([name,...])
    title: str,
    branch_only: bool = False
):
    """
    Replica o estilo do influence_map.py:
    - todas as arestas com espessura idêntica (value=1)
    - arestas cinzentas; ramo selecionado em HILIGHT_COLOR
    - se branch_only=True, mostra apenas o ramo selecionado
    """
    # Índices de nós
    idx = {n: i for i, n in enumerate(nodes)}

    # Paleta para nós (mantém a tua)
    palette = [
        "#a1c9f4", "#ffb482", "#8de5a1", "#ff9f9b", "#d0bbff", "#debb9b",
        "#fab0e4", "#b9f2f0", "#b5e48c", "#e9c46a", "#90be6d", "#e76f51"
    ]
    node_colors = []
    for i, n in enumerate(nodes):
        node_colors.append(HILIGHT_COLOR if n in highlight_nodes else palette[i % len(palette)])

    # Filtrar arestas se só quisermos o ramo selecionado
    if branch_only:
        edges_to_draw = [(s, t, v) for (s, t, v) in edges if (s, t) in highlight_edges]
    else:
        edges_to_draw = edges

    # Converter para arrays Plotly
    src, tgt, val, link_color = [], [], [], []
    for s, t, _v in edges_to_draw:
        src.append(idx[s])
        tgt.append(idx[t])
        val.append(1.0)  # espessura constante
        is_high = (s, t) in highlight_edges
        link_color.append(HILIGHT_COLOR if is_high else LINK_GREY)

    sankey = go.Sankey(
        arrangement="snap",
        node=dict(
            pad=12,
            thickness=12,
            line=dict(color="#111", width=0.5),
            label=nodes,
            color=node_colors,
        ),
        link=dict(
            source=src,
            target=tgt,
            value=val,
            color=link_color,
            hovertemplate="%{source.label} → %{target.label}<extra></extra>",
        ),
    )

    fig = go.Figure(data=[sankey])
    fig.update_layout(
        title=title,
        font=dict(size=13),
        margin=dict(l=20, r=30, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(height=560, margin=dict(l=8, r=8, t=46, b=8))
    return fig

# =======================
#   Constants / tuning
# =======================
DEPTH_DEFAULT     = 4        # base depth (same as Influence)
MAX_CHILDREN      = 30       # compact mode above this number of direct children
LEFT_PAD_PCT      = "1.5%"   # ECharts left margin
RIGHT_PAD_PCT     = "22%"    # ECharts right margin — room for long labels
NODE_GAP          = 6        # vertical gap between nodes
NODE_WIDTH        = 14       # node width
LABEL_WIDTH       = 170      # label width for wrapping
HILIGHT_COLOR     = "#175DDC"
LINK_GREY         = "rgba(0,0,0,0.18)"
CONTROL_COL_FRAC  = 0.26     # left control-column width

# ==================================
#   Normalisation & dedup
# ==================================
_RX = re.compile(r"[^a-z0-9]+")
_ALIASES_NICE = {
    "hiphop": "Hip-Hop",
    "rocknroll": "Rock ’n’ Roll",
    "bluesrock": "Blues Rock",
}

def _canon_local(s: str) -> str:
    """Aggressive local normalisation (ASCII + lowercase + strip punctuation)."""
    if not s:
        return ""
    base = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return _RX.sub("", base)

def _pretty_local(key: str) -> str:
    return _ALIASES_NICE.get(key, key.title())

def _unique_sorted(labels: List[str]) -> List[str]:
    cleaned = {canonical_name(x) for x in labels if isinstance(x, str) and x.strip()}
    return sorted(cleaned, key=str.lower)

def _cap(s: str, n: int = 12) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"

def _set_query(name: str):
    st.session_state["exp_query"] = name


# --------- CSV dynamic (indices) ---------
@st.cache_data(ttl=3600, show_spinner=False)
def _load_children_index():
    df, _ = load_hierarchy_csv()
    children, leaves, roots, leaf_url = build_indices(df)
    return children  # dict[prefix(tuple) -> set(children_str)]

@st.cache_data(ttl=3600, show_spinner=False)
def _all_labels(children_index):
    labels = set()
    for pref, kids in children_index.items():
        if pref:
            labels.add(pref[-1])
        labels.update({k for k in kids if k})
    return sorted(labels, key=str.lower)


# --------- Neighbourhood (parents/children) ---------
def _neighbors(label: str, children_index):
    lab_n = norm(label)
    parents, childs = set(), set()
    for pref, kids in children_index.items():
        parent = pref[-1] if pref else None
        if pref and norm(pref[-1]) == lab_n:
            childs.update({k for k in kids if k})
        if any(norm(k) == lab_n for k in kids):
            if parent:
                parents.add(parent)
    parents = sorted({p for p in parents if p.lower() != label.lower()}, key=str.lower)
    childs  = sorted({c for c in childs  if c.lower() != label.lower()}, key=str.lower)
    return parents, childs


# --------- extra (optional hierarchical CSV) ---------
@st.cache_data(ttl=3600, show_spinner=False)
def _load_extra_edges(path: str = "dados/influences_origins.csv", sep: str = ";"):
    edges = set()
    try:
        df = pd.read_csv(path, sep=sep)
    except Exception:
        return edges
    cols = [c for c in df.columns if re.match(r"^L\d+$", str(c), flags=re.I)]
    if not cols:
        return edges
    cols.sort(key=lambda c: int(re.findall(r"\d+", str(c))[0]))
    for _, row in df.iterrows():
        seq = [str(row[c]).strip() for c in cols
               if str(row[c]).strip() and str(row[c]).strip().lower() != "nan"]
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            if a and b and a != b:
                edges.add((a, b))
    return edges

def _neighbors_from_edges(label: str, edges):
    lab_n = norm(label)
    parents, childs = set(), set()
    for p, c in edges:
        if norm(p) == lab_n:
            childs.add(c)
        if norm(c) == lab_n:
            parents.add(p)
    parents = sorted({p for p in parents if p.lower() != label.lower()}, key=str.lower)
    childs  = sorted({c for c in childs  if c.lower() != label.lower()}, key=str.lower)
    return parents, childs


# --------- Normalised adjacency ---------
@st.cache_data(ttl=3600, show_spinner=False)
def _build_label_adjacency(children_index) -> Dict[str, Set[str]]:
    """Build {parent: {children}} with normalised & pretty labels."""
    tmp: Dict[str, Set[str]] = defaultdict(set)
    for pref, kids in children_index.items():
        if not pref:
            continue
        parent_raw = pref[-1]
        p_key = _canon_local(parent_raw)
        for k in kids:
            if not k:
                continue
            tmp[p_key].add(_canon_local(k))

    adj: Dict[str, Set[str]] = {}
    for p_key, chs in tmp.items():
        adj[_pretty_local(p_key)] = {_pretty_local(c) for c in chs}
    return adj


# --------- BFS & path ---------
def _bfs_down_labels(adj: Dict[str, Set[str]], root: str, depth: int):
    root = canonical_name(root)
    nodes = {root}
    edges: List[Tuple[str, str]] = []
    level = {root: 0}
    q = deque([root])

    while q:
        u = q.popleft()
        if level[u] >= depth:
            continue
        for v in sorted(adj.get(u, set()), key=str.lower):
            v = canonical_name(v)
            edges.append((u, v))
            if v not in nodes:
                nodes.add(v)
                level[v] = level[u] + 1
                q.append(v)

    ordered = sorted(nodes, key=lambda n: (level[n], n.lower()))
    return ordered, edges, level

def _path_edges(edges: List[Tuple[str, str]], start: str, target: str) -> List[Tuple[str, str]]:
    g = defaultdict(list)
    for a, b in edges:
        g[a].append(b)
    start, target = canonical_name(start), canonical_name(target)

    q = deque([start])
    parent: Dict[str, str] = {start: ""}

    while q:
        u = q.popleft()
        if u == target:
            break
        for v in g.get(u, []):
            if v not in parent:
                parent[v] = u
                q.append(v)

    if target not in parent:
        return []
    path = []
    cur = target
    while parent[cur]:
        p = parent[cur]
        path.append((p, cur))
        cur = p
    path.reverse()
    return path

def _subtree_edges(root: str, adj: Dict[str, Set[str]], depth: int) -> Set[Tuple[str, str]]:
    """All edges from root down to depth (aux for highlight/branch-only)."""
    seen_edges: Set[Tuple[str, str]] = set()
    q = deque([(root, 0)])
    while q:
        u, d = q.popleft()
        if d >= depth:
            continue
        for v in adj.get(u, set()):
            seen_edges.add((u, v))
            q.append((v, d + 1))
    return seen_edges


# --------- Icon links (emoji only) ---------
def _icon_link(url: str, emoji: str, title: str, *, new_tab: bool = True):
    """Emoji-only clickable link with tooltip, alinhado à altura do input."""
    target = "_blank" if new_tab else "_self"
    st.markdown(
        f"""
        <a href="{url}" title="{title}" target="{target}"
           style="
             display:flex; align-items:center; justify-content:center;
             height:38px; width:100%;
             text-decoration:none; font-size:1.1rem;">
           {emoji}
        </a>
        """,
        unsafe_allow_html=True,
    )


def _wiki_url(name: str | None) -> str:
    q = (name or "Music").strip()
    return f"https://en.wikipedia.org/w/index.php?search={quote_plus(q)}"

def _spotify_web_url(genre: str | None) -> str:
    g = canonical_name(genre or "").strip() or "music"
    return f"https://open.spotify.com/search/{quote_plus(g)}"


# --------- ECharts options ---------
from typing import List, Tuple, Set

def _echarts_sankey_options(
    nodes: List[str],
    edges: List[Tuple[str, str, float]],
    highlight_edges: Set[Tuple[str, str]],
    highlight_nodes: Set[str],
    title: str
) -> dict:
    # Paleta de nós (mantida)
    palette = [
        "#a1c9f4", "#ffb482", "#8de5a1", "#ff9f9b", "#d0bbff", "#debb9b",
        "#fab0e4", "#b9f2f0", "#b5e48c", "#e9c46a", "#90be6d", "#e76f51"
    ]

    data_nodes = []
    for i, n in enumerate(nodes):
        is_high = n in highlight_nodes
        data_nodes.append({
            "name": n,
            "itemStyle": {
                "color": HILIGHT_COLOR if is_high else palette[i % len(palette)],
                "borderColor": "#111" if is_high else "#999",
                "borderWidth": 2 if is_high else 0,
            },
            "label": {"fontSize": 13},
        })

    # IMPORTANTE: valor fixo (=espessura fixa) como no Influence
    data_links = []
    for s, t, _v in edges:
        is_high = (s, t) in highlight_edges
        link = {
            "source": s,
            "target": t,
            "value": 1.0,  # <— força espessura constante
        }
        if is_high:
            link["lineStyle"] = {
                "color": HILIGHT_COLOR,
                "opacity": 0.95
            }
        data_links.append(link)

    options = {
        "title": {"text": title},
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "sankey",
            "left": "2%", "right": "10%", "top": 20, "bottom": 10,

            # Aspeto alinhado ao Influence (linhas finas)
            "nodeAlign": "left",
            "nodeGap": 4,
            "nodeWidth": 12,

            "data": data_nodes,
            "links": data_links,

            # Opacidade global semelhante ao Influence
            "lineStyle": {"opacity": 0.6},
            "emphasis": {"focus": "adjacency"},
            "label": {"fontSize": 12},
        }]
    }
    return options


# ----------------- PAGE -----------------
def render_explore_page():
    # Mobile / idioma
    is_mobile = bool(st.session_state.get("mobile_layout") or st.session_state.get("mobile"))
    show_page_help("explore", lang=st.session_state.get("lang", "EN"))

    # Título
    st.title("🔎 Explore · Music4all")

    # ---------------------------
    # Entrada do género (atalho + pesquisa simples)
    # ---------------------------
    # Nota: estes widgets de topo já existem no teu ficheiro; aqui mantemos só o essencial
    col_atl, col_wiki, col_sp = st.columns([0.80, 0.10, 0.10])
    with col_atl:
        root = st.selectbox(
            "Atalho",
            options=_unique_sorted(list(_build_label_adjacency(_load_children_index()).keys())),
            index=0,
            key="expl_root",
        )

    # Links rápidos (apenas emoji) – ficam alinhados com o selectbox
    wiki_url = f"https://en.wikipedia.org/wiki/{root.replace(' ', '_')}"
    sp_url   = f"https://open.spotify.com/search/{root.replace(' ', '%20')}"
    with col_wiki:
        st.markdown(
            f'<div style="text-align:right;font-size:1.15rem;">'
            f'<a href="{wiki_url}" title="Wikipedia" target="_blank">📚</a></div>',
            unsafe_allow_html=True,
        )
    with col_sp:
        st.markdown(
            f'<div style="text-align:right;font-size:1.15rem;">'
            f'<a href="{sp_url}" title="Ver no Spotify" target="_blank">🎧</a></div>',
            unsafe_allow_html=True,
        )

    if not root:
        st.warning("Escolhe um género para começar.")
        return

    # ---------------------------
    # Texto/metadata do género (BLURBS)
    # ---------------------------
    b = BLURBS.get(root, {})
    period  = b.get("period", "—")
    regions = ", ".join(b.get("regions", []) or []) or "—"
    chars   = ", ".join(b.get("characteristics", []) or []) or "—"
    st.markdown(f"### {root}")
    st.markdown(f"**Período:** {period}  **Áreas-chave:** {regions}  **Traços típicos:** {chars}")
    st.divider()

    # ---------------------------
    # Adjacências normalizadas (KB)
    # ---------------------------
    children_index = _load_children_index()
    adj = _build_label_adjacency(children_index)

    # ---------------------------
    # Layout: esquerda (listas/controles) + direita (gráfico)
    # ---------------------------
    col_l, col_r = st.columns(
        [CONTROL_COL_FRAC, 1.0 - CONTROL_COL_FRAC] if not is_mobile else [1, 0]
    )

    # ===== Coluna ESQUERDA =====
    with col_l:
        # Influences/Derivatives (listas informativas)
        parents_dyn, children_dyn = _neighbors(root, children_index)
        extra_edges = _load_extra_edges()
        if extra_edges:
            p2, c2 = _neighbors_from_edges(root, extra_edges)
        else:
            p2, c2 = [], []
        p3, c3 = kb_neighbors(root)
        parents  = _unique_sorted(list(set(parents_dyn)  | set(p2) | set(p3)))
        children = _unique_sorted(list(set(children_dyn) | set(c2) | set(c3)))

        st.markdown("#### Influences (upstream)")
        st.write("—" if not parents else " • ".join(parents))
        st.markdown("#### Derivatives (downstream)")
        st.write("—" if not children else " • ".join(children))

        # Modo compacto automático
        num_children = len(adj.get(root, set()))
        compact = num_children > MAX_CHILDREN
        if compact:
            st.info(
                f"**{root}** has many direct branches ({num_children}). "
                f"To keep the chart readable we show **only 2 levels**. "
                f"Pick a sub-genre to drill down, or **show the full view**."
            )
            force_full = st.checkbox("Show full view anyway", value=False, key="expl_show_all")
            depth = DEPTH_DEFAULT if force_full else 2
        else:
            depth = DEPTH_DEFAULT

        # Slider de profundidade (só quando não estamos em modo “compacto forçado”)
        if not compact or (compact and force_full):
            depth = int(st.slider(
                "Map depth (levels below this genre)",
                min_value=2, max_value=7, value=int(depth), key="expl_depth"
            ))

        # Escolha do ramo (Nível 1) + “só ramo”
        level1_options = sorted(adj.get(root, set()), key=str.lower)
        level1 = st.selectbox("Level 1", options=["— select —"] + level1_options, index=0, key="expl_lvl1")
        show_branch_only = st.checkbox("Show only selected branch", value=False, key="expl_branch_only")

        # Breadcrumb
        trail = root
        if level1 and level1 != "— select —":
            trail += f" → {level1}"
        st.caption(trail)

    # ===== Coluna DIREITA =====
    with (col_r if not is_mobile else st.container()):
        # --- construir nós/arestas via BFS ---
        nodes, edges_list, level_map = _bfs_down_labels(adj, root, depth)

        # realce do ramo escolhido
        highlight_edges: Set[Tuple[str, str]] = set()
        highlight_nodes: Set[str] = set([root])

        if level1 and level1 != "— select —":
            # caminho root -> level1
            for e in _path_edges(adj, root, level1):
                highlight_edges.add(e)
                highlight_nodes.update(e)

            if show_branch_only:
                # só o ramo por baixo do level1
                nodes_sub, edges_sub = _subtree_edges(adj, level1, depth - 1)
                nodes = list(dict.fromkeys([root] + nodes_sub))  # manter ordem sem duplicar
                edges = list(dict.fromkeys(_path_edges(adj, root, level1) + edges_sub))
            else:
                edges = edges_list
        else:
            edges = edges_list

        # ECharts (usar estilo afinado para ficar “igual” ao Influence)
        edges_val = [(a, b, 1.0) for (a, b) in edges]
        options = _echarts_sankey_options(
            nodes=nodes,
            edges=edges_val,
            highlight_edges=highlight_edges,
            highlight_nodes=highlight_nodes,
            title=f"{root} — influence map (explore)"
        )
        st_echarts(options=options, height="520px", key=f"explore_{root}")
        st.caption("Blue = branch highlighted from the selected genre.")
