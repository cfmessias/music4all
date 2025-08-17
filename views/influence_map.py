# views/influence_map.py
import streamlit as st
import plotly.graph_objects as go

# Clique em Plotly dentro de Streamlit (opcional; fazemos fallback se faltar)
try:
    from streamlit_plotly_events import plotly_events
    HAS_PLOTLY_EVENTS = True
except Exception:
    HAS_PLOTLY_EVENTS = False

# Para o modo dinâmico (CSV)
from services.genre_csv import load_hierarchy_csv, build_indices, norm


# ====================================================================
# MODO 1 — DADOS CURADOS (mantém o que já existia, sem depender do CSV)
# ====================================================================
def _curated_graph():
    nodes = [
        # Raízes e matrizes
        "African musical traditions", "Work songs/Field hollers", "Spirituals/Gospel",
        "Country/Old-time", "Jazz (early)",

        # Blues e variações
        "Blues", "Delta Blues", "Chicago Blues",

        # Primeiras ramificações populares
        "R&B (40s/50s)", "Rock ’n’ Roll", "Rockabilly", "Soul", "Funk",

        # Rock (linhas clássicas)
        "Blues Rock", "British Blues", "Hard Rock", "Psychedelic Rock",
        "Progressive Rock", "Heavy Metal",

        # Outras derivações
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
# MODO 2 — DADOS DINÂMICOS (a partir do teu CSV de géneros)
# ====================================================================
def _graph_from_csv(root_label: str, down_depth: int = 3, up_levels: int = 1,
                    include_siblings: bool = True, max_edges: int = 2000):
    """
    Constrói NODES/LINKS a partir do CSV para o nó 'root_label'.

    down_depth: nº de níveis a descer (filhos, netos, …)
    up_levels:  nº de níveis a subir (pai, avô, …) para contexto
    include_siblings: incluir irmãos dos nós quando subimos
    """
    try:
        df, _ = load_hierarchy_csv()
        children, leaves, roots, leaf_url = build_indices(df)
    except Exception as e:
        st.error(f"Erro a carregar CSV de géneros: {e}")
        return [], []

    # --- índice de pais para permitir "subir"
    parents_map = {}  # prefixo_do_filho (tuple) -> prefixo_do_pai (tuple)
    for pref, chs in children.items():
        for ch in chs:
            child_pref = tuple(list(pref) + [ch])
            parents_map[child_pref] = pref

    # --- encontrar candidatos cujo último segmento corresponda ao label
    target = norm(root_label)
    candidatos = []
    for pref in children.keys():
        if pref and norm(pref[-1]) == target:
            candidatos.append(pref)
    if not candidatos:
        for pref in children.keys():
            if pref and target in norm(pref[-1]):
                candidatos.append(pref)
    if not candidatos:
        st.warning("Género não encontrado no CSV.")
        return [], []

    # escolher o caminho MAIS PROFUNDO (melhor contexto quando há duplicados)
    root = max(candidatos, key=lambda p: len(p))

    # --- descer (BFS) até "down_depth"
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

    # --- subir "up_levels" e incluir irmãos (mais contexto)
    asc = root
    for _ in range(up_levels):
        parent_pref = parents_map.get(asc)
        # sem pai, ou pai == () (nível raiz virtual) → parar
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

        asc = parent_pref  # sobe mais um nível

    # ordenar nós (root primeiro)
    def _key(n):
        return (0 if norm(n) == target else 1, n.lower())
    nodes = sorted(nodes, key=_key)

    return nodes, links


# ====================================================================
# Utilitários (funcionam com qualquer par nodes/links)
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
    """Resumo automático a partir das ligações fornecidas."""
    parts = []
    if label.lower() == "blues":
        parts.append(
            "**Etimologia**: *blues* vem de **blue devils** (séc. XVII), "
            "associado a tristeza/melancolia — daqui a expressão *to feel blue*. "
            "O estilo ganhou o nome pela função de expressar dor, resistência e esperança "
            "nas comunidades afro-americanas."
        )

    infl = parents.get(label, [])
    if infl:
        parts.append("**Influências diretas**: " + ", ".join(infl) + ".")
    der = children.get(label, [])
    if der:
        parts.append("**Derivações/impacto imediato**: " + ", ".join(der) + ".")
    netos = sorted({g for c in der for g in children.get(c, [])})
    if netos:
        parts.append("**Ramificações seguintes**: " + ", ".join(netos) + ".")

    if not parts:
        parts.append("Sem informação adicional neste mapa para este nó.")
    parts.append("_Texto gerado automaticamente a partir das ligações do mapa._")
    return "\n\n".join(parts)

def _build_sankey(nodes, links, title="Influence map"):
    import plotly.express as px  # para paleta pastel

    idx = {n: i for i, n in enumerate(nodes)}
    src = [idx[s] for (s, t, *_) in links if s in idx and t in idx]
    trg = [idx[t] for (s, t, *_) in links if s in idx and t in idx]
    val = [ (rest[0] if rest else 1) for (s, t, *rest) in links if s in idx and t in idx ]

    FONT_STACK = "Segoe UI Semibold, Segoe UI, Roboto, Helvetica, Arial, sans-serif"

    # paleta suave para nós
    base_palette = px.colors.qualitative.Set3
    repeats = (len(nodes) // len(base_palette)) + 1
    node_colors = (base_palette * repeats)[:len(nodes)]

    LINK_GREY = "rgba(0,0,0,0.18)"  # curvas em cinzento claro

    fig = go.Figure(data=[go.Sankey(
        arrangement="snap",
        node=dict(
            label=nodes,
            pad=22,
            thickness=20,
            color=node_colors,  # cores explícitas dos nós
            line=dict(color="rgba(0,0,0,0.25)", width=0.7),
            hovertemplate="%{label}<extra></extra>",
            customdata=nodes,                    # para clique em NÓ
        ),
        link=dict(
            source=src,
            target=trg,
            value=val,
            color=LINK_GREY,                     # curvas cinzentas
            hovertemplate="%{source.label} → %{target.label} (%{value})<extra></extra>",
            customdata=[nodes[t] for t in trg],  # para clique em LIGAÇÃO (target)
        ),
    )])

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        title=title,
        height=560,
        font=dict(family=FONT_STACK, size=16, color="#1f2937"),
        hoverlabel=dict(font_size=14, font_family=FONT_STACK),
        clickmode="event+select",               # garante evento de clique
    )
    fig.update_traces(textfont=dict(family=FONT_STACK, size=16, color="#222"))
    return fig

def _label_from_event(ev: dict, nodes: list, links: list):
    """Extrai um label fiável de um evento do Sankey (nó ou ligação)."""
    # 1) direto
    label = ev.get("label")
    if isinstance(label, str) and label:
        return label

    # 2) customdata (nós / ligações)
    cd = ev.get("customdata")
    if isinstance(cd, str) and cd:
        return cd
    if isinstance(cd, list) and cd and isinstance(cd[0], str):
        return cd[0]

    # 3) índices específicos do sankey (target preferido)
    trg = ev.get("target"); src = ev.get("source")
    if isinstance(trg, int) and 0 <= trg < len(nodes):
        return nodes[trg]
    if isinstance(src, int) and 0 <= src < len(nodes):
        return nodes[src]

    # 4) fallback genérico por pointNumber
    pn = ev.get("pointIndex") if "pointIndex" in ev else ev.get("pointNumber")
    if isinstance(pn, int):
        # se for nó
        if 0 <= pn < len(nodes):
            return nodes[pn]
        # se for ligação, devolve o target dessa ligação (mais útil)
        if 0 <= pn < len(links):
            try:
                return links[pn][1]
            except Exception:
                pass
    return None


# ====================================================================
# Página
# ====================================================================
def render_influence_map_page():
    st.subheader("🎼 Blues roots & influence map")

    # Modo de dados
    mode = st.radio(
        "Fonte de dados",
        ["Curado", "Dinâmico (CSV de géneros)"],
        horizontal=True,
        key="infl_mode",
    )

    # ===== Construção dos dados =====
    if mode == "Curado":
        nodes, links = _curated_graph()
        title = "Blues → R&B/Rock/Soul/Funk… (influence map)"
        root = "Blues"  # default para diagnóstico
    else:
        colA, colB, colC = st.columns([0.6, 0.25, 0.15])
        with colA:
            root = st.text_input("Género de partida", value="Blues", key="infl_root")
        with colB:
            depth = st.slider("Profundidade (descer)", 1, 5, 3, key="infl_depth")
        with colC:
            up = st.selectbox("Subir", options=[0, 1, 2], index=1, help="Níveis a subir para contexto", key="infl_up")

        nodes, links = _graph_from_csv(root, down_depth=depth, up_levels=up, include_siblings=True)
        if not nodes or not links:
            return
        title = f"{root} — mapa de influências (CSV)"

        # Diagnóstico: profundidade realmente atingida a partir do nó "root"
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

        st.caption(f"📏 Profundidade pedida: {depth} · alcançada: {_max_depth_from(root)} · nós: {len(nodes)} · ligações: {len(links)}")

    # Índices (para resumo dinâmico)
    node_index, parents, children = _index_graph(nodes, links)

    # Layout com gráfico + painel de seleção/explicação
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
                key=f"sankey_{'curado' if mode=='Curado' else 'dinamico'}",
            )
            if events:
                selected_label = _label_from_event(events[0], nodes, links)
        else:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.caption("Para gráfico clicável, instala `streamlit-plotly-events` e reinicia a aplicação.")

    with col_side:
        st.markdown("#### Seleção de nó")

        # Fallback fiável: seletor de nó (funciona mesmo que o clique não venha)
        default_idx = 0
        if selected_label and selected_label in nodes:
            default_idx = nodes.index(selected_label)
        elif st.session_state.get("infl_selected") in nodes:
            default_idx = nodes.index(st.session_state["infl_selected"])

        pick = st.selectbox("Escolhe um nó", options=list(range(len(nodes))),
                            index=default_idx, format_func=lambda i: nodes[i], key="infl_pick")

        chosen = nodes[pick]
        st.session_state["infl_selected"] = chosen

        st.markdown(_explain_label(chosen, parents, children))

        # Atalho para a página de Géneros
        if st.button("🔎 Pesquisar este género na página *🧭 Genres*", use_container_width=True):
            st.session_state["genres_search_q"] = chosen
            st.success("Feito! Abre a aba **🧭 Genres** e carrega em **Search**.")
