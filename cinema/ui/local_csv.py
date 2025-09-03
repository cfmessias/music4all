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

def render_local_results(section: str, local_out: pd.DataFrame) -> None:
    st.subheader("Local results (CSV)")

    if section == "Movies":
        df = local_out.copy()
        if "watched_date" not in df.columns:
            df["watched_date"] = pd.NaT
        else:
            df["watched_date"] = pd.to_datetime(df["watched_date"].replace({"": pd.NA, "NaT": pd.NA}), errors="coerce")
        if "watched" in df.columns:
            df["watched"] = df["watched"].fillna(False).astype(bool)

        view_cols = ["id","title","director","year","genre","streaming","rating","watched","watched_date"]
        for c in view_cols:
            if c not in df.columns:
                df[c] = "" if c != "watched" else False
        local_view = df[view_cols].copy()

        edited = st.data_editor(
            local_view,
            hide_index=True,
            use_container_width=True,
            key=key_for(section, "editor_movies"),
            column_config={
                "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
                "streaming": st.column_config.TextColumn("Streaming"),
                "watched": st.column_config.CheckboxColumn("Watched"),
                "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
            },
        )

        if st.button("Save watched changes", key=key_for(section, "save_watched_movies")):
            base = load_table("Movies"); updates = 0
            edited["watched"] = edited["watched"].fillna(False).astype(bool)
            for _, row in edited.iterrows():
                mid = int(row["id"]); mask = base["id"] == mid
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

    elif section == "Series":
        df = local_out.copy()
        if "watched_date" not in df.columns:
            df["watched_date"] = pd.NaT
        else:
            df["watched_date"] = pd.to_datetime(df["watched_date"].replace({"": pd.NA, "NaT": pd.NA}), errors="coerce")
        if "watched" in df.columns:
            df["watched"] = df["watched"].fillna(False).astype(bool)

        view_cols = ["id","title","creator","season","year_start","year_end","genre","streaming","rating","watched","watched_date"]
        for c in view_cols:
            if c not in df.columns:
                df[c] = "" if c not in ("watched",) else False
        local_view = df[view_cols].copy()

        edited = st.data_editor(
            local_view,
            use_container_width=True,
            hide_index=True,
            key=key_for(section, "editor_series"),
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

        if st.button("Save watched changes (Series)", key=key_for(section, "save_watched_series_local")):
            base = load_table("Series"); updates = 0
            edited["watched"] = edited["watched"].fillna(False).astype(bool)
            for _, row in edited.iterrows():
                sid = int(row["id"]); mask = base["id"] == sid
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

    else:
        show_cols = [c for c in ["id","title","artist","year","genre","rating","notes","related_movie_id","related_series_id"] if c in local_out.columns]
        st.data_editor(
            local_out[show_cols] if show_cols else local_out,
            use_container_width=True,
            hide_index=True,
            key=key_for(section, "editor_st"),
            column_config={
                "year": st.column_config.NumberColumn("year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("rating", format="%.1f", step=0.1),
            },
            disabled=show_cols,
        )
