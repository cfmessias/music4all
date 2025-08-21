# services/wiki.py
from __future__ import annotations

import requests
import streamlit as st

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
