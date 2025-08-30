# services/wiki.py
from __future__ import annotations

import requests
import streamlit as st
import re, unicodedata

WIKI_API = "https://{lang}.wikipedia.org/w/api.php"

@st.cache_data(ttl=86400, show_spinner=False)
def _wiki_api_search(title: str, lang: str = "en") -> str | None:
    try:
        r = requests.get(
            WIKI_API.format(lang=lang),
            params={
                "action": "query",
                "list": "search",
                "srsearch": title,
                "format": "json",
                "srlimit": 1,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        hits = (r.json().get("query") or {}).get("search") or []
        return hits[0]["title"] if hits else None
    except Exception:
        return None

@st.cache_data(ttl=86400, show_spinner=False)
def resolve_wikipedia_title(artist_name: str, lang: str = "en") -> tuple[str | None, str | None]:
    if not artist_name:
        return None, None
    for cand in (f"{artist_name} (band)", f"{artist_name} (music group)", artist_name):
        title = _wiki_api_search(cand, lang=lang)
        if title:
            url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
            return title, url
    return None, None

# --- Wikipédia: helpers robustos --------------------------------------------


def _norm_txt(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii")
    return re.sub(r"\s+", " ", s)

def _wiki_search(lang: str, query: str, limit: int = 5) -> list[dict]:
    try:
        r = requests.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
                "utf8": 1,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return (r.json().get("query") or {}).get("search") or []
    except Exception:
        return []

def _wiki_build_url(lang: str, title: str) -> str:
    from urllib.parse import quote
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"

def resolve_wikipedia_title(name: str, lang: str = "pt", hints: list[str] | None = None) -> tuple[str | None, str | None]:
    """
    Resolve título/URL na Wikipédia com heurística leve:
    - tenta name + (cantor|música|género) + pistas
    - pontua candidatos por proximidade do título ao nome e presença das pistas no snippet
    """
    if not name:
        return None, None

    hints = [h for h in (hints or []) if h]
    base = name.strip()
    qset = [
        base,
        f'{base} (cantor)' if lang == "pt" else f"{base} (singer)",
        f"{base} música" if lang == "pt" else f"{base} music",
    ]
    # acrescenta consultas com pistas
    for h in hints[:3]:
        qset.append(f"{base} {h}")

    target = _norm_txt(base)

    best = (0.0, None)  # (score, (title,url))
    for q in qset:
        for cand in _wiki_search(lang, q, limit=6):
            title = str(cand.get("title") or "").strip()
            snippet = _norm_txt(cand.get("snippet") or "")
            tnorm = _norm_txt(title)
            # score: nome igual/contido, + pistas no snippet
            score = 0.0
            if tnorm == target: score += 3.0
            if target in tnorm: score += 1.5
            score += sum(0.5 for h in hints if _norm_txt(h) in snippet)
            if score > best[0]:
                best = (score, (title, _wiki_build_url(lang, title)))

    return best[1] if best[0] > 0 else (None, None)

def wiki_url_for_artist(artist: dict, preferred_lang: str = "pt") -> tuple[str | None, str | None, str]:
    """
    Tenta resolver URL de Wikipédia para um artista Spotify usando pistas:
    - nome
    - 2-3 géneros do artista
    - nacionalidade/país se existir no dicionário
    Fallback para 'en' se 'pt' não devolver nada.
    """
    name = (artist or {}).get("name") or ""
    genres = (artist or {}).get("genres") or []
    country = (artist or {}).get("country") or (artist or {}).get("nationality") or ""
    hints = list(dict.fromkeys([*genres[:3], country]))

    t, u = resolve_wikipedia_title(name, lang=preferred_lang, hints=hints)
    if u:
        return t, u, preferred_lang
    # fallback EN
    t, u = resolve_wikipedia_title(name, lang="en", hints=hints)
    return t, u, ("en" if u else preferred_lang)
