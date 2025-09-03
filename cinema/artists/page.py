# cinema/artists/page.py
from __future__ import annotations

import os
import re
import requests
import pandas as pd
import streamlit as st

# ------------------------------------------------------------------
# TMDb – chave lida de env ou st.secrets (Streamlit Cloud)
# ------------------------------------------------------------------
TMDB_API_KEY = (
    os.getenv("TMDB_API_KEY")
    or (st.secrets.get("TMDB_API_KEY") if hasattr(st, "secrets") else None)
    or ""
)

TMDB_API = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/"

# ------------------------------------------------------------------
# Helpers HTTP + util
# ------------------------------------------------------------------
def _tmdb_get(path: str, params: dict | None = None) -> dict:
    if not TMDB_API_KEY:
        return {}
    params = dict(params or {})
    params.setdefault("api_key", TMDB_API_KEY)
    params.setdefault("language", "en-US")
    try:
        r = requests.get(f"{TMDB_API}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json() or {}
    except Exception:
        return {}

def _img_url(path: str | None, size: str = "w185") -> str:
    return f"{IMG_BASE}{size}{path}" if path else ""

def _year_from_date(s: str | None) -> str:
    if not s:
        return ""
    m = re.search(r"\d{4}", s)
    return m.group(0) if m else ""

def _clean_bio(txt: str | None, max_chars: int = 900) -> str:
    t = (txt or "").strip()
    if not t:
        return "—"
    t = re.sub(r"\s+\n", "\n", t)
    if len(t) <= max_chars:
        return t
    # corta numa borda “limpa”
    cut = t[:max_chars].rsplit(". ", 1)[0]
    return cut + "…"

# ------------------------------------------------------------------
# TMDb cached calls
# ------------------------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def _search_people(query: str, page: int = 1) -> list[dict]:
    if not query.strip():
        return []
    data = _tmdb_get("/search/person", {"query": query, "page": page, "include_adult": "false"})
    return (data.get("results") or [])[:20]

@st.cache_data(ttl=86400, show_spinner=False)
def _person_details(pid: int) -> dict:
    return _tmdb_get(f"/person/{pid}")

@st.cache_data(ttl=86400, show_spinner=False)
def _person_bio(pid: int) -> dict:
    # biography costuma vir no details; esta chamada extra tem também external_ids
    return _tmdb_get(f"/person/{pid}", {"append_to_response": "external_ids"})

@st.cache_data(ttl=86400, show_spinner=False)
def _person_combined_credits(pid: int) -> dict:
    return _tmdb_get(f"/person/{pid}/combined_credits")

# ------------------------------------------------------------------
# Filmography build
# ------------------------------------------------------------------
def _filmography_df(credits: dict) -> pd.DataFrame:
    rows: list[dict] = []

    for item in (credits.get("cast") or []):
        mt = item.get("media_type")
        title = item.get("title") if mt == "movie" else item.get("name")
        date = item.get("release_date") if mt == "movie" else item.get("first_air_date")
        rows.append({
            "type": "Movie" if mt == "movie" else "Series",
            "title": title or "",
            "year": _year_from_date(date),
            "role": item.get("character") or "",
            "job": "",
            "rating": item.get("vote_average") or 0.0,
            "tmdb_id": item.get("id"),
        })

    for item in (credits.get("crew") or []):
        mt = item.get("media_type")
        title = item.get("title") if mt == "movie" else item.get("name")
        date = item.get("release_date") if mt == "movie" else item.get("first_air_date")
        rows.append({
            "type": "Movie" if mt == "movie" else "Series",
            "title": title or "",
            "year": _year_from_date(date),
            "role": "",
            "job": item.get("job") or "",
            "rating": item.get("vote_average") or 0.0,
            "tmdb_id": item.get("id"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["type","title","year","role","job","rating"])

    # ordena por ano desc, depois rating
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(0.0)
    df["year_i"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)
    df = df.sort_values(["year_i", "rating"], ascending=[False, False]).drop(columns=["year_i"])
    return df

# ------------------------------------------------------------------
# UI
# ------------------------------------------------------------------
def render_artists_page() -> None:
    st.title("🎬 Cinema — Artists")

    if not TMDB_API_KEY:
        st.error("TMDB_API_KEY not configured. Add it to environment or Streamlit secrets.")
        return

    with st.container():
        c1, c2 = st.columns([2, 1])
        name = c1.text_input("Artist name", placeholder="e.g. Geena Davis", key="artists_query")
        page_sel = c2.number_input("Page", min_value=1, value=1, step=1)

        do_search = st.button("Search", type="primary")
        if do_search:
            st.session_state["artists_results"] = _search_people(name, page=int(page_sel))
            st.session_state.pop("artists_selected", None)

    results = st.session_state.get("artists_results", [])

    # Seleção rápida se só houver 1 resultado
    if results and len(results) == 1 and "artists_selected" not in st.session_state:
        st.session_state["artists_selected"] = results[0].get("id")

    # Lista de resultados
    if results and "artists_selected" not in st.session_state:
        st.subheader("Results")
        for p in results:
            pid = p.get("id")
            prof = _img_url(p.get("profile_path"), "w92")
            with st.container(border=True):
                cA, cB, cC = st.columns([0.7, 0.2, 0.1], vertical_alignment="top")
                with cA:
                    st.markdown(f"**{p.get('name','—')}**")
                    st.caption(p.get("known_for_department") or "—")
                    if p.get("known_for"):
                        kn = ", ".join([i.get("title") or i.get("name") or "" for i in p["known_for"]][:4])
                        st.write(kn)
                with cB:
                    if prof:
                        st.image(prof, width=50)
                with cC:
                    if st.button("Open", key=f"open_{pid}"):
                        st.session_state["artists_selected"] = pid
                        st.experimental_rerun()

    # Detalhe do artista
    sel = st.session_state.get("artists_selected")
    if sel:
        det = _person_bio(sel) or {}
        cr = _person_combined_credits(sel) or {}

        name = det.get("name") or "—"
        born = det.get("birthday") or ""
        died = det.get("deathday") or ""
        place = det.get("place_of_birth") or ""
        dept = det.get("known_for_department") or ""
        bio = _clean_bio(det.get("biography") or "")
        prof = _img_url(det.get("profile_path"), "w300")

        # Cabeçalho com poster à direita
        st.markdown("---")
        header = f"**{name}**"
        if born:
            header += f"  \n🗓️ Born: {born}"
        if died:
            header += f"  \n🕯️ Died: {died}"
        if place:
            header += f"  \n📍 {place}"
        if dept:
            header += f"  \n🎭 {dept}"

        cL, cR = st.columns([1, 0.28], vertical_alignment="top")
        with cL:
            st.markdown(header)
            st.markdown("**📜 Biography**")
            st.write(bio)
        with cR:
            if prof:
                st.markdown(
                f"""
                <div style="display:flex;justify-content:flex-end">
                    <img src="{prof}"
                        alt="portrait"
                        style="width:120px;max-width:120px;height:auto;
                                border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.15);" />
                </div>
                """,
                unsafe_allow_html=True,
        )

        # Filmografia
        st.subheader("Filmography")
        df = _filmography_df(cr)

        if df.empty:
            st.info("No credits found.")
            return

        # Filtros simples
        f1, f2, f3 = st.columns([1, 1, 1])
        kind = f1.selectbox("Type", ["All", "Movie", "Series"])
        dept_choice = f2.selectbox("Department", ["All", "Cast (role)", "Crew (job)"])
        q = f3.text_input("Title contains", "")

        fdf = df.copy()
        if kind != "All":
            fdf = fdf[fdf["type"] == kind]
        if dept_choice == "Cast (role)":
            fdf = fdf[(fdf["role"].astype(str).str.strip() != "")]
        elif dept_choice == "Crew (job)":
            fdf = fdf[(fdf["job"].astype(str).str.strip() != "")]
        if q.strip():
            fdf = fdf[fdf["title"].str.contains(q.strip(), case=False, na=False)]

        # Apresentação
        cols = ["type", "title", "year", "role", "job", "rating"]
        fdf = fdf[cols]
        st.dataframe(
            fdf.style.format({"rating": "{:.1f}"}),
            use_container_width=True,
            hide_index=True,
        )

        # Voltar à lista
        st.markdown("")
        if st.button("← Back to results"):
            st.session_state.pop("artists_selected", None)
            st.experimental_rerun()
