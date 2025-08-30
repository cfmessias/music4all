
# views/influence_map_layout_quickpicks.py
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

# Optional click support
try:
    from streamlit_plotly_events import plotly_events
    HAS_PLOTLY_EVENTS = True
except Exception:
    HAS_PLOTLY_EVENTS = False

# Data helpers provided by the project
from services.genre_csv import load_hierarchy_csv, build_indices, norm
from services.page_help import show_page_help

# -------------------------- Layout tuning ----------------------------------
AUTO_H_BASE = 460          # altura base
AUTO_H_PER_BRANCH = 26     # incremento por ramo no nível mais largo
AUTO_H_MIN = 420
AUTO_H_MAX = 1800


def _auto_height_by_breadth(nodes, links, root_label,
                            base_h=AUTO_H_BASE, px_per_branch=AUTO_H_PER_BRANCH,
                            h_min=AUTO_H_MIN, h_max=AUTO_H_MAX):
    """Altura ~ número máximo de nós no mesmo nível (largura do leque)."""
    from collections import defaultdict, deque
    graph = defaultdict(list)
    for s, t, *_ in links:
        graph[s].append(t)

    breadth = defaultdict(int)
    q = deque([(root_label, 0)])
    seen = {root_label}
    breadth[0] = 1
    while q:
        u, d = q.popleft()
        for v in graph.get(u, []):
            if v not in seen:
                seen.add(v)
                q.append((v, d + 1))
                breadth[d + 1] += 1

    max_breadth = max(breadth.values() or [1])
    h = base_h + px_per_branch * max(0, max_breadth - 1)
    return max(h_min, min(h, h_max))


# --------------------------- Graph builder ---------------------------------
def _graph_from_csv(root_label: str, down_depth: int = 3, up_levels: int = 1,
                    include_siblings: bool = True, max_edges: int = 2000):
    """
    Constrói NODES/LINKS a partir do CSV do projeto para o 'root_label'.
    - down_depth: níveis a jusante (derivatives)
    - up_levels: níveis a montante (influences)
    - include_siblings: inclui irmãos quando sobe
    """
    try:
        df, _ = load_hierarchy_csv()
        children, leaves, roots, leaf_url = build_indices(df)
    except Exception as e:
        st.error(f"Failed to load genres CSV: {e}")
        return [], []

    # Mapa de pais para subir na árvore
    parents_map = {}
    for pref, kids in children.items():
        for ch in kids:
            child_pref = tuple(list(pref) + [ch])
            parents_map[child_pref] = pref

    # --- Resolver 'root_label' para um prefixo existente no índice ---
    target = norm(root_label) if root_label else ""
    candidates = []

    if target:
        # 1) match exato em pais (último segmento do prefixo)
        for pref in children.keys():
            if pref and norm(pref[-1]) == target:
                candidates.append(pref)

        # 2) match parcial em pais
        if not candidates:
            for pref in children.keys():
                if pref and target in norm(pref[-1]):
                    candidates.append(pref)

        # 3) match em filhos (ex.: "New Wave" existir apenas como filho)
        if not candidates:
            for pref, kids in children.items():
                for ch in kids:
                    if norm(ch) == target or target in norm(ch):
                        candidates.append(tuple(list(pref) + [ch]))

    if not candidates:
        # Sem nós: devolve pelo menos o nó isolado (sem arestas) —
        # serve para mostrar info em falta em vez de "not found".
        return ([root_label] if root_label else []), []

    # Escolhe o prefixo mais fundo (melhor contexto quando existem duplicados)
    root_pref = max(candidates, key=lambda p: len(p))
    root = root_pref[-1]

    # ----------------- BFS para jusante (derivatives) -----------------
    from collections import deque
    seen_prefixes = {root_pref}
    nodes = set([root])
    links: list[tuple[str, str, float]] = []
    q = deque([(root_pref, 0)])

    while q and len(links) < max_edges:
        cur, d = q.popleft()
        if d >= down_depth:
            continue
        for ch in sorted(children.get(cur, set())):
            if not norm(ch):
                continue
            parent_label = cur[-1]
            child_pref = tuple(list(cur) + [ch])
            nodes.add(parent_label); nodes.add(ch)
            links.append((parent_label, ch, 1.0))
            if child_pref not in seen_prefixes:
                seen_prefixes.add(child_pref)
                q.append((child_pref, d + 1))

    # ----------------- Subida e irmãos (contexto) ---------------------
    if up_levels > 0:
        asc = root_pref
        for _ in range(up_levels):
            parent_pref = parents_map.get(asc)
            if not parent_pref:
                break
            parent_label = parent_pref[-1]
            child_label = asc[-1]
            nodes.add(parent_label); nodes.add(child_label)
            links.append((parent_label, child_label, 1.0))
            if include_siblings:
                for sib in children.get(parent_pref, []):
                    if sib != child_label:
                        nodes.add(sib)
                        links.append((parent_label, sib, 1.0))
            asc = parent_pref

    # Ordena nós (raiz primeiro)
    def _key(n: str):
        return (0 if n.lower() == root.lower() else 1, n.lower())
    nodes_sorted = sorted(nodes, key=_key)

    # Remover duplicados em links preservando ordem
    seen_edges = set()
    uniq_links = []
    for s, t, w in links:
        if (s, t) not in seen_edges:
            seen_edges.add((s, t))
            uniq_links.append((s, t, w))

    return nodes_sorted, uniq_links


# ---------------------------- Plot builder ---------------------------------
def _build_sankey(nodes, links, title="Influence map"):
    idx = {n: i for i, n in enumerate(nodes)}
    src = [idx[s] for (s, t, *_) in links if s in idx and t in idx]
    trg = [idx[t] for (s, t, *_) in links if s in idx and t in idx]

    # Pesos uniformes (espessura relativa normaliza no espaço vertical disponível)
    val = []
    for s, t, *rest in links:
        if s in idx and t in idx:
            w = rest[0] if rest else 1.0
            try:
                w = float(w)
            except (TypeError, ValueError):
                w = 1.0
            val.append(w)

    fig = go.Figure(data=[go.Sankey(
        arrangement="snap",
        node=dict(
            label=nodes,
            pad=14,
            thickness=16,
            color="rgba(31, 119, 180, 0.65)"
        ),
        link=dict(
            source=src,
            target=trg,
            value=val,
            color="rgba(180,180,180,0.6)",
            hovertemplate="%{source.label} → %{target.label} (%{value})<extra></extra>",
        ),
    )])

    fig.update_layout(
        margin=dict(l=10, r=10, t=20, b=10),
        title=title,
        height=560,  # altura base (a dinâmica é aplicada fora)
        font=dict(family="Segoe UI, Roboto, Helvetica, Arial, sans-serif", size=16, color="#1f2937"),
        hoverlabel=dict(font_size=14, font_family="Segoe UI, Roboto, Helvetica, Arial, sans-serif"),
        clickmode="event+select",
    )
    return fig


# ----------------------------- Page ----------------------------------------
def render_influence_map_page():
    show_page_help("influence_map", lang="PT")

    # Header: título (esq.) + quick picks (dir.)
    h1_left, h1_right = st.columns([0.6, 0.4])
    with h1_left:
        st.subheader("🎼 Influence map")
    with h1_right:
        st.markdown("**Quick picks**")
        c1, c2, c3, c4 = st.columns(4)
        def _set_root(lbl):
            st.session_state["infl_root"] = lbl
        with c1:
            st.button("Blues",  key="qp_blues",   on_click=_set_root, args=("Blues",))
            st.button("Metal",  key="qp_metal",   on_click=_set_root, args=("Metal",))
        with c2:
            st.button("Jazz",   key="qp_jazz",    on_click=_set_root, args=("Jazz",))
            st.button("Funk",   key="qp_funk",    on_click=_set_root, args=("Funk",))
        with c3:
            st.button("Rock",   key="qp_rock",    on_click=_set_root, args=("Rock",))
            st.button("New Wave", key="qp_newwave", on_click=_set_root, args=("New Wave",))
        with c4:
            st.button("Pop",    key="qp_pop",     on_click=_set_root, args=("Pop",))
            st.button("Reggae", key="qp_reggae",  on_click=_set_root, args=("Reggae",))

    # Search (sem default)
    st.session_state.setdefault("infl_root", "")
    root = st.text_input("Search genre", key="infl_root", placeholder="Type 2+ letters (e.g., Jazz, Blues, House, Prog Rock...)")

    # Help
    with st.expander("How to use", expanded=True):
        st.markdown("""
1. Type a genre in **Search genre**; the selectbox shows all matches.
2. Pick one to see **influences** (upstream), **derivatives** (downstream) and the **branch map**.
3. In the map you can choose the **depth** (levels below the genre) and select the **branch** step by step.
        """)
    st.selectbox("What can I search?", ["Type any genre or subgenre name you expect in the CSV…"], index=0)

    # Controls
    colB, colC = st.columns([0.7, 0.3])
    with colB:
        depth = st.slider("Depth (downstream)", 1, 5, 3, key="infl_depth")
    with colC:
        up = st.selectbox("Levels up", options=[0, 1, 2], index=1, key="infl_up")

    # Build data only when há um root
    if not root or len(root.strip()) < 1:
        st.info("Start by choosing a genre (Quick pick or type at least 2 letters).")
        return

    nodes, links = _graph_from_csv(root, down_depth=depth, up_levels=up, include_siblings=True)
    if not nodes:
        st.warning("Genre not found in CSV.")
        return

    # Plot area
    col_plot, col_side = st.columns([0.68, 0.32])
    with col_plot:
        if not links:
            st.info("This genre has no downstream links in the current map.")
        else:
            fig = _build_sankey(nodes, links, title=f"{root} — influence map")
            h = _auto_height_by_breadth(nodes, links, root)
            fig.update_layout(height=h)

            if HAS_PLOTLY_EVENTS:
                plotly_events(fig, click_event=True, hover_event=False, select_event=False,
                              override_height=h, override_width="100%",
                              key=f"sankey_dynamic")
            else:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with col_side:
        # Auto explanation simples
        st.markdown("**Selected**")
        st.write(root)
        st.markdown("**Nodes**: {}".format(len(nodes)))
        st.markdown("**Links**: {}".format(len(links)))
        st.caption("Tip: click a label to focus (when clicks are enabled).")

