# cinema/ui/search.py
from __future__ import annotations
import pandas as pd
from cinema.filters import apply_filters
from cinema.providers.tmdb import tmdb_search_movies_advanced, tmdb_search_series_advanced
from cinema.providers.spotify import search_soundtrack_albums

def run_search(section: str, df_local: pd.DataFrame, *,
               title: str, genre: str, year_txt: str, min_rating: float,
               author_key: str, author_val: str, streaming_sel: str | None,
               online: bool) -> tuple[pd.DataFrame, list[dict]]:
    filters = {
        "title": title,
        "genre": genre,
        "year": year_txt,
        "min_rating": min_rating,
        "streaming": streaming_sel,
        author_key: author_val,
        #"watched": watched_sel if section == "Movies" else None,
    }
    local_out = apply_filters(section, df_local, filters)

    remote: list[dict] = []
    if online:
        if section == "Movies":
            remote = tmdb_search_movies_advanced(
                title=title,
                genre_name=(genre if genre != "All" else ""),
                year_txt=year_txt,
                director_name=author_val,
            )
        elif section == "Series":
            remote = tmdb_search_series_advanced(
                title=title,
                genre_name=(genre if genre != "All" else ""),
                year_txt=year_txt,
                creator_name=author_val,
            )
        else:  # Soundtracks page
            remote = search_soundtrack_albums(
                title=(title or ""), year_txt=year_txt, artist=(author_val or ""), limit=25
            )

    # Apply streaming filter to remote results if possible
    try:
        if streaming_sel in ("Yes", "No") and isinstance(remote, list):
            want = (streaming_sel == "Yes")
            def _has_streaming(it):
                v = it.get("streaming")
                if v is None:
                    v = it.get("has_streaming")
                if v is None:
                    prov = it.get("watch_providers") or it.get("providers") or {}
                    v = bool(prov)
                return bool(v)
            remote = [r for r in remote if _has_streaming(r) == want]
    except Exception:
        pass
    return local_out, remote

