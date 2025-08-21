# services/spotify/search_service.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import requests
import streamlit as st

from services.spotify.auth import get_auth_header
from services.spotify.genres import expand_seed_or_group, is_genre_like, normalize_label, fetch_spotify_genre_seeds
from services.genres_bridge import resolve_genre_canon_and_aliases

# ==========
# Wildcards
# ==========
def parse_wildcard(raw: str) -> tuple[str, str]:
    s = (raw or "").strip()
    if not s:
        return "", "all"
    starts = s.startswith("*")
    ends = s.endswith("*")
    core = s.strip("*").strip()
    if not core:
        return "", "all"
    if starts and ends: return core, "contains"
    if starts:          return core, "suffix"
    if ends:            return core, "prefix"
    return core, "exact"

def _match_name(name: str, core: str, mode: str) -> bool:
    n = (name or "").strip().casefold()
    c = (core or "").strip().casefold()
    if not c:            return True
    if mode == "exact":  return n == c
    if mode == "prefix": return n.startswith(c)
    if mode == "suffix": return n.endswith(c)
    if mode == "contains": return c in n
    return True

# ==================
# Pesquisa Spotify
# ==================
@st.cache_data(ttl=900, show_spinner=False)
def _search_artists_api(token: str, q: str, limit: int = 50, offset: int = 0) -> list[dict]:
    if not token or not q:
        return []
    headers = get_auth_header(token)
    params = {"q": q, "type": "artist", "limit": limit, "offset": offset}
    try:
        r = requests.get("https://api.spotify.com/v1/search", headers=headers, params=params, timeout=12)
        if r.status_code != 200:
            return []
        return ((r.json().get("artists") or {}).get("items") or [])
    except Exception:
        return []

@st.cache_data(ttl=900, show_spinner=False)
def search_artists_wildcard(token: str, raw_query: str, max_pages: int = 4) -> list[dict]:
    core, mode = parse_wildcard(raw_query)
    if not core:
        return []
    seen, out = set(), []
    exact_q = f'artist:"{core}"' if mode == "exact" else None
    if exact_q:
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, exact_q, limit=50, offset=off):
                if not isinstance(a, dict): continue
                aid = a.get("id")
                if not aid or aid in seen: continue
                seen.add(aid)
                if _match_name(a.get("name",""), core, mode): out.append(a)
    if (not exact_q) or (exact_q and not out):
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, core, limit=50, offset=off):
                if not isinstance(a, dict): continue
                aid = a.get("id")
                if not aid or aid in seen: continue
                seen.add(aid)
                if _match_name(a.get("name",""), core, mode): out.append(a)
    return out

# ============
# Por género
# ============
def parse_genre_only(raw_q: str) -> str | None:
    if not isinstance(raw_q, str): return None
    m = re.match(r'^\s*genre\s*:\s*"([^"]+)"\s*$', raw_q.strip(), flags=re.IGNORECASE)
    return (m.group(1).strip() if m else None)

@st.cache_data(ttl=900, show_spinner=False)
def search_artists_by_genre(token: str, genre: str, max_pages: int = 4) -> list[dict]:
    """Pesquisa estrita por género, alinhada com a KB:
       - Se 'genre' for grupo (ex.: 'Asian'), expande seeds e agrega (mantém a tua lógica).
       - Caso simples: usa (canónico, aliases) da KB e filtra por artist.genres que contenham
         QUALQUER desses termos normalizados.
    """
    if not (token and genre):
        return []

    # 1) Grupo? (mantém a tua expansão de seeds)
    seeds_or_label = expand_seed_or_group(genre)
    if len(seeds_or_label) > 1:
        seeds_norm = [normalize_label(s) for s in seeds_or_label]
        seen, out = set(), []
        def _g(a): 
            try: return [str(x).casefold() for x in (a.get("genres") or [])]
            except: return []
        for q in seeds_or_label:
            for off in (0,50,100,150)[:max_pages]:
                for a in _search_artists_api(token, q.strip(), limit=50, offset=off):
                    if not isinstance(a, dict): continue
                    aid = a.get("id")
                    if not aid or aid in seen: continue
                    if any(ns in gg for ns in seeds_norm for gg in _g(a)):
                        seen.add(aid); out.append(a)
        return out

    # 2) Género simples → KB
    canon, aliases_norm = resolve_genre_canon_and_aliases(genre)
    queries = list(dict.fromkeys([genre] + aliases_norm))

    def _g(a):
        try: return [str(x).casefold() for x in (a.get("genres") or [])]
        except: return []
    def _accept(a):
        gl = _g(a)
        return any(alias in gg for alias in aliases_norm for gg in gl)

    seen, tmp = set(), []
    for q in queries:
        for off in (0,50,100,150)[:max_pages]:
            for a in _search_artists_api(token, q.strip(), limit=50, offset=off):
                if not isinstance(a, dict): continue
                aid = a.get("id")
                if not aid or aid in seen: continue
                seen.add(aid); tmp.append(a)

    return [a for a in tmp if _accept(a)]

# ============
# Paginação
# ============
def paginate(items: List[dict], page: int, per_page: int) -> tuple[List[dict], int, int]:
    total = len(items)
    if total == 0: return [], 0, 0
    pages = (total - 1) // per_page + 1
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total, pages

# ============
# Deteção de género na query livre (p/ UI Spotify)
# ============
def coerce_query_to_genre_if_applicable(raw_q: str, token: str | None = None) -> str | None:
    """
    Se a query livre parecer um género (ex.: 'Fado'), devolve o canónico (ex.: 'fado').
    Caso contrário devolve None.
    """
    if not raw_q: return None
    isg, canon, _ = is_genre_like(raw_q, token=token)
    return canon if isg else None
