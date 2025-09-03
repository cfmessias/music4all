# cinema/local_results.py
from __future__ import annotations
import pandas as pd
import streamlit as st
from .data import load_table, save_table
from .helpers import key, to_datestr

def render_local_movies(local_out: pd.DataFrame, section_key: str = "Movies") -> None:
    st.subheader("Local results (CSV)")
    local_out = local_out.copy()

    # tipos corretos
    if "watched_date" not in local_out.columns:
        local_out["watched_date"] = pd.NaT
    else:
        local_out["watched_date"] = pd.to_datetime(
            local_out["watched_date"].replace({"": pd.NA, "NaT": pd.NA}),
            errors="coerce"
        )
    if "watched" in local_out.columns:
        local_out["watched"] = local_out["watched"].fillna(False).astype(bool)

    view_cols = ["id","title","director","year","genre","streaming","rating","watched","watched_date"]
    for c in view_cols:
        if c not in local_out.columns:
            local_out[c] = "" if c != "watched" else False
    local_view = local_out[view_cols].copy()

    edited = st.data_editor(
        local_view,
        hide_index=True,
        use_container_width=True,
        key=key(section_key, "editor_movies"),
        column_config={
            "year": st.column_config.NumberColumn("Year", format="%d", step=1),
            "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
            "streaming": st.column_config.TextColumn("Streaming"),
            "watched": st.column_config.CheckboxColumn("Watched"),
            "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
        },
    )

    if st.button("Save watched changes", key=key(section_key, "save_watched_movies")):
        base_df = load_table("Movies")
        updates = 0
        edited["watched"] = edited["watched"].fillna(False).astype(bool)
        for _, row in edited.iterrows():
            mid = int(row["id"])
            mask = base_df["id"] == mid
            if not mask.any():
                continue
            chg = False
            w_new = bool(row["watched"])
            if bool(base_df.loc[mask, "watched"].iloc[0]) != w_new:
                base_df.loc[mask, "watched"] = w_new; chg = True
            wd_str = to_datestr(row.get("watched_date"))
            if str(base_df.loc[mask, "watched_date"].iloc[0] or "") != wd_str:
                base_df.loc[mask, "watched_date"] = wd_str; chg = True
            if chg:
                updates += 1
        save_table("Movies", base_df)
        st.success(f"Saved {updates} change(s).")

def render_local_series(local_out: pd.DataFrame, section_key: str = "Series") -> None:
    st.subheader("Local results (CSV)")
    local_out = local_out.copy()

    if "watched_date" not in local_out.columns:
        local_out["watched_date"] = pd.NaT
    else:
        local_out["watched_date"] = pd.to_datetime(
            local_out["watched_date"].replace({"": pd.NA, "NaT": pd.NA}),
            errors="coerce"
        )
    if "watched" in local_out.columns:
        local_out["watched"] = local_out["watched"].fillna(False).astype(bool)

    view_cols = ["id","title","creator","season","year_start","year_end","genre","streaming","rating","watched","watched_date"]
    for c in view_cols:
        if c not in local_out.columns:
            local_out[c] = "" if c != "watched" else False
    local_view = local_out[view_cols].copy()

    edited = st.data_editor(
        local_view,
        use_container_width=True,
        hide_index=True,
        key=key(section_key, "editor_series"),
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

    if st.button("Save watched changes (Series)", key=key(section_key, "save_watched_series_local")):
        base_df = load_table("Series")
        updates = 0
        edited["watched"] = edited["watched"].fillna(False).astype(bool)
        for _, row in edited.iterrows():
            sid = int(row["id"])
            mask = base_df["id"] == sid
            if not mask.any():
                continue
            chg = False
            w_new = bool(row["watched"])
            if bool(base_df.loc[mask, "watched"].iloc[0]) != w_new:
                base_df.loc[mask, "watched"] = w_new; chg = True
            wd_str = to_datestr(row.get("watched_date"))
            if str(base_df.loc[mask, "watched_date"].iloc[0] or "") != wd_str:
                base_df.loc[mask, "watched_date"] = wd_str; chg = True
            if chg:
                updates += 1
        save_table("Series", base_df)
        st.success(f"Saved {updates} change(s).")
