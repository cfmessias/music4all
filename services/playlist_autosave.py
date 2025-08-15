import os
import pandas as pd
import streamlit as st
from typing import List, Dict, Any

CSV_DEFAULT = "playlists.csv"
COLUMNS = ["PlaylistName", "Title", "Artists", "Album", "TrackID", "TrackURI", "Duration"]

def _csv_path() -> str:
    try:
        return st.secrets.get("PLAYLISTS_CSV_PATH", CSV_DEFAULT)  # type: ignore[attr-defined]
    except Exception:
        return CSV_DEFAULT

def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[COLUMNS]

def autosave_append_rows(playlist_name: str, rows: List[Dict[str, Any]], csv_path: str | None = None) -> int:
    """Append rows to playlists.csv with an extra column PlaylistName.
    De-duplicates on (PlaylistName, TrackURI) when TrackURI exists; else on (PlaylistName, Title, Artists, Album).
    Returns number of rows written after dedupe (delta may be <= len(rows)).
    """
    if not rows:
        return 0
    path = csv_path or _csv_path()

    df_new = pd.DataFrame(rows).copy()
    if df_new.empty:
        return 0

    df_new["PlaylistName"] = playlist_name
    df_new = _ensure_cols(df_new)

    if "TrackURI" in df_new.columns and df_new["TrackURI"].notna().any():
        keys = ["PlaylistName", "TrackURI"]
    else:
        keys = ["PlaylistName", "Title", "Artists", "Album"]

    if os.path.exists(path):
        try:
            df_old = pd.read_csv(path)
        except Exception:
            df_old = pd.DataFrame(columns=COLUMNS)
    else:
        df_old = pd.DataFrame(columns=COLUMNS)

    df_old = _ensure_cols(df_old)
    before_old = len(df_old)

    df_all = pd.concat([df_old, df_new], ignore_index=True)
    df_all.drop_duplicates(subset=keys, keep="first", inplace=True)

    df_all.to_csv(path, index=False)
    return max(0, len(df_all) - before_old)
