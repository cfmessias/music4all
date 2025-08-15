
import streamlit as st

def ms_to_mmss(ms: int) -> str:
    try:
        s = int((ms or 0) // 1000)
        return f"{s//60}:{s%60:02d}"
    except Exception:
        return "0:00"

def ui_mobile() -> bool:
    return bool(st.session_state.get("ui_mobile", False))

def ui_audio_preview() -> bool:
    return bool(st.session_state.get("ui_audio_preview", True))

def ui_album_list_height() -> int:
    return 280 if ui_mobile() else 380
