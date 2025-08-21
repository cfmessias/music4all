import streamlit as st

def render_paginator(total: int, limit: int, offset: int):
    left, mid, right = st.columns([1,2,1])
    with left:
        prev = st.button("◀ Anterior", disabled=(offset==0))
    with mid:
        st.caption(f"{offset+1}–{min(offset+limit,total)} de {total}")
    with right:
        nxt = st.button("Seguinte ▶", disabled=(offset+limit>=total))
    new_offset = offset
    if prev: new_offset = max(0, offset - limit)
    if nxt:  new_offset = offset + limit
    return new_offset
