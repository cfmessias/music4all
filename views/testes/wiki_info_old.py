import os
import re
import html
import requests
import pandas as pd
import streamlit as st

# =========================
#  CSV -> link da Wikipédia
# =========================
@st.cache_data(ttl=86400, show_spinner=False)
def wiki_link_map() -> dict:
    """
    Lê um CSV com (Artista;URL) e devolve { nome_lower: url }.
    Aceita: lista_artistas.csv, wikipedia_styles.csv, dados/lista_artistas.csv, data/lista_artistas.csv
    """
    candidates = [
        "lista_artistas.csv",
        "wikipedia_styles.csv",
        "dados/lista_artistas.csv",
        "data/lista_artistas.csv",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, sep=";")
            except Exception:
                df = pd.read_csv(path)
            cols = {c.lower().strip(): c for c in df.columns}
            name_col = cols.get("artista") or cols.get("artist") or list(df.columns)[0]
            url_col = cols.get("url")
            if not url_col:
                continue
            d = {}
            for _, r in df.iterrows():
                name = str(r.get(name_col, "")).strip()
                url = str(r.get(url_col, "")).strip()
                if name and url:
                    d[name.lower()] = url
            if d:
                return d
    return {}

def find_wiki_url(artist_name: str) -> str | None:
    """Devolve URL da Wikipédia a partir do CSV (ou None)."""
    if not artist_name:
        return None
    return wiki_link_map().get(artist_name.lower())

# =========================
#  Wikipedia & Wikidata API
# =========================
WIKI_HEADERS = {"User-Agent": "music4all/1.0 (contact: you@example.com)"}

def title_from_wiki_url(url: str) -> str | None:
    """Extrai o 'title' (/wiki/<TITLE>) de um URL da Wikipédia."""
    if not url:
        return None
    m = re.search(r"/wiki/([^#?]+)", url)
    return m.group(1) if m else None

@st.cache_data(ttl=86400, show_spinner=False)
def wikidata_qid_from_title(title: str, lang: str = "en") -> str | None:
    """Obtém o QID da Wikidata a partir de um título da Wikipédia (lang = en/pt)."""
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query", "prop": "pageprops", "titles": title,
        "format": "json", "ppprop": "wikibase_item"
    }
    r = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=12)
    if r.status_code != 200:
        return None
    pages = (r.json().get("query") or {}).get("pages") or {}
    for p in pages.values():
        qid = (p.get("pageprops") or {}).get("wikibase_item")
        if qid:
            return qid
    return None

@st.cache_data(ttl=86400, show_spinner=False)
def wiki_guess_title_from_name(name: str, lang: str = "en") -> str | None:
    """
    Fallback: tenta descobrir o título da Wikipédia a partir do nome.
    Retorna o título com underscores (Yes_(band)).
    """
    if not (name and name.strip()):
        return None
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query", "list": "search", "format": "json",
        "srsearch": name.strip(), "srlimit": 1
    }
    try:
        r = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=12)
        if r.status_code != 200:
            return None
        res = (r.json().get("query") or {}).get("search") or []
        return res[0]["title"].replace(" ", "_") if res else None
    except Exception:
        return None

def _as_qid(v):
    """Extrai QID de um valor Wikidata (dict ou str)."""
    if isinstance(v, dict) and "id" in v and isinstance(v["id"], str) and v["id"].startswith("Q"):
        return v["id"]
    if isinstance(v, str) and v.startswith("Q"):
        return v
    return None

@st.cache_data(ttl=86400, show_spinner=False)
def wikidata_labels(ids: list[str], lang="pt") -> dict:
    """
    Recebe QIDs -> devolve {id: label}. Tenta PT e, se faltar, usa EN.
    """
    ids = [i for i in (ids or []) if isinstance(i, str) and i.startswith("Q")]
    if not ids:
        return {}
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "wbgetentities",
            "ids": "|".join(chunk),
            "props": "labels",
            "format": "json",
            "languages": f"{lang}|en",
        }
        r = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=12)
        if r.status_code != 200:
            continue
        ents = (r.json().get("entities") or {})
        for qid, ent in ents.items():
            lab = ((ent.get("labels") or {}).get(lang) or {}).get("value") \
                  or ((ent.get("labels") or {}).get("en") or {}).get("value")
            if lab:
                out[qid] = lab
    return out

@st.cache_data(ttl=86400, show_spinner=False)
def wikidata_rich_info(qid: str, lang="pt") -> dict:
    """
    Info tipo 'infobox' com rótulos legíveis (Wikidata):
      years_active, country, origin, genres, labels, current_members, former_members, website
    Nota: membros na Wikidata são frequentemente incompletos/desatualizados.
    """
    if not qid:
        return {}
    url = "https://www.wikidata.org/w/api.php"
    params = {"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"}
    r = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=12)
    if r.status_code != 200:
        return {}

    ent = (r.json().get("entities") or {}).get(qid) or {}
    claims = ent.get("claims") or {}

    def many(pid):
        arr = []
        for c in (claims.get(pid) or []):
            v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
            q = _as_qid(v)
            if q:
                arr.append(q)
        return arr

    def first_time(pid):
        c = (claims.get(pid) or [{}])[0]
        t = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}).get("time")
        return int(t[1:5]) if isinstance(t, str) and len(t) >= 5 else None

    def first_url(pid):
        c = (claims.get(pid) or [{}])[0]
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        return v if isinstance(v, str) else None

    # anos de atividade
    inception = first_time("P571")
    dissolved = first_time("P576")
    years_active = f"{inception or '—'} – {dissolved or 'present'}"

    # país / origem
    country_q = (many("P17") or many("P495") or [None])[0]
    origin_qs = many("P740") or many("P159")

    # géneros / labels
    genre_qs = many("P136")
    label_qs = many("P264")

    # membros (muitas vezes incompleto na Wikidata)
    current_members_qs = many("P527")[:20]
    former_members_qs = many("P5769")[:20] or []

    website = first_url("P856") or "—"

    all_ids = [x for x in [country_q] if x] + origin_qs + genre_qs + label_qs + current_members_qs + former_members_qs
    labels = wikidata_labels(all_ids, lang=lang)

    def map_labels(qids):
        return [labels.get(q, q) for q in qids if q]

    return {
        "years_active": years_active,
        "country": labels.get(country_q, country_q or "—"),
        "origin": ", ".join(map_labels(origin_qs)) if origin_qs else "—",
        "genres": ", ".join(map_labels(genre_qs)) if genre_qs else "—",
        "labels": ", ".join(map_labels(label_qs)) if label_qs else "—",
        "current_members": ", ".join(map_labels(current_members_qs)) if current_members_qs else "—",
        "former_members": ", ".join(map_labels(former_members_qs)) if former_members_qs else "—",
        "website": website if website and website != "—" else "—",
    }

# =======================================================
#  Membros pela Wikipédia (infobox) — fonte prioritária
# =======================================================
@st.cache_data(ttl=86400, show_spinner=False)
def wiki_members_from_infobox(title: str, lang: str = "en") -> dict:
    """
    Tenta obter 'current_members' e 'past_members' diretamente da infobox da Wikipédia.
    Retorna {'current_members': '—', 'former_members': '—'} se não encontrar.
    """
    if not title:
        return {"current_members": "—", "former_members": "—"}

    # 1) buscar wikitext (main slot)
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "revisions",
        "rvslots": "main",
        "rvprop": "content",
        "format": "json",
        "titles": title,
    }
    try:
        r = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=12)
        if r.status_code != 200:
            return {"current_members": "—", "former_members": "—"}
        pages = (r.json().get("query") or {}).get("pages") or {}
        wikitext = ""
        for p in pages.values():
            revs = p.get("revisions") or []
            if revs and "slots" in revs[0] and "main" in revs[0]["slots"]:
                wikitext = revs[0]["slots"]["main"].get("*") or ""
                break
        if not wikitext:
            return {"current_members": "—", "former_members": "—"}

        def _clean_members_field(raw: str) -> str:
            # limpar wikilinks [[Name|alt]] → alt; [[Name]] → Name
            raw = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", raw)
            raw = re.sub(r"\[\[([^\]]+)\]\]", r"\1", raw)
            # remover refs e templates
            raw = re.sub(r"<ref.*?</ref>", "", raw, flags=re.DOTALL | re.IGNORECASE)
            raw = re.sub(r"\{\{.*?\}\}", "", raw, flags=re.DOTALL)
            # br -> separadores
            raw = raw.replace("<br />", " • ").replace("<br/>", " • ").replace("<br>", " • ")
            # tirar HTML residual
            raw = re.sub(r"<.*?>", "", raw)
            # dividir por bullets/linhas/•/pontos e limpar
            parts = re.split(r"[•\n;]+", raw)
            parts = [html.unescape(p).strip(" •,;") for p in parts if p and p.strip()]
            # normalizar espaços e remover duplicados mantendo ordem
            seen = set(); out = []
            for p in parts:
                p = re.sub(r"\s{2,}", " ", p)
                if p and p not in seen:
                    seen.add(p); out.append(p)
            return ", ".join(out) if out else "—"

        def _extract_field(text: str, field_variants: list[str]) -> str:
            for field in field_variants:
                m = re.search(
                    rf"\|\s*{re.escape(field)}\s*=\s*(.+?)(?:\n\||\n$)",
                    text, flags=re.IGNORECASE | re.DOTALL
                )
                if m:
                    return _clean_members_field(m.group(1).strip())
            return "—"

        # Campos comuns na infobox EN/PT
        current = _extract_field(wikitext, ["current_members", "integrantes", "membros"])
        #former  = _extract_field(wikitext, ["past_members", "ex-integrantes", "ex-membros", "former_members"])
        former  = _extract_field(wikitext, ["ex-integrantes", "former_members"])
        return {
            "current_members": current or "—",
            "former_members": former or "—",
        }
    except Exception:
        return {"current_members": "—", "former_members": "—"}
