#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera um CSV hierárquico (L1;L2;...) drop-in para o Influence Map.
• Fontes: Wikidata (P737/P279) + CSV local (Wikipedia) + curadoria (KB_EDGES).
• Saída: --out (caminhos por níveis). Opcional: --sidecar com arestas/fonte/confiança.
• Uso rápido: python scripts/build_influence_paths.py   (assistente interativo no terminal)
"""

from __future__ import annotations
import argparse, os, sys, re, json, time
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Iterable
import pandas as pd
import requests

# ======================
# Config Wikidata
# ======================
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "music4all-influence-builder/1.0 (+https://example.invalid)"

SPARQL_INFLUENCE = """
SELECT ?childLabel ?parentLabel WHERE {
  ?child wdt:P31/wdt:P279* wd:Q188451 .   # music genre
  ?child wdt:P737 ?parent .
  ?parent wdt:P31/wdt:P279* wd:Q188451 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

SPARQL_SUBclass = """
SELECT ?childLabel ?parentLabel WHERE {
  ?child wdt:P279 ?parent .
  ?child wdt:P31/wdt:P279* wd:Q188451 .
  ?parent wdt:P31/wdt:P279* wd:Q188451 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

def _sparql(query: str, timeout_s: int = 60) -> List[Tuple[str, str]]:
    """Executa SPARQL e devolve lista de arestas (parent, child) com labels canónicas."""
    try:
        r = requests.get(
            WIKIDATA_ENDPOINT,
            params={"query": query, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        out = []
        for b in data.get("results", {}).get("bindings", []):
            child = canon(b.get("childLabel", {}).get("value"))
            parent = canon(b.get("parentLabel", {}).get("value"))
            if child and parent and child != parent:
                out.append((parent, child))  # parent -> child
        return out
    except Exception as e:
        print(f"[Wikidata] ERRO: {e}", file=sys.stderr)
        return []

def fetch_wikidata_edges() -> Set[Tuple[str, str]]:
    """Arestas de 'influenced by' + 'subclass of' entre géneros."""
    inf = _sparql(SPARQL_INFLUENCE)
    time.sleep(0.5)  # cortesia ao endpoint
    sub = _sparql(SPARQL_SUBclass)
    return set(inf) | set(sub)

# ======================
# Canon/aliases
# ======================
ALIASES = {
    "r&b": "Rhythm and Blues",
    "rock & roll": "Rock and Roll",
    "rock n roll": "Rock and Roll",
    "rock ’n’ roll": "Rock and Roll",
    "prog rock": "Progressive Rock",
    "rock progressivo": "Progressive Rock",
    "synthpop": "Synth-pop",
    "dance pop": "Dance-pop",
    "doo wop": "Doo-wop",
    "britpop": "Britpop",
    "art pop": "Art Pop",
    "power pop": "Power Pop",
    "post punk": "Post-punk",
    "hard rock": "Hard Rock",
    "blues rock": "Blues Rock",
    "new wave": "New Wave",
    "country blues": "Country Blues",
    "classico": "Classical",
    "eletrónica": "Electronic",
    "electronica": "Electronic",
}

def canon(x: str) -> str:
    if x is None:
        return ""
    s = re.sub(r"\s+", " ", str(x)).strip()
    s = s.replace("’", "'")
    low = s.lower()
    return ALIASES.get(low, s)

# ======================
# Curadoria (tapa buracos)
# ======================
KB_EDGES: Set[Tuple[str, str]] = {
    # Linha Blues
    ("Blues", "Rhythm and Blues"), ("Blues", "Jazz"), ("Blues", "Country Blues"),
    ("Rhythm and Blues", "Rock and Roll"), ("Rhythm and Blues", "Soul"),
    ("Soul", "Motown"), ("Soul", "Funk"), ("Funk", "Disco"),
    ("Rock and Roll", "Rock"), ("Rock and Roll", "Pop"),

    # Rock/Blues britânico, Prog, Metal
    ("Blues", "British Blues"), ("British Blues", "Blues Rock"),
    ("Blues Rock", "Hard Rock"), ("Hard Rock", "Heavy Metal"),
    ("Psychedelic Rock", "Progressive Rock"),

    # Pop ecossistema
    ("Traditional Pop", "Pop"), ("Doo-wop", "Pop"), ("Motown", "Pop"),
    ("Pop", "Pop Rock"), ("Pop", "Art Pop"), ("Pop", "Synth-pop"), ("Pop", "Dance-pop"),
    ("Pop Rock", "Power Pop"), ("Pop Rock", "Britpop"),

    # Punk/New Wave
    ("Garage Rock", "Punk Rock"), ("Punk Rock", "Post-punk"), ("Punk Rock", "New Wave"),
    ("New Wave", "Synth-pop"),

    # Outras raízes
    ("Classical", "Art Rock"), ("Classical", "Progressive Rock"),
    ("Folk", "Folk Rock"), ("Folk Rock", "Singer-Songwriter"),
    ("Gospel", "Rhythm and Blues"), ("Gospel", "Soul"),
    ("Electronic", "Synth-pop"), ("Electronic", "Dance-pop"),
    ("Country", "Rockabilly"), ("Rockabilly", "Rock and Roll"),
}

DEFAULT_ROOTS = ["Blues", "Classical", "Folk", "Gospel", "Electronic", "Country"]

# ======================
# CSV local (Wikipedia)
# ======================
def edges_from_row_levels(row: pd.Series) -> List[Tuple[str, str]]:
    cols = [c for c in row.index if re.match(r"^(L|Nivel|Level)\d+$", str(c), flags=re.I)]
    if not cols:
        cols = [c for c in row.index if re.match(r"^\d+$", str(c))]
    if not cols:
        return []
    cols_sorted = sorted(cols, key=lambda x: int(re.findall(r"\d+", str(x))[0]))
    labels = [canon(row[c]) for c in cols_sorted if str(row[c]).strip()]
    edges = []
    for i in range(len(labels) - 1):
        if labels[i] != labels[i + 1]:
            edges.append((labels[i], labels[i + 1]))
    return edges

def edges_from_row_path(row: pd.Series) -> List[Tuple[str, str]]:
    for col in row.index:
        if str(col).lower() in {"path", "prefix", "hierarchy"}:
            s = str(row[col])
            if not s or s.strip().lower() in {"nan", "none"}:
                return []
            parts = re.split(r"\s*(?:>|→|\||/)\s*", s)
            parts = [canon(p) for p in parts if p and p.strip()]
            edges = []
            for i in range(len(parts) - 1):
                if parts[i] != parts[i + 1]:
                    edges.append((parts[i], parts[i + 1]))
            return edges
    return []

def edges_from_csv(input_path: str, sep: str | None = None) -> Set[Tuple[str, str]]:
    if not input_path or not os.path.exists(input_path):
        return set()
    df = pd.read_csv(input_path, sep=sep if sep is not None else None, engine="python")
    edges: Set[Tuple[str, str]] = set()
    cols_low = {c.lower(): c for c in df.columns}
    if "parent" in cols_low and "child" in cols_low:
        pcol, ccol = cols_low["parent"], cols_low["child"]
        for p, c in df[[pcol, ccol]].dropna().itertuples(index=False):
            P, C = canon(p), canon(c)
            if P and C and P != C:
                edges.add((P, C))
        return edges
    for _, row in df.iterrows():
        for e in edges_from_row_levels(row):
            edges.add(e)
        for e in edges_from_row_path(row):
            edges.add(e)
    return edges

# ======================
# Fusão + roots + caminhos
# ======================
def fuse_edges(*edge_sets: Iterable[Tuple[str, Set[Tuple[str, str]]]]
               ) -> Tuple[Set[Tuple[str, str]], Dict[Tuple[str, str], Set[str]]]:
    src: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    all_edges: Set[Tuple[str, str]] = set()
    for name, es in edge_sets:
        for e in es:
            all_edges.add(e)
            src[e].add(name)
    return all_edges, src

def find_roots(all_edges: Set[Tuple[str, str]], seeds: List[str]) -> Set[str]:
    parents = defaultdict(set)
    children = defaultdict(set)
    for p, c in all_edges:
        parents[c].add(p)
        children[p].add(c)
    nodes = set(parents) | set(children)
    no_parent = {n for n in nodes if not parents.get(n)}
    seedset = {canon(r) for r in seeds}
    return (no_parent | seedset) or seedset

def build_paths(all_edges: Set[Tuple[str, str]],
                roots: Set[str],
                max_depth: int = 6,
                max_paths_per_leaf: int = 8) -> List[List[str]]:
    children = defaultdict(list)
    parents = defaultdict(list)
    for p, c in all_edges:
        if c not in children[p]:
            children[p].append(c)
        if p not in parents[c]:
            parents[c].append(p)

    paths: List[List[str]] = []
    for root in sorted(roots, key=str.lower):
        if root not in children and root not in parents:
            continue
        stack = [(root, [root])]
        seen = set()
        while stack:
            node, path = stack.pop()
            if len(path) >= max_depth or not children.get(node):
                t = tuple(path)
                if t not in seen:
                    seen.add(t)
                    paths.append(path)
                continue
            for nxt in sorted(children.get(node, []), key=str.lower):
                if nxt in path:
                    continue
                stack.append((nxt, path + [nxt]))
    # limitar caminhos muito repetidos por folha
    bucket: Dict[str, List[List[str]]] = defaultdict(list)
    for p in paths:
        bucket[p[-1]].append(p)
    trimmed: List[List[str]] = []
    for leaf, plist in bucket.items():
        trimmed.extend(plist[:max_paths_per_leaf])
    trimmed.sort(key=lambda seq: tuple(x.lower() for x in seq))
    return trimmed

def write_paths_csv(paths: List[List[str]], out_path: str, sep: str = ";") -> None:
    maxlen = max((len(p) for p in paths), default=0)
    cols = [f"L{i}" for i in range(1, maxlen + 1)]
    rows = [{f"L{i+1}": p[i] for i in range(len(p))} for p in paths]
    pd.DataFrame(rows, columns=cols).to_csv(out_path, sep=sep, index=False, encoding="utf-8")

def write_edges_sidecar(all_edges: Set[Tuple[str, str]],
                        src_map: Dict[Tuple[str, str], Set[str]],
                        out_path: str, sep: str = ";") -> None:
    rows = []
    for (p, c) in sorted(all_edges, key=lambda x: (x[0].lower(), x[1].lower())):
        srcs = sorted(src_map.get((p, c), set()))
        weight = 2 if len(srcs) >= 2 else 1
        conf = 0.95 if "wikidata" in srcs and ("kb" in srcs or "wikipedia" in srcs) else (0.85 if "wikidata" in srcs else 0.75)
        rows.append({"Parent": p, "Child": c, "Source": ",".join(srcs), "Weight": weight, "Confidence": conf})
    pd.DataFrame(rows).to_csv(out_path, sep=sep, index=False, encoding="utf-8")

# ======================
# Execução (interativo + CLI)
# ======================
def run_with_args(args):
    edge_sets = []

    if not getattr(args, "no_wikidata", False):
        print("• A obter arestas da Wikidata (P737/P279)…")
        wd = set(fetch_wikidata_edges())
        print(f"  → {len(wd)} arestas")
        edge_sets.append(("wikidata", wd))

    if getattr(args, "wikipedia_csv", ""):
        print(f"• A fundir CSV dinâmico: {args.wikipedia_csv}")
        wc = edges_from_csv(args.wikipedia_csv, getattr(args, "sep_in", None))
        print(f"  → {len(wc)} arestas")
        edge_sets.append(("wikipedia", wc))

    print("• A adicionar curadoria/KB…")
    kb = {(canon(a), canon(b)) for (a, b) in KB_EDGES}
    print(f"  → {len(kb)} arestas curadas")
    edge_sets.append(("kb", kb))

    all_edges, src_map = fuse_edges(*edge_sets)
    print(f"= Total deduplicado: {len(all_edges)} arestas")

    roots = find_roots(all_edges, getattr(args, "roots", DEFAULT_ROOTS))
    print(f"• Raízes detectadas/forçadas: {', '.join(sorted(roots))}")

    paths = build_paths(all_edges, roots,
                        max_depth=getattr(args, "max_depth", 6),
                        max_paths_per_leaf=getattr(args, "max_paths_per_leaf", 8))
    print(f"• Caminhos gerados: {len(paths)}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_paths_csv(paths, args.out, sep=getattr(args, "sep_out", ";"))
    print(f"✅ CSV hierárquico gravado em: {args.out}")

    sidecar = getattr(args, "sidecar", "")
    if sidecar:
        os.makedirs(os.path.dirname(sidecar) or ".", exist_ok=True)
        write_edges_sidecar(all_edges, src_map, sidecar, sep=getattr(args, "sep_out", ";"))
        print(f"ℹ️  Sidecar de arestas gravado em: {sidecar}")

def interactive_wizard():
    print("\n=== Music4all · Construtor de CSV de Influências ===\n")
    out = input("Destino do CSV (ENTER= dados/influences_origins.csv): ").strip() or "dados/influences_origins.csv"
    sidecar = input("Sidecar de arestas (ENTER= dados/influences_edges.csv; vazio= não criar): ").strip() or "dados/influences_edges.csv"
    wiki = input("Caminho para o teu CSV da Wikipedia (vazio = ignorar): ").strip()
    sep_in = input("Separador do CSV de entrada (ENTER=auto; use ';' ou ','): ").strip() or None
    roots_str = input("Raízes (vírgulas) [default: Blues,Classical,Folk,Gospel,Electronic,Country,Hip Hop,Reggae,Latin]: ").strip()
    if roots_str:
        roots = [canon(x) for x in re.split(r"[;,]\s*|\s+", roots_str) if x]
    else:
        roots = ["Blues","Classical","Folk","Gospel","Electronic","Country","Hip Hop","Reggae","Latin"]
    max_depth = input("Profundidade máxima (ENTER=8): ").strip()
    max_depth = int(max_depth) if max_depth else 8
    max_ppl = input("Máx. caminhos por folha (ENTER=20): ").strip()
    max_ppl = int(max_ppl) if max_ppl else 20
    no_wd = input("Ignorar Wikidata? (s/N): ").strip().lower() in {"s","sim","y","yes"}

    class A: pass
    args = A()
    args.out = out
    args.sidecar = sidecar
    args.wikipedia_csv = wiki
    args.sep_in = sep_in
    args.sep_out = ";"
    args.roots = roots
    args.max_depth = max_depth
    args.max_paths_per_leaf = max_ppl
    args.no_wikidata = no_wd
    run_with_args(args)

def main():
    if len(sys.argv) == 1:
        return interactive_wizard()

    ap = argparse.ArgumentParser(description="Construir CSV hierárquico (L1..Ln) de influências para o Influence Map")
    ap.add_argument("--out", required=True, help="CSV de saída (hierárquico por níveis)")
    ap.add_argument("--sidecar", default="", help="CSV extra com arestas e proveniência (opcional)")
    ap.add_argument("--wikipedia-csv", default="", help="CSV dinâmico a fundir (opcional)")
    ap.add_argument("--sep-in", default=None, help="Separador do CSV de entrada (auto se omitido)")
    ap.add_argument("--sep-out", default=";", help="Separador do CSV de saída (default: ;)")
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS, help="Raízes a considerar")
    ap.add_argument("--max-depth", type=int, default=6, help="Profundidade máxima dos caminhos (default: 6)")
    ap.add_argument("--max-paths-per-leaf", type=int, default=8, help="Limite por folha (default: 8)")
    ap.add_argument("--no-wikidata", action="store_true", help="Não consultar Wikidata (apenas CSV+KB)")
    args = ap.parse_args()
    run_with_args(args)

if __name__ == "__main__":
    main()
