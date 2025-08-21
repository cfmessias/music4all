from typing import Dict, Any, List, Optional, Tuple
from .client import SpotifyClient
from .mappers import map_tracks_page, map_audio_features
from .models import Track, AudioFeatures

BASE = "https://api.spotify.com/v1"

def search_tracks(client: SpotifyClient, q: str, limit: int, offset: int, market: str="PT") -> Tuple[List[Track], int]:
    data = client.get(f"{BASE}/search", params={
        "q": q, "type": "track", "limit": limit, "offset": offset, "market": market
    })
    page = data.get("tracks", {})
    items = map_tracks_page(page)
    return items, int(page.get("total", 0))

def get_audio_features(client: SpotifyClient, ids: List[str]) -> Dict[str, AudioFeatures]:
    if not ids:
        return {}
    data = client.get(f"{BASE}/audio-features", params={"ids": ",".join(ids)})
    feats = {}
    for obj in data.get("audio_features", []):
        if obj and obj.get("id"):
            feats[obj["id"]] = map_audio_features(obj)
    return feats

def recommendations(client: SpotifyClient, seed_tracks: List[str], limit: int = 20, market: str="PT") -> List[Track]:
    data = client.get(f"{BASE}/recommendations", params={
        "seed_tracks": ",".join(seed_tracks[:5]), "limit": limit, "market": market
    })
    from .mappers import map_track
    return [map_track(x) for x in data.get("tracks", [])]
