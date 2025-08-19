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
# Helpers
# ======================
def _unique_sorted(labels: list[str]) -> list[str]:
    """Unique + sort estável (case/alias-insensitive)."""
    cleaned = {canonical_name(x) for x in labels if isinstance(x, str) and x.strip()}
    return sorted(cleaned, key=str.lower)

def _cap(s: str, n: int = 12) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"

def _set_query(name: str):
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
# Grafo (downstream) + destaque do caminho
# ======================
@st.cache_data(ttl=3600, show_spinner=False)
def _build_label_adjacency(children_index) -> Dict[str, Set[str]]:
    """ParentLabel -> {children labels} (ambos canonicalizados)."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    for pref, kids in children_index.items():
        if not pref:
            continue
        parent = canonical_name(pref[-1])
        for k in kids:
            if k:
                adj[parent].add(canonical_name(k))
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

def _branch_sankey(
    nodes: List[str],
    edges: List[Tuple[str, str]],
    level: Dict[str, int],
    root: str,
    focus: str,
    branch_only: bool = False  # <- novo parâmetro
):
    """
    Sankey com:
      • níveis distribuídos de forma estável (mesmo quando só há 2–3 níveis),
      • ramo root→focus destacado a azul,
      • restante a cinzento; se branch_only=True, linhas fora do ramo ficam invisíveis.
    """
    FONT = "Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    PALETTE = px.colors.qualitative.Set3
    LINK_GREY = "rgba(0,0,0,0.18)"
    BLUE = "#3b82f6"

    # Índices dos nós
    idx = {n: i for i, n in enumerate(nodes)}

    # X por nível (robusto com poucos níveis)
    lvls = [level.get(n, 0) for n in nodes]
    uniq_lvls = sorted(set(lvls))
    if len(uniq_lvls) <= 1:
        pos_map = {uniq_lvls[0] if uniq_lvls else 0: 0.5}
    else:
        import numpy as np
        xs_positions = np.linspace(0.06, 0.94, num=len(uniq_lvls))
        pos_map = {lv: float(x) for lv, x in zip(uniq_lvls, xs_positions)}
    xs = [pos_map[level.get(n, 0)] for n in nodes]

    # Cores (nós do caminho a azul)
    reps = (len(nodes) // len(PALETTE)) + 1
    ncolors = (PALETTE * reps)[: len(nodes)]

    path = set(_path_edges(edges, root, focus))
    path_nodes = {root, focus} | {a for a, _ in path} | {b for _, b in path}
    for i, n in enumerate(nodes):
        if n in path_nodes:
            ncolors[i] = BLUE

    # Ligações: azul no caminho; fora do caminho ficam cinzentas ou invisíveis
    src, dst, val, lcol = [], [], [], []
    for a, b in edges:
        if a in idx and b in idx:
            src.append(idx[a])
            dst.append(idx[b])
            val.append(1)
            if (a, b) in path:
                lcol.append(BLUE)
            else:
                lcol.append("rgba(0,0,0,0)" if branch_only else LINK_GREY)

    # Ajustes para grafos pequenos
    few_nodes = len(nodes) <= 8
    node_thickness = 16 if few_nodes else 20
    node_pad = 12 if few_nodes else 18

    fig = go.Figure(
        go.Sankey(
            arrangement="fixed",
            node=dict(
                label=nodes,
                x=xs,
                pad=node_pad,
                thickness=node_thickness,
                color=ncolors,
                line=dict(color="rgba(0,0,0,0.25)", width=0.8),
                hovertemplate="%{label}<extra></extra>",
            ),
            link=dict(
                source=src,
                target=dst,
                value=val,
                color=lcol,
                hovertemplate="%{source.label} → %{target.label}<extra></extra>",
            ),
        )
    )

    fig.update_layout(
        margin=dict(l=8, r=8, t=6, b=6),
        height=600 if few_nodes else 680,
        font=dict(family=FONT, size=15, color="#1f2937"),
        hoverlabel=dict(font_size=14, font_family=FONT),
    )
    fig.update_traces(textfont=dict(family=FONT, size=15, color="#111827"))
    return fig


# ======================
# Página
# ======================
def render_genealogy_page():
    # Título + quick picks
    colT1, colT2 = st.columns([0.62, 0.38])
    with colT1:
        st.title("🧬 Genre Genealogy · Music4all")
    with colT2:
        st.markdown("**Quick picks**")
        quick = ["Blues", "Jazz", "Rock", "Pop", "Metal", "House",
                 "Funk", "Disco", "Hip-hop", "New Wave", "Synth-pop", "Reggae"]
        qcols = st.columns(4)
        for i, name in enumerate(quick):
            with qcols[i % 4]:
                st.button(_cap(name), key=f"gen_chip_top_{i}",
                          on_click=_set_query, args=(name,))

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
3. In the map you can choose the **depth** (levels below the genre) and select the **branch** step by step.
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

    # Listas
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("#### Influences (upstream)")
        st.write("—" if not parents else " • ".join(parents))
    with col_r:
        st.markdown("#### Derivatives (downstream)")
        st.write("—" if not children else " • ".join(children))

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ----- Gráfico: controlos -----
    adj = _build_label_adjacency(children_index)
    depth = st.slider("Map depth (levels below this genre)", 1, 4, 2, key="gen_depth")

    # ---------- Selectboxes em cascata (horizontais, passo-a-passo) ----------
    st.markdown("**Choose branch (level by level)**")

    path: List[str] = st.session_state.get("gen_path") or [genre]
    if not path or path[0] != genre:
        path = [genre]

    COLS_PER_ROW = 6
    row_cols: List[st.delta_generator.DeltaGenerator] = []

    def _col_for(i: int):
        nonlocal row_cols
        if i % COLS_PER_ROW == 0:
            row_cols = st.columns(COLS_PER_ROW)
        return row_cols[i % COLS_PER_ROW]

    for lvl in range(1, depth + 1):
        parent = path[lvl - 1] if len(path) >= lvl else genre
        options = sorted(adj.get(parent, set()), key=str.lower)
        if not options:
            path = path[:lvl]
            break

        default_val = path[lvl] if len(path) > lvl and path[lvl] in options else None
        disp = ["— choose —"] + options
        idx = disp.index(default_val) if default_val else 0

        with _col_for(lvl - 1):
            sel = st.selectbox(f"Level {lvl}", disp, index=idx, key=f"gen_step_{lvl}")

        if not sel or sel == "— choose —":
            path = path[:lvl]
            break

        chosen = canonical_name(sel)
        if len(path) <= lvl or path[lvl] != chosen:
            path = path[:lvl] + [chosen]
        # próximo ciclo usará parent = path[lvl]

    st.session_state["gen_path"] = path
    focus = path[-1] if path else genre

    branch_only = st.checkbox("Show only the selected branch", value=False, key="gen_branch_only")

    # ----- Construção do gráfico e desenho -----

    nodes, edges, level = _bfs_down_labels(adj, genre, depth)

    if not nodes or not edges:
        st.info("Sem ligações para esta profundidade.")
    else:
        fig = _branch_sankey(
            nodes,
            edges,
            level,
            root=genre,
            focus=focus,
            branch_only=branch_only  # <- controla a opacidade das linhas fora do ramo
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("Azul = caminho destacado do género seleccionado até ao ramo escolhido.")

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
