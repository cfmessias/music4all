import streamlit as st
from services.spotify_session_push import push_session_playlist

def _switch_to_playlists_if_possible():
    # If the app uses Streamlit Multi-Page (pages/ directory), use st.switch_page
    # Otherwise, leave a hint.
    try:
        st.switch_page("pages/Playlists.py")
        return True
    except Exception:
        return False

def render_session_playlist_actions(on_goto_playlists=None, default_name: str = "Music4all – Session"):
    st.markdown("### Session playlist")
    playlists = st.session_state.get("playlists", {})
    current = st.session_state.get("current_playlist")
    rows = playlists.get(current or "", [])
    st.caption(f"Current: **{current or 'unnamed'}** — {len(rows)} track(s)")

    with st.container():
        c1, c2 = st.columns([2,1])
        with c1:
            name = st.text_input("Playlist name on Spotify", value=default_name, label_visibility="collapsed")
        with c2:
            go = st.button("Go to Playlists", use_container_width=True)
            if go:
                if _switch_to_playlists_if_possible():
                    return
                if callable(on_goto_playlists):
                    on_goto_playlists("Playlists")
                else:
                    st.toast("Open the 'Playlists' tab at the top.", icon="ℹ️")

        disabled = len(rows) == 0
        send = st.button("Send to Spotify", use_container_width=True, disabled=disabled)
        if send:
            try:
                playlist_id, added, misses = push_session_playlist(playlist_name=name)
                if not playlist_id:
                    st.warning("The session playlist is empty.")
                else:
                    st.success(f"Done! {added} added; {misses} unresolved.")
                    st.link_button("Open on Spotify", f"https://open.spotify.com/playlist/{playlist_id}", use_container_width=True)
            except Exception as e:
                st.error(f"Failed to send: {e}")
