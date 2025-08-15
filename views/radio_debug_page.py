# views/radio_debug_page.py
# Debug da pesquisa de playlists associadas ao artista:
#  - "<Artist> Radio" / "Radio <Artist>" / "Rádio …"
#  - "This Is <Artist>"
# Resultados persistem após cliques (session_state); embed por item.

from __future__ import annotations
import requests
import streamlit as st

try:
    from services.spotify_lookup import embed_spotify
except Exception:
    def embed_spotify(_kind: str, _id: str, height: int = 120):
        st.caption("Embed unavailable.")

def _strip_wildcards(s: str) -> str:
    return (s or "").strip().strip("*").strip()

def search_artist_related_playlists(token: str, artist_raw: str, limit: int = 10):
    """
    Procura playlists relacionadas: Radio + This Is.
    Remove '*' do input antes de montar queries.
    Devolve (results, raw_debug).
    """
    raw_debug = {"queries": [], "calls": []}
    if not token or not (artist_raw or "").strip():
        raw_debug["error"] = "Invalid token or empty artist."
        return [], raw_debug

    artist = _strip_wildcards(artist_raw)
    if not artist:
        raw_debug["error"] = "Empty artist after removing '*'."
        return [], raw_debug

    headers = {"Authorization": f"Bearer {token}"}
    queries = [
        f"{artist} Radio",
        f"Radio {artist}",
        f"Rádio {artist}",
        f"Rádio de {artist}",
        f"This Is {artist}",
        f"\"This Is {artist}\"",
    ]
    raw_debug["queries"] = queries

    results, seen_ids = [], set()
    for q in queries:
        call = {"q": q, "status": None, "count": 0, "error": None}
        try:
            r = requests.get(
                "https://api.spotify.com/v1/search",
                headers=headers,
                params={"q": q, "type": "playlist", "limit": limit},
                timeout=12,
            )
            call["status"] = r.status_code
            if r.status_code != 200:
                call["error"] = f"HTTP {r.status_code}"
                raw_debug["calls"].append(call)
                continue
            body = r.json() or {}
            items = ((body.get("playlists") or {}).get("items") or [])
            for p in items:
                if not isinstance(p, dict):
                    continue
                pid = p.get("id")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                owner = p.get("owner") or {}
                nm = p.get("name") or ""
                kind = "this_is" if nm.lower().startswith("this is ") else ("radio" if "radio" in nm.lower() or "rádio" in nm.lower() else "other")
                results.append({
                    "id": pid,
                    "name": nm,
                    "kind": kind,  # radio | this_is | other
                    "url": (p.get("external_urls") or {}).get("spotify"),
                    "owner": owner.get("display_name"),
                    "owner_id": owner.get("id"),
                    "image": ((p.get("images") or [{}])[0] or {}).get("url"),
                    "description": p.get("description") or "",
                })
                call["count"] += 1
        except Exception as e:
            call["error"] = f"Request error: {e}"
        raw_debug["calls"].append(call)

    # ordenar: owner Spotify primeiro, depois RADIO, depois THIS IS, depois nome
    def _is_spotify_owner(rec: dict) -> bool:
        o = (rec.get("owner") or "").strip().lower()
        oid = (rec.get("owner_id") or "").strip().lower()
        return (o == "spotify") or (oid == "spotify")

    priority = {"radio": 0, "this_is": 1, "other": 2}
    results.sort(key=lambda r: (not _is_spotify_owner(r), priority.get(r.get("kind"), 3), (r.get("name") or "").lower()))
    return results, raw_debug


def _clear_embed_flags():
    for k in list(st.session_state.keys()):
        if k.startswith("radio_dbg_embed_on_"):
            st.session_state.pop(k, None)

def render_radio_debug_page(token: str):
    st.title("📻 Radio (debug)")

    default_artist = st.session_state.get("radio_debug_artist", st.session_state.get("query", ""))
    artist_name = st.text_input(
        "Artist name",
        value=default_artist,
        key="radio_dbg_artist_input",
        placeholder="Genesis | *Genesis | Genesis* | *Genesis*",
        help="Use * at the start/end; searches 'Radio' and 'This Is' playlists.",
    )

    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    with c1:
        limit = st.selectbox("Per query limit", options=[10, 20, 50], index=0, key="radio_dbg_limit_sel")
    with c2:
        show_raw = st.checkbox("Show raw debug", value=bool(st.session_state.get("radio_dbg_show_raw", False)), key="radio_dbg_show_raw")
    with c3:
        search_clicked = st.button("Search", key="radio_dbg_search")
    with c4:
        if st.button("Clear", key="radio_dbg_clear"):
            for k in ["radio_dbg_results", "radio_dbg_raw", "radio_debug_artist"]:
                st.session_state.pop(k, None)
            _clear_embed_flags()
            st.experimental_rerun()

    if search_clicked:
        with st.spinner("Searching…"):
            results, raw_debug = search_artist_related_playlists(token, artist_name, limit=limit)
        st.session_state["radio_dbg_results"] = results
        st.session_state["radio_dbg_raw"] = raw_debug
        st.session_state["radio_debug_artist"] = artist_name
        _clear_embed_flags()

    results = st.session_state.get("radio_dbg_results") or []
    raw_debug = st.session_state.get("radio_dbg_raw") or {}

    if not results:
        st.caption("Type an artist and click Search. We look for both 'Radio' and 'This Is' playlists.")
        if show_raw and raw_debug:
            st.subheader("Raw debug")
            st.json(raw_debug)
        return

    st.subheader("Results")
    st.write(f"Found **{len(results)}** playlists for “{st.session_state.get('radio_debug_artist','')}”.")

    mobile = False
    try:
        from services.ui_helpers import ui_mobile
        mobile = ui_mobile()
    except Exception:
        pass

    for idx, rec in enumerate(results, start=1):
        name = rec.get("name") or "—"
        url = rec.get("url") or "—"
        owner = rec.get("owner") or "—"
        pid = rec.get("id")
        kind = rec.get("kind")

        tag = "🎙 Radio" if kind == "radio" else ("⭐ This Is" if kind == "this_is" else "—")
        st.markdown(
            f"**{idx}. {name}**  \n"
            f"{tag} • Owner: {owner}  \n"
            f"ID: `{pid or '—'}`  \n"
            f"URL: {url}"
        )
        if rec.get("image"):
            st.image(rec["image"], width=96)

        if pid:
            embed_key = f"radio_dbg_embed_on_{pid}"
            if st.button("▶ Embed this playlist", key=f"radio_dbg_btn_embed_{pid}"):
                st.session_state[embed_key] = not st.session_state.get(embed_key, False)
            if st.session_state.get(embed_key):
                try:
                    embed_spotify("playlist", pid, height=80 if mobile else 120)
                except Exception:
                    st.warning("Could not embed the playlist.")
        st.markdown("---")

    if show_raw and raw_debug:
        st.subheader("Raw debug")
        st.json(raw_debug)
