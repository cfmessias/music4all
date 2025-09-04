# cinema/page.py
from __future__ import annotations
import os
from datetime import date
import pandas as pd
import streamlit as st

from .data import load_genres, load_table
from .ui.helpers import key_for, author_label_and_key
from .ui.search import run_search
from .ui.cards import render_remote_results
from .ui.local_csv import render_local_results

# ===== Região por defeito para providers (pode vir de env/secrets) =====
TMDB_REGION_DEFAULT = (
    os.getenv("TMDB_REGION", "")
    or (st.secrets.get("TMDB_REGION") if hasattr(st, "secrets") else "")
    or "PT"
)

# Lista compacta de países/region codes
COUNTRY_CHOICES = [
    ("Portugal", "PT"),
    ("United States", "US"),
    ("United Kingdom", "GB"),
    ("Spain", "ES"),
    ("France", "FR"),
    ("Germany", "DE"),
    ("Italy", "IT"),
    ("Netherlands", "NL"),
    ("Brazil", "BR"),
    ("Mexico", "MX"),
    ("Canada", "CA"),
    ("Australia", "AU"),
    ("Argentina", "AR"),
    ("Chile", "CL"),
    ("Colombia", "CO"),
    ("India", "IN"),
    ("Japan", "JP"),
    ("South Korea", "KR"),
]


def _parse_date_like(v):
    if not v:
        return None
    s = str(v)[:10]
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _lookup_local_watched(section: str, title: str, year_val) -> tuple[bool, str]:
    """Procura no CSV (Movies/Series) por título + ano e devolve (watched, watched_date)."""
    base = load_table("Movies" if section == "Movies" else "Series").copy()
    if base.empty:
        return False, ""
    base["__t"] = base["title"].astype(str).str.strip().str.casefold()
    t = (title or "").strip().casefold()
    ycol = "year" if section == "Movies" else "year_start"

    mask = base["__t"] == t
    if ycol in base.columns and year_val not in (None, "", "nan"):
        try:
            y = int(str(year_val)[:4])
            mask &= (pd.to_numeric(base[ycol], errors="coerce") == y)
        except Exception:
            pass

    row = base.loc[mask].head(1)
    if row.empty:
        return False, ""
    w = bool(row.iloc[0].get("watched", False))
    wd = str(row.iloc[0].get("watched_date") or "")
    return w, wd


def render_cinema_page(section: str = "Movies") -> None:
    st.title(f"🎬 Cinema — {section}")

    # Toggle player compacto (opcional)
    st.session_state.setdefault("spfy_compact", False)
    st.session_state["spfy_compact"] = st.toggle(
        "Compact soundtrack player",
        value=st.session_state["spfy_compact"],
        help="Quando ativo, toca a 1ª faixa (player baixo). Desativado: embebe o álbum/playlist completo.",
        key=key_for(section, "spfy_compact_toggle"),
    )

    # ---- Genres & CSV base ----
    genres, _sub_by_gen, _genres_path = load_genres()
    df_local = load_table(section)

    # ---- Controls ----
    # ---- Controls (compact 2 rows) ----
    st.subheader("Search")

    # Row 1: Title | Director/Creator | Year | Min rating
    r1_c1, r1_c2, r1_c3, r1_c4 = st.columns([2.2, 2.0, 1.2, 1.2])

    with r1_c1:
        st.caption("Title (contains)")
        title = st.text_input(
            "", key=key_for(section, "title"),
            label_visibility="collapsed",
            placeholder="e.g., The Long Kiss Goodnight"
        )

    with r1_c2:
        author_label, author_key = author_label_and_key(section)
        st.caption(author_label)
        author_val = st.text_input(
            "", key=key_for(section, "author"),
            label_visibility="collapsed",
            placeholder="e.g., Renny Harlin" if section == "Movies" else "e.g., Vince Gilligan"
        )

    with r1_c3:
        st.caption("Year (1995 or 1990-1999)")
        year_txt = st.text_input(
            "", key=key_for(section, "year"),
            label_visibility="collapsed",
            placeholder="1996 or 1990-1999"
        )

    with r1_c4:
        st.caption("Min. rating (★)")
        min_rating = st.slider(
            "", 0.0, 10.0, 0.0, 0.1,
            key=key_for(section, "minrating"),
            label_visibility="collapsed"
        )

    # Row 2: Genre | Watched | Search online | Streaming country
    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns([1.6, 1.0, 1.2, 1.6])

    with r2_c1:
        st.caption("Genre")
        genre = st.selectbox(
            "", genres, index=0, key=key_for(section, "genre"),
            label_visibility="collapsed"
        )

    with r2_c2:
        st.caption("Watched")
        watched_sel = st.selectbox(
            "", ["All", "Yes", "No"], index=0,
            key=key_for(section, "watched"),
            label_visibility="collapsed",
        )

    with r2_c3:
        st.caption("Search online (TMDb / Spotify)")
        online = st.toggle(
            "", value=True, key=key_for(section, "online"),
            label_visibility="collapsed",
            help="Quando desligado, só pesquisa no CSV local."
        )

    with r2_c4:
        st.caption("Streaming country")
        # usa COUNTRY_CHOICES e TMDB_REGION_DEFAULT já definidos no ficheiro
        default_idx = next((i for i, (_, code) in enumerate(COUNTRY_CHOICES)
                            if code == TMDB_REGION_DEFAULT), 0)
        country_name = st.selectbox(
            "", options=[n for (n, _) in COUNTRY_CHOICES],
            index=default_idx, key=key_for(section, "region_name"),
            label_visibility="collapsed"
        )
        REGION_SELECTED = dict(COUNTRY_CHOICES)[country_name]
        st.session_state[key_for(section, "region_code")] = REGION_SELECTED


    # ---- Search ----
    if st.button("Search", key=key_for(section, "go"), type="primary"):
        local_out, remote = run_search(
            section, df_local,
            title=title, genre=genre, year_txt=year_txt, min_rating=min_rating,
            author_key=author_key, author_val=author_val, watched_sel=watched_sel,
            online=online,
        )
        st.session_state[key_for(section, "remote_store")] = remote
        st.session_state[key_for(section, "local_store")] = local_out

    # Estado persistente
    remote = st.session_state.get(key_for(section, "remote_store"), [])
    local_out = st.session_state.get(key_for(section, "local_store"), df_local.copy())

    # ---- Online results (cartões) ----
    if remote:
        region_code = st.session_state.get(key_for(section, "region_code"), TMDB_REGION_DEFAULT)
        render_remote_results(section, remote, query_title=title, region_code=region_code)
    else:
        st.info("No online results.")

    # ---- Local results (CSV) ----
    render_local_results(section, local_out)
