# services/spotify/search_service.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Set, Iterable, Optional
import re
import requests
import streamlit as st

from services.spotify.auth import get_auth_header
from services.genres_bridge import resolve_genre_canon_and_aliases, norm_label

SEARCH_URL = "https://api.spotify.com/v1/search"

# Mercado por defeito: PT (ajusta se quiseres outro)
DEFAULT_MARKET = "PT"
DEFAULT_LIMIT = 50

# Conflitos conhecidos de etiquetagem (Spotify genres)
# Se procuras "fado", evita artistas marcados como "morna"/"coladeira" sem token "fado".
GENRE_CONFLICTS: Dict[str, Set[str]] = {
    "fado": {"morna", "coladeira"},
}
# Tokens exatos que consideramos "fado" (normalizados por norm_label)
FADO_TOKENS_WHITELIST = {
    "fado", "fadoportugues", "portuguesefado",
    "fadotradicional", "tradicionalfado",
    "fado-classico", "fadoclassico",
    "fado-tradicional", "fadoantigo",
}

# Conflitos fortes: se estes tokens estiverem presentes, não consideramos "fado"
FADO_CONFLICTS = {"morna", "coladeira", "funana", "kizomba", "mpb", "bossa"}

# ---------------- Utilitários ----------------

def _tokenize_label(s: str) -> Set[str]:
    """Normaliza e tokeniza um rótulo: sem acentos, lower, separa por não-alfa-numérico."""
    return {t for t in re.split(r"[^\w]+", norm_label(s or "")) if t}

def _artist_tokens(artist: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for g in (artist.get("genres") or []):
        out |= _tokenize_label(g)
    return out

def _dedup_keep_order(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for a in items:
        aid = a.get("id")
        if aid and aid not in seen:
            seen.add(aid)
            out.append(a)
    return out

def _paged_search(token: str, q: str, market: Optional[str], max_pages: int = 4) -> List[Dict[str, Any]]:
    """
    Faz GET /v1/search com q e devolve artistas, paginando até max_pages.
    Usa type=artist e limit=50 (máximo).
    """
    params = {
        "q": q,
        "type": "artist",
        "limit": DEFAULT_LIMIT,
        "offset": 0,
    }
    if market:
        params["market"] = market

    headers = get_auth_header(token)
    out: List[Dict[str, Any]] = []
    pages = 0

    url = SEARCH_URL
    while url and pages < max_pages:
        r = requests.get(url, headers=headers, params=params if pages == 0 else None, timeout=20)
        if r.status_code != 200:
            break
        j = r.json() or {}
        artists = (j.get("artists") or {})
        out.extend(artists.get("items") or [])
        url = artists.get("next")   # URL absoluta para próxima página
        pages += 1
    return out

def _strict_genre_accept(artist: Dict[str, Any], wanted_aliases: Iterable[str], wanted_canon: str) -> bool:
    """
    Aceita artista se QUALQUER alias ocorrer como token em QUALQUER genre do artista.
    Para 'fado', aplica regras estritas:
      - tem de conter um token whitelisted (fado, fado portugues, fado tradicional, ...)
      - rejeita se houver conflito (morna/coladeira/…),
        mesmo que também exista a palavra 'fado' nos géneros.
    """
    toks = _artist_tokens(artist)
    wanted = {t for a in wanted_aliases for t in _tokenize_label(a)}

    # Caso geral (outros géneros): interseção por tokens dos aliases
    if norm_label(wanted_canon) != "fado":
        return bool(toks & wanted)

    # Caso específico: FADO
    # 1) conflito forte? rejeita (ex.: morna/coladeira)
    if toks & FADO_CONFLICTS:
        return False

    # 2) exige um token "fado" whitelist
    if not (toks & FADO_TOKENS_WHITELIST):
        return False

    return True


# ---------------- API PÚBLICA ----------------

def coerce_query_to_genre_if_applicable(raw: str, token: Optional[str] = None) -> Optional[str]:
    """
    Se a string do utilizador corresponder a um género na KB, devolve o canónico.
    Caso contrário, None. (token não é usado aqui; guardado por compatibilidade)
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    # sintaxe genre:"…"
    m = re.match(r'^\s*genre\s*:\s*"([^"]+)"\s*$', raw, flags=re.I)
    if m:
        return m.group(1).strip()
    canon, _aliases = resolve_genre_canon_and_aliases(raw)
    # se a normalização não mudou a essência, assume que era género
    return canon if canon and norm_label(canon) == norm_label(raw) else None

@st.cache_data(ttl=1800, show_spinner=False)
def search_artists_by_genre(
    token: str,
    genre: str,
    market: Optional[str] = DEFAULT_MARKET,
    max_pages: int = 4,
) -> List[Dict[str, Any]]:
    """
    Procura via q=genre:"…" (com aliases) e filtra por tokens em artist.genres.
    """
    if not genre:
        return []
    canon, aliases = resolve_genre_canon_and_aliases(genre)
    if not aliases:
        aliases = [canon] if canon else [genre]
    results: List[Dict[str, Any]] = []

    # consulta cada alias explícito como q=genre:"alias"
    for al in aliases:
        q = f'genre:"{al}"'
        items = _paged_search(token, q, market=market, max_pages=max_pages)
        if items:
            results.extend(items)

    results = _dedup_keep_order(results)
    # pós-filtro estrito por tokens/aliases + conflitos
    results = [a for a in results if _strict_genre_accept(a, aliases, canon or genre)]

    # ordenar: followers desc, depois popularity desc
    results.sort(key=lambda a: -((a.get("followers") or {}).get("total") or 0))
    results.sort(key=lambda a: -(a.get("popularity") or 0))
    return results

@st.cache_data(ttl=900, show_spinner=False)
def search_artists_wildcard(
    token: str,
    raw_query: str,
    market: Optional[str] = DEFAULT_MARKET,
    max_pages: int = 3,
) -> List[Dict[str, Any]]:
    """
    Procura por nome/artista. Tenta heurísticas de prefixo/exato:
      - artist:"NAME" (exact-ish)
      - NAME* (prefix)
      - NAME (fallback)
    """
    q0 = (raw_query or "").strip()
    if not q0:
        return []
    items: List[Dict[str, Any]] = []

    # exact-ish pelo campo artist:
    items += _paged_search(token, f'artist:"{q0}"', market=market, max_pages=1)
    # prefixo:
    if len(q0) >= 2:
        items += _paged_search(token, f'{q0}*', market=market, max_pages=1)
    # fallback simples:
    items += _paged_search(token, q0, market=market, max_pages=max_pages)

    items = _dedup_keep_order(items)

    # ordenar: followers desc, depois popularity desc
    items.sort(key=lambda a: -((a.get("followers") or {}).get("total") or 0))
    items.sort(key=lambda a: -(a.get("popularity") or 0))
    return items
