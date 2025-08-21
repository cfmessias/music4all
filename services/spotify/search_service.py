# services/spotify_search.py
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

import requests
import streamlit as st

from services.spotify import get_auth_header

# ==========
# Wildcards
# ==========
def parse_wildcard(raw: str) -> tuple[str, str]:
    """
    Devolve (core, modo) para expressões com '*' no início/fim.
    modos: exact | prefix | suffix | contains | all
    """
    s = (raw or "").strip()
    if not s:
        return "", "all"
    starts = s.startswith("*")
    ends = s.endswith("*")
    core = s.strip("*").strip()
    if not core:
        return "", "all"
    if starts and ends:
        return core, "contains"
    if starts:
        return core, "suffix"
    if ends:
        return core, "prefix"
    return core, "exact"


def _match_name(name: str, core: str, mode: str) -> bool:
    n = (name or "").strip().casefold()
    c = (core or "").strip().casefold()
    if not c:
        return True
    if mode == "exact":
        return n == c
    if mode == "prefix":
        return n.startswith(c)
    if mode == "suffix":
        return n.endswith(c)
    if mode == "contains":
        return c in n
    return True


# ==================
# Pesquisa Spotify
# ==================
@st.cache_data(ttl=900, show_spinner=False)
def _search_artists_api(token: str, q: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Chamada simples a /v1/search para artistas (1 página)."""
    if not token or not q:
        return []
    headers = get_auth_header(token)
    params = {"q": q, "type": "artist", "limit": limit, "offset": offset}
    try:
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params=params,
            timeout=12,
        )
        if r.status_code != 200:
            return []
        return ((r.json().get("artists") or {}).get("items") or [])
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def search_artists_wildcard(token: str, raw_query: str, max_pages: int = 4) -> list[dict]:
    """
    Pesquisa por artistas respeitando wildcards do utilizador.
    - Varre até 4 páginas (offsets 0/50/100/150).
    - Para 'exact', tenta primeiro artist:"<name>" e depois fallback.
    - Dedup por id e filtro local.
    """
    core, mode = parse_wildcard(raw_query)
    if not core:
        return []

    seen, out = set(), []
    exact_q = f'artist:"{core}"' if mode == "exact" else None

    # 1) Exact primeiro (se aplicável)
    if exact_q:
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, exact_q, limit=50, offset=off):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                if _match_name(a.get("name", ""), core, mode):
                    out.append(a)

    # 2) Normal / fallback
    if (not exact_q) or (exact_q and not out):
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, core, limit=50, offset=off):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                if _match_name(a.get("name", ""), core, mode):
                    out.append(a)

    return out


# ============
# Por género
# ============
def parse_genre_only(raw_q: str) -> str | None:
    """
    Se raw_q for exatamente genre:"<valor>", devolve <valor>, senão None.
    """
    if not isinstance(raw_q, str):
        return None
    m = re.match(r'^\s*genre\s*:\s*"([^"]+)"\s*$', raw_q.strip(), flags=re.IGNORECASE)
    return (m.group(1).strip() if m else None)


@st.cache_data(ttl=900, show_spinner=False)
def search_artists_by_genre(token: str, genre: str, max_pages: int = 4) -> list[dict]:
    """
    Pesquisa por “texto do género” e filtra localmente por artist.genres.
    Funciona melhor que o operador genre: da API, que é inconsistente.
    """
    if not (token and genre):
        return []
    g = genre.strip().casefold()
    seen, out = set(), []
    for off in (0, 50, 100, 150)[:max_pages]:
        for a in _search_artists_api(token, genre, limit=50, offset=off):
            if not isinstance(a, dict):
                continue
            aid = a.get("id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            glist = [str(x).casefold() for x in (a.get("genres") or [])]
            if any((g in gg) or (gg in g) for gg in glist):
                out.append(a)
    return out


# ============
# Paginação
# ============
def paginate(items: List[dict], page: int, per_page: int) -> tuple[List[dict], int, int]:
    """Devolve fatia, total e nº total de páginas."""
    total = len(items)
    if total == 0:
        return [], 0, 0
    pages = (total - 1) // per_page + 1
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total, pages
