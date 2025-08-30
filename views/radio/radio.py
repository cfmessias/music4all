# radio.py
# Internet Radio (Radio Browser) — compact cards + inline player
# Reqs: pip install streamlit requests

from __future__ import annotations

import random
import re
from typing import List, Dict, Optional

import requests
import streamlit as st

# -------------- Radio Browser base --------------
RB_SERVERS = [
    "https://api.radio-browser.info",
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://fr1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]
USER_AGENT = "music4all-radio/1.0 (+https://example.com)"


def _rb_get(path: str, params: Optional[dict] = None) -> Optional[requests.Response]:
    """Try several Radio Browser servers until one works."""
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
    """Keep only OK stations with a resolvable URL; optionally drop HLS (.m3u8)."""
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
        params["bitrateMin"] = min_bitrate
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
    """Top-clicked stations (fallback) with local HTTPS/country/HLS filtering."""
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


# -------------- Page renderer --------------
def render_radio_page():
    """Main entry-point: Radio page with compact cards + inline player."""
    # isolate this page's state keys
    st.session_state.setdefault("radio_results", [])
    st.session_state.setdefault("radio_play_url", "")
    st.session_state.setdefault("radio_play_idx", None)
    st.session_state.setdefault("radio_rb_base", "")

    st.subheader("📻 Radio")
    st.caption("Directory: Radio Browser (public)")

    # Filters (left column) + Actions (right column)
    cL, cR = st.columns([3, 2])

    with cL:
        q = st.text_input("Name contains", key="radio_q")
        t = st.text_input("Tag (e.g., jazz, rock, news)", key="radio_t")
        with st.expander("Select country (optional)"):
            cc = st.text_input("Country code (ISO 2 letters)", key="radio_cc")
            countries = _rb_countries()
            if countries:
                examples = ", ".join(sorted({(c.get("iso_3166_1") or "") for c in countries})[:20])
                st.caption("Examples: " + examples + "…")

    with cR:
        codec = st.selectbox("Codec", ["(any)", "mp3", "aac", "ogg"], index=0, key="radio_codec")
        min_bitrate = st.slider("Min bitrate (kbps)", 0, 320, 0, step=32, key="radio_bitrate")
        https_only = st.toggle("HTTPS only", value=True, key="radio_https")
        exclude_hls = st.toggle("Exclude HLS (.m3u8)", value=True, key="radio_nohls")
        limit = st.slider("Results limit", 10, 100, 30, step=10, key="radio_limit")

        a1, a2 = st.columns(2)
        with a1:
            do_search = st.button("Search", use_container_width=True, key="radio_btn_search")
        with a2:
            if st.button("Clear", use_container_width=True, key="radio_btn_clear"):
                st.session_state["radio_results"] = []
                st.session_state["radio_play_url"] = ""
                st.session_state["radio_play_idx"] = None

    # server in use
    if st.session_state["radio_rb_base"]:
        st.caption(f"Radio Browser server: {st.session_state['radio_rb_base']}")
    st.markdown("---")

    # Run search + persist
    if do_search:
        no_filters = not (
            q.strip() or t.strip() or cc.strip()
            or (st.session_state["radio_codec"] != "(any)")
            or st.session_state["radio_bitrate"]
        )
        if no_filters:
            stations = _rb_top_stations(
                limit=limit,
                https_only=https_only,
                countrycode=cc.strip(),
                exclude_hls=exclude_hls,
            )
            if not stations:
                stations = _rb_search_stations(
                    tag="rock",
                    limit=limit,
                    https_only=https_only,
                    exclude_hls=exclude_hls,
                )
        else:
            stations = _rb_search_stations(
                name=q,
                tag=t,
                countrycode=cc,
                codec=(codec if codec != "(any)" else ""),
                min_bitrate=min_bitrate,
                limit=limit,
                https_only=https_only,
                exclude_hls=exclude_hls,
            )
            if not stations:
                stations = _rb_top_stations(
                    limit=limit,
                    https_only=https_only,
                    countrycode=cc.strip(),
                    exclude_hls=exclude_hls,
                )

        st.session_state["radio_results"] = stations
        st.session_state["radio_play_url"] = ""
        st.session_state["radio_play_idx"] = None

    # Render results
    results = st.session_state.get("radio_results", [])
    if not results:
        st.info("Use the filters above and click **Search** to find stations.")
        return

    st.write(f"Found **{len(results)}** station(s).")

    for i, s in enumerate(results, start=1):
        with st.container(border=True):
            cols = st.columns([0.12, 0.63, 0.25])

            # Logo (small)
            with cols[0]:
                fav = (s.get("favicon") or "").strip()
                if fav:
                    st.image(fav, width=64)
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

            # Actions (right): Play + Homepage
            with cols[2]:
                url = s.get("url_resolved") or s.get("url") or ""
                play_clicked = st.button("Play", key=f"radio_play_{i}", use_container_width=True)
                home = (s.get("homepage") or "").strip()
                if home:
                    st.link_button("Homepage", home, use_container_width=True)
                if play_clicked:
                    st.session_state["radio_play_url"] = url
                    st.session_state["radio_play_idx"] = i

            # Inline player
            if st.session_state.get("radio_play_idx") == i and st.session_state.get("radio_play_url"):
                st.audio(st.session_state["radio_play_url"])
                st.caption(st.session_state["radio_play_url"])
