# views/genre_map_auto.py
import streamlit as st
import plotly.graph_objects as go

from services.genre_csv import (
    load_hierarchy_csv, build_indices, norm, make_key as _key
)

def _find_matches(paths, query: str):
    """Devolve (matches_exatos, matches_parciais). Cada item é um path (tuple)."""
    q = norm(query)
    exact, partial = [], []
    for p in paths:
        labels = [norm(x) for x in p]
        if labels and labels[-1] == q:
            exact.append(p)
        elif any(q in x for x in labels):
            partial.append(p)
    # retirar duplicados mantendo ordem
    def dedup(seq):
        seen = set(); out=[]
        for x in seq:
            if x not in seen:
                out.append(x); seen.add(x)
        return out
    return dedup(exact), dedup(partial)

def _collect_descendants(children, root_prefix, max_nodes=3000):
    """Percorre filhos recursivamente a partir de root_prefix."""
    stack = [root_prefix]
    out = set([tuple(root_prefix)])
    while stack and len(out) < max_nodes:
        cur = tuple(stack.pop())
        for ch in sorted(children.get(cur, set())):
            if norm(ch):
                nxt = tuple(list(cur) + [ch])
                if nxt not in out:
                    out.add(nxt); stack.append(list(nxt))
    return sorted(out, key=lambda t: (len(t), " / ".join(t).lower()))

def _build_icicle(paths_subset):
    """Constrói um Icicle (árvore) a partir de um conjunto de paths (tuplos)."""
    # ids únicos = caminho completo; label = último segmento; parent = caminho do pai
    ids, labels, parents = [], [], []
    have = set()

    def add_node(path):
        pid = " / ".join(path)
        if pid in have: return
        have.add(pid)
        ids.append(pid)
        labels.append(path[-1] if path else "Root")
        if len(path) <= 1:
            parents.append("")
        else:
            parents.append(" / ".join(path[:-1]))

    # garantir que todos os prefixos existem
    for p in paths_subset:
        for i in range(1, len(p) + 1):
            add_node(p[:i])

    fig = go.Figure(go.Icicle(
        ids=ids, labels=labels, parents=parents,
        root_color="lightgray", tiling=dict(orientation='v')  # top-down
    ))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=600)
    return fig

def _summarize(prefix, children, leaves):
    """Gera um resumo textual simples para o nó escolhido."""
    path = list(prefix)
    genero = path[-1]
    # Origens (ascendentes)
    origens = path[:-1]
    # Derivações (filhos diretos)
    filhos = sorted([x for x in children.get(tuple(path), set()) if norm(x)])
    # Sub-estilos (netos/folhas abaixo)
    sub = []
    for f in filhos:
        sub += [t[-1] for t in leaves.get(tuple(path + [f]), [])[:5]]
        sub += [g for g in sorted(children.get(tuple(path + [f]), set()))[:5]]
    sub = sorted(list({norm(x): x for x in sub}.values()))[:12]

    blocos = []
    if origens:
        blocos.append("**Origens principais:** " + " → ".join(origens))
    if filhos:
        blocos.append("**Derivações/linhas diretas:** " + ", ".join(filhos))
    if sub:
        blocos.append("**Sub-estilos e ramificações notáveis:** " + ", ".join(sub))

    if not blocos:
        return f"**{genero}** — sem informação adicional no CSV."
    return f"**{genero}**\n\n" + "\n\n".join(blocos)

def render_genre_map_page():
    st.subheader("🧩 Mapa dinâmico de género")

    # 1) carregar hierarquia
    try:
        df, used_path = load_hierarchy_csv()
        children, leaves, roots, leaf_url = build_indices(df)
    except Exception as e:
        st.error(f"Erro a carregar CSV de géneros: {e}")
        return

    # 2) input
    q = st.text_input("Escreve um género/estilo (ex.: *Progressive Rock*, *Bebop*, *Delta Blues*)",
                      key="gm_query")

    if not (q or "").strip():
        st.info("Sugestão: tenta *Blues*, *R&B*, *Psychedelic Rock*, *Funk*…")
        return

    # 3) encontrar paths candidatos
    all_paths = []
    # construímos todos os caminhos possíveis a partir do índice
    for root in roots:
        all_paths.append((root,))
    for k in list(children.keys()):
        for ch in children[k]:
            all_paths.append(tuple(list(k) + [ch]))
    # mais robusto: inclui também as folhas (Texto)
    for pref, rows in leaves.items():
        for txt, url, p in rows:
            all_paths.append(tuple(p))

    exact, partial = _find_matches(all_paths, q)
    candidatos = exact or partial
    if not candidatos:
        st.warning("Sem correspondências.")
        return

    # 4) escolher nó (prioridade a match exato)
    labels = [" / ".join(p) for p in candidatos]
    idx = st.selectbox("Escolhe o nó de partida",
                       list(range(len(candidatos))),
                       format_func=lambda i: labels[i],
                       key="gm_pick")

    prefix = list(candidatos[idx])

    # 5) recolher subárvore e desenhar organograma
    subset = _collect_descendants(children, prefix)
    fig = _build_icicle(subset)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # 6) resumo automático
    resumo = _summarize(prefix, children, leaves)
    st.markdown(resumo)

    # 7) atalho para a página de Géneros
    col1, col2 = st.columns([0.6, 0.4])
    with col1:
        if st.button("🔎 Pesquisar este género na página *Genres*", use_container_width=True):
            st.session_state["genres_search_q"] = prefix[-1]
            st.success("Feito! Abre a página **🧭 Genres** e carrega em **Search**.")
