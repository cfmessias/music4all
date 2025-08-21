# views/explore_page.py  — versão ECharts
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

import pandas as pd
import streamlit as st
from streamlit_echarts import st_echarts

from services.genre_csv import load_hierarchy_csv, build_indices, norm
from services.genres_kb import kb_neighbors, canonical_name, BLURBS
from services.page_help import show_page_help

# =======================
#   Constantes / tuning
# =======================
DEPTH_DEFAULT     = 4        # profundidade base (igual à Influence)
MAX_CHILDREN      = 30       # entra no “modo compacto” acima deste nº de filhos diretos
LEFT_PAD_PCT      = "1.5%"   # margem esquerda (ECharts)
RIGHT_PAD_PCT     = "22%"    # margem direita (ECharts) — espaço para rótulos grandes
NODE_GAP          = 6        # espaço vertical entre nós (ECharts)
NODE_WIDTH        = 14       # largura do nó (ECharts)
LABEL_WIDTH       = 170      # largura para quebra de linha dos rótulos
HILIGHT_COLOR     = "#175DDC"
LINK_GREY         = "rgba(0,0,0,0.18)"
CONTROL_COL_FRAC  = 0.26     # largura da coluna de controlos (esquerda)

# ==================================
#   Normalização e deduplicação
# ==================================
_RX = re.compile(r"[^a-z0-9]+")
_ALIASES_NICE = {
    "hiphop": "Hip-Hop",
    "rocknroll": "Rock ’n’ Roll",
    "bluesrock": "Blues Rock",
}

def _canon_local(s: str) -> str:
    """Normalização agressiva local (ASCII + minúsculas + remove pontuação)."""
    if not s:
        return ""
    base = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return _RX.sub("", base)

def _pretty_local(key: str) -> str:
    return _ALIASES_NICE.get(key, key.title())

def _unique_sorted(labels: List[str]) -> List[str]:
    """Lista única ordenada (usa canonical_name do teu serviço)."""
    cleaned = {canonical_name(x) for x in labels if isinstance(x, str) and x.strip()}
    return sorted(cleaned, key=str.lower)

def _cap(s: str, n: int = 12) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"

def _set_query(name: str):
    st.session_state["exp_query"] = name


# --------- CSV dinâmico (índices) ---------
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


# --------- Vizinhança (pais/filhos) ---------
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


# --------- extra (CSV hierárquico opcional) ---------
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


# --------- Adjacências normalizadas ---------
@st.cache_data(ttl=3600, show_spinner=False)
def _build_label_adjacency(children_index) -> Dict[str, Set[str]]:
    """
    Constrói {pai: {filhos}} com rótulos normalizados e “bonitos”,
    agregando variantes (Blues-rock ≡ Blues Rock).
    """
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


# --------- BFS e caminho ---------
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
    """Todas as arestas a partir de root até depth (auxiliar para realce/ramo)."""
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


# --------- ECharts: construir opções ---------
def _echarts_sankey_options(nodes: List[str],
                            edges: List[Tuple[str, str, float]],
                            highlight_edges: Set[Tuple[str, str]],
                            highlight_nodes: Set[str],
                            title: str) -> dict:
    data_nodes = []
    palette = [
        "#a1c9f4", "#ffb482", "#8de5a1", "#ff9f9b", "#d0bbff", "#debb9b",
        "#fab0e4", "#b9f2f0", "#b5e48c", "#e9c46a", "#90be6d", "#e76f51"
    ]
    for i, n in enumerate(nodes):
        data_nodes.append({
            "name": n,
            "itemStyle": {
                "color": HILIGHT_COLOR if n in highlight_nodes else palette[i % len(palette)],
                "borderColor": "#111" if n in highlight_nodes else "#999",
                "borderWidth": 2 if n in highlight_nodes else 0,
            },
            "label": {"fontSize": 13},
        })

    data_links = []
    for s, t, v in edges:
        is_high = (s, t) in highlight_edges
        data_links.append({
            "source": s, "target": t, "value": v,
            "lineStyle": {
                "color": HILIGHT_COLOR if is_high else LINK_GREY,
                "curveness": 0.10,
                "opacity": 0.95 if is_high else 0.45
            }
        })

    options = {
        "title": {"text": title},
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "sankey",
            "left": LEFT_PAD_PCT, "right": RIGHT_PAD_PCT, "top": 10, "bottom": 10,
            "data": data_nodes,
            "links": data_links,
            "nodeWidth": NODE_WIDTH,
            "nodeGap": NODE_GAP,
            "nodeAlign": "justify",
            "emphasis": {"focus": "adjacency"},
            "lineStyle": {"opacity": 0.6},
            "label": {"fontSize": 13, "distance": 2, "width": LABEL_WIDTH, "overflow": "break"},
        }]
    }
    return options


# ----------------- PÁGINA -----------------
def render_explore_page():
    # mobile / idioma
    is_mobile = bool(st.session_state.get("mobile_layout") or st.session_state.get("mobile"))
    show_page_help("explore", lang=st.session_state.get("lang", "EN"))

    # Título + quick picks (topo)
    if not is_mobile:
        colT1, colT2 = st.columns([0.62, 0.38])
    else:
        colT1, colT2 = st.columns([1.0, 0.0])
    with colT1:
        st.title("🔎 Explore · Music4all")

    quick = ["Blues", "Jazz", "Rock", "Pop", "Metal", "House",
             "Funk", "Disco", "Hip-Hop", "New Wave", "Synth-pop", "Reggae"]
    if not is_mobile:
        with colT2:
            st.markdown("**Atalhos**")
            qcols = st.columns(4)
            for i, name in enumerate(quick):
                with qcols[i % 4]:
                    st.button(_cap(name), key=f"exp_chip_top_{i}",
                              on_click=_set_query, args=(name,))
    else:
        pick = st.selectbox("Atalho", ["— escolher —"] + quick, key="exp_qp_select")
        if pick and pick != "— escolher —":
            _set_query(pick)

    # Estado base
    st.session_state.setdefault("exp_query", "")
    st.session_state.setdefault("exp_depth", DEPTH_DEFAULT)

    # Dados principais
    children_index = _load_children_index()
    labels = _all_labels(children_index)

    # Pesquisa
    st.text_input(
        "Pesquisar género",
        placeholder="Escreve pelo menos 2 letras (ex.: Jazz, Blues, House, Prog Rock…)",
        key="exp_query",
        help="Pesquisa qualquer género/subgénero. Começa a escrever."
    )
    q = st.session_state["exp_query"].strip()
    matches = [x for x in labels if q and q.lower() in x.lower()]
    exact = next((x for x in labels if q and x.lower() == q.lower()), None)

    if exact:
        root = canonical_name(exact)
    elif len(matches) == 1:
        root = canonical_name(matches[0])
    else:
        root = ""

    if not root:
        st.caption("Refina a pesquisa ou escolhe um subgénero em **Nível 1**.")
        return

    # Texto/metadata do género (BLURBS)
    b = BLURBS.get(root, {})
    period  = b.get("period", "—")
    regions = ", ".join(b.get("regions", []) or []) or "—"
    chars   = ", ".join(b.get("characteristics", []) or []) or "—"
    st.markdown(f"### {root}")
    st.markdown(f"**Período:** {period}  **Áreas-chave:** {regions}  **Traços típicos:** {chars}")
    st.divider()

    # Adjacências normalizadas para o mapa
    adj = _build_label_adjacency(children_index)

    # Layout: esquerda (controlos/listas) + direita (gráfico)
    col_l, col_r = st.columns([CONTROL_COL_FRAC, 1.0 - CONTROL_COL_FRAC] if not is_mobile else [1, 0])

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

        st.markdown("#### Influências (a montante)")
        st.write("—" if not parents else " • ".join(parents))
        st.markdown("#### Derivações (a jusante)")
        st.write("—" if not children else " • ".join(children))

        # Modo compacto automático
        num_children = len(adj.get(root, set()))
        compact = num_children > MAX_CHILDREN
        if compact:
            st.info(
                f"**{root}** tem muitas ramificações diretas ({num_children}). "
                f"Para manter o gráfico legível mostramos **apenas 2 níveis**. "
                f"Escolhe um subgénero para detalhar, ou força a vista completa."
            )
            force_full = st.checkbox("Mostrar tudo assim mesmo", value=False, key="expl_show_all")
            depth = DEPTH_DEFAULT if force_full else 2
        else:
            depth = st.slider("Profundidade do mapa (níveis abaixo deste género)",
                              2, 7, int(st.session_state.get("exp_depth", DEPTH_DEFAULT)),
                              key="exp_depth")

        # Escolha do ramo (Nível 1) + “só ramo”
        level1_options = sorted(adj.get(root, set()), key=str.lower)
        level1 = st.selectbox("Nível 1", options=["— selecionar —"] + level1_options, index=0, key="expl_lvl1")
        show_branch_only = st.checkbox("Mostrar só o ramo selecionado", value=False, key="expl_branch_only")

        # Quick picks para incentivar drill-down quando há muitos filhos
        if level1_options and compact:
            st.caption("Atalhos de subgéneros")
            scored = sorted(level1_options, key=lambda x: len(adj.get(x, set())), reverse=True)[:12]
            rows = (len(scored) + 2) // 3
            i = 0
            for _ in range(rows):
                c1, c2, c3 = st.columns(3)
                for c in (c1, c2, c3):
                    if i < len(scored):
                        label = scored[i]
                        if c.button(label, key=f"qp_{label}"):
                            st.session_state["expl_lvl1"] = label
                            st.rerun()
                        i += 1

        # Breadcrumb
        trilho = root
        if level1 and level1 != "— selecionar —":
            trilho += f" → {level1}"
        st.caption(trilho)

    with (col_r if not is_mobile else st.container()):
        # Construção de nós/arestas com BFS
        nodes, edges_list, level_map = _bfs_down_labels(adj, root, depth)

        # Se não houver arestas, mostra pelo menos root -> filhos diretos
        if not edges_list:
            direct_children = sorted(adj.get(root, set()), key=str.lower)
            if direct_children:
                nodes = [root] + direct_children
                edges_list = [(root, c) for c in direct_children]

        if not nodes or not edges_list:
            st.info("Sem ligações para esta profundidade.")
            return

        # Destaque do ramo
        highlight_edges: Set[Tuple[str, str]] = set()
        highlight_nodes: Set[str] = {root}
        if level1 and level1 != "— selecionar —":
            path_e = set(_path_edges(edges_list, root, level1))
            sub_e = _subtree_edges(level1, adj, max(depth - 1, 0))
            highlight_edges |= path_e | sub_e
            highlight_nodes |= {a for a, _ in highlight_edges} | {b for _, b in highlight_edges}

        # “Só ramo selecionado”
        if show_branch_only and level1 and level1 != "— selecionar —":
            # limitar arestas ao conjunto destacado; nós = incidentes nessas arestas
            edges = list(highlight_edges)
            nodes_set = {root} | {a for a, _ in edges} | {b for _, b in edges}
            nodes = [n for n in nodes if n in nodes_set]
        else:
            edges = edges_list

        # ECharts
        edges_val = [(a, b, 1.0) for (a, b) in edges]
        options = _echarts_sankey_options(
            nodes=nodes,
            edges=edges_val,
            highlight_edges=highlight_edges,
            highlight_nodes=highlight_nodes,
            title=f"{root} — mapa de influências (explore)"
        )
        st_echarts(options=options, height="700px", key=f"explore_{root}")
        st.caption("Azul = ramo destacado desde o género selecionado.")
