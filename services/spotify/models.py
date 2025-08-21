from dataclasses import dataclass
from typing import List, Optional, Dict

@dataclass(frozen=True)
class Artist:
    id: str
    name: str
    url: str

@dataclass(frozen=True)
class Album:
    id: str
    name: str
    release_date: Optional[str]
    image_url: Optional[str]
    url: str

@dataclass(frozen=True)
class Track:
    id: str
    name: str
    artists: List[Artist]
    album: Album
    duration_ms: int
    popularity: int
    explicit: bool
    url: str
    preview_url: Optional[str]

@dataclass(frozen=True)
class AudioFeatures:
    id: str
    tempo: Optional[float]
    danceability: Optional[float]
    energy: Optional[float]
    valence: Optional[float]
    acousticness: Optional[float]
    instrumentalness: Optional[float]
    liveness: Optional[float]
    speechiness: Optional[float]

@dataclass(frozen=True)
class Page:
    items: List[Track]
    total: int
    limit: int
    offset: int
    next_url: Optional[str]
    prev_url: Optional[str]
