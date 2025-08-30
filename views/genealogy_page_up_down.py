# views/genealogy_page.py
# -----------------------------------------------------------------------------
# Music4all · Genre Genealogy (dynamic CSV + extra CSV + curated KB)
# - Quick picks: em desktop são botões; em mobile uma select.
# - Selectboxes em cascata (níveis) com correção do "reset".
# - Sankey: 10% de folga lateral; linhas não-destacadas mais claras;
#           "Show only the selected branch" mantém o layout e esconde só as linhas.
# -----------------------------------------------------------------------------
from __future__ import annotations

import os
import re
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services.genre_csv import load_hierarchy_csv, build_indices, norm
from services.genres_kb import genre_summary, kb_neighbors, canonical_name, BLURBS
from services.page_help import show_page_help


# ======================
# Helpers
# ======================
def _unique_sorted(labels: List[str]) -> List[str]:
    """Unique + sort (case/alias-insensitive)."""
    cleaned = {canonical_name(x) for x in labels if isinstance(x, str) and x.strip()}
    return sorted(cleaned, key=str.lower)


def _cap(s: str, n: int = 12) -> str:
    s = (s or '').strip()
    return s if len(s) <= n else s[: n - 1] + '…'


def _set_query(name: str):
    st.session_state['gen_query'] = name


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


def _build_reverse_adjacency(adj: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """child -> {parents} a partir de Parent -> {children}."""
    rev: Dict[str, Set[str]] = defaultdict(set)
    for parent, childs in adj.items():
        for c in childs:
            if c:
                rev[canonical_name(c)].add(canonical_name(parent))
    return rev


def _bfs_up_labels(adj_up: Dict[str, Set[str]], root: str, depth: int):
    """
    BFS 'para cima' (upstream), com níveis negativos:
    root = 0; pais diretos = -1; avós = -2; ...
    As arestas continuam orientadas Parent → Child (esquerda → direita).
    """
    root = canonical_name(root)
    nodes = {root}
    edges: List[Tuple[str, str]] = []
    level: Dict[str, int] = {root: 0}
    q = deque([root])

    while q:
        u = q.popleft()
        if abs(level[u]) >= depth:
            continue
        for p in sorted(adj_up.get(u, set()), key=str.lower):
            p = canonical_name(p)
            edges.append((p, u))  # parent → child
            if p not in nodes:
                nodes.add(p)
                level[p] = level[u] - 1
                q.append(p)

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
    branch_only: bool = False,
    is_mobile: bool = False,
):
    """
    Sankey com:
      • níveis distribuídos de forma estável (10%…90%),
      • ramo root→focus a azul,
      • esquerda (upstream) a azul translúcido,
      • direita (downstream) em cinzentos por ramo de 1º nível,
      • linhas fininhas via link ‘calibrador’ invisível fora do grafo.
    """
    import numpy as np
    from collections import defaultdict, deque as _deque

    FONT = "Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    PALETTE = px.colors.qualitative.Set3
    LINK_GREY = "rgba(0,0,0,0.24)"
    BLUE = "#3b82f6"

    # ---- Calibrar para links finos com par de nós invisíveis isolados ----
    CALIBRATE_THIN = True
    DUMMY_A = "\u200b"   # zero-width space
    DUMMY_B = "\u200c"   # zero-width non-joiner
    if CALIBRATE_THIN and DUMMY_A not in nodes:
        nodes = nodes + [DUMMY_A, DUMMY_B]
        last_lvl = max(level.values()) if level else 0
        level[DUMMY_A] = last_lvl + 1
        level[DUMMY_B] = last_lvl + 2

    # Índices dos nós
    idx = {n: i for i, n in enumerate(nodes)}

    # X por nível com 10% de folga lateral
    uniq_lvls = sorted({level.get(n, 0) for n in nodes})
    pos_map = {uniq_lvls[0] if uniq_lvls else 0: 0.5} if len(uniq_lvls) <= 1 else {
        lv: float(x) for lv, x in zip(uniq_lvls, np.linspace(0.10, 0.90, num=len(uniq_lvls)))
    }
    xs = [pos_map.get(level.get(n, 0), 0.5) for n in nodes]

    # Distribuição vertical por nível (evita nós encavalitados)
    DUMMIES = {DUMMY_A, DUMMY_B} if CALIBRATE_THIN else set()
    ys_map = {}
    for lv in uniq_lvls:
        col = [n for n in nodes if n not in DUMMIES and level.get(n, 0) == lv]
        if not col:
            continue
        ys_lv = np.linspace(0.20, 0.80, num=len(col))  # ajusta 0.20..0.80 conforme preferires
        for n, y in zip(sorted(col, key=str.lower), ys_lv):
            ys_map[n] = float(y)
    for d in DUMMIES:
        ys_map[d] = 0.5  # dummys ao centro
    ys = [ys_map.get(n, 0.5) for n in nodes]

    # Cores de nós (o caminho a azul; dummys invisíveis)
    reps = (len(nodes) // len(PALETTE)) + 1
    ncolors = (PALETTE * reps)[: len(nodes)]

    # ---- Mapa do "primeiro filho" (first-hop) para o lado direito ----
    children_map = defaultdict(list)
    for a, b in edges:
        if level.get(a, 0) >= 0 and level.get(b, 0) > 0:
            children_map[a].append(b)

    firsthop = {}
    for child in children_map.get(root, []):
        firsthop[child] = child
        dq = _deque([child])
        while dq:
            u = dq.popleft()
            for v in children_map.get(u, []):
                if v not in firsthop:
                    firsthop[v] = firsthop[u]
                    dq.append(v)

    # Tons por ramo (direita)
    TONE_ROOT_DIRECT   = "rgba(0,0,0,0.22)"
    TONE_DARK_WAVE     = "rgba(0,0,0,0.34)"
    TONE_ETHEREAL_WAVE = "rgba(0,0,0,0.28)"
    BRANCH_TONES = {
        canonical_name("Dark wave"):     TONE_DARK_WAVE,
        canonical_name("Ethereal wave"): TONE_ETHEREAL_WAVE,
    }

    BLUE_LEFT = "rgba(59,130,246,0.55)"  # azul translúcido p/ upstream

    # Caminho root→focus (para pintar nós/links a azul)
    path = set(_path_edges(edges, root, focus))
    path_nodes = {root, focus} | {a for a, _ in path} | {b for _, b in path}
    for i, n in enumerate(nodes):
        if n in path_nodes:
            ncolors[i] = BLUE
    if CALIBRATE_THIN:
        ncolors[idx[DUMMY_A]] = "rgba(0,0,0,0)"
        ncolors[idx[DUMMY_B]] = "rgba(0,0,0,0)"

    # Ligações
    src, dst, val, lcol = [], [], [], []
    for a, b in edges:
        if a not in idx or b not in idx:
            continue
        src.append(idx[a]); dst.append(idx[b]); val.append(1)

        is_left_edge = (level.get(a, 0) < 0) and (level.get(b, 0) <= 0)
        on_path = (a, b) in path

        if on_path:
            lcol.append(BLUE)
        elif is_left_edge:
            lcol.append(BLUE_LEFT)
        else:
            if level.get(a, 0) == 0 and level.get(b, 0) == 1:
                lcol.append(TONE_ROOT_DIRECT)  # root → filho direto
            elif level.get(a, 0) >= 0 and level.get(b, 0) > 0:
                fh = canonical_name(firsthop.get(b) or firsthop.get(a) or "")
                lcol.append(BRANCH_TONES.get(fh, LINK_GREY))
            else:
                lcol.append("rgba(0,0,0,0)" if branch_only else LINK_GREY)

    # Link calibrador invisível (não ligado ao grafo real)
    if CALIBRATE_THIN:
        CAL_FACTOR = 7                      # ↓ menor = linhas mais grossas
        src.append(idx[DUMMY_A])
        dst.append(idx[DUMMY_B])
        val.append(max(40, CAL_FACTOR * len(edges)))
        lcol.append("rgba(0,0,0,0)")

    # Proporções / tamanhos
    few = len(nodes) <= 8
    node_thickness = (10 if is_mobile else (12 if few else 20))
    node_pad       = (8  if is_mobile else (10 if few else 18))

    # Altura dinâmica (ignora dummies)
    DUMMIES = {DUMMY_A, DUMMY_B} if CALIBRATE_THIN else set()
    visible_nodes = [n for n in nodes if n not in DUMMIES]
    if visible_nodes:
        uniq_lvls_vis = sorted({level.get(n, 0) for n in visible_nodes})
        max_per_level = max(sum(1 for n in visible_nodes if level.get(n, 0) == lv) for lv in uniq_lvls_vis)
    else:
        max_per_level = 1
    base_h   = 180 if is_mobile else 280
    chart_height = int(min(560, max(260, base_h + 28 * max_per_level)))

    font_size  = (13 if is_mobile else 15)
    hover_size = (12 if is_mobile else 14)

    fig = go.Figure(go.Sankey(
        arrangement="fixed",
        node=dict(
            label=nodes,
            x=xs,
            y=ys,
            pad=node_pad,
            thickness=node_thickness,
            color=ncolors,
            line=dict(color="rgba(0,0,0,0)", width=0),  # sem contorno (esconde dummys)
            hovertemplate="%{label}<extra></extra>",
        ),
        link=dict(
            source=src,
            target=dst,
            value=val,
            color=lcol,
            hovertemplate="%{source.label} → %{target.label}<extra></extra>",
        ),
    ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=chart_height,
        font=dict(family=FONT, size=font_size, color="#1f2937"),
        hoverlabel=dict(font_size=hover_size, font_family=FONT),
    )
    fig.update_traces(textfont=dict(family=FONT, size=font_size, color="#111827"))
    return fig


# ======================
# Página
# ======================
def render_genealogy_page():
    # Sinal de "mobile layout" (usa toggle global se existir)
    show_page_help("genealogy", lang="PT")

    is_mobile = bool(st.session_state.get("mobile_layout") or st.session_state.get("mobile"))

    # Título + quick picks (desktop=botões; mobile=select)
    if not is_mobile:
        colT1, colT2 = st.columns([0.62, 0.38])
    else:
        colT1, colT2 = st.columns([1.0, 0.0])

    with colT1:
        st.title("🧬 Genre Genealogy · Music4all")

    quick = ["Blues", "Jazz", "Rock", "Pop", "Metal", 
             "Funk",  "New Wave", "Reggae"]

    if not is_mobile:
        with colT2:
            st.markdown("**Quick picks**")
            qcols = st.columns(4)
            for i, name in enumerate(quick):
                with qcols[i % 4]:
                    st.button(_cap(name), key=f"gen_chip_top_{i}",
                              on_click=_set_query, args=(name,))
    else:
        pick = st.selectbox("Quick pick", ["— choose —"] + quick, key="gen_qp_select")
        if pick and pick != "— choose —":
            _set_query(pick)

    st.session_state.setdefault("gen_query", "")

    # Dados
    try:
        children_index = _load_children_index()
    except Exception as e:
        st.error(f"Error loading dynamic genres CSV: {e}")
        return
    labels = _all_labels(children_index)

    # Pesquisa
    st.text_input(
        "Search genre",
        placeholder="Type 2+ letters (e.g., Jazz, Blues, House, Prog Rock…)",
        key="gen_query",
        help="Search any music genre or subgenre. Start typing.",
    )
    q = st.session_state["gen_query"].strip()

    # Resolve género a partir do texto:
    matches = [x for x in labels if q and q.lower() in x.lower()]
    exact = next((x for x in labels if q and x.lower() == q.lower()), None)

    if exact:
        genre = canonical_name(exact)
    elif len(matches) == 1:
        genre = canonical_name(matches[0])
    else:
        genre = ""   # sem root fixo; o utilizador escolhe no Level 1

    # Dica quando há ambiguidade
    if q and not genre and len(matches) > 1:
        st.caption("Refina a pesquisa ou escolhe o ramo em **Level 1**.")

    # Sem seleção ainda → mostra ajuda (corrigido: sem st.markdown vazio)
    if not genre:
        with st.expander("What can I search?"):
            st.write(
                "You can search **any music genre or subgenre** you know. "
                "Start typing (2+ letters) and pick from the suggestions. "
                "Examples: *Blues*, *Jazz*, *Rock*, *Pop*, *House*, *Synth-pop*, *Hard Rock*, *New Wave*."
            )
        return

    adj    = _build_label_adjacency(children_index)
    adj_up = _build_reverse_adjacency(adj)

    # Vizinhos DIRETOS do género selecionado (o que o grafo mostra a 1 nível)
    parents  = sorted(adj_up.get(genre, set()), key=str.lower)   # esquerda
    children = sorted(adj.get(genre, set()),     key=str.lower)  # direita

    # ---- contagens diretas (nível 1) ----
    upstream   = set(parents or [])
    downstream = set(children or [])
    n_infl = len(upstream)
    n_der  = len(downstream)

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
        st.subheader(f"Influences ({n_infl} upstream)")
        st.write("—" if not parents else " • ".join(parents))
    with col_r:
        st.subheader(f"Derivatives ({n_der} downstream)")
        st.write("—" if not children else " • ".join(children))

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ----- Gráfico: controlos -----
    adj = _build_label_adjacency(children_index)
    depth = st.slider("Map depth (levels below this genre)", 1, 4, 2, key="gen_depth")

    # Selectboxes em cascata (nível a nível)
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

    st.session_state["gen_path"] = path
    focus = path[-1] if path else genre

    branch_only = st.checkbox("Show only the selected branch", value=False, key="gen_branch_only")

    # ----- Limitar géneros com demasiados ramos de 1.º nível -----
    MAX_FIRST_LEVEL = 30
    first_children = sorted(adj.get(genre, set()), key=str.lower)
    too_many = len(first_children) > MAX_FIRST_LEVEL

    if too_many and len(path) <= 1:
        st.info(
            f"“{genre}” tem {len(first_children)} subgéneros diretos. "
            "Para manter o gráfico legível, seleciona um subgénero no seletor **Level 1** acima "
            "ou procura diretamente por um subgénero (ex.: 'Active rock')."
        )
        return

    # Se tem muitos ramos e já escolheste um subgénero → mostrar só esse ramo
    force_branch_only = too_many and len(path) > 1

    # ----- Construção do grafo e desenho -----
    # Downstream (direita)
    nodes_ds, edges_ds, level_ds = _bfs_down_labels(adj, genre, depth)

    # Upstream (esquerda) — níveis negativos
    adj_up = _build_reverse_adjacency(adj)
    nodes_up, edges_up, level_up = _bfs_up_labels(adj_up, genre, depth)

    # Merge dos dois lados, com o género a nível 0
    nodes = sorted(set([*nodes_up, *nodes_ds, genre]), key=str.lower)
    edges = edges_up + edges_ds
    level = {genre: 0, **level_up, **level_ds}

    # --- Mostrar só o ramo escolhido quando aplicável (muitos ramos ou checkbox) ---
    selected_first = path[1] if len(path) > 1 else None
    if (branch_only or force_branch_only) and selected_first:
        # Reconstroi o lado direito apenas para o subgénero escolhido
        right_nodes, right_edges, right_level = _bfs_down_labels(
            adj, selected_first, max(0, depth - 1)
        )
        edges = edges_up + [(genre, selected_first)] + right_edges
        level = {
            **level_up,
            genre: 0,
            selected_first: 1,
            **{n: l + 1 for n, l in right_level.items()},
        }
        nodes = sorted(set([*nodes_up, genre, selected_first, *right_nodes]), key=str.lower)

    # Fallback “1-hop” se não houver arestas
    if not edges:
        direct_children = sorted(adj.get(genre, set()), key=str.lower)
        direct_parents  = sorted(adj_up.get(genre, set()), key=str.lower)
        if direct_children or direct_parents:
            nodes = [*direct_parents, genre, *direct_children]
            edges = [(p, genre) for p in direct_parents] + [(genre, c) for c in direct_children]
            level = {**{p: -1 for p in direct_parents}, genre: 0, **{c: 1 for c in direct_children}}

    if not nodes or not edges:
        st.info("Sem ligações para esta profundidade.")
    else:
        fig = _branch_sankey(
            nodes, edges, level,
            root=genre, focus=focus,
            branch_only=(branch_only or force_branch_only),
            is_mobile=is_mobile,
        )
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
        st.button(
            "🗺️ Open in Influence map (Dynamic)",
            use_container_width=True, on_click=_go_influence, args=(genre,),
        )
    with colR2:
        st.button(
            "🧭 Search on *Genres* page",
            use_container_width=True, on_click=_go_genres, args=(genre,),
        )
