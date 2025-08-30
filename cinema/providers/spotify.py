# cinema/providers/spotify.py
import os
import requests
import streamlit as st
from ..filters import parse_year_filter

# 1) Tenta usar os TEUS serviços (services/spotify)
_spfy_client = None
_spfy_search_fn = None
_spfy_token_fn = None

try:
    # Tenta padrões comuns do teu projeto
    # a) função direta de procura
    from services.spotify.search import search_albums as _svc_search_albums  # ex.: retorna lista de álbuns
    _spfy_search_fn = _svc_search_albums
except Exception:
    pass

if _spfy_search_fn is None:
    try:
        # b) serviço com método .search_albums(...)
        from services.spotify.core import SpotifyService  # ajusta se o teu serviço tiver outro nome
        _spfy_client = SpotifyService()
        _spfy_search_fn = _spfy_client.search_albums
    except Exception:
        pass

if _spfy_token_fn is None:
    try:
        # caso o teu core exponha get_spotify_token(client_id, client_secret)
        from services.spotify.core import get_spotify_token as _svc_get_token
        _spfy_token_fn = _svc_get_token
    except Exception:
        pass

# 2) Fallback para API se os serviços não estiverem carregáveis
def _fallback_token() -> str:
    cid = ""
    csec = ""
    try:
        cid = st.secrets.get("SPOTIFY_CLIENT_ID", "") or st.secrets.get("client_id", "")
        csec = st.secrets.get("SPOTIFY_CLIENT_SECRET", "") or st.secrets.get("client_secret", "")
    except Exception:
        pass
    cid = cid or os.getenv("SPOTIFY_CLIENT_ID", "")
    csec = csec or os.getenv("SPOTIFY_CLIENT_SECRET", "")

    if _spfy_token_fn:
        try:
            tok = _spfy_token_fn(cid, csec)
            if isinstance(tok, dict):
                tok = tok.get("access_token") or tok.get("token")
            return tok or ""
        except Exception as e:
            st.warning(f"Spotify service token error: {e}")

    if not cid or not csec:
        return ""
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(cid, csec),
        timeout=15,
    )
    if r.ok:
        return (r.json() or {}).get("access_token", "")
    try:
        st.warning(f"Spotify token HTTP {r.status_code}: {r.json()}")
    except Exception:
        st.warning(f"Spotify token HTTP {r.status_code}: {r.text}")
    return ""

def _fallback_search_albums(query: str, limit: int = 10, market: str = "PT") -> list[dict]:
    token = _fallback_token()
    if not token:
        return []
    r = requests.get(
        "https://api.spotify.com/v1/search",
        params={"q": query, "type": "album", "limit": limit, "market": market},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if not r.ok:
        try:
            st.warning(f"Spotify search HTTP {r.status_code}: {r.json()}")
        except Exception:
            st.warning(f"Spotify search HTTP {r.status_code}: {r.text}")
        return []
    data = r.json() or {}
    return (data.get("albums") or {}).get("items") or []

def _looks_like_ost(name: str) -> bool:
    s = (name or "").lower()
    return any(k in s for k in ["soundtrack", "original score", "motion picture", "ost", "score"])

def _album_fields(item: dict) -> dict:
    """Normaliza campos essenciais de um álbum Spotify (nome, url, uri, ano, artista)."""
    name = item.get("name", "")
    url = (item.get("external_urls", {}) or {}).get("spotify", "") or item.get("url", "")
    uri = item.get("uri", "") or item.get("spotify_uri", "")
    rel = (item.get("release_date") or "")[:4]
    year = int(rel) if rel.isdigit() else None
    artist_name = ", ".join([a.get("name","") for a in item.get("artists", []) if a.get("name")]) or item.get("artist","")
    return {"title": name, "url": url, "uri": uri, "year": year, "artist": artist_name}

def search_soundtrack_albums(title: str, year_txt: str | None = None, artist: str | None = None, limit: int = 10) -> list[dict]:
    """
    Usa os TEUS serviços se existirem; senão faz fallback à Web API.
    Query força intenção de OST, e filtra por ano (exato ou intervalo).
    """
    base_ost = '(soundtrack OR "original score" OR "motion picture" OR ost OR score)'
    t = (title or "").strip()
    a = (artist or "").strip()
    # queries do mais forte ao mais lato
    queries = []
    if t and a:
        queries = [f'album:"{t}" artist:"{a}" {base_ost}', f'album:"{t}" {base_ost}', f'artist:"{a}" {base_ost}', base_ost]
    elif t:
        queries = [f'album:"{t}" {base_ost}', f'{t} {base_ost}', base_ost]
    elif a:
        queries = [f'artist:"{a}" {base_ost}', base_ost]
    else:
        queries = [base_ost, "soundtrack"]

    mode, val = parse_year_filter(year_txt or "")
    def _year_ok(y):
        if mode == "none":  return True
        if mode == "exact": return y == val
        a_, b_ = val;       return (y or 0) >= a_ and (y or 0) <= b_

    results = []
    for q in queries:
        items = []
        if _spfy_search_fn:
            try:
                # serviços teus — assumimos assinatura search_albums(query, limit=...)
                items = _spfy_search_fn(q, limit=limit) or []
            except TypeError:
                # alguns serviços podem usar (query) sem limit
                items = _spfy_search_fn(q) or []
            except Exception as e:
                st.warning(f"Spotify service search error: {e}")
                items = []
        else:
            items = _fallback_search_albums(q, limit=limit, market=os.getenv("SPOTIFY_MARKET", "PT") or "PT")

        if not items:
            continue

        batch = []
        for it in items:
            if not _looks_like_ost(it.get("name","")):
                continue
            fld = _album_fields(it)
            if not _year_ok(fld["year"]):
                continue
            batch.append(fld)
        results.extend(batch)
        if results:
            break

    return results

def pick_best_soundtrack(title: str, year_txt: str | None = None, artist: str | None = None) -> dict | None:
    """Devolve o melhor matching: primeiro resultado da pesquisa normalizada."""
    albs = search_soundtrack_albums(title=title, year_txt=year_txt, artist=artist, limit=10)
    return albs[0] if albs else None
