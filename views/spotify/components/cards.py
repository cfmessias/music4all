import streamlit as st
from typing import List, Dict
from services.spotify.models import Track, AudioFeatures

def ms_to_minsec(ms: int) -> str:
    m, s = divmod(int(ms/1000), 60)
    return f"{m}:{s:02d}"

def track_card(t: Track, f: AudioFeatures | None):
    with st.container():
        cols = st.columns([0.12, 0.58, 0.30])
        with cols[0]:
            if t.album.image_url:
                st.image(t.album.image_url, use_container_width=True)
        with cols[1]:
            st.markdown(f"**[{t.name}]({t.url})**")
            st.caption(", ".join(a.name for a in t.artists))
            st.caption(f"Álbum: [{t.album.name}]({t.album.url}) • {ms_to_minsec(t.duration_ms)} • Popularidade {t.popularity}")
        with cols[2]:
            if f:
                st.progress(min(1, (f.energy or 0.0)), text="Energia")
                st.progress(min(1, (f.danceability or 0.0)), text="Dançabilidade")

def track_list(items: List[Track], feats: Dict[str, AudioFeatures]):
    for t in items:
        track_card(t, feats.get(t.id))
        st.divider()
