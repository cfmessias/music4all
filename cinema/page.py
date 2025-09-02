# cinema/page.py
from __future__ import annotations

import datetime
import pandas as pd
import streamlit as st
import re
import os, requests

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
from .data import load_genres, load_table, save_table
from .filters import apply_filters
from .providers.tmdb import tmdb_search_movies_advanced, tmdb_search_series_advanced
from .providers.spotify import search_soundtrack_albums, pick_best_soundtrack
from .views.spotify_embed import render_player   # Spotify player embutido

DEBUG_ARTISTS = True  # mete False quando não precisares

# ------------------------ Helpers ------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def _tmdb_search_id(kind: str, title: str, year: int | None) -> int | None:
    """Procura ID no TMDb por título (+ ano). kind: 'movie'|'tv'."""
    if not TMDB_API_KEY or not title:
        return None
    url = f"https://api.themoviedb.org/3/search/{'movie' if kind=='movie' else 'tv'}"
    params = {"api_key": TMDB_API_KEY, "query": title, "include_adult": "false"}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = int(year)
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json() or {}
        results = data.get("results") or []
        if results:
            rid = results[0].get("id")
            return int(rid) if rid else None
    except Exception:
        pass
    return None

def _resolve_tmdb_id(row: dict, section: str) -> int | None:
    """Tenta obter o TMDb id a partir de vários campos/fallbacks."""
    # 1) campos diretos
    for key in ("tmdb_id", "tmdbId", "tmdb", "id"):
        tid = row.get(key)
        tid = int(tid) if str(tid).strip().isdigit() else None
        if tid:
            return tid

    # 2) tentar extrair de URL (se existir)
    for url_key in ("tmdb_url", "url", "webpage", "homepage"):
        u = str(row.get(url_key) or "")
        m = re.search(r"themoviedb\.org/(movie|tv)/(\d+)", u)
        if m:
            return int(m.group(2))

    # 3) pesquisa por título + ano
    title = (row.get("title") or row.get("name") or "").strip()
    year = row.get("year") or row.get("year_start")
    year_i = None
    try:
        if year not in (None, "", "nan"):
            year_i = int(float(str(year)))
    except Exception:
        year_i = None

    kind = "movie" if section == "Movies" else "tv"
    return _tmdb_search_id(kind, title, year_i)

def _artists_from_row_or_fetch(row: dict, section: str) -> str:
    """Usa o que vier no row; se vazio, pede credits ao TMDb (com cache)."""
    # 1) tentar extrair diretamente (o teu helper atual)
    txt = _artists_from_row(row)
    if txt:
        return txt

    # 2) se não houver nada, pedir credits ao TMDb
    if not TMDB_API_KEY:
        return ""  # sem API key não conseguimos ir buscar

    tid = _resolve_tmdb_id(row, section)
    if not tid:
        return ""

    names = _fetch_tmdb_credits("movie" if section == "Movies" else "tv", tid)
    return ", ".join(names[:12]) if names else ""

@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_tmdb_credits(kind: str, tmdb_id: int) -> list[str]:
    """Devolve até 12 nomes do cast via TMDb /movie|tv/{id}/credits."""
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

def _dbg_preview(v, limit=80):
    try:
        if isinstance(v, (list, tuple)):
            head = []
            for it in v[:5]:
                if isinstance(it, dict):
                    nm = it.get("name") or it.get("original_name") or it.get("title") or it.get("person") or it.get("actor")
                    head.append(str(nm or it)[:40])
                else:
                    head.append(str(it)[:40])
            return f"list[{len(v)}]: " + ", ".join(head) + (" …" if len(v) > 5 else "")
        if isinstance(v, dict):
            keys = list(v.keys())[:8]
            return f"dict keys: {', '.join(keys)}" + (" …" if len(v) > 8 else "")
        s = str(v)
        return s if len(s) <= limit else s[:limit] + " …"
    except Exception:
        return str(v)[:limit] + " …"

def _artists_from_row(row: dict) -> str:
    """Extrai até 12 nomes de artistas/atores a partir de chaves e estruturas variadas."""
    # chaves candidatas (case-insensitive); aceita variações com espaços/underscores
    key_pat = re.compile(r"(artists?|cast|actors?|top[_\s-]*cast|starring|credits?|people|members|performers?)", re.I)

    def _extract_names(obj):
        out = []
        if obj is None:
            return out

        # string -> quebra por vírgulas/pontos e vírgulas/pipes
        if isinstance(obj, str):
            parts = [p.strip() for p in re.split(r"[;,|]", obj) if p and p.strip()]
            out.extend(parts or [obj.strip()])
            return out

        # lista/tuplo -> concatena extrações de cada elemento
        if isinstance(obj, (list, tuple)):
            for it in obj:
                out.extend(_extract_names(it))
            return out

        # dict -> tenta chaves típicas; se não achar, percorre subitens
        if isinstance(obj, dict):
            # nomes diretos
            for k in ("name", "original_name", "person", "actor", "title"):
                if k in obj and obj[k]:
                    n = str(obj[k]).strip()
                    if n:
                        out.append(n)

            # casos TMDB: credits.cast (lista de dicts com "name"), crew (filtra Acting/Actor)
            cast = obj.get("cast")
            if isinstance(cast, (list, tuple)):
                for it in cast:
                    if isinstance(it, dict):
                        nm = it.get("name") or it.get("original_name")
                        if nm:
                            out.append(str(nm).strip())

            crew = obj.get("crew")
            if isinstance(crew, (list, tuple)):
                for it in crew:
                    if isinstance(it, dict):
                        dep = (it.get("known_for_department") or it.get("department") or "").lower()
                        job = (it.get("job") or "").lower()
                        if dep == "acting" or "actor" in job:
                            nm = it.get("name") or it.get("original_name")
                            if nm:
                                out.append(str(nm).strip())

            # varrer restantes subcampos que “pareçam” conter elenco
            for k, v in obj.items():
                if key_pat.search(str(k)) and v is not None:
                    out.extend(_extract_names(v))

            return out

        return out  # outros tipos: ignora

    # 1) tenta diretamente pelas chaves do row
    names = []
    for k, v in (row or {}).items():
        if key_pat.search(str(k)) and v is not None:
            names.extend(_extract_names(v))

    # 2) fallback: se existir 'credits' no topo
    if not names and isinstance(row.get("credits"), (dict, list, tuple)):
        names.extend(_extract_names(row["credits"]))

    # 3) dedupe mantendo ordem e limita a 12
    seen, deduped = set(), []
    for nm in names:
        nm = str(nm).strip()
        if not nm:
            continue
        low = nm.lower()
        if low not in seen:
            seen.add(low)
            deduped.append(nm)

    return ", ".join(deduped[:12])

def _key(section: str, name: str) -> str:
    return f"cin_{section}_{name}"

def _author_label_and_key(section: str) -> tuple[str, str]:
    if section == "Movies":
        return "Director (contains)", "director"
    if section == "Series":
        return "Creator (contains)", "creator"
    return "Artist (contains)", "artist"

def _to_spotify_embed(url_or_uri: str) -> str:
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

@st.cache_data(ttl=86400, show_spinner=False)
def _ost_link_cached(title: str, year: int | str | None) -> dict:
    """Resolve best-match soundtrack no Spotify para <title>/<year> (link e uri)."""
    year_txt = str(year) if year not in (None, "", "nan") else ""
    alb = pick_best_soundtrack(title=title or "", year_txt=year_txt, artist=None)
    return alb or {}

def _safe_intlike(v):
    try:
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return None
        return int(float(s))
    except Exception:
        return None

def _safe_year(v):
    try:
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return None
        return int(float(s))
    except Exception:
        return None

def _parse_date_like(v) -> datetime.date | None:
    if v in (None, "", "None", "nan"):
        return None
    if isinstance(v, datetime.date):
        return v
    try:
        s = str(v)[:10]
        y, m, d = s.split("-")
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None

# ---- persistência de watched para um único item ----
def _save_watched_item_movies(row: dict, watched: bool, watched_date: str) -> tuple[int, int]:
    base_df = load_table("Movies")
    updates, inserts = 0, 0

    y = _safe_year(row.get("year"))
    title_r = str(row.get("title", "")).strip().casefold()

    mask = (base_df["title"].astype(str).str.casefold() == title_r)
    if y is not None and "year" in base_df.columns:
        mask &= (pd.to_numeric(base_df["year"], errors="coerce") == y)

    if mask.any():
        chg = False
        if bool(base_df.loc[mask, "watched"].iloc[0]) != bool(watched):
            base_df.loc[mask, "watched"] = bool(watched); chg = True
        if "watched_date" in base_df.columns and str(base_df.loc[mask, "watched_date"].iloc[0]) != watched_date:
            base_df.loc[mask, "watched_date"] = watched_date; chg = True
        if chg: updates += 1
    else:
        new_id = int(base_df["id"].max()) + 1 if not base_df.empty else 1
        base_df.loc[len(base_df)] = {
            "id": new_id,
            "title": row.get("title", ""),
            "director": row.get("director", ""),
            "year": y or "",
            "genre": row.get("genre", "") if "genre" in base_df.columns else "",
            "streaming": row.get("streaming", "") if "streaming" in base_df.columns else "",
            "rating": row.get("rating", "") or "",
            "notes": "",
            "watched": bool(watched),
            "watched_date": watched_date if "watched_date" in base_df.columns else "",
        }
        inserts += 1

    save_table("Movies", base_df)
    return updates, inserts

def _save_watched_item_series(row: dict, watched: bool, watched_date: str) -> tuple[int, int]:
    base_df = load_table("Series")
    updates, inserts = 0, 0

    ys = _safe_year(row.get("year_start"))
    season = row.get("season")
    title_r = str(row.get("title", "")).strip().casefold()

    mask = (base_df["title"].astype(str).str.casefold() == title_r)
    if season is not None and "season" in base_df.columns:
        mask &= (pd.to_numeric(base_df["season"], errors="coerce") == pd.to_numeric(pd.Series([season]), errors="coerce").iloc[0])
    if ys is not None and "year_start" in base_df.columns:
        mask &= (pd.to_numeric(base_df["year_start"], errors="coerce") == ys)

    if mask.any():
        chg = False
        if bool(base_df.loc[mask, "watched"].iloc[0]) != bool(watched):
            base_df.loc[mask, "watched"] = bool(watched); chg = True
        if "watched_date" in base_df.columns and str(base_df.loc[mask, "watched_date"].iloc[0]) != watched_date:
            base_df.loc[mask, "watched_date"] = watched_date; chg = True
        if chg: updates += 1
    else:
        new_id = int(base_df["id"].max()) + 1 if not base_df.empty else 1
        base_df.loc[len(base_df)] = {
            "id": new_id,
            "title": row.get("title", ""),
            "creator": row.get("creator", ""),
            "season": int(season) if str(season).isdigit() else season,
            "year_start": ys or "",
            "year_end": row.get("year_end", "") or "",
            "genre": row.get("genre", "") if "genre" in base_df.columns else "",
            "streaming": row.get("streaming", "") if "streaming" in base_df.columns else "",
            "rating": row.get("rating", "") or "",
            "notes": "",
            "watched": bool(watched),
            "watched_date": watched_date if "watched_date" in base_df.columns else "",
        }
        inserts += 1

    save_table("Series", base_df)
    return updates, inserts


# ------------------------ Page ------------------------

def render_cinema_page(section: str = "Movies") -> None:
    st.title(f"🎬 Cinema — {section}")

    # estilo: botões compactos
    st.markdown("""
    <style>
      .stButton > button { padding: 2px 10px; min-height: 28px; }
      .cin-card > div:first-child { padding-top: 0.25rem; padding-bottom: 0.25rem; }
    </style>
    """, unsafe_allow_html=True)

    # ---- Genres ----
    genres, _sub_by_gen, genres_path = load_genres()
    st.caption(f"Genres CSV: `{genres_path}`")

    # ---- Local table ----
    df = load_table(section)

    # ---- Controls ----
    st.subheader("Search")
    c1, c2, _ = st.columns([2, 2, 2])
    title = c1.text_input("Title (contains)", key=_key(section, "title"))
    author_label, author_key = _author_label_and_key(section)
    author_val = c2.text_input(author_label, key=_key(section, "author"))

    col_g, col_w = st.columns([1, 1])
    genre = col_g.selectbox("Genre", genres, index=0, key=_key(section, "genre"))

    watched_sel = None
    if section == "Movies":
        watched_sel = col_w.selectbox(
            "Watched", ["All", "Yes", "No"], index=0, key=_key(section, "watched")
        )
    else:
        col_w.write("")

    c4, c5 = st.columns([1, 1])
    year_txt = c4.text_input(
        "Year (optional — e.g., 1995 or 1990-1999)",
        placeholder="1995 or 1990-1999",
        key=_key(section, "year"),
    )
    min_rating = c5.slider(
        "Min. rating (optional)", 0.0, 10.0, 0.0, 0.1, key=_key(section, "minrating")
    )

    online = st.checkbox(
        "Search online (TMDb / Spotify)",
        value=True,
        key=_key(section, "online"),
        help="Movies/Series: TMDb • Soundtracks: Spotify",
    )

    # ---- Run search ----
    if st.button("Search", key=_key(section, "go")):
        # 1) Local (CSV)
        filters = {
            "title": title,
            "genre": genre,
            "year": year_txt,
            "min_rating": min_rating,
            author_key: author_val,
            "watched": watched_sel if section == "Movies" else None,
        }
        local_out = apply_filters(section, df, filters)

        # 2) Online
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

        # Persistir resultados
        st.session_state[_key(section, "remote_store")] = remote
        st.session_state[_key(section, "local_store")] = local_out

    # Recarregar estado
    remote = st.session_state.get(_key(section, "remote_store"), [])
    local_out = st.session_state.get(_key(section, "local_store"), pd.DataFrame())

    # ---- Online results (ÚNICA lista — cartões tipo Spotify) ----
    if remote:
        st.subheader("Online results")

        if section in ("Movies", "Series"):
            df_remote = pd.DataFrame(remote)

            # Coluna do ano a usar
            year_col = "year" if "year" in df_remote.columns else "year_start"
            if year_col not in df_remote.columns:
                df_remote[year_col] = ""

            # Normalizar colunas para evitar KeyError
            for c in [
                "id","title","name","director","creator","season",
                "genre","genres","streaming","rating","overview",
                "poster_url","poster","image",
                "web","play_url","notes","notes_text","watched","watched_date"
            ]:
                if c not in df_remote.columns:
                    if c == "watched":
                        df_remote[c] = False
                    elif c == "watched_date":
                        df_remote[c] = ""
                    else:
                        df_remote[c] = ""

            # Enriquecer com link Spotify (se faltar) e notas
            def _resolve_spfy(row):
                w = str(row.get("web") or "").strip()
                p = str(row.get("play_url") or "").strip()
                if not (w or p):
                    info = _ost_link_cached(
                        str(row.get("title") or row.get("name") or ""),
                        row.get(year_col),
                    )
                    w = (info or {}).get("url") or ""
                    p = (info or {}).get("uri") or ""
                play_src = _to_spotify_embed(p or w)
                notes = (
                    str(row.get("notes_text") or "").strip()
                    or str(row.get("notes") or "").strip()
                    or str(row.get("overview") or "").strip()
                )
                return pd.Series({"play_src": play_src, "notes_text2": notes})

            if not df_remote.empty:
                df_remote = pd.concat([df_remote, df_remote.apply(_resolve_spfy, axis=1)], axis=1)
            else:
                df_remote["play_src"] = ""
                df_remote["notes_text2"] = ""

            # ---- Paginação ----
            per_page = 10
            total = len(df_remote)
            total_pages = max(1, (total - 1) // per_page + 1)
            page_key = _key(section, "page")
            current = st.session_state.get(page_key, 1)
            try:
                current = int(current)
            except Exception:
                current = 1
            current = max(1, min(int(current), total_pages))

            colp1, colp2, _ = st.columns([1, 1, 6])
            with colp1:
                if st.button("⟨ Prev", disabled=(current <= 1), key=_key(section, "pg_prev")):
                    current = max(1, current - 1)
            with colp2:
                if st.button("Next ⟩", disabled=(current >= total_pages), key=_key(section, "pg_next")):
                    current = min(total_pages, current + 1)
            st.session_state[page_key] = current
            st.caption(f"Page {current} / {total_pages} • {total} results")

            start, end = (current - 1) * per_page, min(current * per_page, total)
            page_rows = df_remote.iloc[start:end].reset_index(drop=True)

            # ---- Cartões/Expanders (tipo Spotify) — única lista
            for i, r in page_rows.iterrows():
                row = r.to_dict()
                rid = _safe_intlike(row.get("id")) or (start + i)
                title_i = row.get("title") or row.get("name") or "—"
                who = row.get("director") if section == "Movies" else row.get("creator")
                rating = row.get("rating")

                yv = row.get(year_col)
                ytxt = ""
                if yv not in (None, "", "nan"):
                    try:
                        ytxt = f"{int(float(yv))}"
                    except Exception:
                        ytxt = str(yv)

                head_bits = [title_i]
                if ytxt:
                    head_bits.append(f"({ytxt})")
                if pd.notna(rating) and str(rating).strip().lower() not in ("", "nan"):
                    try:
                        rating_val = float(str(rating).replace(",", "."))
                        head_bits.append(f"— ★ {rating_val:.1f}")
                    except Exception:
                        # fallback se não der para converter
                        head_bits.append(f"— ★ {rating}")
                header = " ".join(head_bits).strip()

                with st.expander(header, expanded=False):
                    # duas colunas: conteúdo | poster
                    colA, colB = st.columns([2, 1])

                    with colA:
                       # 1) Director/Creator • Genres • Streaming (mesma linha)
                        who = row.get("director") if section == "Movies" else row.get("creator")
                        gl = row.get("genres") or row.get("genre") or ""
                        gl_txt = ", ".join(gl) if isinstance(gl, (list, tuple)) else str(gl)
                        streaming = row.get("streaming") or ""

                        meta_parts = []
                        if who:
                            meta_parts.append(f"**{'Director' if section=='Movies' else 'Creator'}:** {who}")
                        if gl_txt.strip():
                            meta_parts.append(f"**Genres:** {gl_txt}")
                        if streaming:
                            meta_parts.append(f"**Streaming:** {streaming}")
                        if meta_parts:
                            st.markdown(" • ".join(meta_parts))

                        # 2) Artists (novo) — robusto a diferentes formatos
                        artists_txt = _artists_from_row_or_fetch(row, section)

                        if DEBUG_ARTISTS:
                            title_dbg = row.get("title") or row.get("name")
                            print(f"[ARTISTS] {title_dbg!r} -> {artists_txt!r}")

                       
                        if DEBUG_ARTISTS:
                            def _lenlike(x):
                                return len(x) if isinstance(x, (list, tuple, dict, str)) else type(x).__name__
                            title_dbg = row.get("title") or row.get("name")
                            print(f"[ARTISTS] {title_dbg!r} -> extracted = {artists_txt!r}")
                            print("          raw keys sizes:",
                                "artists=", _lenlike(row.get("artists")),
                                "cast=", _lenlike(row.get("cast")),
                                "actors=", _lenlike(row.get("actors")),
                                "top_cast=", _lenlike(row.get("top_cast")),
                                "starring=", _lenlike(row.get("starring")),
                                "credits.cast=", _lenlike((row.get('credits') or {}).get('cast')),
                                "credits.crew=", _lenlike((row.get('credits') or {}).get('crew')))

                        if artists_txt:
                            st.markdown(f"**Artists:** {artists_txt}")
                        # 3) Overview (uma vez só)
                        notes = (row.get("notes_text2") or "").strip()
                        st.markdown("**📖 Overview:**")
                        st.write(notes or "—")

                        # 4) Soundtrack — botão + player
                        if st.button("🎧 Play soundtrack", key=_key(section, f"play_{rid}")):
                            st.session_state[_key(section, "play_open_id")] = rid
                            src = row.get("play_src") or ""
                            if not src:
                                t = row.get("title") or row.get("name") or ""
                                got = _ost_link_cached(t, yv)
                                src = _to_spotify_embed((got or {}).get("url") or (got or {}).get("uri") or "")
                            st.session_state[_key(section, "play_src")] = src

                        if st.session_state.get(_key(section, "play_open_id")) == rid:
                            src = st.session_state.get(_key(section, "play_src")) or ""
                            if src:
                                try:
                                    render_player(src, height=152)
                                except Exception:
                                    pass

                        # 5) Linha final — Watched + Date + Save (à ESQUERDA)
                        w_key = _key(section, f"w_{rid}")
                        d_key = _key(section, f"wd_{rid}")
                        default_w = bool(row.get("watched"))
                        default_d = _parse_date_like(row.get("watched_date"))

                        cW, cLbl, cD, cSave = st.columns([0.18, 0.16, 0.28, 0.12])  # afina se precisares
                        with cW:
                            w_val = st.checkbox("Watched", value=default_w, key=w_key)
                        with cLbl:
                            st.markdown("<div style='padding-top:0.45rem; font-weight:600;'>Watched date</div>", unsafe_allow_html=True)
                        with cD:
                            d_val = st.date_input(
                                "Watched date",
                                value=default_d, format="YYYY-MM-DD",
                                key=d_key, label_visibility="collapsed"  # mantém o label escondido na UI
)
                        with cSave:
                            if st.button("💾 Save", key=_key(section, f"savew_{rid}")):
                                wd_str = str(d_val)[:10] if d_val else ""
                                if section == "Movies":
                                    up, ins = _save_watched_item_movies(row, w_val, wd_str)
                                    st.success(f"Saved: {up} update(s), {ins} new row(s).")
                                else:
                                    up, ins = _save_watched_item_series(row, w_val, wd_str)
                                    st.success(f"Saved: {up} update(s), {ins} new row(s).")

                    with colB:
                        poster = row.get("poster_url") or row.get("poster") or row.get("image") or ""
                        if poster:
                            st.image(poster, width=140)

        else:
            # Página Soundtracks (mantida simples)
            df_sp = pd.DataFrame(remote)
            show_cols = [c for c in ["title", "artist", "year", "url"] if c in df_sp.columns]
            st.data_editor(
                df_sp[show_cols] if show_cols else df_sp,
                use_container_width=True, hide_index=True,
                key=_key(section, "online_editor_sp"),
                column_config={"year": st.column_config.NumberColumn("year", format="%d", step=1)},
                disabled=show_cols,
            )
    else:
        st.info("No online results.")

    # ---- Local results (CSV) ----
    st.subheader("Local results (CSV)")

    if section == "Movies":
        view_cols = ["id", "title", "director", "year", "genre", "streaming", "rating", "watched", "watched_date"]
        for c in view_cols:
            if c not in local_out.columns:
                local_out[c] = "" if c != "watched" else False
        local_view = local_out[view_cols].copy()

        edited_local = st.data_editor(
            local_view,
            hide_index=True,
            use_container_width=True,
            key=_key(section, "editor_movies"),
            column_config={
                "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
                "streaming": st.column_config.TextColumn("Streaming"),
                "watched": st.column_config.CheckboxColumn("Watched"),
                "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD", help="Optional"),
            },
        )

        if st.button("Save watched changes", key=_key(section, "save_watched_movies")):
            base_df = load_table("Movies")
            updates = 0
            edited_local["watched"] = edited_local["watched"].fillna(False).astype(bool)
            edited_local["watched_date"] = edited_local["watched_date"].astype(str).fillna("")
            for _, row in edited_local.iterrows():
                mid = int(row["id"])
                mask = base_df["id"] == mid
                if not mask.any():
                    continue
                chg = False
                if bool(base_df.loc[mask, "watched"].iloc[0]) != bool(row["watched"]):
                    base_df.loc[mask, "watched"] = bool(row["watched"]); chg = True
                wd = (str(row["watched_date"]).strip() or "")[:10]
                if str(base_df.loc[mask, "watched_date"].iloc[0]) != wd:
                    base_df.loc[mask, "watched_date"] = wd; chg = True
                if chg:
                    updates += 1
            save_table("Movies", base_df)
            st.success(f"Saved {updates} change(s).")

    elif section == "Series":
        view_cols = ["id","title","creator","season","year_start","year_end","genre","streaming","rating","watched","watched_date"]
        for c in view_cols:
            if c not in local_out.columns:
                local_out[c] = "" if c not in ("watched",) else False
        local_view = local_out[view_cols].copy()

        edited_local = st.data_editor(
            local_view,
            use_container_width=True,
            hide_index=True,
            key=_key(section, "editor_series"),
            column_config={
                "season": st.column_config.NumberColumn("season", format="%d", step=1),
                "year_start": st.column_config.NumberColumn("year_start", format="%d", step=1),
                "year_end": st.column_config.NumberColumn("year_end", format="%d", step=1),
                "rating": st.column_config.NumberColumn("rating", format="%.1f", step=0.1),
                "streaming": st.column_config.TextColumn("streaming"),
                "watched": st.column_config.CheckboxColumn("Watched"),
                "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
            },
        )

        if st.button("Save watched changes (Series)", key=_key(section, "save_watched_series_local")):
            base_df = load_table("Series")
            updates = 0
            edited_local["watched"] = edited_local["watched"].fillna(False).astype(bool)
            edited_local["watched_date"] = edited_local["watched_date"].astype(str).fillna("")
            for _, row in edited_local.iterrows():
                sid = int(row["id"])
                mask = base_df["id"] == sid
                if not mask.any():
                    continue
                chg = False
                if bool(base_df.loc[mask, "watched"].iloc[0]) != bool(row["watched"]):
                    base_df.loc[mask, "watched"] = bool(row["watched"]); chg = True
                wd = (str(row["watched_date"]).strip() or "")[:10]
                if str(base_df.loc[mask, "watched_date"].iloc[0]) != wd:
                    base_df.loc[mask, "watched_date"] = wd; chg = True
                if chg:
                    updates += 1
            save_table("Series", base_df)
            st.success(f"Saved {updates} change(s).")

    else:  # Soundtracks
        show_cols = [c for c in ["id","title","artist","year","genre","rating","notes","related_movie_id","related_series_id"] if c in local_out.columns]
        st.data_editor(
            local_out[show_cols] if show_cols else local_out,
            use_container_width=True,
            hide_index=True,
            key=_key(section, "editor_st"),
            column_config={
                "year": st.column_config.NumberColumn("year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("rating", format="%.1f", step=0.1),
            },
            disabled=show_cols,
        )
