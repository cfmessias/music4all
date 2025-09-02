# views/radio/radio.py
# Internet Radio (Radio Browser) — per-device defaults & favorites via localStorage
# Compact UI (mobile-friendly), 🤔/🙂 favorites toggle, single active player, no CSV import/export.

from __future__ import annotations

import json
import random
import re
from typing import List, Dict, Optional

import requests
import streamlit as st
from streamlit_local_storage import LocalStorage

# ---------------- Defaults ----------------
DEFAULTS = {
    "name": "",               # Name contains
    "tag": "",                # Tag
    "countrycode": "",        # ISO-2 (e.g., PT, US)
    "codec": "(any)",         # "(any)" | "mp3" | "aac" | "ogg"
    "min_bitrate": 96,        # kbps
    "limit": 30,              # results
    "https_only": True,       # HTTPS only
    "exclude_hls": True,      # exclude HLS (.m3u8)
}

# Map defaults keys -> widget session keys
WIDGET_KEYS = {
    "name": "radio_name",
    "tag": "radio_tag",
    "countrycode": "radio_cc",
    "codec": "radio_codec",
    "min_bitrate": "radio_minbr",
    "limit": "radio_limit",
    "https_only": "radio_https",
    "exclude_hls": "radio_nohls",
}

# ---------------- Local (browser) storage ----------------
ls = LocalStorage()

# Guard: só 1 setItem por render (a tua versão da lib não aceita key= e pode dar DuplicateElementKey)
st.session_state.setdefault("_radio_storage_written", False)

def _ls_get(item_key: str, default=None):
    # lê do dicionário em memória (sem levantar KeyError)
    return st.session_state.get("_radio_storage", {}).get(item_key, default)

def _merge_defaults(data: Dict | None) -> Dict:
    base = DEFAULTS.copy()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in base:
                base[k] = v   # <- corrigido (tinha um ']' a mais)
    return base

def load_device_defaults() -> Dict:
    raw = ls.getItem("radio.defaults")
    try:
        return _merge_defaults(json.loads(raw) if raw else {})
    except Exception:
        return DEFAULTS.copy()

def _ls_set(item_key: str, value: str):
    # escreve no dicionário e marca como "escrito"
    store = st.session_state.setdefault("_radio_storage", {})
    store[item_key] = value
    st.session_state["_radio_storage_written"] = True

def save_device_defaults(prefs: Dict) -> None:
    payload = json.dumps(_merge_defaults(prefs), ensure_ascii=False)
    _ls_set("radio.defaults", payload)

def load_device_favorites() -> List[Dict]:
    raw = ls.getItem("radio.favorites")
    try:
        rows = json.loads(raw) if raw else []
        return rows if isinstance(rows, list) else []
    except Exception:
        return []

def save_device_favorites(rows: List[Dict]) -> None:
    _ls_set("radio.favorites", json.dumps(rows, ensure_ascii=False))

def _ls_load_bool(item_key: str, default: bool = False) -> bool:
    raw = ls.getItem(item_key)
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("true", "1", "yes", "on"):  return True
        if s in ("false", "0", "no", "off"): return False
    return default

def _ls_save_bool(item_key: str, value: bool):
    _ls_set(item_key, "true" if value else "false")
# Helpers para favoritos
def _fav_key(s: Dict) -> str:
    su = (s.get("stationuuid") or "").strip()
    if su:
        return su
    return (s.get("url_resolved") or s.get("url") or "").strip()

def _station_minimal(s: Dict) -> Dict:
    return {
        "key": _fav_key(s),
        "name": s.get("name") or "",
        "url": (s.get("url_resolved") or s.get("url") or ""),
        "homepage": (s.get("homepage") or ""),
        "countrycode": (s.get("countrycode") or s.get("country") or ""),
        "codec": (s.get("codec") or ""),
        "bitrate": int(s.get("bitrate") or 0),
        "tags": s.get("tags") or s.get("tag") or "",
        "favicon": (s.get("favicon") or ""),
        "stationuuid": (s.get("stationuuid") or ""),
    }

def add_favorite_local(station: Dict) -> None:
    favs = load_device_favorites()
    k = _fav_key(station)
    if k and not any(f.get("key") == k for f in favs):
        favs.append(_station_minimal(station))
        save_device_favorites(favs)

def remove_favorite_local(key: str) -> None:
    favs = load_device_favorites()
    favs = [r for r in favs if r.get("key") != key]
    save_device_favorites(favs)

# ---------------- Radio Browser base ----------------
RB_SERVERS = [
    "https://api.radio-browser.info",
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://fr1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]
USER_AGENT = "music4all-radio/1.0 (+https://example.com)"

def _rb_get(path: str, params: Optional[dict] = None) -> Optional[requests.Response]:
    params = params or {}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    servers = RB_SERVERS[:]
    random.shuffle(servers)
    for base in servers:
        url = f"{base}/json{path}"
        try:
            r = requests.get(url, params=params, headers=headers, timeout=12)
            if r.status_code == 200:
                st.session_state["radio_rb_base"] = base
                return r
        except Exception:
            continue
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def _rb_countries() -> List[Dict]:
    r = _rb_get("/countries")
    if not r:
        return []
    try:
        return r.json() or []
    except Exception:
        return []

def _is_hls_url(url: str) -> bool:
    return bool(re.search(r"\.m3u8(\?.*)?$", url, flags=re.IGNORECASE))

def _clean_results(raw: List[Dict], exclude_hls: bool) -> List[Dict]:
    out = []
    for s in raw or []:
        if s.get("lastcheckok") != 1:
            continue
        url = (s.get("url_resolved") or "").strip() or (s.get("url") or "").strip()
        if not url:
            continue
        if exclude_hls and (s.get("hls") == 1 or _is_hls_url(url)):
            continue
        out.append({**s, "url_resolved": url})
    return out

@st.cache_data(ttl=1800, show_spinner=True)
def _rb_search_stations(
    name: str = "",
    tag: str = "",
    countrycode: str = "",
    codec: str = "",
    min_bitrate: int = 0,
    limit: int = 30,
    https_only: bool = True,
    exclude_hls: bool = True,
) -> List[Dict]:
    params = {
        "limit": limit,
        "order": "clickcount",
        "reverse": "true",
    }
    if name:
        params["name"] = name.strip()
    if tag:
        params["tag"] = tag.strip()
    if countrycode:
        params["countrycode"] = countrycode.strip().upper()
    if codec:
        params["codec"] = codec.strip().lower()
    if min_bitrate:
        params["bitrateMin"] = int(min_bitrate)
    if https_only:
        params["is_https"] = "true"

    r = _rb_get("/stations/search", params)
    if not r:
        return []
    try:
        data = r.json() or []
    except Exception:
        return []
    return _clean_results(data, exclude_hls=exclude_hls)

@st.cache_data(ttl=600, show_spinner=False)
def _rb_top_stations(
    limit: int = 30,
    https_only: bool = True,
    countrycode: str = "",
    exclude_hls: bool = True,
) -> List[Dict]:
    r = _rb_get(f"/stations/topclick/{max(1, min(limit, 100))}")
    if not r:
        return []
    try:
        data = r.json() or []
    except Exception:
        return []
    out = []
    for s in data:
        if s.get("lastcheckok") != 1:
            continue
        url = (s.get("url_resolved") or "").strip() or (s.get("url") or "").strip()
        if not url:
            continue
        if https_only and not url.lower().startswith("https://"):
            continue
        if countrycode and (s.get("countrycode") or "").upper() != countrycode.upper():
            continue
        if exclude_hls and (s.get("hls") == 1 or _is_hls_url(url)):
            continue
        out.append({**s, "url_resolved": url})
    return out

# ---------------- Defaults scheduling ----------------
def _schedule_apply_defaults(prefs: dict | None = None):
    if prefs is None:
        prefs = load_device_defaults()
    payload = {k: prefs.get(k, DEFAULTS[k]) for k in DEFAULTS}
    st.session_state["_radio_apply_defaults"] = True
    st.session_state["_radio_defaults_payload"] = payload

# ---------------- Page ----------------
def render_radio_page():
    """Radio page: per-device defaults & favorites, compact cards, single active player."""
    # --- garantir estado interno do "localStorage" em memória ---
    st.session_state.setdefault("_radio_storage", {})
    st.session_state.setdefault("_radio_storage_written", False)

    # Aplicar defaults agendados (ou 1ª carga) ANTES de criar widgets
    if st.session_state.get("_radio_apply_defaults", False) or "radio_defaults_loaded" not in st.session_state:
        prefs = st.session_state.pop("_radio_defaults_payload", None)
        if prefs is None:
            prefs = load_device_defaults()  # auto na 1ª execução
        for k in DEFAULTS:
            st.session_state[WIDGET_KEYS[k]] = prefs.get(k, DEFAULTS[k])
        st.session_state["radio_defaults_loaded"] = True
        st.session_state["_radio_apply_defaults"] = False

    # Estado geral da página
    st.session_state.setdefault("radio_results", [])
    st.session_state.setdefault("radio_play_url", "")
    st.session_state.setdefault("radio_play_idx", None)
    st.session_state.setdefault("radio_play_source", None)  # "results" | "favorites"
    st.session_state.setdefault("radio_audio_rev", 0)
    st.session_state.setdefault("radio_rb_base", "")
    # Show favorites: ON por defeito e persistente
    st.session_state.setdefault("radio_show_favs", _ls_load_bool("radio.showFavs", True))

    st.subheader("📻 Radio")
    st.caption("Directory: Radio Browser (public)")

    # --------- Favoritos (sem CSV) ---------
    favs = load_device_favorites()
    st.markdown("#### ⭐ My favorites (on this device)")
    show_favs = st.toggle(
        "Show my favorites list",
        value=st.session_state.get("radio_show_favs", True),
        key="radio_show_favs",
    )
    # Se mudou, grava no dispositivo e termina o render
    prev = st.session_state.get("_radio_prev_showfavs", None)
    changed = (prev is None) or (prev != bool(show_favs))
    if changed:
        _ls_save_bool("radio.showFavs", bool(show_favs))  # 1º setItem deste render
        st.session_state["_radio_prev_showfavs"] = bool(show_favs)
        st.rerun()

    if show_favs:
        if not favs:
            st.info("No favorites yet.")
        else:
            st.caption(f"{len(favs)} favorite(s). Tap **Play** to listen.")
            for j, row in enumerate(favs, start=1):
                with st.container(border=True):
                    cols = st.columns([0.12, 0.63, 0.25])
                    # logo — 40px (mobile)
                    with cols[0]:
                        favico = (row.get("favicon") or "").strip()
                        if favico:
                            st.image(favico, width=40)
                        else:
                            st.write("—")
                    # info
                    with cols[1]:
                        name = row.get("name") or "—"
                        country = row.get("countrycode") or "—"
                        codec = (row.get("codec") or "—").upper()
                        br = int(row.get("bitrate") or 0)
                        tags = row.get("tags") or ""
                        st.markdown(f"**{name}**  \n{country} • {codec} • {br} kbps")
                        if tags:
                            st.caption(tags)
                    # actions
                    with cols[2]:
                        a1, a2 = st.columns([0.35, 0.65])
                        with a1:
                            st.button("🙂", key=f"radio_fav_icon_{j}", help="In favorites",
                                      use_container_width=True, disabled=True)
                        with a2:
                            if st.button("Play", key=f"radio_fav_play_{j}", use_container_width=True):
                                st.session_state["radio_play_url"] = row.get("url","")
                                st.session_state["radio_play_idx"] = f"fav_{j}"
                                st.session_state["radio_play_source"] = "favorites"
                                st.session_state["radio_audio_rev"] += 1
                    # inline player
                    if (
                        st.session_state.get("radio_play_source") == "favorites" and
                        st.session_state.get("radio_play_idx") == f"fav_{j}" and
                        st.session_state.get("radio_play_url")
                    ):
                        st.audio(st.session_state["radio_play_url"])
                        st.caption(st.session_state["radio_play_url"])

    st.markdown("---")

    # --------- Search bar + advanced options ---------
    cA, cB = st.columns([3, 2])
    with cA:
        name_val = st.text_input("Name contains", key="radio_name")
        tag_val = st.text_input("Tag (e.g., jazz, rock, news)", key="radio_tag")

    with cB:
        opt_col, load_col, save_col = st.columns([1.2, 0.9, 0.9])
        with opt_col:
            show_opts = st.toggle("Show options", value=False, key="radio_show_opts")
        with load_col:
            if st.button("Load defaults", use_container_width=True, key="radio_btn_loaddefs"):
                _schedule_apply_defaults()  # aplica no próximo render antes dos widgets
                st.rerun()
        with save_col:
            if st.button("Save defaults", use_container_width=True, key="radio_btn_savedefs"):
                bundle = {k: st.session_state.get(WIDGET_KEYS[k], DEFAULTS[k]) for k in DEFAULTS}
                save_device_defaults(bundle)  # 1º setItem deste render
                st.rerun()

        if show_opts:
            cc = st.text_input("Country code (ISO 2 letters)", key="radio_cc")
            codec = st.selectbox("Codec", ["(any)", "mp3", "aac", "ogg"], key="radio_codec")
            min_br = st.slider("Min bitrate (kbps)", 0, 320, key="radio_minbr", step=32)
            https_only = st.toggle("HTTPS only", key="radio_https")
            exclude_hls = st.toggle("Exclude HLS (.m3u8)", key="radio_nohls")
            limit = st.slider("Results limit", 10, 100, key="radio_limit", step=10)

            c1, c2 = st.columns(2)
            with c1:
                do_search = st.button("Search", use_container_width=True, key="radio_btn_search")
            with c2:
                if st.button("Reset to defaults", use_container_width=True, key="radio_btn_reset"):
                    _schedule_apply_defaults(DEFAULTS)  # força defaults de fábrica
                    st.rerun()
        else:
            cc = st.session_state.get("radio_cc", DEFAULTS["countrycode"])
            codec = st.session_state.get("radio_codec", DEFAULTS["codec"])
            min_br = int(st.session_state.get("radio_minbr", DEFAULTS["min_bitrate"]))
            https_only = bool(st.session_state.get("radio_https", DEFAULTS["https_only"]))
            exclude_hls = bool(st.session_state.get("radio_nohls", DEFAULTS["exclude_hls"]))
            limit = int(st.session_state.get("radio_limit", DEFAULTS["limit"]))
            do_search = st.button("Search", use_container_width=True, key="radio_btn_search_hidden")

    if st.session_state.get("radio_rb_base"):
        st.caption(f"Radio Browser server: {st.session_state['radio_rb_base']}")

    st.markdown("---")

    # --------- Execute search ---------
    if do_search:
        no_filters = not (
            name_val.strip() or tag_val.strip()
            or (cc and show_opts) or (codec != "(any)" and show_opts) or (min_br and show_opts)
        )
        if no_filters:
            stations = _rb_top_stations(
                limit=limit, https_only=https_only, countrycode=cc.strip(), exclude_hls=exclude_hls
            ) or _rb_search_stations(
                tag="rock", limit=limit, https_only=https_only, exclude_hls=exclude_hls
            )
        else:
            stations = _rb_search_stations(
                name=name_val, tag=tag_val, countrycode=cc,
                codec=(codec if codec != "(any)" else ""),
                min_bitrate=min_br, limit=limit,
                https_only=https_only, exclude_hls=exclude_hls,
            ) or _rb_top_stations(
                limit=limit, https_only=https_only, countrycode=cc.strip(), exclude_hls=exclude_hls
            )

        st.session_state["radio_results"] = stations
        # parar qualquer player anterior
        st.session_state["radio_play_url"] = ""
        st.session_state["radio_play_idx"] = None
        st.session_state["radio_play_source"] = None
        st.session_state["radio_audio_rev"] += 1

    # --------- Autosave dos filtros (no dispositivo) ---------
    current_prefs = {k: st.session_state.get(WIDGET_KEYS[k], DEFAULTS[k]) for k in DEFAULTS}
    cur_sig = json.dumps(current_prefs, sort_keys=True)
    if (cur_sig != st.session_state.get("_radio_last_saved", "")) and (not st.session_state["_radio_storage_written"]):
        save_device_defaults(current_prefs)  # 1º (e único) setItem deste render
        st.session_state["_radio_last_saved"] = cur_sig

    # Reset do guard para o próximo render
    st.session_state["_radio_storage_written"] = False

    # --------- Results ---------
    results = st.session_state.get("radio_results", [])
    if not results:
        st.info("Use the filters above and click **Search** to find stations.")
        return

    fav_keys = {r.get("key") for r in load_device_favorites()}

    st.write(f"Found **{len(results)}** station(s).")

    for i, s in enumerate(results, start=1):
        with st.container(border=True):
            cols = st.columns([0.12, 0.63, 0.25])

            # Logo — 40px (mobile-friendly)
            with cols[0]:
                favico = (s.get("favicon") or "").strip()
                if favico:
                    st.image(favico, width=40)
                else:
                    st.write("—")

            # Info
            with cols[1]:
                name = s.get("name") or "—"
                country = s.get("countrycode") or s.get("country") or "—"
                codec_s = (s.get("codec") or "—").upper()
                br = s.get("bitrate") or 0
                tags = s.get("tags") or s.get("tag") or ""
                tags_txt = (
                    ", ".join(sorted(set(tok for tok in re.split(r"[;, ]+", tags) if tok)))
                    if isinstance(tags, str) else ""
                )
                st.markdown(f"**{name}**  \n{country} • {codec_s} • {br} kbps")
                if tags_txt:
                    st.caption(tags_txt)

            # Actions (right): 🤔/🙂 favorite toggle + Play + Homepage
            with cols[2]:
                url = s.get("url_resolved") or s.get("url") or ""
                key = _fav_key(s)
                is_fav = key in fav_keys

                a1, a2, a3 = st.columns([0.25, 0.4, 0.35])

                with a1:
                    face = "🙂" if is_fav else "🤔"
                    tip  = "Remove from favorites" if is_fav else "Add to favorites"
                    if st.button(face, key=f"radio_face_{i}", help=tip, use_container_width=True):
                        if is_fav:
                            remove_favorite_local(key)  # 1º setItem
                        else:
                            add_favorite_local(s)       # 1º setItem
                        st.rerun()  # termina render aqui -> evita 2º setItem

                with a2:
                    if st.button("Play", key=f"radio_play_{i}", use_container_width=True):
                        st.session_state["radio_play_url"] = url
                        st.session_state["radio_play_idx"] = i
                        st.session_state["radio_play_source"] = "results"
                        st.session_state["radio_audio_rev"] += 1

                with a3:
                    home = (s.get("homepage") or "").strip()
                    if home:
                        st.link_button("Homepage", home, use_container_width=True)

            # Inline player (apenas um, global)
            if (
                st.session_state.get("radio_play_source") == "results" and
                st.session_state.get("radio_play_idx") == i and
                st.session_state.get("radio_play_url")
            ):
                st.audio(st.session_state["radio_play_url"])
                st.caption(st.session_state["radio_play_url"])
