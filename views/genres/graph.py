# views/genres/graph.py
# BFS + Sankey
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from collections import defaultdict, deque
import numpy as np

# canonical_name opcional (fallback seguro)
try:
    from services.genres_kb import canonical_name
except Exception:
    def canonical_name(x: str) -> str: return (x or "").strip()

def build_label_adjacency(children_index):
    adj = defaultdict(set)
    for pref, kids in children_index.items():
        if not pref: continue
        parent = canonical_name(pref[-1])
        for k in kids:
            if k: adj[parent].add(canonical_name(k))
    return adj

def build_reverse_adjacency(adj):
    rev = defaultdict(set)
    for parent, childs in adj.items():
        for c in childs:
            if c: rev[canonical_name(c)].add(canonical_name(parent))
    return rev

def bfs_down_labels(adj, root: str, depth: int):
    root = canonical_name(root)
    nodes = {root}; edges = []; level = {root: 0}; q = deque([root])
    while q:
        u = q.popleft()
        if level[u] >= depth: continue
        for v in sorted(adj.get(u, set()), key=str.lower):
            v = canonical_name(v); edges.append((u, v))
            if v not in nodes:
                nodes.add(v); level[v] = level[u] + 1; q.append(v)
    ordered = sorted(nodes, key=lambda n: (level[n], n.lower()))
    return ordered, edges, level

def bfs_up_labels(adj_up, root: str, depth: int):
    root = canonical_name(root)
    nodes = {root}; edges = []; level = {root: 0}; q = deque([root])
    while q:
        u = q.popleft()
        if abs(level[u]) >= depth: continue
        for p in sorted(adj_up.get(u, set()), key=str.lower):
            p = canonical_name(p); edges.append((p, u))
            if p not in nodes:
                nodes.add(p); level[p] = level[u] - 1; q.append(p)
    ordered = sorted(nodes, key=lambda n: (level[n], n.lower()))
    return ordered, edges, level

def _path_edges(edges, start: str, target: str):
    g = defaultdict(list)
    for a, b in edges: g[a].append(b)
    parent = {start: None}; q = deque([start])
    while q:
        u = q.popleft()
        for v in g.get(u, []):
            if v not in parent: parent[v] = u; q.append(v)
    if target not in parent: return []
    path, cur = [], target
    while parent[cur]:
        p = parent[cur]; path.append((p, cur)); cur = p
    path.reverse(); return path

# def branch_sankey(
#     nodes, edges, level, root, focus,
#     branch_only=False, is_mobile=False,
#     height_override=None, font_size_override=None
# ):
    
#     PALETTE = px.colors.qualitative.Set3
#     BLUE="#3b82f6"; BLUE_LEFT="rgba(59,130,246,0.55)"; LINK_GREY="rgba(0,0,0,0.24)"
#     TONE_ROOT_DIRECT="rgba(0,0,0,0.50)"
#     # Calibração p/ manter links finos
#     CALIBRATE_THIN=True; DUMMY_A="\u200b"; DUMMY_B="\u200c"
#     if CALIBRATE_THIN and DUMMY_A not in nodes:
#         nodes = nodes + [DUMMY_A, DUMMY_B]
#         last_lvl = max(level.values()) if level else 0
#         level[DUMMY_A] = last_lvl+1; level[DUMMY_B] = last_lvl+2

#     idx = {n:i for i,n in enumerate(nodes)}
#     uniq_lvls = sorted({level.get(n,0) for n in nodes})
#     pos_map = ({uniq_lvls[0] if uniq_lvls else 0:0.5}
#                if len(uniq_lvls)<=1 else {lv:float(x) for lv,x in zip(uniq_lvls, np.linspace(0.10,0.90,len(uniq_lvls)))})
#     xs = [pos_map.get(level.get(n,0),0.5) for n in nodes]

#     ys_map={}
#     for lv in uniq_lvls:
#         col=[n for n in nodes if n not in {DUMMY_A,DUMMY_B} and level.get(n,0)==lv]
#         if not col: continue
#         ys_lv=np.linspace(0.20,0.80,num=len(col))
#         for n,y in zip(sorted(col, key=str.lower), ys_lv):
#             ys_map[n]=float(y)
#     ys_map[DUMMY_A]=ys_map.get(DUMMY_A,0.5); ys_map[DUMMY_B]=ys_map.get(DUMMY_B,0.5)
#     ys=[ys_map.get(n,0.5) for n in nodes]

#     reps=(len(nodes)//len(PALETTE))+1
#     ncolors=(PALETTE*reps)[:len(nodes)]

#     from collections import defaultdict as _dd, deque as _deq
#     children_map=_dd(list)
#     for a,b in edges:
#         if level.get(a,0)>=0 and level.get(b,0)>0: children_map[a].append(b)
#     firsthop={}
#     for child in children_map.get(root,[]):
#         firsthop[child]=child; dq=_deq([child])
#         while dq:
#             u=dq.popleft()
#             for v in children_map.get(u,[]):
#                 if v not in firsthop: firsthop[v]=firsthop[u]; dq.append(v)

#     BRANCH_TONES={ "Alternative rock":"rgba(0,0,0,0.38)","Hard rock":"rgba(0,0,0,0.38)",
#                    "Punk rock":"rgba(0,0,0,0.38)","Pop rock":"rgba(0,0,0,0.38)",
#                    "Funk":"rgba(0,0,0,0.38)","Hip hop":"rgba(0,0,0,0.38)",
#                    "Dark wave":"rgba(0,0,0,0.38)","Ethereal wave":"rgba(0,0,0,0.38)" }

#     path=set(_path_edges(edges, root, focus))
#     path_nodes={root,focus}|{a for a,_ in path}|{b for _,b in path}
#     for i,n in enumerate(nodes):
#         if n in path_nodes: ncolors[i]=BLUE
#     if CALIBRATE_THIN:
#         ncolors[idx[DUMMY_A]]="rgba(0,0,0,0)"; ncolors[idx[DUMMY_B]]="rgba(0,0,0,0)"

#     src,dst,val,lcol=[],[],[],[]
#     for a,b in edges:
#         if a not in idx or b not in idx: continue
#         src.append(idx[a]); dst.append(idx[b]); val.append(1)
#         is_left_edge=(level.get(a,0)<0) and (level.get(b,0)<=0)
#         on_path=(a,b) in path
#         if on_path: lcol.append(BLUE)
#         elif is_left_edge: lcol.append(BLUE_LEFT)
#         else:
#             if level.get(a,0)==0 and level.get(b,0)==1: lcol.append(TONE_ROOT_DIRECT)
#             elif level.get(a,0)>=0 and level.get(b,0)>0:
#                 fh=canonical_name(firsthop.get(b) or firsthop.get(a) or "")
#                 lcol.append(BRANCH_TONES.get(fh, LINK_GREY))
#             else: lcol.append("rgba(0,0,0,0)" if branch_only else LINK_GREY)

#     if CALIBRATE_THIN:
#         CAL_FACTOR=7
#         src.append(idx[DUMMY_A]); dst.append(idx[DUMMY_B]); val.append(max(40, CAL_FACTOR*len(edges)))
#         lcol.append("rgba(0,0,0,0)")

#     few=len(nodes)<=8
#     node_thickness=(10 if is_mobile else (14 if few else 22))
#     node_pad=(8 if is_mobile else (10 if few else 18))

#     visible=[n for n in nodes if n not in {DUMMY_A,DUMMY_B}]
#     uniq_lvls_vis=sorted({level.get(n,0) for n in visible}) if visible else [0]
#     max_per_level=max(sum(1 for n in visible if level.get(n,0)==lv) for lv in uniq_lvls_vis) if visible else 1

#     base_h=180 if is_mobile else 320
#     chart_height=int(min(680, max(300, base_h + 26*max_per_level)))
#     if height_override: chart_height=int(height_override)

#     font_size=(13 if is_mobile else 15)
#     if font_size_override: font_size=int(font_size_override)
#     hover_size=max(10, font_size-1)

#     fig=go.Figure(go.Sankey(
#         arrangement="fixed",
#         node=dict(label=nodes, x=xs, y=ys, pad=node_pad, thickness=node_thickness,
#                   color=ncolors, line=dict(color="rgba(0,0,0,0.05)", width=0.5)),
#         link=dict(source=src, target=dst, value=val, color=lcol),
#     ))
#     fig.update_layout(margin=dict(l=0,r=0,t=0,b=0), height=chart_height,
#                       font=dict(family="Segoe UI, Roboto, Helvetica, Arial, sans-serif",
#                                 size=font_size, color="#1f2937"),
#                       hoverlabel=dict(font_size=hover_size, font_family="Segoe UI"))
#     fig.update_traces(textfont=dict(family="Segoe UI, Roboto, Helvetica, Arial, sans-serif",
#                                     size=font_size, color="#111827"))
#     return fig
def branch_sankey(
    nodes, edges, level, root, focus,
    branch_only=False, is_mobile=False,
    height_override=None, font_size_override=None
):
    # 🎨 TEMA (dark)
    # Fundo da figura
    DARK_BG = "#0b0f19"             # quase preto (agradável nos LCDs)
    # Tipografia
    FONT_CLR = "#e5e7eb"            # texto estrutural (legendas, títulos)
    TEXT_CLR = "#f9fafb"            # rótulos dos nós (mais claro)
    # Cores de ligação/contornos para fundo escuro
    LINK_GREY = "rgba(255,255,255,0.28)"
    TONE_ROOT_DIRECT = "rgba(255,255,255,0.55)"
    NODE_LINE = "rgba(255,255,255,0.08)"  # contorno dos nós
    # Azul de destaque
    BLUE = "#3b82f6"
    BLUE_LEFT = "rgba(59,130,246,0.50)"

    import numpy as np, plotly.express as px, plotly.graph_objects as go

    # Paleta mais adequada para fundo escuro
    PALETTE = px.colors.qualitative.Dark24

    # Calibração p/ manter links finos
    CALIBRATE_THIN = True
    DUMMY_A = "\u200b"; DUMMY_B = "\u200c"
    if CALIBRATE_THIN and DUMMY_A not in nodes:
        nodes = nodes + [DUMMY_A, DUMMY_B]
        last_lvl = max(level.values()) if level else 0
        level[DUMMY_A] = last_lvl + 1
        level[DUMMY_B] = last_lvl + 2

    idx = {n: i for i, n in enumerate(nodes)}
    uniq_lvls = sorted({level.get(n, 0) for n in nodes})
    pos_map = ({uniq_lvls[0] if uniq_lvls else 0: 0.5}
               if len(uniq_lvls) <= 1 else {lv: float(x) for lv, x in zip(uniq_lvls, np.linspace(0.10, 0.90, len(uniq_lvls)))})
    xs = [pos_map.get(level.get(n, 0), 0.5) for n in nodes]

    ys_map = {}
    for lv in uniq_lvls:
        col = [n for n in nodes if n not in {DUMMY_A, DUMMY_B} and level.get(n, 0) == lv]
        if not col:
            continue
        ys_lv = np.linspace(0.20, 0.80, num=len(col))
        for n, y in zip(sorted(col, key=str.lower), ys_lv):
            ys_map[n] = float(y)
    ys_map[DUMMY_A] = ys_map.get(DUMMY_A, 0.5)
    ys_map[DUMMY_B] = ys_map.get(DUMMY_B, 0.5)
    ys = [ys_map.get(n, 0.5) for n in nodes]

    reps = (len(nodes) // len(PALETTE)) + 1
    ncolors = (PALETTE * reps)[:len(nodes)]

    from collections import defaultdict as _dd, deque as _deq
    children_map = _dd(list)
    for a, b in edges:
        if level.get(a, 0) >= 0 and level.get(b, 0) > 0:
            children_map[a].append(b)
    firsthop = {}
    for child in children_map.get(root, []):
        firsthop[child] = child
        dq = _deq([child])
        while dq:
            u = dq.popleft()
            for v in children_map.get(u, []):
                if v not in firsthop:
                    firsthop[v] = firsthop[u]
                    dq.append(v)

    # Tons neutros por ramo (agora claros para fundo escuro)
    BRANCH_TONES = {
        "Alternative rock": "rgba(255,255,255,0.34)",
        "Hard rock":        "rgba(255,255,255,0.34)",
        "Punk rock":        "rgba(255,255,255,0.34)",
        "Pop rock":         "rgba(255,255,255,0.34)",
        "Funk":             "rgba(255,255,255,0.34)",
        "Hip hop":          "rgba(255,255,255,0.34)",
        "Dark wave":        "rgba(255,255,255,0.34)",
        "Ethereal wave":    "rgba(255,255,255,0.34)",
    }

    # caminho foco
    path = set(_path_edges(edges, root, focus))
    path_nodes = {root, focus} | {a for a, _ in path} | {b for _, b in path}
    for i, n in enumerate(nodes):
        if n in path_nodes:
            ncolors[i] = BLUE
    if CALIBRATE_THIN:
        ncolors[idx[DUMMY_A]] = "rgba(0,0,0,0)"
        ncolors[idx[DUMMY_B]] = "rgba(0,0,0,0)"

    # links
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
                lcol.append(TONE_ROOT_DIRECT)
            elif level.get(a, 0) >= 0 and level.get(b, 0) > 0:
                fh = canonical_name(firsthop.get(b) or firsthop.get(a) or "")
                lcol.append(BRANCH_TONES.get(fh, LINK_GREY))
            else:
                lcol.append("rgba(0,0,0,0)" if branch_only else LINK_GREY)

    if CALIBRATE_THIN:
        CAL_FACTOR = 7
        src.append(idx[DUMMY_A]); dst.append(idx[DUMMY_B]); val.append(max(40, CAL_FACTOR * len(edges)))
        lcol.append("rgba(0,0,0,0)")

    few = len(nodes) <= 8
    node_thickness = (10 if is_mobile else (14 if few else 22))
    node_pad = (8 if is_mobile else (10 if few else 18))

    visible = [n for n in nodes if n not in {DUMMY_A, DUMMY_B}]
    uniq_lvls_vis = sorted({level.get(n, 0) for n in visible}) if visible else [0]
    max_per_level = max(sum(1 for n in visible if level.get(n, 0) == lv) for lv in uniq_lvls_vis) if visible else 1

    base_h = 180 if is_mobile else 320
    chart_height = int(min(680, max(300, base_h + 26 * max_per_level)))
    if height_override:
        chart_height = int(height_override)

    font_size = (13 if is_mobile else 15)
    if font_size_override:
        font_size = int(font_size_override)
    hover_size = max(10, font_size - 1)

    fig = go.Figure(go.Sankey(
        arrangement="fixed",
        node=dict(
            label=nodes, x=xs, y=ys, pad=node_pad, thickness=node_thickness,
            color=ncolors, line=dict(color=NODE_LINE, width=0.5)
        ),
        link=dict(source=src, target=dst, value=val, color=lcol),
    ))

    fig.update_layout(
        paper_bgcolor=DARK_BG, plot_bgcolor=DARK_BG,
        margin=dict(l=0, r=0, t=0, b=0), height=chart_height,
        font=dict(
            family="Segoe UI, Roboto, Helvetica, Arial, sans-serif",
            size=font_size, color=FONT_CLR
        ),
        hoverlabel=dict(
            bgcolor="rgba(17,24,39,0.92)",
            bordercolor="rgba(255,255,255,0.15)",
            font=dict(
                family="Segoe UI, Roboto, Helvetica, Arial, sans-serif",
                size=hover_size, color=FONT_CLR
            )
        )
    )

    fig.update_traces(
        selector=dict(type="sankey"),
        textfont=dict(
            family="Segoe UI, Roboto, Helvetica, Arial, sans-serif",
            size=font_size, color=TEXT_CLR
        )
    )

    return fig
