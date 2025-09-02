# cinema/page.py
from __future__ import annotations

import pandas as pd
import streamlit as st

from .data import load_genres, load_table, save_table
from .filters import apply_filters
from .providers.tmdb import tmdb_search_movies_advanced, tmdb_search_series_advanced
from .providers.spotify import search_soundtrack_albums, pick_best_soundtrack
from .views.spotify_embed import render_player   # embebe player do Spotify


# ------------------------ Helpers ------------------------

def _key(section: str, name: str) -> str:
    return f"cin_{section}_{name}"

def _author_label_and_key(section: str) -> tuple[str, str]:
    if section == "Movies":
        return "Director (contains)", "director"
    if section == "Series":
        return "Creator (contains)", "creator"
    return "Artist (contains)", "artist"

def _to_spotify_embed(url_or_uri: str) -> str:
    """Converte URL/URI do Spotify para URL do player embed (caso precises de abrir noutra aba)."""
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

# ---- UI helpers (info e player Spotify embutido) ----
def _toggle_info(section: str, row_id):
    k = _key(section, "info_open")
    cur = st.session_state.get(k)
    st.session_state[k] = None if cur == row_id else row_id

def _play_spotify_inline(section: str, url_or_uri: str, row_id):
    st.session_state[_key(section, "spfy_url")] = url_or_uri
    st.session_state[_key(section, "spfy_row")] = row_id
    st.session_state[_key(section, "spfy_rev")] = st.session_state.get(_key(section, "spfy_rev"), 0) + 1

def _render_spotify_if_current(section: str, row_id):
    url = st.session_state.get(_key(section, "spfy_url")) or ""
    if st.session_state.get(_key(section, "spfy_row")) != row_id or not url:
        return
    # Altura compacta típica (álbum/playlist)
    render_player(url, height=152)


# ------------------------ Page ------------------------

def render_cinema_page(section: str = "Movies") -> None:
    """Streamlit page para Cinema: Movies | Series | Soundtracks."""
    st.title(f"🎬 Cinema — {section}")

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
        # Local (CSV)
        filters = {
            "title": title,
            "genre": genre,
            "year": year_txt,
            "min_rating": min_rating,
            author_key: author_val,
            "watched": watched_sel if section == "Movies" else None,
        }
        local_out = apply_filters(section, df, filters)

        # Online
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

        # Guardar resultados para persistir entre reruns
        st.session_state[_key(section, "remote_store")] = remote
        st.session_state[_key(section, "local_store")] = local_out

    # Render com dados persistidos
    remote = st.session_state.get(_key(section, "remote_store"), [])
    local_out = st.session_state.get(_key(section, "local_store"), pd.DataFrame())

    # ---- Online results ----
    if remote:
        st.subheader("Online results")

        if section in ("Movies", "Series"):
            df_remote = pd.DataFrame(remote)

            # coluna de ano a usar
            year_col = "year" if "year" in df_remote.columns else "year_start"

            # garantir colunas Watched/Date em ambos
            if "watched" not in df_remote.columns:
                df_remote["watched"] = False
            if "watched_date" not in df_remote.columns:
                df_remote["watched_date"] = ""

            # Spotify links (cache)
            def _resolve(row):
                info = _ost_link_cached(str(row.get("title", "")), row.get(year_col))
                web = info.get("url", "")
                uri = info.get("uri", "")
                return pd.Series({
                    "web": web,                               # Spotify Web
                    "play_url": _to_spotify_embed(web or uri) # Spotify embed (caso abras noutra aba)
                })

            if not df_remote.empty:
                extra = df_remote.apply(_resolve, axis=1)
                df_remote = pd.concat([df_remote, extra], axis=1)
                # Notes → guardar texto e mostrar ícone
                if "notes" in df_remote.columns:
                    df_remote["notes_text"] = df_remote["notes"].fillna("").astype(str)
                    df_remote = df_remote.drop(columns=["notes"])
                else:
                    df_remote["notes_text"] = ""

            # colunas a mostrar no editor (para Series inclui 'season' quando existir)
            base_cols = [
                "title",
                "director" if section == "Movies" else "creator",
            ]
            if section == "Series" and "season" in df_remote.columns:
                base_cols.append("season")
            base_cols += [
                year_col,
                "genre", "genres", "streaming", "rating",
                "watched", "watched_date",
                
            ]
            show_cols = [c for c in base_cols if c in df_remote.columns]

            # Converter watched_date para datetime (evita erro do editor)
            if "watched_date" in df_remote.columns:
                df_remote["watched_date"] = pd.to_datetime(df_remote["watched_date"], errors="coerce")
            # === AÇÕES PARA CONTROLAR O QUICK (ADICIONA ISTO ANTES DO st.data_editor) ===
            df_remote = df_remote.reset_index(drop=True).copy()
            df_remote["row_key"] = df_remote.index.astype(str)

            # Links internos (não abrem nova aba): só colocam query params para o Quick
            df_remote["act_play"] = df_remote["row_key"].apply(lambda k: f"?cinsec={section}&quick=play&row={k}")
            df_remote["act_info"] = df_remote["row_key"].apply(lambda k: f"?cinsec={section}&quick=info&row={k}")

            # Garante que aparecem na grelha
            if "act_play" not in show_cols: show_cols.append("act_play")
            if "act_info" not in show_cols: show_cols.append("act_info")

            # --- Editor (continua a permitir marcar watched e data) ---
            edited = st.data_editor(
                df_remote[show_cols],
                use_container_width=True,
                hide_index=True,
                key=_key(section, "online_editor"),
                column_config={
                    year_col: st.column_config.NumberColumn(year_col, format="%d", step=1),
                    "season": st.column_config.NumberColumn("season", format="%d", step=1),
                    "rating": st.column_config.NumberColumn("rating", format="%.1f", step=0.1),
                    "genres": st.column_config.TextColumn("genres"),
                    "streaming": st.column_config.TextColumn("streaming"),
                    # watched (editável)
                    "watched": st.column_config.CheckboxColumn("Watched"),
                    "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
                    # spotify (só links informativos)
                    "act_play": st.column_config.LinkColumn(" ", display_text="🎧", help="Ver player no Quick"),
                    "act_info": st.column_config.LinkColumn("Notes", display_text="ℹ️", help="Ver notas no Quick"),

                },
                disabled=[
                    # não bloquear watched/watched_date
                    "title", "director", "creator", "season", year_col,
                    "genre", "genres", "streaming", "rating",
                    "act_play", "act_info",
                ],
            )

            # --- Ações de salvar watched a partir do editor (mantido) ---
            if section == "Movies" and st.button("Save watched from online list", key=_key(section, "save_w_online_movies")):
                base_df = load_table("Movies")
                updates, inserts = 0, 0

                def _safe_year(v):
                    s = str(v)
                    return int(s) if s.isdigit() else None

                for _, r in edited.iterrows():
                    if not bool(r.get("watched")):
                        continue
                    y = _safe_year(r.get(year_col))
                    title_r = str(r.get("title", "")).strip().casefold()
                    mask = (base_df["title"].astype(str).str.casefold() == title_r)
                    if y is not None and "year" in base_df.columns:
                        mask &= (pd.to_numeric(base_df["year"], errors="coerce") == y)

                    if mask.any():
                        wd = (str(r.get("watched_date") or "")[:10])
                        if (base_df.loc[mask, "watched"].iloc[0] != True) or (str(base_df.loc[mask, "watched_date"].iloc[0]) != wd):
                            base_df.loc[mask, "watched"] = True
                            if "watched_date" in base_df.columns:
                                base_df.loc[mask, "watched_date"] = wd
                            updates += 1
                    else:
                        new_id = int(base_df["id"].max()) + 1 if not base_df.empty else 1
                        base_df.loc[len(base_df)] = {
                            "id": new_id,
                            "title": r.get("title", ""),
                            "director": r.get("director", ""),
                            "year": y or "",
                            "genre": r.get("genre", ""),
                            "streaming": r.get("streaming", ""),
                            "rating": r.get("rating", "") or "",
                            "notes": "",
                            "watched": True,
                            "watched_date": (str(r.get("watched_date") or "")[:10]) if "watched_date" in base_df.columns else "",
                        }
                        inserts += 1

                save_table("Movies", base_df)
                st.success(f"Saved watched (Movies): {updates} update(s), {inserts} new row(s).")

            if section == "Series" and st.button("Save watched from online list", key=_key(section, "save_w_online_series")):
                base_df = load_table("Series")
                updates, inserts = 0, 0

                def _safe_year(v):
                    s = str(v)
                    return int(s) if s.isdigit() else None

                for _, r in edited.iterrows():
                    if not bool(r.get("watched")):
                        continue
                    ys = _safe_year(r.get("year_start"))
                    season = r.get("season")
                    title_r = str(r.get("title", "")).strip().casefold()

                    mask = (base_df["title"].astype(str).str.casefold() == title_r)
                    if "season" in base_df.columns:
                        mask &= (pd.to_numeric(base_df["season"], errors="coerce") == pd.to_numeric(pd.Series([season]), errors="coerce").iloc[0])
                    if ys is not None and "year_start" in base_df.columns:
                        mask &= (pd.to_numeric(base_df["year_start"], errors="coerce") == ys)

                    if mask.any():
                        wd = (str(r.get("watched_date") or "")[:10])
                        if (base_df.loc[mask, "watched"].iloc[0] != True) or (str(base_df.loc[mask, "watched_date"].iloc[0]) != wd):
                            base_df.loc[mask, "watched"] = True
                            base_df.loc[mask, "watched_date"] = wd
                            updates += 1
                    else:
                        new_id = int(base_df["id"].max()) + 1 if not base_df.empty else 1
                        base_df.loc[len(base_df)] = {
                            "id": new_id,
                            "title": r.get("title", ""),
                            "creator": r.get("creator", ""),
                            "season": int(season) if str(season).isdigit() else season,
                            "year_start": ys or "",
                            "year_end": r.get("year_end", "") or "",
                            "genre": r.get("genre", ""),
                            "streaming": r.get("streaming", ""),
                            "rating": r.get("rating", "") or "",
                            "notes": "",
                            "watched": True,
                            "watched_date": (str(r.get("watched_date") or "")[:10]),
                        }
                        inserts += 1

                save_table("Series", base_df)
                st.success(f"Saved watched (Series): {updates} update(s), {inserts} new row(s).")

            # --- Cartões com ℹ️ (expander) + 🎧 (Spotify embutido) por item ---
            # === QUICK VIEW & PLAY (MOSTRA APENAS O ITEM CLICADO NA TABELA) ===
        st.markdown("#### Quick view & play")

        def _qp_one(name: str):
            v = st.query_params.get(name)
            if isinstance(v, list):
                return v[0] if v else None
            return v

        # Só reage se o clique veio desta secção
        if _qp_one("cinsec") == section:
            row_key = _qp_one("row")
            quick   = _qp_one("quick")  # "play" ou "info"

            idx = int(row_key) if row_key and row_key.isdigit() else None
            if idx is not None and 0 <= idx < len(df_remote):
                sel = df_remote.iloc[idx]

                if quick == "info":
                    # notas: notes_text > notes > overview
                    notes_txt = (
                        str(sel.get("notes_text") or "").strip()
                        or str(sel.get("notes") or "").strip()
                        or str(sel.get("overview") or "").strip()
                    )
                    with st.expander("Overview", expanded=True):
                        st.write(notes_txt or "—")

                elif quick == "play":
                    # player: tenta play_url > web; senão resolve por cache
                    url_or_uri = (
                        str(sel.get("play_url") or "").strip()
                        or str(sel.get("web") or "").strip()
                    )
                    if not url_or_uri:
                        t = sel.get("title") or sel.get("name") or ""
                        y = sel.get("year") if "year" in sel else sel.get("year_start")
                        got = _ost_link_cached(t, y)
                        url_or_uri = (got or {}).get("url") or (got or {}).get("uri") or ""

                    # força formato embed quando for URL web
                    if url_or_uri and "open.spotify.com" in url_or_uri and "/embed/" not in url_or_uri:
                        url_or_uri = _to_spotify_embed(url_or_uri)

                    if url_or_uri:
                        with st.expander("Soundtrack", expanded=True):
                            render_player(url_or_uri, height=152)
                    else:
                        st.info("No soundtrack found on Spotify.")

            # limpa apenas os nossos parâmetros (para não “colar” entre pesquisas/cliques)
            for k in ("cinsec", "quick", "row"):
                if k in st.query_params:
                    del st.query_params[k]


        else:  # página Soundtracks
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
                if chg: updates += 1
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
                if chg: updates += 1
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
