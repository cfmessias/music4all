
from __future__ import annotations
import streamlit as st
from .ui_helpers import ms_to_mmss

def _ensure_bootstrap():
    if 'playlists' not in st.session_state:
        st.session_state['playlists'] = {
            'My Playlist': {'public': True, 'description': '', 'tracks': []}
        }
        st.session_state['current_playlist'] = 'My Playlist'

def ensure_playlist(name: str):
    _ensure_bootstrap()
    pls = st.session_state['playlists']
    if name not in pls:
        pls[name] = {'public': True, 'description': '', 'tracks': []}
    st.session_state['playlists'] = pls

def list_playlists() -> list[str]:
    _ensure_bootstrap()
    return list(st.session_state.get('playlists', {}).keys())

def get_current_playlist():
    _ensure_bootstrap()
    pls = st.session_state['playlists']
    name = st.session_state.get('current_playlist') or next(iter(pls))
    return name, pls[name]

def set_current_playlist(name: str):
    _ensure_bootstrap()
    ensure_playlist(name)
    st.session_state['current_playlist'] = name

def add_tracks_to_playlist(name: str, tracks: list[dict]):
    _ensure_bootstrap()
    ensure_playlist(name)
    pls = st.session_state['playlists']
    cur = pls[name]['tracks']
    seen = {t.get('id') for t in cur if t.get('id')}
    for t in tracks or []:
        tid = (t or {}).get('id')
        if tid and tid not in seen:
            cur.append(t)
            seen.add(tid)
    pls[name]['tracks'] = cur
    st.session_state['playlists'] = pls

def remove_track_at(idx: int):
    _ensure_bootstrap()
    pname, pl = get_current_playlist()
    if 0 <= idx < len(pl['tracks']):
        del pl['tracks'][idx]

def move_track(idx: int, delta: int):
    _ensure_bootstrap()
    pname, pl = get_current_playlist()
    j = idx + delta
    if 0 <= idx < len(pl['tracks']) and 0 <= j < len(pl['tracks']):
        pl['tracks'][idx], pl['tracks'][j] = pl['tracks'][j], pl['tracks'][idx]

def clear_playlist():
    _ensure_bootstrap()
    pname, pl = get_current_playlist()
    pl['tracks'].clear()

def dedupe_playlist():
    _ensure_bootstrap()
    pname, pl = get_current_playlist()
    seen, out = set(), []
    for t in pl['tracks']:
        tid = t.get('id')
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(t)
    pl['tracks'] = out

def export_playlist_csv() -> str:
    import io, csv
    _ensure_bootstrap()
    pname, pl = get_current_playlist()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(["Title","Artists","Album","Duration","TrackID","TrackURI","TrackURL"])
    for t in pl['tracks']:
        w.writerow([t.get('name',''), t.get('artists',''), t.get('album',''),
                    ms_to_mmss(t.get('duration_ms',0)), t.get('id',''),
                    t.get('uri',''), t.get('external_url','')])
    return buf.getvalue()

def export_playlist_m3u() -> str:
    _ensure_bootstrap()
    urls = [t.get('external_url','') for t in get_current_playlist()[1]['tracks'] if t.get('external_url')]
    return "#EXTM3U\n" + "\n".join(urls)
