# providers/__init__.py

from .tmdb import tmdb_search_movies_advanced, tmdb_search_series_advanced
from .spotify import spotify_soundtrack_search

__all__ = [
    "tmdb_search_movies_advanced",
    "tmdb_search_series_advanced",
    "spotify_soundtrack_search",
]
