from __future__ import annotations
from typing import List, Tuple
import unicodedata, re

def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii")

def norm_label(s: str) -> str:
    s0 = (s or "").strip()
    s1 = _strip_accents(s0).lower()
    s1 = re.sub(r"\s*\(.*?\)\s*$","", s1)   # corta “ (Spotify seeds)”
    s1 = re.sub(r"\s+genre\s*$","", s1)     # corta “ genre” no fim
    s1 = re.sub(r"\s+"," ", s1).strip()
    return s1

def _dedup(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def resolve_genre_canon_and_aliases(label: str) -> Tuple[str, List[str]]:
    """Consulta a tua KB (services.genres_kb) e devolve (canónico, aliases) normalizados.
       Fallback: (norm(label), [norm(label)]).
    """
    n = norm_label(label)
    try:
        from services import genres_kb as kb  # tua KB
        for name in ("resolve_canonical","canonical_for","resolve_genre","canon_and_aliases"):
            fn = getattr(kb, name, None)
            if callable(fn):
                res = fn(label)
                if isinstance(res, tuple) and len(res) == 2:
                    canon, aliases = res
                elif isinstance(res, dict):
                    canon = res.get("canonical") or n
                    aliases = res.get("aliases") or []
                else:
                    canon, aliases = n, []
                canon_n = norm_label(canon)
                aliases_n = [norm_label(a) for a in aliases if a]
                return canon_n, _dedup([canon_n]+aliases_n)
        for name in ("aliases_for","get_aliases","synonyms_for"):
            fn = getattr(kb, name, None)
            if callable(fn):
                aliases = [norm_label(a) for a in (fn(label) or [])]
                return n, _dedup([n]+aliases)
    except Exception:
        pass
    return n, [n]
