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

        _streaming_as_text(df)  # <- manter nomes dos fornecedores (texto)

        view_cols = ["id","title","director","year","genre","streaming","rating","watched","watched_date"]
        for c in view_cols:
            if c not in df.columns:
                df[c] = "" if c not in ("watched",) else False

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
                "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
                "streaming": st.column_config.TextColumn("Streaming"),  # <- texto (read-only)
                "watched": st.column_config.CheckboxColumn("Watched"),
                "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
            },
            # Só editar o que é persistido pelos botões abaixo
            disabled=["id","title","director","year","genre","streaming","rating"],
        )

        if st.button("Save watched changes", key=key_for(section, "save_watched_movies")):
            base = load_table("Movies"); updates = 0
            edited["watched"] = edited["watched"].fillna(False).astype(bool)
            for _, row in edited.iterrows():
                try:
                    mid = int(row["id"])
                except Exception:
                    continue
                mask = base["id"] == mid
                if not mask.any():
                    continue
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

        _streaming_as_text(df)  # <- manter nomes dos fornecedores (texto)

        view_cols = ["id","title","creator","season","year_start","year_end","genre","streaming","rating","watched","watched_date"]
        for c in view_cols:
            if c not in df.columns:
                df[c] = "" if c not in ("watched",) else False

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
                "season": st.column_config.NumberColumn("Season", format="%d", step=1),
                "year_start": st.column_config.NumberColumn("Year start", format="%d", step=1),
                "year_end": st.column_config.NumberColumn("Year end", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
                "streaming": st.column_config.TextColumn("Streaming"),  # <- texto (read-only)
                "watched": st.column_config.CheckboxColumn("Watched"),
                "watched_date": st.column_config.DateColumn("Watched date", format="YYYY-MM-DD"),
            },
            # Só editar o que é persistido pelos botões abaixo
            disabled=["id","title","creator","season","year_start","year_end","genre","streaming","rating"],
        )

        if st.button("Save watched changes (Series)", key=key_for(section, "save_watched_series_local")):
            base = load_table("Series"); updates = 0
            edited["watched"] = edited["watched"].fillna(False).astype(bool)
            for _, row in edited.iterrows():
                try:
                    sid = int(row["id"])
                except Exception:
                    continue
                mask = base["id"] == sid
                if not mask.any():
                    continue
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
        # Soundtracks: apenas leitura
        df = local_out.copy()
        show_cols = [c for c in ["id","title","artist","year","genre","rating","notes","related_movie_id","related_series_id"] if c in df.columns]
        st.data_editor(
            df[show_cols] if show_cols else df,
            use_container_width=True,
            hide_index=True,
            key=key_for(section, "editor_st"),
            column_config={
                "year": st.column_config.NumberColumn("Year", format="%d", step=1),
                "rating": st.column_config.NumberColumn("Rating", format="%.1f", step=0.1),
            },
            disabled=True,
        )
