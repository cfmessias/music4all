# echarts_stepper_branch.py
# Ramo por etapas: botão "Blues" + selectboxes dependentes.
# O Sankey mostra o caminho escolhido e "abre em leque" os FILHOS do último nó (estilo do teu exemplo).

import streamlit as st
from streamlit_echarts import st_echarts
from collections import defaultdict

st.set_page_config(page_title="Mapa de influências (ramo a crescer)", page_icon="🧭", layout="wide")

# ---------- CSS: botão primário em azul (robusto em vários temas/versões) ----------
st.markdown(
    """
    <style>
    .stButton > button[kind="primary"],
    .stButton > button,
    div[data-testid="baseButton-primary"] > button {
        background-color: #2563eb !important;
        border: 1px solid #1e40af !important;
        color: #ffffff !important;
    }
    .info-emoji { font-size: 22px; line-height: 1; cursor: help; user-select: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- dados curados (exemplo; podes trocar por CSV) ----------
NODES = [
    "African musical traditions", "Work songs/Field hollers", "Spirituals/Gospel",
    "Country/Old-time", "Jazz (early)",
    "Blues", "Delta Blues", "Chicago Blues",
    "R&B (40s/50s)", "Rock ’n’ Roll", "Rockabilly", "Soul", "Funk",
    "Blues Rock", "British Blues", "Hard Rock", "Psychedelic Rock",
    "Progressive Rock", "Heavy Metal",
    "Jazz Fusion", "Disco", "Hip-Hop", "Pop/Rock (mainstream)",
]
LINKS = [
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

# Índices auxiliares (pais/filhos, valores por aresta)
PARENTS   = defaultdict(list)
CHILDREN  = defaultdict(list)
VAL_BY_ST = {}
for s, t, v in LINKS:
    if s not in PARENTS[t]:
        PARENTS[t].append(s)
    if t not in CHILDREN[s]:
        CHILDREN[s].append(t)
    VAL_BY_ST[(s, t)] = v

ROOT = "Blues"
PH   = "— selecionar —"

# ---------- helpers de estado ----------
def reset_branch_state():
    for k in list(st.session_state.keys()):
        if str(k).startswith("lvl_"):
            st.session_state.pop(k, None)
    st.session_state.pop("branch_path", None)

def build_path_from_state():
    path = [ROOT]
    lvl  = 1
    while True:
        key = f"lvl_{lvl}_choice"
        choice = st.session_state.get(key)
        if not choice or choice == PH:
            break
        path.append(choice)
        lvl += 1
    return path

def render_level_selectboxes():
    # nível 2
    filhos = CHILDREN.get(ROOT, [])
    if not filhos:
        return
    st.selectbox(
        "Nível 2",
        options=[PH] + filhos,
        index=0,  # sem pré-seleção
        key="lvl_1_choice",
        label_visibility="collapsed",
    )
    # níveis seguintes
    lvl = 2
    while True:
        pkey = f"lvl_{lvl-1}_choice"
        pval = st.session_state.get(pkey)
        if not pval or pval == PH:
            break
        filhos = CHILDREN.get(pval, [])
        if not filhos:
            break
        key = f"lvl_{lvl}_choice"
        st.selectbox(
            f"Nível {lvl+1}",
            options=[PH] + filhos,
            index=0,
            key=key,
            label_visibility="collapsed",
        )
        lvl += 1

# ---------- construção do gráfico estilo “leque a crescer” ----------
def options_branch_fanout(path):
    """
    Mostra:
      • o CAMINHO selecionado (ROOT -> ... -> último)
      • todos os FILHOS do ÚLTIMO nó (fan-out)
    """
    last = path[-1]
    children = CHILDREN.get(last, [])

    # Conjunto de nós a mostrar (caminho + filhos do último)
    nodes_order = list(dict.fromkeys(path + children))

    # Links do caminho
    links = []
    for i in range(len(path)-1):
        s, t = path[i], path[i+1]
        links.append((s, t, VAL_BY_ST.get((s, t), 3)))

    # Links do fan-out (último -> cada filho)
    for c in children:
        links.append((last, c, VAL_BY_ST.get((last, c), 3)))

    # Estética (cores genéricas + labels legíveis)
    palette = [
        "#8dd3c7","#ffffb3","#bebada","#fb8072","#80b1d3",
        "#fdb462","#b3de69","#fccde5","#d9d9d9","#bc80bd",
        "#ccebc5","#ffed6f",
    ]

    # Nós (com borda nos do caminho)
    path_set = set(path)
    data_nodes = [{
        "name": n,
        "label": {"fontSize": 13, "fontWeight": 600},
        "itemStyle": {"borderWidth": 2 if n in path_set else 0, "borderColor": "#111"}
    } for n in nodes_order]

    # Ligações (ligeira curvatura; caminho igual aos do fan-out)
    data_links = [{
        "source": s, "target": t, "value": v,
        "lineStyle": {"color": "rgba(0,0,0,0.28)", "curveness": 0.22}
    } for (s, t, v) in links]

    # Altura dinâmica em função dos filhos (evita espaços “mornos”)
    n_children = len(children)
    dynamic_height = max(360, min(720, 280 + n_children * 22))

    opts = {
        "color": palette,
        "tooltip": {"trigger": "item"},
        "title": {"text": "Sankey — ramo selecionado (com fan-out do último nó)", "left": "center"},
        "series": [{
            "type": "sankey",
            "orient": "horizontal",
            "nodeAlign": "left",
            "layoutIterations": 0,     # layout estável
            "nodeWidth": 12,           # nós estreitos
            "nodeGap": 6,              # menos espaço vertical
            "levels": [                # gaps ainda mais curtos no lado dos filhos
                {"depth": 0, "itemStyle": {"borderWidth": 0}, "lineStyle": {"opacity": 0.9}},
                {"depth": 1, "lineStyle": {"opacity": 0.85}},
                {"depth": 2, "lineStyle": {"opacity": 0.8}},
            ],
            "data": data_nodes,
            "links": data_links,
            "emphasis": {"focus": "adjacency"},
            "left": "3%", "right": "5%", "top": "6%", "bottom": "6%",
        }],
    }
    return opts, dynamic_height

# ---------- UI ----------
st.title("🧭 Ramo por etapas — caminho + leque de filhos no fim")

# Botão raiz + tooltip
c_btn, c_info = st.columns([0.16, 0.84])
with c_btn:
    if st.button("Blues", type="primary", use_container_width=True, key="btn_root"):
        is_open = not st.session_state.get("branch_open", False)
        st.session_state["branch_open"] = is_open
        if is_open:
            reset_branch_state()
            st.session_state["branch_path"] = ["Blues"]
        else:
            reset_branch_state()
with c_info:
    st.markdown(
        '<span class="info-emoji" title="Clique em Blues para abrir/fechar as opções. '
        'A cada seleção, o gráfico mostra o caminho e, à direita, os filhos do último nó.">ℹ️</span>',
        unsafe_allow_html=True
    )

st.divider()

# Layout
col_ctrls, col_plot = st.columns([0.30, 0.70], gap="small")

with col_ctrls:
    if st.session_state.get("branch_open", False):
        render_level_selectboxes()
        st.session_state["branch_path"] = build_path_from_state()
        path = st.session_state["branch_path"]
        if len(path) > 1:
            st.caption(" → ".join(path))
    else:
        path = ["Blues"]  # fechado: só raiz

with col_plot:
    opts, h = options_branch_fanout(path)
    st_echarts(options=opts, height=f"{h}px", key=f"sankey_path_{'-'.join(path)}")
