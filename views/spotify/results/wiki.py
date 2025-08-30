# views/spotify/results/wiki.py
# Resumo curto (2–3 frases) SEMPRE em INGLÊS.

from __future__ import annotations

import re
import requests
import streamlit as st
from urllib.parse import quote


@st.cache_data(ttl=86400, show_spinner=False)
def wiki_search(q: str, lang: str = "en", limit: int = 6) -> list[dict]:
    try:
        r = requests.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": q,
                "format": "json",
                "srlimit": limit,
                "utf8": 1,
            },
            headers={"user-agent": "music4all/1.0"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return (r.json().get("query") or {}).get("search") or []
    except Exception:
        return []


def _norm(s: str) -> str:
    import unicodedata
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s)


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_wiki_title(name: str, hints: list[str] | None = None, lang: str = "en") -> tuple[str | None, str | None]:
    if not name:
        return None, None
    hints = [h for h in (hints or []) if h]
    base = name.strip()
    qset = [
        base,
        f"{base} (band)",
        f"{base} (singer)",
        f"{base} (musician)",
        f"{base} (musical group)",
    ]
    for h in hints[:3]:
        qset.append(f"{base} {h}")

    target = _norm(base)
    best = (0.0, None)
    for q in qset:
        for c in wiki_search(q, lang=lang, limit=6):
            title = str(c.get("title") or "").strip()
            snippet = _norm(c.get("snippet") or "")
            tnorm = _norm(title)
            score = 0.0
            if tnorm == target:
                score += 3.0
            if target in tnorm:
                score += 1.5
            score += sum(0.5 for h in hints if _norm(h) in snippet)
            if score > best[0]:
                best = (score, (title, f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"))
    return best[1] if best[0] > 0 else (None, None)


@st.cache_data(ttl=86400, show_spinner=False)
def wiki_summary(title: str, lang: str = "en") -> str:
    try:
        r = requests.get(
            f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}",
            headers={"accept": "application/json", "user-agent": "music4all/1.0"},
            timeout=8,
        )
        if r.status_code != 200:
            return ""
        j = r.json()
        if (j.get("type") or "").lower() == "disambiguation":
            return ""
        txt = (j.get("extract") or "").strip()
        if not txt:
            return ""
        sents = re.split(r"(?<=[.!?])\s+", txt)
        return " ".join(sents[:3])
    except Exception:
        return ""


@st.cache_data(ttl=86400, show_spinner=False)
def artist_blurb(name: str, hints: list[str] | None = None) -> tuple[str, str]:
    """
    Obtém 2–3 frases da Wikipédia em INGLÊS (sem fallback para PT).
    Se falhar, tenta variantes comuns com sufixos (band/musical group).
    """
    # 1) tentar resolver título normalmente
    title, url = resolve_wiki_title(name, hints=hints, lang="en")
    tried = set()
    if title:
        tried.add(title)
        txt = wiki_summary(title, lang="en")
        if txt:
            return txt, (url or f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}")

    # 2) variantes de banda/grupo
    for t in (f"{name} (band)", f"{name} (musical group)"):
        if t in tried:
            continue
        txt = wiki_summary(t, lang="en")
        if txt:
            return txt, f"https://en.wikipedia.org/wiki/{t.replace(' ', '_')}"

    return "", ""
