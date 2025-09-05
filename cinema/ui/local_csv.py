# cinema/ui/local_csv.py
from __future__ import annotations
import pandas as pd
import streamlit as st
from cinema.data import load_table, save_table
from .helpers import key_for

def _to_datestr(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        return v.strftime("%Y-%m-%d")
    except Exception:
        s = str(v).strip()
        return "" if s.lower() in ("", "nat", "none") else s[:10]

def _streaming_as_text(df: pd.DataFrame) -> None:
    """Garante que a coluna 'streaming' é string (para TextColumn no editor)."""
    if "streaming" not in df.columns:
        df["streaming"] = ""
    else:
        df["streaming"] = df["streaming"].apply(
            lambda v: "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)
        )

def _safe_int(v):
    try:
        return int(v)
    except Exception:
        return None

def _post_save_refresh(section: str, df_new: pd.DataFrame):
    # Atualiza a store local no estado e tenta forçar rerun (se disponível)
    st.session_state[key_for(section, "local_store")] = df_new.copy()
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()

def render_local_results(section: str, local_out: pd.DataFrame) -> None:
    st.subheader("Local results (CSV)")

    if section == "Movies":
        df = local_out.copy()

        # Tipagem saudável
        if "watched_date" not in df.columns:
            df["watched_date"] = pd.NaT
        else:
            df["watched_date"] = pd.to_datetime(
                df["watched_date"].replace({"": pd.NA, "NaT": pd.NA}),
                errors="coerce"
            )
        if "watched" in df.columns:
            df["watched"] = df["watched"].fillna(False).astype(bool)

        _streaming_as_text(df)  # manter nomes dos fornecedores (texto)

        view_cols = ["delete","id","title","director","year","genre","streaming","rating","watched","watched_date"]
        for c in view_cols:
            if c not in df.columns:
                df[c] = (
                    False if c in ("watched", "delete") else
                    ""    if c != "year" else pd.NA
                )

        # numéricos
        if "year" in df.columns:
            df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        if "rating" in df.columns:
            df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

        local_view = df[view_cols].copy()

        edited = st.data_editor(
            local_view,
            hide_index=True,
            use_container_width=True,
            key=key_for(section, "editor_movies"),
            column_config={
                "delete": st.column_config.CheckboxColumn("Delete"),
                "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
                "streaming": st.column_config.TextColumn("Streaming"),
                "watched": st.column_config.CheckboxColumn("Watched"),
                "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
            },
            # Só editar o que é persistido + delete
            disabled=["id","title","director","year","genre","streaming","rating"],
        )

        col_a, col_b = st.columns([1,1])
        with col_a:
            if st.button("Save watched changes", key=key_for(section, "save_watched_movies")):
                base = load_table("Movies"); updates = 0
                edited["watched"] = edited["watched"].fillna(False).astype(bool)
                for _, row in edited.iterrows():
                    mid = _safe_int(row["id"])
                    if mid is None: continue
                    mask = base["id"] == mid
                    if not mask.any(): continue
                    chg = False
                    if bool(base.loc[mask, "watched"].iloc[0]) != bool(row["watched"]):
                        base.loc[mask, "watched"] = bool(row["watched"]); chg = True
                    wd_str = _to_datestr(row.get("watched_date"))
                    if str(base.loc[mask, "watched_date"].iloc[0] or "") != wd_str:
                        base.loc[mask, "watched_date"] = wd_str; chg = True
                    if chg: updates += 1
                save_table("Movies", base)
                st.success(f"Saved {updates} change(s).")
                _post_save_refresh(section, base)

        with col_b:
            if st.button("Delete selected (Movies)", type="secondary", key=key_for(section, "delete_movies")):
                to_del = [ _safe_int(r["id"]) for _, r in edited.iterrows() if bool(r.get("delete")) ]
                to_del = [i for i in to_del if i is not None]
                if not to_del:
                    st.info("No rows marked for deletion.")
                else:
                    base = load_table("Movies")
                    before = len(base)
                    base = base[~base["id"].isin(to_del)].copy()
                    removed = before - len(base)
                    save_table("Movies", base)
                    st.success(f"Deleted {removed} row(s).")
                    _post_save_refresh(section, base)

    elif section == "Series":
        df = local_out.copy()

        # Tipagem saudável
        if "watched_date" not in df.columns:
            df["watched_date"] = pd.NaT
        else:
            df["watched_date"] = pd.to_datetime(
                df["watched_date"].replace({"": pd.NA, "NaT": pd.NA}),
                errors="coerce"
            )
        if "watched" in df.columns:
            df["watched"] = df["watched"].fillna(False).astype(bool)

        _streaming_as_text(df)  # manter nomes dos fornecedores (texto)

        view_cols = ["delete","id","title","creator","season","year_start","year_end","genre","streaming","rating","watched","watched_date"]
        for c in view_cols:
            if c not in df.columns:
                df[c] = (
                    False if c in ("watched", "delete") else
                    ""    if c not in ("season","year_start","year_end") else pd.NA
                )

        # numéricos
        for col in ("season","year_start","year_end"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        if "rating" in df.columns:
            df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

        local_view = df[view_cols].copy()

        edited = st.data_editor(
            local_view,
            use_container_width=True,
            hide_index=True,
            key=key_for(section, "editor_series"),
            column_config={
                "delete": st.column_config.CheckboxColumn("Delete"),
                "season": st.column_config.NumberColumn("Season", format="%d", step=1),
                "year_start": st.column_config.NumberColumn("Year start", format="%d", step=1),
                "year_end": st.column_config.NumberColumn("Year end", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
                "streaming": st.column_config.TextColumn("Streaming"),
                "watched": st.column_config.CheckboxColumn("Watched"),
                "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
            },
            disabled=["id","title","creator","season","year_start","year_end","genre","streaming","rating"],
        )

        col_a, col_b = st.columns([1,1])
        with col_a:
            if st.button("Save watched changes (Series)", key=key_for(section, "save_watched_series_local")):
                base = load_table("Series"); updates = 0
                edited["watched"] = edited["watched"].fillna(False).astype(bool)
                for _, row in edited.iterrows():
                    sid = _safe_int(row["id"])
                    if sid is None: continue
                    mask = base["id"] == sid
                    if not mask.any(): continue
                    chg = False
                    if bool(base.loc[mask, "watched"].iloc[0]) != bool(row["watched"]):
                        base.loc[mask, "watched"] = bool(row["watched"]); chg = True
                    wd_str = _to_datestr(row.get("watched_date"))
                    if str(base.loc[mask, "watched_date"].iloc[0] or "") != wd_str:
                        base.loc[mask, "watched_date"] = wd_str; chg = True
                    if chg: updates += 1
                save_table("Series", base)
                st.success(f"Saved {updates} change(s).")
                _post_save_refresh(section, base)

        with col_b:
            if st.button("Delete selected (Series)", type="secondary", key=key_for(section, "delete_series")):
                to_del = [ _safe_int(r["id"]) for _, r in edited.iterrows() if bool(r.get("delete")) ]
                to_del = [i for i in to_del if i is not None]
                if not to_del:
                    st.info("No rows marked for deletion.")
                else:
                    base = load_table("Series")
                    before = len(base)
                    base = base[~base["id"].isin(to_del)].copy()
                    removed = before - len(base)
                    save_table("Series", base)
                    st.success(f"Deleted {removed} row(s).")
                    _post_save_refresh(section, base)

    else:
        # Soundtracks: leitura + apagar
        df = local_out.copy()
        # preparar colunas
        show_cols = ["delete","id","title","artist","year","genre","rating","notes","related_movie_id","related_series_id"]
        for c in show_cols:
            if c not in df.columns:
                df[c] = "" if c not in ("delete",) else False
        if "year" in df.columns:
            df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        if "rating" in df.columns:
            df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

        edited = st.data_editor(
            df[show_cols],
            use_container_width=True,
            hide_index=True,
            key=key_for(section, "editor_st"),
            column_config={
                "delete": st.column_config.CheckboxColumn("Delete"),
                "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
            },
            disabled=["id","title","artist","year","genre","rating","notes","related_movie_id","related_series_id"],
        )

        if st.button("Delete selected (Soundtracks)", type="secondary", key=key_for(section, "delete_st")):
            to_del = [ _safe_int(r["id"]) for _, r in edited.iterrows() if bool(r.get("delete")) ]
            to_del = [i for i in to_del if i is not None]
            if not to_del:
                st.info("No rows marked for deletion.")
            else:
                base = load_table("Soundtracks")
                before = len(base)
                base = base[~base["id"].isin(to_del)].copy()
                removed = before - len(base)
                save_table("Soundtracks", base)
                st.success(f"Deleted {removed} row(s).")
                _post_save_refresh(section, base)
