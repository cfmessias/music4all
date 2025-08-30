# cinema_page.py — CSV-only + Online search (TMDb/OMDb + iTunes)
from __future__ import annotations

from pathlib import Path
import os
import requests
import pandas as pd
import streamlit as st

# ---------------- Paths/Config ----------------
BASE_DIR = Path(__file__).resolve().parent
SEP = ";"

GENRES_CSV = BASE_DIR / "generos_cinema_selectbox.csv"  # headers PT (Genero;Subgenero) ou EN (Genre;Subgenre)

FILES = {
    "Movies":      BASE_DIR / "movies.csv",
    "Series":      BASE_DIR / "series.csv",
    "Soundtracks": BASE_DIR / "soundtracks.csv",
}
SCHEMA = {
    "Movies":      ["id","title","director","year","genre","subgenre","rating","notes","watched","watched_date"],
    "Series":      ["id","title","creator","year_start","year_end","genre","subgenre","rating","notes"],
    "Soundtracks": ["id","title","artist","year","genre","subgenre","rating","notes","related_movie_id","related_series_id"],
}

TMDB_BASE = "https://api.themoviedb.org/3"
OMDB_BASE = "https://www.omdbapi.com/"
ITUNES_BASE = "https://itunes.apple.com/search"

# ---------------- Utilities (local CSVs) ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_genres():
    # Ler com BOM-safe e normalizar cabeçalhos
    try:
        df = pd.read_csv(GENRES_CSV, sep=SEP, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(GENRES_CSV, sep=SEP, encoding="utf-8")
    df = df.rename(columns=lambda c: str(c).replace("\ufeff", "").strip())

    # aceitar EN também
    if {"Genre","Subgenre"}.issubset(df.columns):
        df = df.rename(columns={"Genre":"Genero","Subgenre":"Subgenero"})

    df = df[["Genero","Subgenero"]].dropna().drop_duplicates()
    df = df.sort_values(["Genero","Subgenero"])

    generos = ["All"] + df["Genero"].unique().tolist()
    sub_by_gen = {g: ["All"] + df.loc[df["Genero"] == g, "Subgenero"].unique().tolist()
                  for g in df["Genero"].unique()}
    return generos, sub_by_gen, str(GENRES_CSV)

def ensure_csv(path: Path, columns: list[str]) -> None:
    if not path.exists():
        pd.DataFrame(columns=columns).to_csv(path, sep=SEP, index=False, encoding="utf-8")

def _ensure_schema(df: pd.DataFrame, section: str) -> pd.DataFrame:
    for c in SCHEMA[section]:
        if c not in df.columns:
            if section == "Movies" and c == "watched":
                df[c] = False
            elif section == "Movies" and c == "watched_date":
                df[c] = ""
            else:
                df[c] = ""
    return df[SCHEMA[section]]

def load_table(section: str) -> pd.DataFrame:
    path = FILES[section]
    ensure_csv(path, SCHEMA[section])
    df = pd.read_csv(path, sep=SEP, encoding="utf-8")
    df = _ensure_schema(df, section)
    for c in ("year","year_start","year_end","rating","related_movie_id","related_series_id"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if section == "Movies":
        df["watched"] = df["watched"].astype(bool, copy=False)
        df["watched_date"] = df["watched_date"].astype(str, copy=False)
    return df

def save_table(section: str, df: pd.DataFrame) -> None:
    path = FILES[section]
    df.to_csv(path, sep=SEP, index=False, encoding="utf-8")

def save_row(section: str, row: dict) -> int:
    df = load_table(section)
    next_id = int(df["id"].max() + 1) if not df.empty else 1
    row["id"] = next_id
    for c in SCHEMA[section]:
        row.setdefault(c, "")
    if section == "Movies":
        row["watched"] = bool(row.get("watched", False))
        row["watched_date"] = str(row.get("watched_date", "") or "")
    df = pd.concat([df, pd.DataFrame([row])[SCHEMA[section]]], ignore_index=True)
    save_table(section, df)
    return next_id

def parse_year_filter(txt: str):
    """'', '1995' ou '1990-1999' -> ('none'|'exact'|'range', value)."""
    if not txt or not str(txt).strip():
        return ("none", None)
    s = str(txt).strip()
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            a, b = int(a.strip()), int(b.strip())
            if a > b: a, b = b, a
            return ("range", (a, b))
        except Exception:
            return ("none", None)
    try:
        return ("exact", int(s))
    except Exception:
        return ("none", None)

def apply_filters(section: str, df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)

    def contains(col, val):
        return df[col].astype(str).str.contains(str(val), case=False, na=False)

    if filters.get("title"):
        m &= contains("title", filters["title"])
    if section == "Movies" and filters.get("director"):
        m &= contains("director", filters["director"])
    if section == "Series" and filters.get("creator"):
        m &= contains("creator", filters["creator"])
    if section == "Soundtracks" and filters.get("artist"):
        m &= contains("artist", filters["artist"])

    gen = filters.get("genre")
    if gen and gen != "All":
        m &= df["genre"].fillna("").astype(str).str.strip().str.casefold().eq(str(gen).strip().casefold())

        # Movies: filter by watched Y/N
    if section == "Movies":
        w = filters.get("watched")
        if w in ("Yes", "No"):
            m &= df["watched"].fillna(False) == (w == "Yes")

    mode, val = parse_year_filter(filters.get("year", ""))
    if mode != "none":
        col = "year" if "year" in df.columns else "year_start"
        coln = pd.to_numeric(df[col], errors="coerce")
        if mode == "exact":
            m &= (coln == val)
        else:
            a, b = val
            m &= coln.between(a, b, inclusive="both")

    mr = filters.get("min_rating")
    if mr is not None and mr > 0:
        m &= (pd.to_numeric(df["rating"], errors="coerce") >= mr)

    out = df[m].copy()
    if "rating" in out.columns:
        out = out.sort_values(by=["rating","title"], ascending=[False,True], na_position="last")
    else:
        out = out.sort_values(by=["title"], ascending=True)
    return out

# ---------------- Online search (TMDb / OMDb / iTunes) ----------------
def _tmdb_auth():
    """Prefer v4 Bearer em st.secrets; fallback para v3 api_key/env var."""
    bearer = ""
    try: bearer = st.secrets.get("TMDB_BEARER", "")
    except Exception: pass
    api_key = ""
    try: api_key = st.secrets.get("TMDB_API_KEY", "")
    except Exception: pass
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
    p = dict(base)
    if params: p.update(params)
    r = requests.get(f"{TMDB_BASE}{path}", headers=hdrs, params=p, timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=86400, show_spinner=False)
def _tmdb_genres(kind: str) -> dict[str, int]:
    data = _tmdb_get(f"/genre/{'movie' if kind=='movie' else 'tv'}/list", {"language":"en-US"})
    return { (g.get("name","")).casefold(): int(g["id"]) for g in data.get("genres", []) }

def _year_mode(year_txt: str | None):
    mode, val = parse_year_filter(year_txt or "")
    if mode == "exact":  return ("exact", val, None, None)
    if mode == "range":  return ("range", None, val[0], val[1])
    return ("none", None, None, None)

def tmdb_search_movies_advanced(title: str, genre_name: str | None, year_txt: str | None, director_name: str | None) -> list[dict]:
    gmap = _tmdb_genres("movie")
    gid = gmap.get((genre_name or "").casefold())
    mode, year_exact, year_a, year_b = _year_mode(year_txt)

    # base fetch
    if (title or "").strip():
        params = {"query": title.strip(), "include_adult":"false"}
        if mode == "exact": params["year"] = int(year_exact)
        data = _tmdb_get("/search/movie", params); base = data.get("results", [])[:25]
    else:
        params = {"include_adult":"false","sort_by":"popularity.desc"}
        if gid: params["with_genres"] = gid
        if mode == "exact":
            params["primary_release_year"] = int(year_exact)
        elif mode == "range":
            params["primary_release_date.gte"] = f"{int(year_a)}-01-01"
            params["primary_release_date.lte"] = f"{int(year_b)}-12-31"
        data = _tmdb_get("/discover/movie", params); base = data.get("results", [])[:25]

    if gid:
        base = [it for it in base if gid in (it.get("genre_ids") or [])]
    if mode == "range" and (title or "").strip():
        def _y(it): 
            y = (it.get("release_date") or "")[:4]; 
            return int(y) if y.isdigit() else None
        base = [it for it in base if (lambda y: y is not None and year_a <= y <= year_b)(_y(it))]

    out = []
    for it in base:
        mid = it.get("id"); 
        if not mid: continue
        det = _tmdb_get(f"/movie/{mid}", {"append_to_response":"credits"})
        director = ""
        for c in (det.get("credits", {}) or {}).get("crew", []) or []:
            if str(c.get("job")).lower() == "director":
                director = c.get("name") or ""; break
        if director_name and director_name.strip():
            if director.lower().find(director_name.strip().lower()) == -1: 
                continue
        title_f = det.get("title") or it.get("title") or ""
        release = (det.get("release_date") or it.get("release_date") or "")[:4]
        year_f = int(release) if release.isdigit() else None
        genres_list = [g.get("name","") for g in (det.get("genres") or []) if g.get("name")]
        if genre_name and any(g.lower() == genre_name.lower() for g in genres_list):
            genre_f = genre_name
        else:
            genre_f = genres_list[0] if genres_list else ""
        genres_join = ", ".join(genres_list)
        rating_f = float(det.get("vote_average")) if det.get("vote_average") is not None else None
        notes_f = det.get("overview") or ""
        out.append({"title":title_f,"director":director,"year":year_f,"genre":genre_f,"subgenre":"",
                    "rating":rating_f,"notes":notes_f,"genres": genres_join, "watched":False,"watched_date":""})
    return out

def tmdb_search_series_advanced(title: str, genre_name: str | None, year_txt: str | None, creator_name: str | None) -> list[dict]:
    gmap = _tmdb_genres("tv")
    gid = gmap.get((genre_name or "").casefold())
    mode, year_exact, year_a, year_b = _year_mode(year_txt)

    if (title or "").strip():
        params = {"query": title.strip(), "include_adult":"false"}
        if mode == "exact": params["first_air_date_year"] = int(year_exact)
        data = _tmdb_get("/search/tv", params); base = data.get("results", [])[:25]
    else:
        params = {"include_adult":"false","sort_by":"popularity.desc"}
        if gid: params["with_genres"] = gid
        if mode == "exact":
            params["first_air_date_year"] = int(year_exact)
        elif mode == "range":
            params["first_air_date.gte"] = f"{int(year_a)}-01-01"
            params["first_air_date.lte"] = f"{int(year_b)}-12-31"
        data = _tmdb_get("/discover/tv", params); base = data.get("results", [])[:25]

    if gid:
        base = [it for it in base if gid in (it.get("genre_ids") or [])]
    if mode == "range" and (title or "").strip():
        def _y(it):
            y = (it.get("first_air_date") or "")[:4]
            return int(y) if y.isdigit() else None
        base = [it for it in base if (lambda y: y is not None and year_a <= y <= year_b)(_y(it))]

    out = []
    for it in base:
        tid = it.get("id"); 
        if not tid: continue
        det = _tmdb_get(f"/tv/{tid}")
        creators = ", ".join([c.get("name","") for c in det.get("created_by") or [] if c.get("name")]) or ""
        if creator_name and creator_name.strip():
            if creators.lower().find(creator_name.strip().lower()) == -1: 
                continue
        title_f = det.get("name") or it.get("name") or ""
        first_air = (det.get("first_air_date") or it.get("first_air_date") or "")[:4]
        year_start = int(first_air) if first_air.isdigit() else None
        genre_f = (det.get("genres") or [{}])[0].get("name","") if det.get("genres") else ""
        rating_f = float(det.get("vote_average")) if det.get("vote_average") is not None else None
        notes_f = det.get("overview") or ""
        out.append({"title":title_f,"creator":creators,"year_start":year_start,"year_end":"",
                    "genre":genre_f,"subgenre":"","rating":rating_f,"notes":notes_f})
    return out

def _get_omdb_apikey() -> str:
    try: key = st.secrets.get("OMDB_API_KEY", "")
    except Exception: key = ""
    if not key: key = os.getenv("OMDB_API_KEY", "")
    return str(key).strip()

def _omdb_detail(imdb_id: str, apikey: str) -> dict:
    r = requests.get(OMDB_BASE, params={"apikey":apikey,"i":imdb_id,"plot":"short","r":"json"}, timeout=15)
    r.raise_for_status(); return r.json()

def omdb_search(title: str, year_txt: str | None, kind: str) -> list[dict]:
    apikey = _get_omdb_apikey()
    if not apikey or not (title or "").strip():
        return []
    params = {"apikey":apikey, "s":title.strip(), "type":kind, "r":"json"}
    if year_txt and year_txt.isdigit(): params["y"] = int(year_txt)
    s = requests.get(OMDB_BASE, params=params, timeout=15); s.raise_for_status()
    data = s.json()
    if data.get("Response") != "True": return []
    out = []
    for item in data.get("Search", []):
        imdb_id = item.get("imdbID") or ""
        full = _omdb_detail(imdb_id, apikey) if imdb_id else {}
        title_f = (full.get("Title") or item.get("Title") or "").strip()
        year_raw = full.get("Year") or item.get("Year")
        year_f = int(year_raw.split("–")[0]) if isinstance(year_raw, str) and year_raw[:4].isdigit() else None
        genre_f = (full.get("Genre") or "").split(",")[0] or ""
        rating_f = None
        try:
            rating_f = float(full.get("imdbRating")) if full.get("imdbRating") not in (None, "N/A") else None
        except Exception:
            rating_f = None
        notes_f = full.get("Plot") if full.get("Plot") not in (None, "N/A") else ""
        if kind == "movie":
            out.append({"title":title_f,"director":"" if full.get("Director") in (None,"N/A") else full.get("Director"),
                        "year":year_f,"genre":genre_f,"subgenre":"","rating":rating_f,"notes":notes_f,
                        "watched":False,"watched_date":""})
        else:
            out.append({"title":title_f,"creator":"" if full.get("Writer") in (None,"N/A") else full.get("Writer"),
                        "year_start":year_f,"year_end":"","genre":genre_f,"subgenre":"","rating":rating_f,"notes":notes_f})
    return out

def itunes_soundtrack_search(title: str, artist: str | None, year_txt: str | None) -> list[dict]:
    if not (title or "").strip(): return []
    term = f"{title.strip()} soundtrack" + (f" {artist}" if artist else "")
    r = requests.get(ITUNES_BASE, params={"term":term,"entity":"album","limit":25,"media":"music"}, timeout=15)
    r.raise_for_status(); data = r.json()
    items = []
    for it in data.get("results", []):
        year = None; rd = str(it.get("releaseDate") or "")
        if rd[:4].isdigit(): year = int(rd[:4])
        if year_txt and year_txt.isdigit() and year is not None and int(year_txt) != year: continue
        items.append({"title":it.get("collectionName",""),"artist":it.get("artistName",""),
                      "year":year,"genre":it.get("primaryGenreName","") or "","subgenre":"",
                      "rating":"","notes":it.get("collectionViewUrl",""),
                      "related_movie_id":"","related_series_id":""})
    return items

# ---------------- Page ----------------
def render_cinema_page(section: str = "Movies"):
    k = lambda name: f"cin_{section}_{name}"

    st.title(f"🎬 Cinema — {section}")

    generos, sub_by_gen, genres_path = load_genres()
    st.caption(f"Genres CSV: `{genres_path}`")

    df = load_table(section)

    # --- Search controls ---
    st.subheader("Search")
    c1, c2, _ = st.columns([2, 2, 2])
    title = c1.text_input("Title (contains)", key=k("search_title"))

    if section == "Movies":
        author_label, author_key = "Director (contains)", "director"
    elif section == "Series":
        author_label, author_key = "Creator (contains)", "creator"
    else:
        author_label, author_key = "Artist (contains)", "artist"
    author_val = c2.text_input(author_label, key=k("search_author"))

    col_g, col_w = st.columns([1, 1])
    genre = col_g.selectbox("Genre", generos, index=0, key=k("search_genre"))

    # Watched filter only makes sense for Movies
    watched_sel = None
    if section == "Movies":
        watched_sel = col_w.selectbox("Watched", ["All", "Yes", "No"], index=0, key=k("search_watched"))
    else:
        col_w.write("")  # filler to keep layout


    c4, c5 = st.columns([1, 1])
    year_txt = c4.text_input("Year (optional — e.g., 1995 or 1990-1999)",
                             placeholder="1995 or 1990-1999", key=k("search_year"))
    min_rating = c5.slider("Min. rating (optional)", 0.0, 10.0, 0.0, 0.1, key=k("search_minrating"))

    online = st.checkbox("Search online", value=True, key=k("search_online"),
                         help="Movies/Series: TMDb or OMDb • Soundtracks: iTunes")

    provider = None
    if section in ("Movies", "Series"):
        provider = st.selectbox("Provider", ["TMDb (recommended)", "OMDb"], index=0, key=k("provider"))

    if st.button("Search", key=k("btn_search")):
        # ----- Local (CSV) -----
        filters = {"title": title, "genre": genre,
           "year": year_txt, "min_rating": min_rating, author_key: author_val,
           "watched": watched_sel if section == "Movies" else None}

        local_out = apply_filters(section, df, filters)

        if section == "Movies" and filters.get("watched") == "Yes":
            online = False  # remote sources don't know your watched list

        # ----- Online (optional) -----
        remote = []
        if online:
            if section == "Movies":
                if provider.startswith("TMDb"):
                    remote = tmdb_search_movies_advanced(
                        title=title,
                        genre_name=(genre if genre != "All" else ""),
                        year_txt=year_txt,
                        director_name=author_val,
                    )
                else:
                    # OMDb: fetch por título e filtrar localmente pelos restantes campos
                    raw = omdb_search(title, year_txt, "movie")
                    if raw:
                        mode, val = parse_year_filter(year_txt or "")
                        def _year_ok(y):
                            if mode == "none":  return True
                            if mode == "exact": return y == val
                            a, b = val;         return (y or 0) >= a and (y or 0) <= b
                        remote = [
                            r for r in raw
                            if (genre == "All" or genre.lower() in str(r.get("genre","")).lower())
                            and (not author_val or author_val.lower() in str(r.get("director","")).lower())
                            and (r.get("rating") is None or float(r["rating"]) >= float(min_rating or 0))
                            and _year_ok(r.get("year"))
                        ]
            elif section == "Series":
                if provider.startswith("TMDb"):
                    remote = tmdb_search_series_advanced(
                        title=title,
                        genre_name=(genre if genre != "All" else ""),
                        year_txt=year_txt,
                        creator_name=author_val,
                    )
                else:
                    raw = omdb_search(title, year_txt, "series")
                    if raw:
                        mode, val = parse_year_filter(year_txt or "")
                        def _year_ok(y):
                            if mode == "none":  return True
                            if mode == "exact": return y == val
                            a, b = val;         return (y or 0) >= a and (y or 0) <= b
                        remote = [
                            r for r in raw
                            if (genre == "All" or genre.lower() in str(r.get("genre","")).lower())
                            and (not author_val or author_val.lower() in str(r.get("creator","")).lower())
                            and (r.get("rating") is None or float(r["rating"]) >= float(min_rating or 0))
                            and _year_ok(r.get("year_start"))
                        ]
            else:
                remote = itunes_soundtrack_search(title, author_val, year_txt)
                if genre and genre != "All":
                    remote = [r for r in remote if genre.lower() in str(r.get("genre","")).lower()]

        # Online results
        if remote:
            st.subheader("Online results")
            st.dataframe(
                pd.DataFrame(remote),
                use_container_width=True, hide_index=True,
                column_config={
                    "year": st.column_config.NumberColumn("year", format="%d", step=1),
                    "year_start": st.column_config.NumberColumn("year_start", format="%d", step=1),
                    "year_end": st.column_config.NumberColumn("year_end", format="%d", step=1),
                    "rating": st.column_config.NumberColumn("rating", format="%.1f", step=0.1),
                },
            )
        else:
            st.info("No online results.")

        # ----- Show local results -----
        st.subheader("Local results (CSV)")
        if section == "Movies":
            view_cols = ["id","title","director","year","genre","rating","watched","watched_date"]
            for c in view_cols:
                if c not in local_out.columns:
                    local_out[c] = "" if c != "watched" else False
            local_view = local_out[view_cols].copy()

            edited = st.data_editor(
                local_view,
                hide_index=True,
                use_container_width=True,
                key=k("editor_movies"),
                column_config={
                    "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                    "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
                    "watched": st.column_config.CheckboxColumn("Watched"),
                    "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD", help="Optional"),
                },
            )

            if st.button("Save watched changes", key=k("btn_save_watched")):
                base_df = load_table("Movies")
                base_df = _ensure_schema(base_df, "Movies")
                updates = 0
                edited["watched"] = edited["watched"].fillna(False).astype(bool)
                edited["watched_date"] = edited["watched_date"].astype(str).fillna("")
                for _, row in edited.iterrows():
                    mid = int(row["id"])
                    mask = base_df["id"] == mid
                    if mask.any():
                        chg = False
                        if base_df.loc[mask, "watched"].iloc[0] != bool(row["watched"]):
                            base_df.loc[mask, "watched"] = bool(row["watched"]); chg = True
                        wd = str(row["watched_date"]).strip()
