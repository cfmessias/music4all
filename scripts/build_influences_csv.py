#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera um CSV de influências/origens para o Influence Map.

Entrada:
- Um CSV "dinâmico" (Wikipedia) com ligações de género/subgénero.
  Formatos suportados automaticamente:
    A) Colunas Parent/Child (qualquer capitalização)
    B) Colunas multinível (L1,L2,L3... ou Nivel1,Nivel2...)
    C) Uma coluna 'Path'/'Prefix' com hierarquias separadas por '>' '|' '/' '→'

Saída (por omissão): dados/influences_origins.csv  [sep=';']
Colunas: Parent;Child;Fonte;Peso;Confianca;Raiz

Uso:
  python scripts/build_influences_csv.py \
      --wikipedia-csv dados/graficos_generos.csv \
      --out dados/influences_origins.csv \
      --roots Blues Classical Folk Gospel Electronic Country

Integração:
- Aponta o loader do Influence Map para o ficheiro gerado (sem mexer nas outras páginas).
- Se houver várias raízes, podes trocar o input do "Blues" por uma selectbox (patch no fim).
"""

import argparse, os, sys, re
from collections import defaultdict, deque
from typing import List, Tuple, Set, Dict
import pandas as pd


# ======================
# 1) BASE CURADA (arestas Pai->Filho)
#    Mantém Blues como raiz principal + outras raízes úteis
# ======================
ALIASES = {
    # comuns
    "r&b": "Rhythm and Blues", "rock & roll": "Rock and Roll", "rock n roll": "Rock and Roll",
    "prog rock": "Progressive Rock", "rock progressivo": "Progressive Rock",
    "synthpop": "Synth-pop", "dance pop": "Dance-pop", "doo wop": "Doo-wop",
    "art pop": "Art Pop", "power pop": "Power Pop", "hard rock": "Hard Rock",
    "blues rock": "Blues Rock", "new wave": "New Wave", "post punk": "Post-punk",
    "garage": "Garage Rock", "country blues": "Country Blues", "eletronica": "Electronic",
    "eletrónica": "Electronic", "classico": "Classical", "classical music": "Classical",
}

def canon(x: str) -> str:
    if x is None: return ""
    k = re.sub(r"\s+", " ", str(x).strip())
    low = k.lower()
    return ALIASES.get(low, k)

# Arestas curadas (pais -> filhos)
KB_EDGES = {
    # Raiz Blues e 1ª geração
    ("Blues", "Country Blues"),
    ("Blues", "Rhythm and Blues"),
    ("Blues", "Jazz"),
    ("Blues", "British Blues"),
    ("British Blues", "Blues Rock"),
    ("Blues Rock", "Hard Rock"),
    ("Rhythm and Blues", "Rock and Roll"),
    ("Rhythm and Blues", "Soul"),
    ("Soul", "Motown"),
    ("Soul", "Funk"),
    ("Funk", "Disco"),

    # Rock & vizinhanças
    ("Rock and Roll", "Rock"),
    ("Rock and Roll", "Pop"),
    ("Rock", "Psychedelic Rock"),
    ("Rock", "Art Rock"),
    ("Rock", "Progressive Rock"),
    ("Rock", "Blues Rock"),
    ("Rock", "Hard Rock"),
    ("Rock", "Punk Rock"),
    ("Rock", "Pop Rock"),
    ("Garage Rock", "Punk Rock"),
    ("Punk Rock", "Post-punk"),
    ("Punk Rock", "New Wave"),
    ("New Wave", "Synth-pop"),
    ("Pop Rock", "Power Pop"),
    ("Pop Rock", "Britpop"),
    ("Psychedelic Rock", "Progressive Rock"),
    ("Progressive Rock", "Neo-progressive Rock"),
    ("Progressive Rock", "Progressive Metal"),

    # Pop ecossistema
    ("Traditional Pop", "Pop"),
    ("Doo-wop", "Pop"),
    ("Motown", "Pop"),
    ("Pop", "Pop Rock"),
    ("Pop", "Art Pop"),
    ("Pop", "Synth-pop"),
    ("Pop", "Dance-pop"),
    ("Disco", "Dance-pop"),

    # Outras raízes úteis
    ("Classical", "Art Rock"),
    ("Classical", "Progressive Rock"),
    ("Folk", "Folk Rock"),
    ("Folk Rock", "Singer-Songwriter"),
    ("Gospel", "Rhythm and Blues"),
    ("Gospel", "Soul"),
    ("Electronic", "Synth-pop"),
    ("Electronic", "Dance-pop"),
    ("Country", "Rockabilly"),
    ("Rockabilly", "Rock and Roll"),
}

# Conjunto de raízes canónicas (podes ajustar por CLI)
DEFAULT_ROOTS = ["Blues", "Classical", "Folk", "Gospel", "Electronic", "Country"]


# ======================
# 2) EXTRAÇÃO do CSV DINÂMICO (Wikipedia)
# ======================
def edges_from_row_levels(row: pd.Series) -> List[Tuple[str, str]]:
    """Extrai arestas de colunas multinível (L1..Ln / Nivel1..N)."""
    cols = [c for c in row.index if re.match(r"^(L|Nivel|Level)\d+$", str(c), flags=re.I)]
    if not cols:  # tentar ordinal simples
        cols = [c for c in row.index if re.match(r"^\d+$", str(c))]
    if not cols:
        return []
    cols_sorted = sorted(cols, key=lambda x: int(re.findall(r"\d+", str(x))[0]))
    labels = [canon(row[c]) for c in cols_sorted if str(row[c]).strip()]
    edges = []
    for i in range(len(labels) - 1):
        if labels[i] != labels[i+1]:
            edges.append((labels[i], labels[i+1]))
    return edges

def edges_from_row_path(row: pd.Series) -> List[Tuple[str, str]]:
    """Extrai arestas de uma coluna 'Path'/'Prefix' tipo 'A > B > C'."""
    for col in row.index:
        if str(col).lower() in {"path", "prefix", "hierarchy"}:
            s = str(row[col])
            if not s or s.strip().lower() in {"nan", "none"}:
                return []
            # aceita divisores comuns
            parts = re.split(r"\s*[>\|/→]\s*|\s*>\s*", s)
            parts = [canon(p) for p in parts if p and p.strip()]
            edges = []
            for i in range(len(parts) - 1):
                if parts[i] != parts[i+1]:
                    edges.append((parts[i], parts[i+1]))
            return edges
    return []

def infer_edges_from_df(df: pd.DataFrame) -> Set[Tuple[str, str]]:
    edges: Set[Tuple[str, str]] = set()

    # Caso A: colunas Parent/Child
    cols_low = {c.lower(): c for c in df.columns}
    if "parent" in cols_low and "child" in cols_low:
        pcol, ccol = cols_low["parent"], cols_low["child"]
        for p, c in df[[pcol, ccol]].dropna().itertuples(index=False):
            P, C = canon(p), canon(c)
            if P and C and P != C:
                edges.add((P, C))
        return edges

    # Caso B/C: multinível ou path
    for _, row in df.iterrows():
        for e in edges_from_row_levels(row):
            edges.add(e)
        for e in edges_from_row_path(row):
            edges.add(e)

    # Se nada foi encontrado mas há colunas conhecidas, tenta heurística:
    if not edges:
        # qual coluna parece ser 'Parent' / 'Child' pelo nome?
        maybe_parent = [c for c in df.columns if re.search(r"parent|pai|from|source", str(c), re.I)]
        maybe_child  = [c for c in df.columns if re.search(r"child|filho|to|target", str(c), re.I)]
        if maybe_parent and maybe_child:
            pcol, ccol = maybe_parent[0], maybe_child[0]
            for p, c in df[[pcol, ccol]].dropna().itertuples(index=False):
                P, C = canon(p), canon(c)
                if P and C and P != C:
                    edges.add((P, C))
    return edges


# ======================
# 3) FUSAO + ROOTS + SAÍDA
# ======================
def find_roots(all_edges: Set[Tuple[str, str]], seed_roots: List[str]) -> Set[str]:
    """Determina raízes reais (sem pais) + interseção com seeds fornecidas."""
    parents = defaultdict(set)
    children = defaultdict(set)
    for p, c in all_edges:
        parents[c].add(p)
        children[p].add(c)
    all_nodes = set(parents.keys()) | set(children.keys())
    no_parent = {n for n in all_nodes if not parents.get(n)}
    seeds = {canon(r) for r in seed_roots}
    # inclui seeds mesmo que tenham pais (o utilizador quer tratá-los como raízes)
    return (no_parent | seeds) or seeds

def assign_root_for_node(node: str, parents: Dict[str, List[str]], root_set: Set[str]) -> str:
    """Sobe a árvore a partir de node até encontrar a primeira raiz conhecida."""
    if node in root_set:
        return node
    q = deque([node])
    seen = {node}
    while q:
        u = q.popleft()
        for p in parents.get(u, []):
            if p in root_set:
                return p
            if p not in seen:
                seen.add(p); q.append(p)
    return ""  # desconhecida

def main():
    ap = argparse.ArgumentParser(description="Construir influences_origins.csv para o Influence Map")
    ap.add_argument("--wikipedia-csv", required=True, help="CSV dinâmico (Wikipedia) a fundir")
    ap.add_argument("--out", default="dados/influences_origins.csv", help="Caminho de saída")
    ap.add_argument("--sep", default=None, help="Separador do CSV de entrada (auto se omitido)")
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS,
                    help="Lista de raízes a considerar (default: %(default)s)")
    args = ap.parse_args()

    in_path = args.wikipedia_csv
    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # 1) Ler CSV dinâmico (tenta auto-separador)
    try:
        if args.sep:
            df = pd.read_csv(in_path, sep=args.sep)
        else:
            df = pd.read_csv(in_path, sep=None, engine="python")
    except Exception as e:
        print(f"ERRO a ler {in_path}: {e}", file=sys.stderr)
        sys.exit(2)

    wiki_edges = infer_edges_from_df(df)
    kb_edges = {(canon(a), canon(b)) for (a, b) in KB_EDGES}

    # 2) Fusão + marca da fonte
    src_map: Dict[Tuple[str, str], str] = {}
    all_edges: Set[Tuple[str, str]] = set()

    for e in wiki_edges:
        all_edges.add(e)
        src_map[e] = "wikipedia"

    for e in kb_edges:
        if e in all_edges:
            src_map[e] = "ambos"
        else:
            all_edges.add(e)
            src_map[e] = "kb"

    # 3) Índices para cálculo de raiz por nó
    parents = defaultdict(list)
    children = defaultdict(list)
    for p, c in all_edges:
        parents[c].append(p)
        children[p].append(c)

    root_set = find_roots(all_edges, args.roots)

    # 4) Materializar DataFrame
    records = []
    for p, c in sorted(all_edges, key=lambda x: (x[0].lower(), x[1].lower())):
        fonte = src_map[(p, c)]
        peso = 2 if fonte == "ambos" else 1
        confianca = 0.95 if fonte == "ambos" else (0.85 if fonte == "wikipedia" else 0.75)
        raiz = assign_root_for_node(p, parents, root_set)
        records.append({
            "Parent": p,
            "Child": c,
            "Fonte": fonte,
            "Peso": peso,
            "Confianca": round(confianca, 2),
            "Raiz": raiz or "",
        })

    out_df = pd.DataFrame.from_records(records)

    # 5) Guardar (sep=';')
    out_df.to_csv(out_path, sep=";", index=False, encoding="utf-8")
    print(f"✅ Gerado: {out_path} ({len(out_df)} arestas, {len(root_set)} raízes: {', '.join(sorted(root_set))})")


if __name__ == "__main__":
    main()
