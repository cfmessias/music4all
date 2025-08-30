# views/genres/search.py
import streamlit as st
from services.genre_csv import build_indices, norm

@st.cache_data(ttl=86400, show_spinner=False)
def build_indices_cached(df):
    return build_indices(df)

@st.cache_data(ttl=86400, show_spinner=False)
def flatten_all_paths(df):
    children, leaves, roots, leaf_url = build_indices(df)
    paths_set = set()
    level_cols = [c for c in df.columns if c.startswith("H")]
    level_cols.sort(key=lambda x: int(x[1:]) if x[1:].isdigit() else 99)
    for _, row in df.iterrows():
        cur = []
        for col in level_cols:
            val = (row.get(col) or "").strip()
            if not val: break
            cur.append(val)
            paths_set.add(tuple(cur))
    url_by_path = {}
    for _, row in df.iterrows():
        cur = []
        for col in level_cols:
            val = (row.get(col) or "").strip()
            if not val: break
            cur.append(val)
        if cur:
            url = (row.get("URL") or "").strip()
            if url: url_by_path[tuple(cur)] = url
    return sorted(paths_set), url_by_path

def search_paths(paths, q, max_results=300):
    qn = norm(q)
    if not qn: return []
    hits = []
    for p in paths:
        if qn in norm(" / ".join(p)):
            hits.append(p)
            if len(hits) >= max_results: break
    return hits
