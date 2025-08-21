import streamlit as st
from typing import List, Dict
from .models import AudioFeatures

@st.cache_data(ttl=3600, show_spinner=False)
def cached_features(token: str, ids: str, fetch):
    # ids: string estável para a cache (ex.: ",".join(sorted(list)))
    return fetch()

def features_cached(fetch_fn, token: str, ids_list: List[str]) -> Dict[str, AudioFeatures]:
    key = ",".join(sorted(ids_list))
    return cached_features(token, key, fetch=lambda: fetch_fn())
