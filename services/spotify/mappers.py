from typing import Dict, Any, List
from .models import Artist, Album, Track, AudioFeatures

def map_artist(a: Dict[str, Any]) -> Artist:
    return Artist(id=a["id"], name=a["name"], url=a["external_urls"]["spotify"])

def map_album(a: Dict[str, Any]) -> Album:
    img = a.get("images", [])
    return Album(
        id=a["id"], name=a["name"],
        release_date=a.get("release_date"),
        image_url=(img[0]["url"] if img else None),
        url=a["external_urls"]["spotify"]
    )

def map_track(t: Dict[str, Any]) -> Track:
    return Track(
        id=t["id"], name=t["name"],
        artists=[map_artist(x) for x in t.get("artists", [])],
        album=map_album(t["album"]),
        duration_ms=t.get("duration_ms", 0),
        popularity=t.get("popularity", 0),
        explicit=t.get("explicit", False),
        url=t["external_urls"]["spotify"],
        preview_url=t.get("preview_url")
    )

def map_tracks_page(data: Dict[str, Any]) -> List[Track]:
    return [map_track(x) for x in data.get("items", [])]

def map_audio_features(d: Dict[str, Any]) -> AudioFeatures:
    return AudioFeatures(
        id=d["id"],
        tempo=d.get("tempo"),
        danceability=d.get("danceability"),
        energy=d.get("energy"),
        valence=d.get("valence"),
        acousticness=d.get("acousticness"),
        instrumentalness=d.get("instrumentalness"),
        liveness=d.get("liveness"),
        speechiness=d.get("speechiness"),
    )
