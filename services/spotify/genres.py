# services/spotify/genres.py
from __future__ import annotations

from typing import List, Dict, Tuple
import re
import unicodedata
import requests
import streamlit as st

from services.spotify.auth import get_auth_header

# ----------------------------
# Seeds baseline (fallback)
# ----------------------------
BASELINE_SEEDS: List[str] = sorted(list({
    "acoustic","alt-rock","alternative","blues","brazil","breakbeat","british",
    "classical","club","country","dance","dancehall","deep-house","detroit-techno",
    "disco","drum-and-bass","dub","dubstep","edm","electro","electronic","emo",
    "folk","funk","garage","gospel","goth","grindcore","groove","grunge","guitar",
    "hard-rock","hardcore","hip-hop","house","idm","indie","indie-pop","industrial",
    "jazz","latin","metal","minimal-techno","new-wave","opera","piano","pop",
    "power-pop","progressive-house","psychedelic","punk","r-n-b","reggae","reggaeton",
    "rock","rock-n-roll","salsa","samba","ska","soul","spanish","synth-pop","tango",
    "techno","trance","trip-hop","world-music",
    # regionais (ajudam a pesquisa local):
    "indian","iranian","j-pop","j-rock","j-dance","j-idol","k-pop",
    "mandopop","malay","philippines-opm","turkish",
}))

# ----------------------------
# Grupos amigáveis → seeds
# ----------------------------
SEED_GROUPS: Dict[str, List[str]] = {
    "asian": [
        "indian","iranian","j-dance","j-idol","j-pop","j-rock",
        "k-pop","malay","mandopop","philippines-opm","turkish",
    ],
}

# Extras “não-oficiais” mas relevantes (uniformização com a tua KB)
EXTRA_GENRES_SYNONYMS: Dict[str, List[str]] = {
    # canónico : sinónimos (lower/sem acentos)
    "fado": ["fado","fado portugues","fado português","fado portugues "],
}

# -------- Normalização de rótulos --------
def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii")

def normalize_label(s: str) -> str:
    """
    pt-PT friendly:
    - remove acentos, põe em lower
    - corta sufixos tipo " (Spotify seeds)"
    - remove ' genre' no fim
    - colapsa espaços
    """
    s0 = (s or "").strip()
    s1 = _strip_accents(s0).lower()
    s1 = re.sub(r"\s*\(.*?\)\s*$","", s1)
    s1 = re.sub(r"\s+genre\s*$","", s1)
    s1 = re.sub(r"\s+"," ", s1).strip()
    return s1

# -------- Spotify API: seeds dinâmicas --------
@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_spotify_seeds_api(token: str) -> List[str]:
    if not token:
        return []
    try:
        r = requests.get(
            "https://api.spotify.com/v1/recommendations/available-genre-seeds",
            headers=get_auth_header(token),
            timeout=15,
        )
        if r.status_code != 200:
            return []
        seeds = (r.json() or {}).get("genres") or []
        out = sorted(list(dict.fromkeys([str(x).strip() for x in seeds if str(x).strip()])))
        return out
    except Exception:
        return []

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_spotify_genre_seeds(token: str | None = None) -> List[str]:
    dynamic = _fetch_spotify_seeds_api(token) if token else []
    if dynamic:
        return sorted(list(dict.fromkeys(dynamic + BASELINE_SEEDS)))
    return BASELINE_SEEDS

# -------- Expansão de grupos --------
def expand_seed_or_group(label: str) -> List[str]:
    key = normalize_label(label)
    return list(dict.fromkeys(SEED_GROUPS.get(key, [label])))

# -------- “É provavelmente um género?” --------
def is_genre_like(label: str, token: str | None = None) -> Tuple[bool, str, List[str]]:
    """
    Devolve (is_genre, canonical, synonyms/seeds)
    - Verifica nas seeds (dinâmicas ou fallback)
    - Verifica grupos (asian → seeds)
    - Verifica extras (ex.: fado)
    """
    raw = label or ""
    norm = normalize_label(raw)
    # 1) grupo?
    if norm in SEED_GROUPS:
        return True, norm, SEED_GROUPS[norm]
    # 2) seed oficial?
    seeds = set(fetch_spotify_genre_seeds(token))
    if norm in seeds:
        return True, norm, [norm]
    # 3) extras/sinónimos (ex.: fado)
    for canon, syns in EXTRA_GENRES_SYNONYMS.items():
        if norm in syns:
            return True, canon, syns
    return False, norm, []
