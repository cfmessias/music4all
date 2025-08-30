# cinema/providers/tmdb.py
from __future__ import annotations

import os
import requests
import streamlit as st
from ..filters import parse_year_filter

TMDB_BASE = "https://api.themoviedb.org/3"

# ---------- Auth & GET ----------

def _tmdb_auth():
    bearer = ""
    try:
        bearer = st.secrets.get("TMDB_BEARER", "")
    except Exception:
        pass

    api_key = ""
    try:
        api_key = st.secrets.get("TMDB_API_KEY", "")
    except Exception:
        pass
    if not api_key:
        api_key = os.getenv("TMDB_API_KEY", "")

    if bearer:
        return ({"Authorization": f"Bearer {bearer}"}, {})
    elif api_key:
        return ({}, {"api_key": api_key})
    else:
        return ({}, {})

def _tmdb_get(path: str, params: dict | None = None) -> dict:
    hdrs, base = _tmdb_auth()
    q = dict(base)
    if params:
        q.update(params)
    r = requests.get(f"{TMDB_BASE}{path}", headers=hdrs, params=q, timeout=20)
    r.raise_for_status()
    return r.json()

# ---------- Utilities ----------

@st.cache_data(ttl=86400, show_spinner=False)
def _tmdb_genres(kind: str) -> dict[str, int]:
    data = _tmdb_get(f"/genre/{'movie' if kind=='movie' else 'tv'}/list", {"language": "en-US"})
    return {(g.get("name", "") or "").casefold(): int(g["id"]) for g in data.get("genres", [])}

def _get_country_code() -> str:
    try:
        cc = st.secrets.get("COUNTRY_CODE", "PT")
    except Exception:
        cc = os.getenv("COUNTRY_CODE", "PT")
    return (cc or "PT").upper()

@st.cache_data(ttl=86400, show_spinner=False)
def _tmdb_watch_providers(kind: str, tmdb_id: int, country: str | None = None) -> str:
    """Return 'MAX; Netflix; Prime Video' where available in flatrate."""
    country = (country or _get_country_code()).upper()
    try:
        data = _tmdb_get(f"/{kind}/{tmdb_id}/watch/providers")
    except Exception:
        return ""
    results = (data or {}).get("results", {})
    c = results.get(country) or {}
    flatrate = c.get("flatrate") or []
    names = {(p.get("provider_name") or "").strip() for p in flatrate if p.get("provider_name")}

    out = []
    if any(n in names for n in ("Max", "HBO Max", "HBO GO", "HBO")):
        out.append("MAX")
    if "Netflix" in names:
        out.append("Netflix")
    if any(n in names for n in ("Amazon Prime Video", "Prime Video")):
        out.append("Prime Video")
    return "; ".join(out)

def _year_mode(year_txt: str | None):
    mode, val = parse_year_filter(year_txt or "")
    if mode == "exact":
        return ("exact", val, None, None)
    if mode == "range":
        return ("range", None, val[0], val[1])
    return ("none", None, None, None)

# ---------- People (director) ----------

@st.cache_data(ttl=86400, show_spinner=False)
def _tmdb_find_person_id(name: str, department: str | None = None) -> int | None:
    if not (name or "").strip():
        return None
    data = _tmdb_get("/search/person", {"query": name.strip(), "include_adult": "false"})
    results = data.get("results", []) or []
    if department:
        results = [r for r in results if str(r.get("known_for_department", "")).lower() == department.lower()]
    return int(results[0]["id"]) if results else None

def _tmdb_person_movie_directing(person_id: int) -> list[int]:
    data = _tmdb_get(f"/person/{person_id}/movie_credits")
    crew = data.get("crew", []) or []
    return [int(c["id"]) for c in crew if str(c.get("job", "")).lower() == "director"]

# ---------- Movies ----------

def tmdb_search_movies_advanced(
    title: str,
    genre_name: str | None,
    year_txt: str | None,
    director_name: str | None,
) -> list[dict]:
    gmap = _tmdb_genres("movie")
    gid = gmap.get((genre_name or "").casefold())
    mode, year_exact, year_a, year_b = _year_mode(year_txt)

    base = []

    if (director_name or "").strip() and not (title or "").strip():
        pid = _tmdb_find_person_id(director_name, department="Directing")
        if pid:
            ids = _tmdb_person_movie_directing(pid)
            for mid in ids[:50]:
                det = _tmdb_get(f"/movie/{mid}", {"append_to_response": "credits"})
                if gid and gid not in [g.get("id") for g in (det.get("genres") or [])]:
                    continue
                y = (det.get("release_date") or "")[:4]
                y = int(y) if y.isdigit() else None
                if mode == "exact" and y != year_exact:
                    continue
                if mode == "range" and not (y and year_a <= y <= year_b):
                    continue
                base.append({"id": mid, "_detail": det})
    elif (title or "").strip():
        params = {"query": title.strip(), "include_adult": "false"}
        if mode == "exact":
            params["year"] = int(year_exact)
        data = _tmdb_get("/search/movie", params)
        base = data.get("results", [])[:25]
    else:
        params = {"include_adult": "false", "sort_by": "popularity.desc"}
        if gid:
            params["with_genres"] = gid
        if mode == "exact":
            params["primary_release_year"] = int(year_exact)
        elif mode == "range":
            params["primary_release_date.gte"] = f"{int(year_a)}-01-01"
            params["primary_release_date.lte"] = f"{int(year_b)}-12-31"
        data = _tmdb_get("/discover/movie", params)
        base = data.get("results", [])[:25]

    if gid and base and "_detail" not in base[0]:
        base = [it for it in base if gid in (it.get("genre_ids") or [])]
    if mode == "range" and (title or "").strip() and base and "_detail" not in base[0]:
        def _y(it):
            y = (it.get("release_date") or "")[:4]
            return int(y) if y.isdigit() else None
        base = [it for it in base if (lambda y: y is not None and year_a <= y <= year_b)(_y(it))]

    out = []
    for it in base:
        if "_detail" in it:
            det = it["_detail"]
            mid = int(det.get("id") or it.get("id"))
        else:
            mid = it.get("id")
            if not mid:
                continue
            det = _tmdb_get(f"/movie/{mid}", {"append_to_response": "credits"})

        director = ""
        for c in (det.get("credits", {}) or {}).get("crew", []) or []:
            if str(c.get("job")).lower() == "director":
                director = c.get("name") or ""
                break

        if (director_name or "").strip():
            if director.lower().find(director_name.strip().lower()) == -1:
                continue

        genres_list = [g.get("name", "") for g in (det.get("genres") or []) if g.get("name")]
        genre_f = genre_name if (genre_name and any(g.lower() == genre_name.lower() for g in genres_list)) else (genres_list[0] if genres_list else "")
        genres_join = ", ".join(genres_list)

        title_f = det.get("title") or it.get("title") or ""
        release = (det.get("release_date") or it.get("release_date") or "")[:4]
        year_f = int(release) if release.isdigit() else None
        rating_f = float(det.get("vote_average")) if det.get("vote_average") is not None else None
        notes_f = det.get("overview") or ""

        streaming = _tmdb_watch_providers("movie", mid)

        out.append({
            "title": title_f,
            "director": director,
            "year": year_f,
            "genre": genre_f,
            "genres": genres_join,
            "streaming": streaming,
            "rating": rating_f,
            "notes": notes_f,
            "watched": False,
            "watched_date": "",
        })
    return out

# ---------- Series (linha por temporada) ----------

def tmdb_search_series_advanced(
    title: str,
    genre_name: str | None,
    year_txt: str | None,
    creator_name: str | None,
) -> list[dict]:
    """
    Devolve uma linha por temporada:
    {title, creator, season, year_start, year_end, genre, genres, streaming, rating, notes}
    """
    gmap = _tmdb_genres("tv")
    gid = gmap.get((genre_name or "").casefold())
    mode, year_exact, year_a, year_b = _year_mode(year_txt)

    # Base de séries
    if (title or "").strip():
        params = {"query": title.strip(), "include_adult": "false"}
        if mode == "exact":
            params["first_air_date_year"] = int(year_exact)
        data = _tmdb_get("/search/tv", params)
        base = data.get("results", [])[:25]
    else:
        params = {"include_adult": "false", "sort_by": "popularity.desc"}
        if gid:
            params["with_genres"] = gid
        if mode == "exact":
            params["first_air_date_year"] = int(year_exact)
        elif mode == "range":
            params["first_air_date.gte"] = f"{int(year_a)}-01-01"
            params["first_air_date.lte"] = f"{int(year_b)}-12-31"
        data = _tmdb_get("/discover/tv", params)
        base = data.get("results", [])[:25]

    # Filtrar por género/ano quando vieram de search
    if gid and base:
        base = [it for it in base if gid in (it.get("genre_ids") or [])]
    if mode == "range" and (title or "").strip() and base:
        def _y(it):
            y = (it.get("first_air_date") or "")[:4]
            return int(y) if y.isdigit() else None
        base = [it for it in base if (lambda y: y is not None and year_a <= y <= year_b)(_y(it))]

    out = []
    for it in base:
        tid = it.get("id")
        if not tid:
            continue
        det = _tmdb_get(f"/tv/{tid}")  # detalhes da série (tem seasons)

        # creators
        creators = ", ".join([c.get("name", "") for c in det.get("created_by") or [] if c.get("name")]) or ""
        if (creator_name or "").strip():
            if creators.lower().find(creator_name.strip().lower()) == -1:
                continue

        # géneros
        genres_list = [g.get("name", "") for g in (det.get("genres") or []) if g.get("name")]
        genre_f = genre_name if (genre_name and any(g.lower() == genre_name.lower() for g in genres_list)) else (genres_list[0] if genres_list else "")
        genres_join = ", ".join(genres_list)

        # onde ver
        streaming = _tmdb_watch_providers("tv", tid)

        # rating/overview da série
        rating_f = float(det.get("vote_average")) if det.get("vote_average") is not None else None
        series_overview = det.get("overview") or ""

        # seasons → uma linha por temporada (ignorar specials season 0)
        seasons = det.get("seasons") or []
        for s in seasons:
            sn = s.get("season_number")
            if sn in (None, 0):
                continue
            s_name = s.get("name") or f"Season {sn}"
            s_over = s.get("overview") or ""
            air = (s.get("air_date") or "")[:4]
            ys = int(air) if air.isdigit() else None

            # aplicar filtro de ano ao ano da temporada
            if mode == "exact" and ys is not None and ys != year_exact:
                continue
            if mode == "range" and ys is not None and not (year_a <= ys <= year_b):
                continue

            notes_f = f"{series_overview}".strip()
            if s_over:
                notes_f = (notes_f + (" — " if notes_f else "") + f"{s_name}: {s_over}").strip()

            out.append({
                "title": det.get("name") or it.get("name") or "",
                "creator": creators,
                "season": int(sn),
                "year_start": ys,
                "year_end": "",
                "genre": genre_f,
                "genres": genres_join,
                "streaming": streaming,
                "rating": rating_f,
                "notes": notes_f,
            })

    return out
