# views/spotify/results/search.py
# Lógica de pesquisa: artist-first (strict), wildcard quando o utilizador usa '*',
# pesquisa por género quando o campo Artist está vazio,
# e filtro de artistas por género (conjunção).

from __future__ import annotations

import re
import unicodedata
import requests
import streamlit as st

from services.spotify import get_auth_header


# ------------------ util: ler o que o utilizador escreveu ------------------

def extract_user_query_from_state(state: dict) -> str:
    """Tenta ler a query do campo principal (sem depender de uma key fixa)."""
    for k in ["query", "artist", "artist_query", "spotify_artist",
              "search", "artist_name", "name_input"]:
        v = state.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# ------------------ wildcards do utilizador ------------------

def parse_wildcard(raw: str) -> tuple[str, str]:
    """
    devolve (core, mode) onde mode ∈ {"exact","prefix","suffix","contains","all"}
    - "exact": sem '*'
    - "prefix": termina com '*'
    - "suffix": começa com '*'
    - "contains": começa e termina com '*'
    """
    s = (raw or "").strip()
    if not s:
        return "", "all"
    starts, ends = s.startswith("*"), s.endswith("*")
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
    n, c = (name or "").strip().casefold(), (core or "").strip().casefold()
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


# ------------------ chamadas à API ------------------

@st.cache_data(ttl=900, show_spinner=False)
def _search_artists_api(token: str, q: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Uma página de resultados do endpoint /v1/search para artistas."""
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


def dedup_by_id(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for a in items:
        aid = a.get("id")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append(a)
    return out


# ------------------ PESQUISA ESTRITA (sem falsos positivos) ------------------

@st.cache_data(ttl=900, show_spinner=False)
def search_artists_strict(token: str, name: str) -> list[dict]:
    """
    Sem '*' → devolve SÓ artistas cujo nome é exatamente igual ao que o
    utilizador digitou (case-insensitive e sem acentos). Sem fallback “largo”.
    """
    def _norm_simple(s: str) -> str:
        s = (s or "").strip().lower()
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", s)

    core = (name or "").strip()
    if not core:
        return []
    target = _norm_simple(core)

    # Tenta pesquisa exata com aspas
    exact_q = f'artist:"{core}"'
    items: list[dict] = []
    for off in (0, 50, 100, 150):
        items.extend(_search_artists_api(token, exact_q, limit=50, offset=off))

    # Filtra por igualdade normalizada (sem acentos / case)
    out = [a for a in items if _norm_simple(a.get("name", "")) == target]
    if out:
        return dedup_by_id(out)

    # Sem fallback amplo → preferimos devolver vazio a falsos positivos
    return []


# ------------------ PESQUISA COM WILDCARDS (quando o utilizador usa '*') ------------------

@st.cache_data(ttl=900, show_spinner=False)
def search_artists_wildcard(token: str, raw_query: str, max_pages: int = 4) -> list[dict]:
    core, mode = parse_wildcard(raw_query)
    if not core:
        return []
    seen, out = set(), []

    # Pesquisa “larga” + filtro local pelo wildcard
    for off in (0, 50, 100, 150)[:max_pages]:
        for a in _search_artists_api(token, core, limit=50, offset=off):
            if not isinstance(a, dict):
                continue
            aid = a.get("id")
            if not aid or aid in seen:
                continue
            if _match_name(a.get("name", ""), core, mode):
                seen.add(aid)
                out.append(a)

    # Se pediste “exact” via parse_wildcard (sem '*') e nada veio, tenta com aspas
    if mode == "exact" and not out:
        exact_q = f'artist:"{core}"'
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, exact_q, limit=50, offset=off):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                if _match_name(a.get("name", ""), core, mode):
                    seen.add(aid)
                    out.append(a)

    return out


# ------------------ PESQUISA POR GÉNERO (usada quando o campo Artist está vazio) ------------------

@st.cache_data(ttl=900, show_spinner=False)
def search_artists_by_genre(token: str, genre: str, max_pages: int = 4) -> list[dict]:
    """
    Pesquisa por género: pergunta à API por artistas com 'genre' como texto.
    (Depois podemos filtrar por tokens para maior precisão.)
    """
    if not (token and genre):
        return []
    seen, out = set(), []
    for off in (0, 50, 100, 150)[:max_pages]:
        for a in _search_artists_api(token, genre, limit=50, offset=off):
            if not isinstance(a, dict):
                continue
            aid = a.get("id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            out.append(a)
    return out


# ------------------ FILTRO por género (conjunção Artist ∩ Genre) ------------------

def _norm_txt(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s)

def filter_artists_by_genre(artists: list[dict], genre_term: str) -> list[dict]:
    """
    Mantém só artistas cujo(s) género(s) contêm todas as palavras do 'genre_term'.
    Ex.: 'progressive rock' → {'progressive','rock'} ⊆ tokens(artist.genres)
    """
    if not genre_term:
        return artists

    target_tokens = {t for t in re.split(r"[^\w]+", _norm_txt(genre_term)) if t}
    if not target_tokens:
        return artists

    out = []
    for a in artists:
        gl = a.get("genres") or []
        artist_tokens = set()
        for g in gl:
            artist_tokens |= {t for t in re.split(r"[^\w]+", _norm_txt(g)) if t}
        if target_tokens.issubset(artist_tokens):
            out.append(a)
    return out
