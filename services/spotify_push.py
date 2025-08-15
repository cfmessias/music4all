from __future__ import annotations
from typing import List, Dict, Tuple
import time
import spotipy

def find_or_create_playlist(sp: spotipy.Spotify, user_id: str, name: str, public: bool=True, description: str="") -> Dict:
    """Procura playlist por nome exato; se não existir, cria."""
    results = sp.current_user_playlists(limit=50)
    while results:
        for pl in results.get("items", []):
            if (pl.get("name") or "").strip().casefold() == (name or "").strip().casefold():
                return pl
        next_url = results.get("next")
        if not next_url:
            break
        results = sp.next(results)
    return sp.user_playlist_create(user=user_id, name=name, public=public, description=description)

def _mk_queries(title: str, artist: str):
    """Gera algumas queries para melhorar o matching de faixas."""
    t = (title or "").strip()
    a = (artist or "").strip()
    return [
        f'track:"{t}" artist:"{a}"',
        f'{t} {a}',
        f'"{t}" {a}',
    ]

def _best_track_from_search(sp: spotipy.Spotify, q: str):
    res = sp.search(q=q, type="track", limit=3)
    items = (res.get("tracks") or {}).get("items") or []
    if not items:
        return None
    return items[0]

def resolve_track_uri(sp: spotipy.Spotify, title: str, artist: str) -> str | None:
    for q in _mk_queries(title, artist):
        tr = _best_track_from_search(sp, q)
        if not tr:
            continue
        name = (tr.get("name") or "").strip().casefold()
        arts = ", ".join([a.get("name","") for a in (tr.get("artists") or [])]).strip().casefold()
        if (title or "").strip().casefold() in name and (artist or "").strip().casefold() in arts:
            return tr.get("uri")
        # fallback (melhor esforço)
        return tr.get("uri")
    return None

def _chunked(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i:i+n] for i in range(0, len(seq), n)]

def push_playlist_from_rows(sp: spotipy.Spotify, rows: List[Dict], playlist_name: str, public: bool=True) -> Tuple[str, int, int]:
    """
    rows: lista de dicts com pelo menos 'Title' e 'Artist'
    Retorna: (playlist_id, matched, missing)
    """
    user_id = sp.me()["id"]
    pl = find_or_create_playlist(sp, user_id, playlist_name, public=public)
    pl_id = pl["id"]

    # normalizar
    norm_rows = []
    for r in rows:
        keys = {str(k).lower(): v for k, v in r.items()}
        title = keys.get("title") or keys.get("track") or keys.get("song") or r.get("Title") or r.get("Track")
        artist = keys.get("artist") or keys.get("artists") or r.get("Artist") or r.get("Artists")
        if title and artist:
            norm_rows.append({"Title": str(title), "Artist": str(artist)})

    uris = []
    misses = 0
    for it in norm_rows:
        uri = resolve_track_uri(sp, it["Title"], it["Artist"])
        if uri:
            uris.append(uri)
        else:
            misses += 1
        if (len(uris) % 20) == 0:
            time.sleep(0.2)  # respeitar API rate-limits

    for batch in _chunked(uris, 100):
        sp.playlist_add_items(pl_id, batch)

    return pl_id, len(uris), misses
