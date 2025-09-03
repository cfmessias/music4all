# cinema/page.py
from __future__ import annotations
import pandas as pd
import streamlit as st

from .data import load_genres, load_table
from .ui.helpers import key_for, author_label_and_key
from .ui.search import run_search
from .ui.cards import render_remote_results
from .ui.local_csv import render_local_results

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
    genres, _sub_by_gen, genres_path = load_genres()
    #st.caption(f"Genres CSV: `{genres_path}`")
    df_local = load_table(section)

    # ---- Controls ----
    st.subheader("Search")
    c1, c2, _ = st.columns([2, 2, 2])
    title = c1.text_input("Title (contains)", key=key_for(section, "title"))
    author_label, author_key = author_label_and_key(section)
    author_val = c2.text_input(author_label, key=key_for(section, "author"))

    col_g, col_w = st.columns([1, 1])
    genre = col_g.selectbox("Genre", genres, index=0, key=key_for(section, "genre"))

    watched_sel = None
    if section == "Movies":
        watched_sel = col_w.selectbox(
            "Watched", ["All", "Yes", "No"], index=0, key=key_for(section, "watched")
        )
    else:
        col_w.write("")

    c4, c5 = st.columns([1, 1])
    year_txt = c4.text_input(
        "Year (optional — e.g., 1995 or 1990-1999)",
        placeholder="1995 or 1990-1999",
        key=key_for(section, "year"),
    )
    min_rating = c5.slider(
        "Min. rating (optional)", 0.0, 10.0, 0.0, 0.1, key=key_for(section, "minrating")
    )

    online = st.checkbox(
        "Search online (TMDb / Spotify)",
        value=True,
        key=key_for(section, "online"),
        help="Movies/Series: TMDb • Soundtracks: Spotify",
    )

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
        render_remote_results(section, remote, query_title=title)
    else:
        st.info("No online results.")

    # ---- Local results (CSV) ----
    render_local_results(section, local_out)
