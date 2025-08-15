# views/wiki_page.py
import os
import requests
import pandas as pd
import streamlit as st
from urllib.parse import quote

# -----------------------------
# Helpers Wikipedia (REST API)
# -----------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def _wiki_summary(title: str, lang: str = "en") -> dict:
    """
    Lê o resumo/thumbnail via Wikipedia REST API.
    Devolve: {'title','extract','thumb','content_url'} (quando disponível).
    """
    if not title:
        return {}
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return {}
        j = r.json() or {}
        return {
            "title": (j.get("title") or "").strip(),
            "extract": (j.get("extract") or "").strip(),
            "thumb": ((j.get("thumbnail") or {}).get("source") or "").strip(),
            "content_url": ((j.get("content_urls") or {}).get("desktop") or {}).get("page"),
        }
    except Exception:
        return {}

def _lang_from_wiki_url(url: str) -> str:
    """Extrai o lang do domínio (ex.: en.wikipedia.org → 'en')."""
    try:
        host = url.split("//", 1)[1].split("/", 1)[0]
        if host.endswith("wikipedia.org"):
            sub = host.split(".")[0]
            if sub and sub != "www":
                return sub
    except Exception:
        pass
    return "en"

def _title_from_url(url: str) -> str:
    try:
        tail = url.rsplit("/", 1)[-1]
        return tail.replace("_", " ")
    except Exception:
        return ""


# -----------------------------
# CSV quick loader
# -----------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def load_wiki_styles_csv_quick():
    """
    Procura um CSV com colunas Artista;Genero;URL (ou equivalentes).
    Aceita ';' ou ',' como separador. Normaliza para {'name','style','wiki_url'}.
    """
    candidates = [
        "lista_artistas.csv",
        "wikipedia_styles.csv",
        "dados/lista_artistas.csv",
        "data/lista_artistas.csv",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, sep=";")
            except Exception:
                df = pd.read_csv(path)
            cols = {c.lower().strip(): c for c in df.columns}
            name_col = cols.get("artista") or cols.get("artist") or list(df.columns)[0]
            genre_col = cols.get("genero") or cols.get("género") or cols.get("genre") or list(df.columns)[1]
            url_col = cols.get("url")

            out = pd.DataFrame({
                "name": df[name_col].astype(str).fillna("").str.strip(),
                "style": df[genre_col].astype(str).fillna("").str.strip(),
                "wiki_url": df[url_col].astype(str).fillna("").str.strip() if url_col else "",
            })
            out = out[(out["name"] != "") & (out["style"] != "")]
            return out
    return None


# -----------------------------
# Página
# -----------------------------
def render_wikipedia_page(token: str):
    df = load_wiki_styles_csv_quick()
    if df is None:
        st.info("To enable 'Wikipedia styles', place a CSV named 'lista_artistas.csv' (or 'wikipedia_styles.csv') with columns Artista;Genero;URL in the app folder.")
        return

    st.subheader("📚 Wikipedia styles — CSV list (fast)")

    # ---- Form de pesquisa (Search / Clear) ----
    styles = sorted(df["style"].dropna().astype(str).unique().tolist())

    with st.form("wiki_csv_form", clear_on_submit=False):
        c_style, c_filter = st.columns([1, 1])
        with c_style:
            sel_style = st.selectbox(
                "Style (optional)",
                options=[""] + styles,
                index=0,
                key="wiki_csv_style"
            )
        with c_filter:
            filter_txt = st.text_input(
                "Filter artists (optional)",
                key="wiki_csv_filter",
                placeholder="type a name…"
            )

        cb1, cb2 = st.columns([1, 1])
        with cb1:
            do_search = st.form_submit_button("Search")
        with cb2:
            do_reset = st.form_submit_button("Clear")

    # Ações dos botões
    if do_reset:
        for k in ["wiki_csv_style", "wiki_csv_filter", "wiki_csv_page", "wiki_csv_ps", "wiki_open_name", "wiki_open_url"]:
            st.session_state.pop(k, None)
        st.rerun()

    if do_search:
        # reset pag quando há nova pesquisa
        st.session_state["wiki_csv_page"] = 1

    # Lê os valores atuais (após form)
    sel_style = st.session_state.get("wiki_csv_style", "")
    filter_txt = st.session_state.get("wiki_csv_filter", "")

    # ---- Filtragem principal
    sub = df.copy()

    # 1) Filtro por estilo (se houver)
    if sel_style:
        sub = sub[sub["style"].str.lower() == str(sel_style).lower()]

    # 2) Filtro por artista (contains, case-insensitive)
    if filter_txt:
        sub = sub[sub["name"].str.contains(str(filter_txt), case=False, na=False)]

    # 3) Deduplicação quando a pesquisa é SÓ por artista (sem estilo selecionado)
    #    Ignora a coluna 'style' e faz distinct pelas restantes (name, wiki_url).
    if filter_txt and not sel_style:
        sub = sub.drop_duplicates(subset=["name", "wiki_url"], keep="first")

    # Ordenação por nome
    sub.sort_values("name", inplace=True)

    # ---- Paginação (Page + Page size)
    default_ps = int(st.session_state.get("ui_wiki_page_size", 20))
    options = [20, 50, 100]
    try:
        default_index = options.index(default_ps)
    except ValueError:
        default_index = 0

    c_page, c_ps = st.columns([1, 1])
    with c_page:
        page_num = st.number_input(
            "Page",
            min_value=1,
            value=int(st.session_state.get("wiki_csv_page", 1)),
            key="wiki_csv_page",
        )
    with c_ps:
        page_size = st.selectbox("Page size", options, index=default_index, key="wiki_csv_ps")

    total = len(sub)
    total_pages = (total - 1) // page_size + 1 if total else 1
    if page_num > total_pages:
        page_num = total_pages
        st.session_state["wiki_csv_page"] = total_pages

    st.caption(f"{total} artists • {total_pages} pages")

    bp1, bp2 = st.columns(2)
    with bp1:
        if st.button("◀ Prev", key="wiki_csv_prev"):
            st.session_state["wiki_csv_page"] = max(1, int(st.session_state.get("wiki_csv_page", 1)) - 1)
            st.rerun()
    with bp2:
        if st.button("Next ▶", key="wiki_csv_next"):
            st.session_state["wiki_csv_page"] = min(total_pages, int(st.session_state.get("wiki_csv_page", 1)) + 1)
            st.rerun()

    start = (int(page_num) - 1) * page_size
    end = start + page_size
    view = sub.iloc[start:end]

    # ---- Render da lista
    selected_name = st.session_state.get('wiki_open_name')
    for i, row in enumerate(view.itertuples(index=False), start=start + 1):
        name = getattr(row, 'name')
        wiki_url = getattr(row, 'wiki_url', '')
        c1, c2 = st.columns([4, 1])
        with c1:
            if wiki_url:
                st.markdown(f"**{i}. {name}** — [Wikipedia]({wiki_url})")
            else:
                st.markdown(f"**{i}. {name}**")
        with c2:
            if st.button("Open detail", key=f"wiki_csv_open_{i}"):
                st.session_state['wiki_open_name'] = name
                st.session_state['wiki_open_url'] = wiki_url
                st.rerun()

        # Detalhe on demand (thumb + resumo + links)
        if selected_name == name:
            url = st.session_state.get('wiki_open_url') or wiki_url
            lang = _lang_from_wiki_url(url) if url else "en"
            title_guess = _title_from_url(url) if url else name
            info = _wiki_summary(title_guess, lang=lang) if title_guess else {}

            cimg, ctxt = st.columns([1, 4])
            with cimg:
                if info.get("thumb"):
                    st.image(info["thumb"], width=96)
            with ctxt:
                st.markdown(f"**{info.get('title') or name}**")
                if info.get("extract"):
                    st.write(info["extract"])
                else:
                    st.caption("No summary available from Wikipedia.")

                links = []
                if url:
                    links.append(f"[Open on Wikipedia]({url})")
                elif info.get("content_url"):
                    links.append(f"[Open on Wikipedia]({info['content_url']})")
                # pequeno atalho para pesquisar no Spotify
                links.append(f"[Search in Spotify](https://open.spotify.com/search/{quote(f'artist:{name}').replace('%20','%20')})")
                st.markdown(" • ".join(links))

            if st.button("Close detail", key=f"wiki_close_{i}"):
                st.session_state.pop('wiki_open_name', None)
                st.session_state.pop('wiki_open_url', None)
                st.rerun()
