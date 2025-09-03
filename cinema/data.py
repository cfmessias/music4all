# cinema/data.py
from __future__ import annotations

from pathlib import Path
import pandas as pd
# (mantém) lê config do projeto
from .config import BASE_DIR, FILES, SCHEMA, SEP, GENRE_FILES


# ---------- NOVO: resolver caminho real antes de criar vazio ----------
def _candidate_dirs() -> list[Path]:
    """Locais prováveis onde os CSVs podem estar (raiz, cwd, cinema/, cinema/data/)."""
    base = Path(BASE_DIR).resolve()
    return [
        Path.cwd(),
        base,
        base / "cinema",
        base / "cinema" / "data",
    ]

def _resolve_path_like(path: Path) -> Path:
    """
    Se 'path' não existir, tenta encontrar um ficheiro com o MESMO NOME
    nas pastas candidatas (raiz/cwd/cinema/...). Se achar, usa esse.
    Caso contrário, devolve o 'path' original (para eventual criação).
    """
    if path.exists():
        return path
    fname = path.name
    for d in _candidate_dirs():
        p = d / fname
        if p.exists():
            return p
    return path
# ----------------------------------------------------------------------


def ensure_csv(path: Path, headers: list[str]) -> None:
    """
    Garante que o ficheiro existe com as colunas mínimas.
    ATENÇÃO: antes de criar, tentamos resolver um existente noutro diretório.
    """
    # ---------- ALTERADO: resolver antes de criar ----------
    path = _resolve_path_like(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        pd.DataFrame(columns=headers).to_csv(path, index=False, sep=SEP, encoding="utf-8")


def _ensure_schema(df: pd.DataFrame, section: str) -> pd.DataFrame:
    cols = SCHEMA[section]
    # adiciona colunas em falta
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c not in ("watched",) else False
    # remove extras para manter consistência
    df = df[cols]
    return df


def load_table(section: str) -> pd.DataFrame:
    # ---------- ALTERADO: resolver caminho de forma robusta ----------
    path = FILES[section]
    path = Path(path) if not isinstance(path, Path) else path
    path = _resolve_path_like(path)

    ensure_csv(path, SCHEMA[section])
    df = pd.read_csv(path, sep=SEP, encoding="utf-8")

    # MIGRAÇÕES/garantias
    if section in ("Movies", "Series"):
        # subgenre → streaming (caso existisse)
        if "streaming" not in df.columns and "subgenre" in df.columns:
            df = df.rename(columns={"subgenre": "streaming"})
        if "streaming" not in df.columns:
            df["streaming"] = ""

    if section == "Series":
        if "season" not in df.columns:
            df["season"] = ""
        if "watched" not in df.columns:
            df["watched"] = False
        if "watched_date" not in df.columns:
            df["watched_date"] = ""

    if section == "Movies":
        if "watched" not in df.columns:
            df["watched"] = False
        if "watched_date" not in df.columns:
            df["watched_date"] = ""

    df = _ensure_schema(df, section)

    # ---------- ALTERADO: remover FutureWarning do pandas ----------
    # Em vez de errors="ignore", usamos "coerce" e tratamos NaN a jusante.
    if "watched" in df.columns:
        df["watched"] = df["watched"].astype(bool, copy=False)
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
    if "year_start" in df.columns:
        df["year_start"] = pd.to_numeric(df["year_start"], errors="coerce")
    if "year_end" in df.columns:
        df["year_end"] = pd.to_numeric(df["year_end"], errors="coerce")
    if "season" in df.columns:
        df["season"] = pd.to_numeric(df["season"], errors="coerce")

    return df


def save_table(section: str, df: pd.DataFrame) -> None:
    # ---------- ALTERADO: resolver caminho de forma robusta ----------
    path = FILES[section]
    path = Path(path) if not isinstance(path, Path) else path
    path = _resolve_path_like(path)

    ensure_csv(path, SCHEMA[section])
    df = _ensure_schema(df, section)
    df.to_csv(path, index=False, sep=SEP, encoding="utf-8")


def load_genres() -> tuple[list[str], dict[str, list[str]], Path]:
    """
    Lê generos_cinema_selectbox.csv (PT por omissão).
    Aceita cabeçalhos PT ('Genero','Subgenero') ou EN ('genre','subgenre').
    Devolve: (lista_generos_com_All, mapa_subgeneros_por_genero, caminho)
    """
    file_path = None
    for p in GENRE_FILES:
        if p.exists():
            file_path = p
            break
    if file_path is None:
        # Fallback básico
        return (["All"], {}, Path(BASE_DIR) / "generos_cinema_selectbox.csv")

    df = pd.read_csv(file_path, sep=SEP, encoding="utf-8")
    # normalizar nomes das colunas
    cols = {c.lower(): c for c in df.columns}
    gcol = cols.get("genero") or cols.get("genre")
    scol = cols.get("subgenero") or cols.get("subgenre")
    if not gcol or not scol:
        # tenta nomes já corretos
        if "Genero" in df.columns and "Subgenero" in df.columns:
            gcol, scol = "Genero", "Subgenero"
        elif "genre" in df.columns and "subgenre" in df.columns:
            gcol, scol = "genre", "subgenre"
        else:
            # fallback
            return (["All"], {}, file_path)

    df = df[[gcol, scol]].rename(columns={gcol: "Genero", scol: "Subgenero"})
    df["Genero"] = df["Genero"].astype(str).str.strip()
    df["Subgenero"] = df["Subgenero"].astype(str).str.strip()

    generos = ["All"] + sorted([g for g in df["Genero"].unique() if g])
    sub_by_gen = {}
    for g in df["Genero"].unique():
        subs = sorted(df.loc[df["Genero"] == g, "Subgenero"].dropna().astype(str).unique().tolist())
        sub_by_gen[g] = subs

    return (generos, sub_by_gen, file_path)
