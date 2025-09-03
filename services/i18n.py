from __future__ import annotations
import json, os
import streamlit as st
SUPPORTED = {'EN': 'English', 'PT': 'Português (pt‑PT)'}
DEFAULT_LANG = 'EN'
_cache = {}
def _load_catalog(lang):
    lang = lang.upper()
    if lang in _cache: return _cache[lang]
    base_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(base_dir, '..'))
    path = os.path.join(root, 'i18n', f"{'pt-PT' if lang=='PT' else 'en'}.json")
    try:
        with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
    except Exception:
        data = {}
    _cache[lang] = data
    return data
def init_i18n(default=DEFAULT_LANG):
    lang = (st.session_state.get('lang') or default or DEFAULT_LANG).upper()
    if lang not in SUPPORTED: lang = DEFAULT_LANG
    st.session_state['lang'] = lang
    return lang
def set_lang(lang):
    lang = (lang or DEFAULT_LANG).upper()
    if lang not in SUPPORTED: lang = DEFAULT_LANG
    st.session_state['lang'] = lang
def get_lang():
    return (st.session_state.get('lang') or DEFAULT_LANG).upper()
def t(key, **kwargs):
    lang = get_lang()
    cat = _load_catalog(lang)
    base = _load_catalog('EN')
    txt = cat.get(key, base.get(key, key))
    try: return txt.format(**kwargs)
    except Exception: return txt
def lang_selector(location='sidebar'):
    opts = ['EN','PT']; labels = {'EN':'English','PT':'Português'}
    if location == 'sidebar':
        with st.sidebar:
            choice = st.selectbox('Language / Idioma', opts,
                                  index=opts.index(get_lang()),
                                  format_func=lambda x: labels[x], key='ui_lang')
    else:
        choice = st.selectbox('Language / Idioma', opts,
                               index=opts.index(get_lang()),
                               format_func=lambda x: labels[x], key='ui_lang')
    set_lang(choice); return choice
