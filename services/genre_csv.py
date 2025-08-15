# services/genre_csv.py
import os, re, unicodedata
import pandas as pd

CSV_PATHS = [
    "hierarquia_generos.csv",
    "dados/hierarquia_generos.csv",
    "data/hierarquia_generos.csv",
]
MAX_LEVEL = 7
LEVEL_COLS = [f"H{i}" for i in range(1, MAX_LEVEL + 1)]

def norm(s) -> str:
    if s is None:
        return ""
    try:
        if pd.isna(s):
            return ""
    except Exception:
        pass
    s = str(s).replace("\xa0", " ").strip()
    if s.lower() == "nan":
        return ""
    return re.sub(r"\s{2,}", " ", s)

def slug(s: str) -> str:
    s = norm(s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9\-_.]+", "-", s).strip("-").lower()
    return s or "x"

def path_key(path: list[str]) -> str:
    if not path:
        return "root"
    return "__".join(slug(p) for p in path)

def make_key(prefix: str, path: list[str] | tuple[str, ...], idx: int | None = None, extra: str = "") -> str:
    base = f"{prefix}_{path_key(list(path))}"
    if idx is not None:
        base += f"_{idx}"
    if extra:
        base += f"_{slug(extra)}"
    return base

def read_csv_fixed(path: str) -> pd.DataFrame:
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, sep=",", encoding=enc)
        except Exception as e:
            last_err = e
    raise last_err or FileNotFoundError(path)

def load_hierarchy_csv() -> tuple[pd.DataFrame, str]:
    for p in CSV_PATHS:
        if os.path.exists(p):
            df = read_csv_fixed(p)
            need = ["URL", "Texto"] + LEVEL_COLS
            for c in need:
                if c not in df.columns:
                    df[c] = ""
            df[need] = df[need].where(~df[need].isna(), "")
            for c in need:
                df[c] = df[c].map(norm)
            mask_any = df[["Texto"] + LEVEL_COLS].apply(
                lambda r: any(bool(norm(x)) for x in r), axis=1
            )
            df = df[mask_any].copy()
            return df, p
    raise FileNotFoundError("Não encontrei 'hierarquia_generos.csv' (nem em dados/ ou data/).")

def build_indices(df: pd.DataFrame):
    """
    children[prefix] -> set de ramos do próximo nível
    leaves[prefix]   -> lista de folhas (texto, url, caminho completo)
    roots            -> lista H1
    leaf_url[path]   -> URL quando *aquele* path é folha em alguma linha
    """
    roots = sorted({norm(x) for x in df["H1"].fillna("").tolist() if norm(x)})

    children: dict[tuple, set] = {(): set(roots)}
    leaves: dict[tuple, list] = {(): []}
    leaf_url: dict[tuple, str] = {}

    LEVEL_COLS_LOCAL = [c for c in df.columns if c.startswith("H")]
    LEVEL_COLS_LOCAL.sort(key=lambda x: int(x[1:]) if x[1:].isdigit() else 99)

    for _, r in df.iterrows():
        levs = [norm(r.get(c, "")) for c in LEVEL_COLS_LOCAL]
        levs = [x for x in levs if x]
        leaf_text = norm(r.get("Texto", ""))
        url = norm(r.get("URL", ""))

        full_path = list(levs)
        if leaf_text and (not full_path or full_path[-1] != leaf_text):
            full_path.append(leaf_text)
        if not full_path:
            continue

        for i in range(len(full_path) - 1):
            prefix = tuple(full_path[: i + 1])
            nxt = full_path[i + 1]
            if nxt:
                children.setdefault(prefix, set()).add(nxt)

        txt = leaf_text if leaf_text else full_path[-1]
        for i in range(len(full_path)):
            prefix = tuple(full_path[: i + 1])
            leaves.setdefault(prefix, []).append((txt, url, full_path))

        if url:
            leaf_url[tuple(full_path)] = url

        leaves[()].append((txt, url, full_path))

    return children, leaves, roots, leaf_url

def build_context_keywords(path: list[str], leaf: str) -> list[str]:
    """
    Usa até 2 ancestrais além do leaf para afinar a pesquisa.
    Ex.: ['World', 'Latin', 'Samba'] -> ['samba', 'latin']
    """
    p = [x for x in path if norm(x)]
    if p and p[-1].lower() == norm(leaf).lower():
        ancestors = p[:-1]
    else:
        ancestors = p
    anc = [a for a in ancestors if a][-2:]
    out = [norm(leaf)]
    out.extend(anc)
    seen, uniq = set(), []
    for t in out:
        t2 = t.lower()
        if t2 and t2 not in seen:
            seen.add(t2); uniq.append(t)
    return uniq
