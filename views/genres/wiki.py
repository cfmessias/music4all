# views/genres/wiki.py
# Resumo e infobox da Wikipédia (com cache)
import re
import requests
from urllib.parse import quote
import streamlit as st

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# ------- Summary -------
@st.cache_data(ttl=86400, show_spinner=False)
@st.cache_data(ttl=86400, show_spinner=False)
def wiki_fetch_summary(lang: str, title: str):
    """REST API page/summary: devolve (texto, url) ou ('','')."""
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
        headers = {
            "accept": "application/json",
            "user-agent": "music4all/1.0 (+https://example.com)"
        }
        r = requests.get(url, timeout=6, headers=headers)
        if not r.ok:
            return "", ""
        data = r.json()
        if (data.get("type") or "").lower() == "disambiguation":
            return "", ""
        txt = (data.get("extract") or "").strip()
        page_url = (data.get("content_urls", {}) or {}).get("desktop", {}).get("page", "")
        return txt, page_url
    except Exception:
        return "", ""

def wiki_summary_any(name: str):
    variants = [name, f"{name} (music)", f"{name} music", f"{name} (genre)", f"{name} (musical genre)"]
    for lang in ("en", "pt"):
        for title in variants:
            txt, url = wiki_fetch_summary(lang, title)
            if txt:
                sents = re.split(r"(?<=[.!?])\s+", txt.strip())
                return " ".join(sents[:3]), url
    return "", ""

# ------- Infobox -------
def _norm(s: str) -> str:
    return " ".join((s or "").split())

def _parse_infobox_fields(html: str) -> dict[str, str]:
    if not BeautifulSoup: return {}
    soup = BeautifulSoup(html, "html.parser")
    infobox = soup.select_one("table.infobox")
    if not infobox: return {}
    wanted = {
        "stylistic origins": "Stylistic origins",
        "cultural origins": "Cultural origins",
        "typical instruments": "Typical instruments",
        "instruments": "Typical instruments",
    }
    got: dict[str, str] = {}
    for tr in infobox.select("tr"):
        th, td = tr.find("th"), tr.find("td")
        if not th or not td: continue
        label = _norm(th.get_text(" ", strip=True)).lower()
        if label in wanted:
            links = [a.get_text(" ", strip=True) for a in td.select("a") if a.get_text(strip=True)]
            text = " · ".join(links) if links else td.get_text(" ", strip=True)
            text = _norm(text)
            if text: got[wanted[label]] = text
    return got

@st.cache_data(ttl=86400, show_spinner=False)
def wiki_infobox_any(name: str) -> tuple[dict[str, str], str]:
    base = "https://en.wikipedia.org/wiki/"
    headers = {"user-agent": "music4all/1.0 (+streamlit)"}
    variants = [name, f"{name} (music)", f"{name} music", f"{name} (genre)", f"{name} (musical genre)"]
    for title in variants:
        try:
            url = base + quote(title)
            r = requests.get(url, timeout=8, headers=headers)
            if not r.ok: continue
            if "mw-disambig" in r.text or "(disambiguation)" in title.lower(): continue
            fields = _parse_infobox_fields(r.text)
            if fields: return fields, url
        except Exception:
            continue
    return {}, ""
