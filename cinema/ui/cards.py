# cinema/ui/cards.py
from __future__ import annotations
import pandas as pd
import streamlit as st
from cinema.providers.tmdb import tmdb_poster_url
from cinema.views.spotify_embed import render_player
from .helpers import (
    key_for, title_match_score, artists_from_row_or_fetch, parse_date_like,
    on_click_play, safe_intlike, to_spotify_embed,
    save_watched_item_movies, save_watched_item_series, _norm
)

def render_remote_results(section: str, remote: list[dict], query_title: str) -> None:
    if not remote:
        return
    st.subheader("Online results")

    if section not in ("Movies", "Series"):
        # Soundtracks page simples
        df_sp = pd.DataFrame(remote)
        show_cols = [c for c in ["title", "artist", "year", "url"] if c in df_sp.columns]
        st.data_editor(
            df_sp[show_cols] if show_cols else df_sp,
            use_container_width=True, hide_index=True,
            key=key_for(section, "online_editor_sp"),
            column_config={"year": st.column_config.NumberColumn("year", format="%d", step=1)},
            disabled=show_cols,
        )
        return

    df_remote = pd.DataFrame(remote)
    if df_remote.empty:
        st.info("No results.")
        return

    # Relevância por título (filtro suave)
    if (query_title or "").strip():
        df_remote["__ttl"] = df_remote.get("title", df_remote.get("name", ""))
        df_remote["__score"] = df_remote["__ttl"].apply(lambda s: title_match_score(str(s), query_title))
        thr = 78 if len(_norm(query_title).split()) >= 2 else 65
        df_remote = (
            df_remote[df_remote["__score"] >= thr]
            .sort_values(["__score"], ascending=[False])
            .drop(columns=["__score", "__ttl"], errors="ignore")
            .reset_index(drop=True)
        )

    if df_remote.empty:
        st.info("No results after relevance filter.")
        return

    year_col = "year" if "year" in df_remote.columns else "year_start"
    if year_col not in df_remote.columns:
        df_remote[year_col] = ""

    # Normalizar colunas
    for c in [
        "id","title","name","director","creator","season",
        "genre","genres","streaming","rating","overview",
        "poster_url","poster","image","tmdb_id",
        "web","play_url","notes","notes_text","watched","watched_date",
    ]:
        if c not in df_remote.columns:
            if c == "watched":
                df_remote[c] = False
            elif c == "watched_date":
                df_remote[c] = ""
            else:
                df_remote[c] = ""

    df_remote["notes_text2"] = df_remote.apply(
        lambda row: (str(row.get("notes_text") or "").strip()
                     or str(row.get("notes") or "").strip()
                     or str(row.get("overview") or "").strip()),
        axis=1
    )

    # Paginação
    per_page = 10
    total = len(df_remote)
    total_pages = max(1, (total - 1) // per_page + 1)
    page_key = key_for(section, "page")
    current = int(st.session_state.get(page_key, 1))
    current = max(1, min(current, total_pages))

    colp1, colp2, _ = st.columns([1, 1, 6])
    with colp1:
        if st.button("⟨ Prev", disabled=(current <= 1), key=key_for(section, "pg_prev")):
            current = max(1, current - 1)
            st.session_state.pop(key_for(section, "open_card_id"), None)
    with colp2:
        if st.button("Next ⟩", disabled=(current >= total_pages), key=key_for(section, "pg_next")):
            current = min(total_pages, current + 1)
            st.session_state.pop(key_for(section, "open_card_id"), None)

    st.session_state[page_key] = current
    st.caption(f"Page {current} / {total_pages} • {total} results")

    start, end = (current - 1) * per_page, min(current * per_page, total)
    page_rows = df_remote.iloc[start:end].reset_index(drop=True)

    # Cartões
    for i, r in page_rows.iterrows():
        row = r.to_dict()
        rid = safe_intlike(row.get("id")) or (start + i)
        title_i = row.get("title") or row.get("name") or "—"
        rating = row.get("rating")
        yv = row.get(year_col)

        # Header
        ytxt = ""
        if yv not in (None, "", "nan"):
            try: ytxt = f"{int(float(yv))}"
            except Exception: ytxt = str(yv)
        head_bits = [title_i]
        if ytxt: head_bits.append(f"({ytxt})")
        if pd.notna(rating) and str(rating).strip().lower() not in ("", "nan"):
            try:
                rating_val = float(str(rating).replace(",", "."))
                head_bits.append(f"— ★ {rating_val:.1f}")
            except Exception:
                head_bits.append(f"— ★ {rating}")
        header = " ".join(head_bits).strip()

        # Poster
        poster = row.get("poster_url") or row.get("poster") or row.get("image") or ""
        if not poster:
            y_try = None
            try:
                y_raw = row.get("year") if section == "Movies" else row.get("year_start")
                y_try = int(str(y_raw)[:4]) if y_raw not in (None, "", "nan") else None
            except Exception:
                pass
            poster = tmdb_poster_url(
                "movie" if section == "Movies" else "tv",
                row.get("tmdb_id") or row.get("id"),
                (row.get("title") or row.get("name") or ""),
                y_try,
            )

        is_open = st.session_state.get(key_for(section, "open_card_id")) == rid
        with st.expander(header, expanded=is_open):
            c_left, c_right = st.columns([1, 0.25], vertical_alignment="top")

            with c_left:
                who = row.get("director") if section == "Movies" else row.get("creator")
                gl = row.get("genres") or row.get("genre") or ""
                gl_txt = ", ".join(gl) if isinstance(gl, (list, tuple)) else str(gl)
                streaming = row.get("streaming") or ""
                meta_parts = []
                if who: meta_parts.append(f"**{'Director' if section=='Movies' else 'Creator'}:** {who}")
                if gl_txt.strip(): meta_parts.append(f"**Genres:** {gl_txt}")
                if streaming: meta_parts.append(f"**Streaming:** {streaming}")
                if meta_parts: st.markdown(" • ".join(meta_parts))

                artists_txt = artists_from_row_or_fetch(row, section)
                if artists_txt:
                    st.markdown(f"**Artists:** {artists_txt}")

                st.markdown("**📖 Overview:**")
                st.write((row.get("notes_text2") or "").strip() or "—")

                tmdb_id_val = row.get("tmdb_id") or row.get("id")
                st.button(
                    "🎧 Play soundtrack",
                    key=key_for(section, f"play_{rid}"),
                    on_click=on_click_play,
                    kwargs={"section": section, "rid": rid, "title_i": title_i, "yv": yv, "tmdb_id": tmdb_id_val},
                )
                if st.session_state.get(key_for(section, "play_open_id")) == rid:
                    src = st.session_state.get(key_for(section, "play_src")) or ""
                    msg = st.session_state.get(key_for(section, "play_msg")) or ""
                    if src:
                        h = st.session_state.get(key_for(section, "play_height"), 380)
                        render_player(src, height=h)
                    else:
                        st.info(msg or "🎧 Soundtrack not found")

                # Watched line
                w_key = key_for(section, f"w_{rid}")
                d_key = key_for(section, f"wd_{rid}")
                default_w = bool(row.get("watched"))
                default_d = parse_date_like(row.get("watched_date"))

                cW, cLbl, cD, cSave = st.columns([0.18, 0.16, 0.28, 0.12])
                with cW:
                    w_val = st.checkbox("Watched", value=default_w, key=w_key)
                with cLbl:
                    st.markdown("<div style='padding-top:0.45rem; font-weight:600;'>Watched date</div>", unsafe_allow_html=True)
                with cD:
                    d_val = st.date_input(
                        "Watched date",
                        value=default_d, format="YYYY-MM-DD",
                        key=d_key, label_visibility="collapsed",
                    )
                with cSave:
                    if st.button("💾 Save", key=key_for(section, f"savew_{rid}")):
                        wd_str = str(d_val)[:10] if d_val else ""
                        if section == "Movies":
                            up, ins = save_watched_item_movies(row, w_val, wd_str)
                        else:
                            up, ins = save_watched_item_series(row, w_val, wd_str)
                        st.success(f"Saved: {up} update(s), {ins} new row(s).")

            with c_right:
                if poster:
                    st.image(poster, width=100)
