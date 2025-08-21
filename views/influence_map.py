# views/influence_map.py
import streamlit as st
import plotly.graph_objects as go

# Optional: clickable Plotly inside Streamlit; we fallback if missing
try:
    from streamlit_plotly_events import plotly_events
    HAS_PLOTLY_EVENTS = True
except Exception:
    HAS_PLOTLY_EVENTS = False

# Dynamic mode (CSV)
from services.genre_csv import load_hierarchy_csv, build_indices, norm
from services.page_help import show_page_help

# ====================================================================
# MODE 1 — CURATED DATA (kept as before, independent of CSV)
# ====================================================================
def _curated_graph():
    nodes = [
        # Roots & matrices
        "African musical traditions", "Work songs/Field hollers", "Spirituals/Gospel",
        "Country/Old-time", "Jazz (early)",

        # Blues and variants
        "Blues", "Delta Blues", "Chicago Blues",

        # Early popular branches
        "R&B (40s/50s)", "Rock ’n’ Roll", "Rockabilly", "Soul", "Funk",

        # Rock (classic lines)
        "Blues Rock", "British Blues", "Hard Rock", "Psychedelic Rock",
        "Progressive Rock", "Heavy Metal",

        # Other derivations
        "Jazz Fusion", "Disco", "Hip-Hop", "Pop/Rock (mainstream)",
    ]
    links = [
        ("African musical traditions", "Work songs/Field hollers", 6),
        ("African musical traditions", "Spirituals/Gospel",         6),
        ("Work songs/Field hollers",  "Blues",                      8),
        ("Spirituals/Gospel",         "Blues",                      3),
        ("Country/Old-time",          "Blues",                      2),
        ("Jazz (early)",              "Blues",                      2),

        ("Blues",       "Delta Blues",   6),
        ("Blues",       "Chicago Blues", 5),

        ("Blues",       "R&B (40s/50s)", 6),
        ("R&B (40s/50s)","Rock ’n’ Roll",6),
        ("Country/Old-time", "Rockabilly", 5),
        ("Rockabilly",  "Rock ’n’ Roll", 4),

        ("Chicago Blues", "Blues Rock", 6),
        ("Delta Blues",   "British Blues", 5),

        ("British Blues", "Hard Rock", 6),
        ("Psychedelic Rock", "Progressive Rock", 5),
        ("Blues Rock",   "Hard Rock", 4),
        ("Hard Rock",    "Heavy Metal", 6),

        ("R&B (40s/50s)","Soul", 6),
        ("Soul",         "Funk", 6),
        ("Funk",         "Disco", 5),

        ("Jazz (early)", "Jazz Fusion", 5),
        ("Funk",         "Jazz Fusion", 3),

        ("Funk",         "Hip-Hop", 5),
        ("Soul",         "Hip-Hop", 3),

        ("Rock ’n’ Roll","Pop/Rock (mainstream)", 6),
        ("Soul",         "Pop/Rock (mainstream)", 4),
    ]
    return nodes, links


# ====================================================================
# MODE 2 — DYNAMIC DATA (from your genres CSV)
# ====================================================================
def _graph_from_csv(root_label: str, down_depth: int = 3, up_levels: int = 1,
                    include_siblings: bool = True, max_edges: int = 2000):
    """
    Build NODES/LINKS from the CSV for 'root_label'.

    down_depth: how many levels to go down (children, grandchildren, …)
    up_levels:  how many levels to go up (parent, grandparent, …) for context
    include_siblings: include siblings when going up (adds context)
    """
    try:
        df, _ = load_hierarchy_csv()
        children, leaves, roots, leaf_url = build_indices(df)
    except Exception as e:
        st.error(f"Failed to load genres CSV: {e}")
        return [], []

    # parent index to allow going up
    parents_map = {}  # child_prefix (tuple) -> parent_prefix (tuple)
    for pref, chs in children.items():
        for ch in chs:
            child_pref = tuple(list(pref) + [ch])
            parents_map[child_pref] = pref

    # find candidates whose last segment matches the label
    target = norm(root_label)
    candidates = []
    for pref in children.keys():
        if pref and norm(pref[-1]) == target:
            candidates.append(pref)
    if not candidates:
        for pref in children.keys():
            if pref and target in norm(pref[-1]):
                candidates.append(pref)
    if not candidates:
        st.warning("Genre not found in CSV.")
        return [], []

    # choose the DEEPEST matching path (best context when duplicates exist)
    root = max(candidates, key=lambda p: len(p))

    # BFS down
    from collections import deque
    seen_prefixes = {root}
    nodes = set([root[-1]])
    links = []
    q = deque([(root, 0)])

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
            links.append((parent_label, ch, 1))
            if child_pref not in seen_prefixes:
                seen_prefixes.add(child_pref)
                q.append((child_pref, d + 1))

    # BFS up (with siblings)
    asc = root
    for _ in range(up_levels):
        parent_pref = parents_map.get(asc)
        if not parent_pref or len(parent_pref) == 0:
            break

        parent_label = parent_pref[-1]
        child_label = asc[-1]
        nodes.add(parent_label); nodes.add(child_label)
        links.append((parent_label, child_label, 1))

        if include_siblings:
            for sib in sorted(children.get(parent_pref, set())):
                if sib != child_label:
                    nodes.add(sib)
                    links.append((parent_label, sib, 1))

        asc = parent_pref  # go up another level

    # sort nodes (root first)
    def _key(n):
        return (0 if norm(n) == target else 1, n.lower())
    nodes = sorted(nodes, key=_key)

    return nodes, links


# ====================================================================
# Utilities (work with any nodes/links pair)
# ====================================================================
def _index_graph(nodes, links):
    from collections import defaultdict
    node_index = {n: i for i, n in enumerate(nodes)}
    parents = defaultdict(list)
    children = defaultdict(list)
    for s, t, *rest in links:
        if s in node_index and t in node_index:
            if s not in parents[t]:
                parents[t].append(s)
            if t not in children[s]:
                children[s].append(t)
    return node_index, parents, children

def _explain_label(label: str, parents, children):
    """Auto summary from provided links."""
    parts = []
    if label.lower() == "blues":
        parts.append(
            "**Etymology**: *blues* links to **blue devils** (17th c.), "
            "i.e., melancholy/sadness — hence *to feel blue*. "
            "The style’s name reflects its role expressing sorrow, resilience, and hope "
            "in African-American communities."
        )

    infl = parents.get(label, [])
    if infl:
        parts.append("**Direct influences**: " + ", ".join(infl) + ".")
    der = children.get(label, [])
    if der:
        parts.append("**Immediate derivatives/impact**: " + ", ".join(der) + ".")
    grand = sorted({g for c in der for g in children.get(c, [])})
    if grand:
        parts.append("**Next branches**: " + ", ".join(grand) + ".")

    if not parts:
        parts.append("No additional information in this map for this node.")
    parts.append("_Text generated from the current map links._")
    return "\n\n".join(parts)

def _build_sankey(nodes, links, title="Influence map"):
    import plotly.express as px  # for a soft qualitative palette

    idx = {n: i for i, n in enumerate(nodes)}
    src = [idx[s] for (s, t, *_) in links if s in idx and t in idx]
    trg = [idx[t] for (s, t, *_) in links if s in idx and t in idx]
    val = [(rest[0] if rest else 1) for (s, t, *rest) in links if s in idx and t in idx]

    FONT_STACK = "Segoe UI, Roboto, Helvetica, Arial, sans-serif"

    base_palette = px.colors.qualitative.Set3
    repeats = (len(nodes) // len(base_palette)) + 1
    node_colors = (base_palette * repeats)[:len(nodes)]

    LINK_GREY = "rgba(0,0,0,0.18)"

    fig = go.Figure(data=[go.Sankey(
        arrangement="snap",
        node=dict(
            label=nodes,
            pad=22,
            thickness=20,
            color=node_colors,
            line=dict(color="rgba(0,0,0,0.25)", width=0.7),
            hovertemplate="%{label}<extra></extra>",
            customdata=nodes,                    # for node click
        ),
        link=dict(
            source=src,
            target=trg,
            value=val,
            color=LINK_GREY,
            hovertemplate="%{source.label} → %{target.label} (%{value})<extra></extra>",
            customdata=[nodes[t] for t in trg],  # for link click (target)
        ),
    )])

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        title=title,
        height=560,
        font=dict(family=FONT_STACK, size=16, color="#1f2937"),
        hoverlabel=dict(font_size=14, font_family=FONT_STACK),
        clickmode="event+select",
    )
    fig.update_traces(textfont=dict(family=FONT_STACK, size=16, color="#222"))
    return fig

def _label_from_event(ev: dict, nodes: list, links: list):
    """Extract a reliable label from a Sankey event (node or link)."""
    label = ev.get("label")
    if isinstance(label, str) and label:
        return label
    cd = ev.get("customdata")
    if isinstance(cd, str) and cd:
        return cd
    if isinstance(cd, list) and cd and isinstance(cd[0], str):
        return cd[0]
    trg = ev.get("target"); src = ev.get("source")
    if isinstance(trg, int) and 0 <= trg < len(nodes):
        return nodes[trg]
    if isinstance(src, int) and 0 <= src < len(nodes):
        return nodes[src]
    pn = ev.get("pointIndex") if "pointIndex" in ev else ev.get("pointNumber")
    if isinstance(pn, int):
        if 0 <= pn < len(nodes):
            return nodes[pn]
        if 0 <= pn < len(links):
            try:
                return links[pn][1]
            except Exception:
                pass
    return None


# ====================================================================
# Page
# ====================================================================
def render_influence_map_page():

    show_page_help("influence_map", lang="PT")

    st.subheader("🎼 Blues roots & influence map")

    # --- Read defaults coming from Genealogy (if any) ---
    root_default  = st.session_state.get("infl_root", "Blues")
    focus_default = st.session_state.get("infl_focus", root_default)
    depth_default = int(st.session_state.get("infl_depth", 3))
    up_default    = int(st.session_state.get("infl_up", 1))

    # --- Data source (guard + radio) ---
    options = ["Dynamic", "Curated"]
    aliases = {"Dinâmico": "Dynamic", "Dinamico": "Dynamic", "Curado": "Curated"}

    # normalizar ANTES do widget existir
    prior = st.session_state.get("infl_mode")
    if prior in aliases:
        st.session_state["infl_mode"] = aliases[prior]
    if st.session_state.get("infl_mode") not in options:
        st.session_state["infl_mode"] = options[0]

    mode = st.radio(
        "Data source",
        options,
        index=options.index(st.session_state["infl_mode"]),
        horizontal=True,
        key="infl_mode",     # o próprio radio passa a gerir esta key
    )

# >>> NÃO escrevas st.session_state["infl_mode"] = mode aqui <<< 
# (o radio já atualiza esta key por nós)


    # --- Controls (always visible) ---
    # --- defaults antes de criar os widgets (importante) ---
    st.session_state.setdefault("infl_root", st.session_state.get("infl_root", "Blues"))
    st.session_state.setdefault("infl_depth", st.session_state.get("infl_depth", 3))
    st.session_state.setdefault("infl_up",    st.session_state.get("infl_up", 1))

    colA, colB, colC = st.columns([0.55, 0.30, 0.15])

    with colA:
        # O text_input passa a gerir a própria key "infl_root"
        root = st.text_input("Start genre", key="infl_root")

        # Nunca escrevas diretamente na mesma key depois do widget.
        # Usa callback: executa antes da próxima renderização.
        def _jump_blues():
            st.session_state["infl_root"] = "Blues"
        st.button("Blues", help="Quick jump to the Blues branch", on_click=_jump_blues)

    with colB:
        depth = st.slider("Depth (downstream)", 1, 5, key="infl_depth")

    with colC:
        up = st.selectbox("Levels up", options=[0, 1, 2], key="infl_up")

    # ===== Build data =====
    if mode == "Curated":
        nodes, links = _curated_graph()
        title = "Blues → R&B/Rock/Soul/Funk… (influence map)"
        root_for_depth = "Blues"
    else:
        nodes, links = _graph_from_csv(root, down_depth=depth, up_levels=up, include_siblings=True)
        if not nodes or not links:
            return
        title = f"{root} — influence map (dynamic)"
        root_for_depth = root

        # Diagnose actual depth reached from root
        from collections import deque, defaultdict
        graph = defaultdict(list)
        for s, t, *_ in links:
            graph[s].append(t)

        def _max_depth_from(start):
            seen = {start}
            q = deque([(start, 0)])
            maxd = 0
            while q:
                u, d = q.popleft()
                maxd = max(maxd, d)
                for v in graph.get(u, []):
                    if v not in seen:
                        seen.add(v)
                        q.append((v, d + 1))
            return maxd

        st.caption(f"Requested depth: {depth} · reached: {_max_depth_from(root_for_depth)} · nodes: {len(nodes)} · links: {len(links)}")

    # Indices (for the auto explanation)
    node_index, parents, children = _index_graph(nodes, links)

    # Layout: plot (left) + side panel (right)
    col_plot, col_side = st.columns([0.68, 0.32])

    with col_plot:
        fig = _build_sankey(nodes, links, title=title)

        selected_label = None
        if HAS_PLOTLY_EVENTS:
            events = plotly_events(
                fig,
                click_event=True,
                hover_event=False,
                select_event=False,
                override_height=560,
                override_width="100%",
                key=f"sankey_{'curated' if mode=='Curated' else 'dynamic'}",
            )
            if events:
                selected_label = _label_from_event(events[0], nodes, links)
        else:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.caption("Tip: install `streamlit-plotly-events` for clickable nodes & links.")

    with col_side:
        st.markdown("#### Pick a node")

        # Fallback selector by label (works even if no click happens)
        default_label = selected_label or (st.session_state.get("infl_selected") or focus_default)
        if default_label not in nodes:
            default_label = nodes[0]
        chosen = st.selectbox("Node", options=nodes, index=nodes.index(default_label), key="infl_pick_label")

        st.session_state["infl_selected"] = chosen
        st.markdown(_explain_label(chosen, parents, children))

        # Shortcut to Genres page
        if st.button("🔎 Search this genre on the *🧭 Genres* page", use_container_width=True):
            st.session_state["genres_search_q"] = chosen
            st.success("Done! Open the **🧭 Genres** tab and hit **Search**.")

    # Keep state in sync for cross-page navigation
    # st.session_state["infl_root"]  = root
    # st.session_state["infl_focus"] = chosen
    # st.session_state["infl_depth"] = depth
    # st.session_state["infl_up"]    = up
