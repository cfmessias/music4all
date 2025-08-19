# views/genealogy_page.py
# -----------------------------------------------------------------------------
# Music4all · Genre Genealogy (dynamic CSV + extra CSV + curated KB)
# Gráfico de ramo multi-nível com destaque do caminho + quick picks no topo
# -----------------------------------------------------------------------------
from __future__ import annotations

import os
import re
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services.genre_csv import load_hierarchy_csv, build_indices, norm
from services.genres_kb import genre_summary, kb_neighbors, canonical_name, BLURBS


# ======================
# Helpers comuns
# ======================
def _unique_sorted(labels: list[str]) -> list[str]:
    """Unique + sort estável (case/alias-insensitive)."""
    cleaned = {canonical_name(x) for x in labels if isinstance(x, str) and x.strip()}
    return sorted(cleaned, key=str.lower)

def _cap(s: str, n: int = 12) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"

def _set_query(name: str):
    # usado pelos quick picks
    st.session_state["gen_query"] = name


# ======================
# Dynamic CSV
# ======================
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


def _neighbors(label: str, children_index):
    """Pais e filhos imediatos a partir do índice de prefixos do CSV dinâmico."""
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


# ======================
# Extra hierarchical CSV (L1..Ln) — opcional
# ======================
@st.cache_data(ttl=3600, show_spinner=False)
def _load_extra_edges(path: str = "dados/influences_origins.csv", sep: str = ";"):
    edges = set()
    if not os.path.exists(path):
        return edges
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
            a, b = seq[i], seq[i+1]
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


# ======================
# Grafo “ramo” multi-nível (downstream) + destaque do caminho
# ======================
@st.cache_data(ttl=3600, show_spinner=False)
def _build_label_adjacency(children_index) -> Dict[str, Set[str]]:
    """Colapsa o índice de prefixos para um mapa simples ParentLabel -> {children labels}."""
    adj = defaultdict(set)
    for pref, kids in children_index.items():
        if pref:
            parent_label = pref[-1]
            for k in kids:
                if k:
                    adj[parent_label].add(k)
    return adj


def _bfs_down_labels(adj: Dict[str, Set[str]], root: str, depth: int):
    """BFS a partir de root por labels (até 'depth' níveis)."""
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

    # ordenar por nível e nome
    ordered = sorted(nodes, key=lambda n: (level[n], n.lower()))
    return ordered, edges, level


def _path_edges(edges: List[Tuple[str, str]], start: str, target: str) -> List[Tuple[str, str]]:
    """Um caminho dirigido start→target (se existir)."""
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


def _branch_sankey(nodes: List[str], edges: List[Tuple[str, str]],
                   level: Dict[str, int], root: str, focus: str):
    """Sankey com níveis fixos e destaque do caminho root→focus."""
    FONT = "Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    PALETTE = px.colors.qualitative.Set3
    LINK_GREY = "rgba(0,0,0,0.18)"
    BLUE = "#3b82f6"

    idx = {n: i for i, n in enumerate(nodes)}
    max_lv = max(level.values()) if level else 0

    # posições X por nível (encurtar links)
    xs = []
    for n in nodes:
        lv = level.get(n, 0)
        x = 0.08 + (0.82 * (lv / max(1, max_lv)))  # 0.08 .. 0.90
        xs.append(x)

    # cores dos nós (override a azul no caminho)
    reps = (len(nodes) // len(PALETTE)) + 1
    ncolors = (PALETTE * reps)[:len(nodes)]
    path = set(_path_edges(edges, root, focus))
    path_nodes = {root, focus} | {a for a, _ in path} | {b for _, b in path}
    for i, n in enumerate(nodes):
        if n in path_nodes:
            ncolors[i] = BLUE

    src, dst, val, lcol = [], [], [], []
    for a, b in edges:
        if a in idx and b in idx:
            src.append(idx[a]); dst.append(idx[b]); val.append(1)
            lcol.append(BLUE if (a, b) in path else LINK_GREY)

    fig = go.Figure(go.Sankey(
        arrangement="fixed",
        node=dict(
            label=nodes,
            x=xs,
            pad=18,
            thickness=20,
            color=ncolors,
            line=dict(color="rgba(0,0,0,0.25)", width=0.8),
            hovertemplate="%{label}<extra></extra>",
        ),
        link=dict(
            source=src, target=dst, value=val, color=lcol,
            hovertemplate="%{source.label} → %{target.label}<extra></extra>",
        ),
    ))
    fig.update_layout(
        margin=dict(l=8, r=8, t=6, b=6),
        height=680,
        font=dict(family=FONT, size=15, color="#1f2937"),
        hoverlabel=dict(font_size=14, font_family=FONT),
    )
    fig.update_traces(textfont=dict(family=FONT, size=15, color="#111827"))
    return fig


# ======================
# Página
# ======================
def render_genealogy_page():
    # Título + quick picks (sempre visíveis)
    colT1, colT2 = st.columns([0.62, 0.38])

    with colT1:
        st.title("🧬 Genre Genealogy · Music4all")

    with colT2:
        st.markdown("**Quick picks**")
        quick = [
            "Blues", "Jazz", "Rock", "Pop", "Metal", "House",
            "Funk", "Disco", "Hip-hop", "New Wave", "Synth-pop", "Reggae",
        ]
        qcols = st.columns(4)
        for i, name in enumerate(quick):
            with qcols[i % 4]:
                st.button(_cap(name), key=f"gen_chip_top_{i}",
                          on_click=_set_query, args=(name,))

    # estado base
    st.session_state.setdefault("gen_query", "")

    # dados
    try:
        children_index = _load_children_index()
    except Exception as e:
        st.error(f"Error loading dynamic genres CSV: {e}")
        return
    labels = _all_labels(children_index)

    # Pesquisa + Select
    col1, col2 = st.columns([0.7, 0.3])
    with col1:
        st.text_input(
            "Search genre",
            placeholder="Type 2+ letters (e.g., Jazz, Blues, House, Prog Rock…)",
            key="gen_query",
            help="Search any music genre or subgenre. Start typing and pick from the suggestions.",
        )
        q = st.session_state["gen_query"].strip()
    with col2:
        if q:
            matches = [x for x in labels if q.lower() in x.lower()] or labels
            exact_idx = next((i for i, x in enumerate(matches) if x.lower() == q.lower()), None)
            if exact_idx is not None:
                picked = st.selectbox("Select", matches, index=exact_idx, key="gen_pick")
            else:
                sentinel = "— select a genre —"
                disp = [sentinel] + matches
                picked = st.selectbox("Select", disp, index=0, key="gen_pick")
                if picked == sentinel:
                    picked = ""
        else:
            st.selectbox("Select", ["— type to see options —"], index=0, disabled=True, key="gen_pick_disabled")
            picked = ""

    genre = canonical_name(picked or (q if any(x.lower() == q.lower() for x in labels) else ""))

    # Sem seleção ainda → ajuda
    if not genre:
        st.markdown(
            """
**How to use**

1. Type a genre in **Search genre**; the selectbox shows all matches.
2. Pick one to see **influences** (upstream), **derivatives** (downstream) and the **branch map**.
3. In the map you can **choose the depth** (levels below the genre) and **highlight** a branch (blue).
            """
        )
        with st.expander("What can I search?"):
            st.write(
                "You can search **any music genre or subgenre** you know. "
                "Start typing (2+ letters) and pick from the suggestions. "
                "Examples: *Blues*, *Jazz*, *Rock*, *Pop*, *House*, *Synth-pop*, *Hard Rock*, *New Wave*."
            )
        return

    # 1) dinâmico
    parents, children = _neighbors(genre, children_index)
    # 2) extra (se houver)
    extra_edges = _load_extra_edges()
    if extra_edges:
        p2, c2 = _neighbors_from_edges(genre, extra_edges)
    else:
        p2, c2 = [], []
    # 3) KB
    p3, c3 = kb_neighbors(genre)

    parents  = _unique_sorted(list(set(parents)  | set(p2) | set(p3)))
    children = _unique_sorted(list(set(children) | set(c2) | set(c3)))

    # Cabeçalho compacto
    b = BLURBS.get(genre, {})
    period  = b.get("period", "—")
    regions = ", ".join(b.get("regions", []) or []) or "—"
    chars   = ", ".join(b.get("characteristics", []) or []) or "—"
    st.markdown(f"### {genre}")
    st.markdown(f"**Period:** {period}  **Key areas:** {regions}  **Typical traits:** {chars}")
    st.divider()

    # Listas em duas colunas
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("#### Influences (upstream)")
        st.write("—" if not parents else " • ".join(parents))
    with col_r:
        st.markdown("#### Derivatives (downstream)")
        st.write("—" if not children else " • ".join(children))

    # ----- Gráfico: ramo multi-nível + destaque -----
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # controlos do gráfico
    adj = _build_label_adjacency(children_index)
    depth = st.slider("Map depth (levels below this genre)", 1, 4, 2, key="gen_depth")
    nodes, edges, level = _bfs_down_labels(adj, genre, depth)

    # highlight list: nós do mapa atual (exceto o root) + opção "None"
    highlight_opts = ["— none —"] + [n for n in nodes if n != genre]
    # se o utilizador escolheu um item na selectbox de cima que esteja dentro do mapa atual, destacamos
    default_focus = genre
    upper_pick = st.session_state.get("gen_pick")
    if upper_pick and canonical_name(upper_pick) in nodes:
        default_focus = canonical_name(upper_pick)
    focus = st.selectbox("Highlight branch", options=highlight_opts,
                         index=(highlight_opts.index(default_focus) if default_focus in highlight_opts else 0),
                         key="gen_highlight")
    if focus == "— none —":
        focus = genre

    if not nodes or not edges:
        st.info("No connections found for this depth.")
    else:
        fig = _branch_sankey(nodes, edges, level, root=genre, focus=focus)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("Blue = highlighted path from the selected genre to the chosen branch.")

    st.divider()

    # Navegação para outras páginas
    def _go_influence(focus_name: str):
        st.session_state["infl_root"]  = focus_name
        st.session_state["infl_focus"] = focus_name
        st.session_state["infl_mode"]  = "Dynamic"
        st.session_state.setdefault("infl_depth", 3)
        st.session_state.setdefault("infl_up", 1)
        st.session_state["active_tab"] = "🗺️ Influence map"
        st.rerun()

    def _go_genres(focus_name: str):
        st.session_state["genres_search_q"] = focus_name
        st.session_state["active_tab"] = "🧭 Genres"
        st.rerun()

    colL2, colR2 = st.columns(2)
    with colL2:
        st.button("🗺️ Open in Influence map (Dynamic)",
                  use_container_width=True, on_click=_go_influence, args=(genre,))
    with colR2:
        st.button("🧭 Search on *Genres* page",
                  use_container_width=True, on_click=_go_genres, args=(genre,))
