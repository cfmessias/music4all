# cinema/ui/helpers.py
from __future__ import annotations
import os, re, requests, unicodedata, datetime
from typing import Any
import pandas as pd
import streamlit as st
from rapidfuzz import fuzz

TMDB_API_KEY = (
    os.getenv("TMDB_API_KEY", "")
    or (st.secrets.get("TMDB_API_KEY") if hasattr(st, "secrets") else "")
)

# ---------- Keys & basic ----------
def key_for(section: str, name: str) -> str:
    return f"cin_{section}_{name}"

def author_label_and_key(section: str) -> tuple[str, str]:
    if section == "Movies":
        return "Director (contains)", "director"
    if section == "Series":
        return "Creator (contains)", "creator"
    return "Artist (contains)", "artist"

def safe_intlike(v) -> int | None:
    try:
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return None
        return int(float(s))
    except Exception:
        return None

def safe_year(v) -> int | None:
    try:
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return None
        return int(float(s))
    except Exception:
        return None

def parse_date_like(v) -> datetime.date | None:
    if v in (None, "", "None", "nan", "NaT"):
        return None
    if isinstance(v, datetime.date):
        return v
    try:
        s = str(v)[:10]
        y, m, d = s.split("-")
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None

# ---------- Title scoring ----------
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[\W_]+", " ", s).strip()

def title_match_score(title: str, query: str) -> float:
    t = _norm(title)
    q = _norm(query)
    if not t or not q:
        return 0.0
    qtoks, ttoks = set(q.split()), set(t.split())
    coverage = len(qtoks & ttoks) / max(1, len(qtoks))
    base = max(fuzz.WRatio(t, q), fuzz.token_set_ratio(t, q))
    phrase_bonus = 25 if q in t else 0
    prefix_bonus = 10 if t.startswith(q) else 0
    loose_pen = -20 if coverage < 0.6 else 0
    return float(base + phrase_bonus + prefix_bonus + (coverage * 15) + loose_pen)

# ---------- Spotify helpers ----------
def to_spotify_embed(url_or_uri: str) -> str:
    s = (url_or_uri or "").strip()
    if not s:
        return ""
    if s.startswith("spotify:"):
        parts = s.split(":")
        if len(parts) >= 3:
            return f"https://open.spotify.com/embed/{parts[1]}/{parts[2]}"
        return ""
    if "open.spotify.com/" in s and "/embed/" not in s:
        return s.replace("open.spotify.com/", "open.spotify.com/embed/")
    return s

# ---------- TMDb helpers (id / credits) ----------
@st.cache_data(ttl=86400, show_spinner=False)
def tmdb_search_id(kind: str, title: str, year: int | None) -> int | None:
    if not TMDB_API_KEY or not title:
        return None
    url = f"https://api.themoviedb.org/3/search/{'movie' if kind=='movie' else 'tv'}"
    params = {"api_key": TMDB_API_KEY, "query": title, "include_adult": "false"}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = int(year)
    try:
        r = requests.get(url, params=params, timeout=8); r.raise_for_status()
        data = r.json() or {}
        res = (data.get("results") or [])
        rid = res[0].get("id") if res else None
        return int(rid) if rid else None
    except Exception:
        return None

def resolve_tmdb_id(row: dict, section: str) -> int | None:
    for key in ("tmdb_id", "tmdbId", "tmdb", "id"):
        tid = row.get(key)
        tid = int(tid) if str(tid).strip().isdigit() else None
        if tid:
            return tid
    for url_key in ("tmdb_url", "url", "webpage", "homepage"):
        u = str(row.get(url_key) or "")
        m = re.search(r"themoviedb\.org/(movie|tv)/(\d+)", u)
        if m:
            return int(m.group(2))
    title = (row.get("title") or row.get("name") or "").strip()
    year = row.get("year") or row.get("year_start")
    return tmdb_search_id("movie" if section=="Movies" else "tv", title, safe_year(year))

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_tmdb_credits(kind: str, tmdb_id: int) -> list[str]:
    if not tmdb_id or not TMDB_API_KEY:
        return []
    base = "https://api.themoviedb.org/3"
    kind_path = "movie" if kind.lower().startswith("movie") else "tv"
    url = f"{base}/{kind_path}/{int(tmdb_id)}/credits"
    try:
        r = requests.get(url, params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
        r.raise_for_status()
        data = r.json() or {}
        cast = data.get("cast") or []
        names = []
        for it in cast[:12]:
            if isinstance(it, dict):
                nm = it.get("name") or it.get("original_name")
                if nm:
                    names.append(str(nm).strip())
        return names
    except Exception:
        return []

# ---------- Artists extraction ----------
def _artists_from_row_shallow(row: dict) -> list[str]:
    key_pat = re.compile(r"(artists?|cast|actors?|top[_\s-]*cast|starring|credits?)", re.I)
    def _extract(obj):
        out = []
        if obj is None: return out
        if isinstance(obj, str):
            parts = [p.strip() for p in re.split(r"[;,|]", obj) if p and p.strip()]
            out.extend(parts or [obj.strip()]); return out
        if isinstance(obj, (list, tuple)):
            for it in obj: out.extend(_extract(it)); return out
        if isinstance(obj, dict):
            for k in ("name", "original_name", "person", "actor", "title"):
                if k in obj and obj[k]:
                    out.append(str(obj[k]).strip())
            cast = obj.get("cast")
            if isinstance(cast, (list, tuple)):
                for it in cast:
                    if isinstance(it, dict):
                        nm = it.get("name") or it.get("original_name")
                        if nm: out.append(str(nm).strip())
            crew = obj.get("crew")
            if isinstance(crew, (list, tuple)):
                for it in crew:
                    if isinstance(it, dict):
                        dep = (it.get("known_for_department") or it.get("department") or "").lower()
                        job = (it.get("job") or "").lower()
                        if dep == "acting" or "actor" in job:
                            nm = it.get("name") or it.get("original_name")
                            if nm: out.append(str(nm).strip())
            for k, v in obj.items():
                if key_pat.search(str(k)) and v is not None:
                    out.extend(_extract(v))
            return out
        return out
    names = []
    for k, v in (row or {}).items():
        if key_pat.search(str(k)) and v is not None:
            names.extend(_extract(v))
    if not names and isinstance(row.get("credits"), (dict, list, tuple)):
        names.extend(_extract(row["credits"]))
    # dedupe e limita a 12
    seen, ded = set(), []
    for nm in names:
        nm = str(nm).strip()
        if not nm: continue
        low = nm.lower()
        if low not in seen:
            seen.add(low); ded.append(nm)
    return ded[:12]

def artists_from_row_or_fetch(row: dict[str, Any], section: str) -> str:
    shallow = _artists_from_row_shallow(row)
    if shallow:
        return ", ".join(shallow)
    tid = resolve_tmdb_id(row, section)
    if not tid:
        return ""
    names = fetch_tmdb_credits("movie" if section=="Movies" else "tv", tid)
    return ", ".join(names[:12]) if names else ""

# ---------- Spotify: pick + cache + button callback ----------
@st.cache_data(ttl=86400, show_spinner=False)
def ost_link_cached(title: str, year: int | str | None, section: str = "Movies",
                    tmdb_id: int | None = None) -> dict:
    from cinema.providers.spotify import pick_best_soundtrack
    # composer hints (opcional)
    hint_artists = []
    try:
        from cinema.providers.tmdb import tmdb_get_composers
        media = "tv" if section == "Series" else "movie"
        if tmdb_id:
            hint_artists = tmdb_get_composers(media, int(tmdb_id)) or []
    except Exception:
        hint_artists = []
    year_txt = str(year) if year not in (None, "", "nan") else ""
    media_kind = "tv" if section == "Series" else "movie"
    try:
        return pick_best_soundtrack(title=title or "", year_txt=year_txt,
                                    media_kind=media_kind, hint_artists=hint_artists) or {}
    except TypeError:
        return pick_best_soundtrack(title=title or "", year_txt=year_txt,
                                    media_kind=media_kind) or {}

def on_click_play(section: str, rid: int, title_i: str, yv, tmdb_id: int | None = None):
    from cinema.providers.spotify import compact_embed_url
    # manter cartão aberto
    st.session_state[key_for(section, "open_card_id")] = rid
    st.session_state[key_for(section, "play_open_id")] = rid
    info = ost_link_cached(title_i, yv, section, tmdb_id=tmdb_id)
    raw = (info or {}).get("uri") or (info or {}).get("url") or ""
    if raw:
        if not st.session_state.get("spfy_compact", False):
            src = to_spotify_embed(raw); height = 380
        else:
            src = compact_embed_url(raw); height = 100
        st.session_state[key_for(section, "play_src")] = src
        st.session_state[key_for(section, "play_height")] = height
        st.session_state[key_for(section, "play_msg")] = ""
    else:
        st.session_state[key_for(section, "play_src")] = ""
        st.session_state[key_for(section, "play_msg")] = "🎧 Soundtrack not found"

# ---------- Save helpers ----------
from cinema.data import load_table, save_table

def save_watched_item_movies(row: dict, watched: bool, watched_date: str) -> tuple[int, int]:
    base_df = load_table("Movies"); updates = inserts = 0
    y = safe_year(row.get("year"))
    title_r = (row.get("title") or row.get("name") or "").strip().casefold()
    mask = (base_df["title"].astype(str).str.strip().str.casefold() == title_r)
    if y is not None and "year" in base_df.columns:
        mask &= (pd.to_numeric(base_df["year"], errors="coerce") == y)
    if mask.any():
        chg = False
        if bool(base_df.loc[mask, "watched"].iloc[0]) != bool(watched):
            base_df.loc[mask, "watched"] = bool(watched); chg = True
        wd = (watched_date or "")[:10]
        if str(base_df.loc[mask, "watched_date"].iloc[0] or "") != wd:
            base_df.loc[mask, "watched_date"] = wd; chg = True
        if chg: updates += 1
    else:
        new_id = int(base_df["id"].max()) + 1 if "id" in base_df.columns and not base_df.empty else 1
        base_df.loc[len(base_df)] = {
            "id": new_id,
            "title": row.get("title", "") or row.get("name", ""),
            "director": row.get("director", ""),
            "year": y or "",
            "genre": row.get("genre", "") if "genre" in base_df.columns else "",
            "streaming": row.get("streaming", "") if "streaming" in base_df.columns else "",
            "rating": row.get("rating", "") or "",
            "notes": "",
            "watched": bool(watched),
            "watched_date": (watched_date or "")[:10] if "watched_date" in base_df.columns else "",
        }
        inserts += 1
    save_table("Movies", base_df)
    return updates, inserts

def save_watched_item_series(row: dict, watched: bool, watched_date: str) -> tuple[int, int]:
    base_df = load_table("Series"); updates = inserts = 0
    ys = safe_year(row.get("year_start"))
    season = row.get("season")
    title_r = (row.get("title") or row.get("name") or "").strip().casefold()
    mask = (base_df["title"].astype(str).str.strip().str.casefold() == title_r)
    if "season" in base_df.columns and season not in (None, "", "nan"):
        try:
            season_i = int(float(season))
            mask &= (pd.to_numeric(base_df["season"], errors="coerce") == season_i)
        except Exception:
            pass
    if ys is not None and "year_start" in base_df.columns:
        mask &= (pd.to_numeric(base_df["year_start"], errors="coerce") == ys)
    if mask.any():
        chg = False
        if bool(base_df.loc[mask, "watched"].iloc[0]) != bool(watched):
            base_df.loc[mask, "watched"] = bool(watched); chg = True
        wd = (watched_date or "")[:10]
        if str(base_df.loc[mask, "watched_date"].iloc[0] or "") != wd:
            base_df.loc[mask, "watched_date"] = wd; chg = True
        if chg: updates += 1
    else:
        new_id = int(base_df["id"].max()) + 1 if "id" in base_df.columns and not base_df.empty else 1
        base_df.loc[len(base_df)] = {
            "id": new_id,
            "title": row.get("title") or row.get("name") or "",
            "creator": row.get("creator", ""),
            "season": int(season) if str(season).isdigit() else season,
            "year_start": ys or "",
            "year_end": row.get("year_end", "") or "",
            "genre": row.get("genre", "") if "genre" in base_df.columns else "",
            "streaming": row.get("streaming", "") if "streaming" in base_df.columns else "",
            "rating": row.get("rating", "") or "",
            "notes": "",
            "watched": bool(watched),
            "watched_date": (watched_date or "")[:10],
        }
        inserts += 1
    save_table("Series", base_df)
    return updates, inserts
