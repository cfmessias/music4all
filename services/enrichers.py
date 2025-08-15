# services/enrichers.py
import os
import requests
from urllib.parse import quote

# ---- MusicBrainz ----
def musicbrainz_lifespan(name: str) -> dict:
    out = {"begin": None, "end": None, "type": None}
    try:
        r = requests.get(
            "https://musicbrainz.org/ws/2/artist/",
            params={"query": f"artist:\"{name}\"", "fmt": "json", "limit": 1},
            headers={"User-Agent": "SpotifyArtistSearch/1.0 (contact@example.com)"},
            timeout=8,
        )
        if r.status_code == 200 and r.json().get("artists"):
            a0 = r.json()["artists"][0]
            life = a0.get("life-span", {})
            out["begin"] = life.get("begin")
            out["end"] = life.get("end")
            out["type"] = a0.get("type")
    except Exception:
        pass
    return out

# ---- Wikidata ----
def wikidata_search_qid(name: str) -> str | None:
    try:
        r = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "format": "json",
                "type": "item",
                "limit": 1,
            },
            timeout=8,
        )
        if r.status_code == 200:
            j = r.json()
            if j.get("search"):
                return j["search"][0]["id"]
    except Exception:
        pass
    return None

def wikidata_fetch_entity(qid: str) -> dict | None:
    try:
        r = requests.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def wikidata_band_facts(entity: dict) -> dict:
    facts = {"inception": None, "dissolved": None, "members_count": None, "country": None}
    try:
        ent = next(iter(entity.get("entities", {}).values()))
        claims = ent.get("claims", {})
        def _time(prop):
            v = claims.get(prop, [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value", {})
            t = v.get("time")
            return t[1:5] if t else None
        facts["inception"] = _time("P571")
        facts["dissolved"] = _time("P576")
        for prop in ("P495", "P17"):
            if prop in claims:
                facts["country"] = claims[prop][0]["mainsnak"]["datavalue"]["value"].get("id")
                break
        if "P527" in claims:
            facts["members_count"] = len(claims.get("P527", []))
    except Exception:
        pass
    return facts

# ---- Wikipedia ----
def wikipedia_search_title(name: str) -> str | None:
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": name, "format": "json", "srlimit": 1},
            timeout=8,
        )
        if r.status_code == 200 and r.json().get("query", {}).get("search"):
            return r.json()["query"]["search"][0]["title"]
    except Exception:
        pass
    return None

def wikipedia_summary(title: str) -> dict:
    out = {"title": title, "url": None, "extract": None}
    try:
        r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}", timeout=8)
        if r.status_code == 200:
            j = r.json()
            out["extract"] = j.get("extract")
            out["url"] = j.get("content_urls", {}).get("desktop", {}).get("page")
    except Exception:
        pass
    return out

def wikipedia_enrich(name: str) -> dict:
    title = wikipedia_search_title(name)
    if not title:
        return {}
    return wikipedia_summary(title)

# ---- Discogs ----
DISCOGS_USER_AGENT = os.getenv("DISCOGS_USER_AGENT", "RepositórioRock/1.0 +https://cfmessias.pt")
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN", "")

def discogs_headers():
    h = {"User-Agent": DISCOGS_USER_AGENT}
    if DISCOGS_TOKEN:
        h["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"
    return h

def discogs_search_artist(name: str) -> int | None:
    try:
        r = requests.get(
            "https://api.discogs.com/database/search",
            params={"q": name, "type": "artist", "per_page": 5},
            headers=discogs_headers(),
            timeout=8,
        )
        if r.status_code == 200:
            res = r.json().get("results", [])
            for x in res:
                if x.get("type") == "artist" and x.get("id"):
                    return x["id"]
    except Exception:
        pass
    return None

def discogs_artist_details(artist_id: int) -> dict:
    try:
        r = requests.get(f"https://api.discogs.com/artists/{artist_id}", headers=discogs_headers(), timeout=8)
        if r.status_code == 200:
            j = r.json()
            return {"profile": j.get("profile"), "members": [m.get("name") for m in j.get("members", []) if m.get("name")]}
    except Exception:
        pass
    return {}

def discogs_enrich(name: str) -> dict:
    aid = discogs_search_artist(name)
    if not aid:
        return {}
    return discogs_artist_details(aid)

# ---- Aggregator ----
def enrich_from_external(name: str) -> dict:
    mb = musicbrainz_lifespan(name)
    qid = wikidata_search_qid(name)
    wd = wikidata_band_facts(wikidata_fetch_entity(qid)) if qid else {}
    wp = wikipedia_enrich(name)
    dg = discogs_enrich(name)
    return {"musicbrainz": mb, "wikidata": wd, "wikipedia": wp, "discogs": dg}
