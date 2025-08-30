# views/wiki_page.py
import os
import requests
import pandas as pd
import streamlit as st
from urllib.parse import quote
from services.page_help import show_page_help


    

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

    show_page_help("wikipedia", lang="PT")

    df = load_wiki_styles_csv_quick()
    if df is None:
        st.info("To enable 'Wikipedia styles', place a CSV named 'lista_artistas.csv' (or 'wikipedia_styles.csv') with columns Artista;Genero;URL in the app folder.")
        return

    st.subheader("📚 Wikipedia - Styles")

    # === Botões de topo (como no Spotify): Search / Reset ===
    b1, b2 = st.columns([0.12, 0.18])
    with b1:
        if st.button("🔎 Search", key="wiki_top_search"):
            # força re-render e volta à primeira página
            st.session_state["wiki_csv_page"] = 1
            st.rerun()
    with b2:
        if st.button("🧹 Reset filters", key="wiki_top_reset"):
            for k in ["wiki_csv_style", "wiki_csv_filter", "wiki_csv_page", "wiki_open_name", "wiki_open_url"]:
                st.session_state.pop(k, None)
            st.rerun()

    # ---- Inputs simples (sem form), alinhados com Spotify ----
    styles = sorted(df["style"].dropna().astype(str).unique().tolist())
    c_style, c_filter = st.columns([1, 1])
    with c_style:
        st.selectbox(
            "Style (optional)",
            options=[""] + styles,
            index=0,
            key="wiki_csv_style"
        )
    with c_filter:
        st.text_input(
            "Filter artists (optional)",
            key="wiki_csv_filter",
            placeholder="type a name…"
        )

    # Valores atuais
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

    # 3) Deduplicação condicional (Nome + URL)
    #    • Dedup quando: (a) há pesquisa por artista  OU  (b) não há filtros (sem artista e sem estilo)
    has_artist = bool((filter_txt or "").strip())
    has_style  = bool(sel_style)
    do_dedup   = has_artist or (not has_artist and not has_style)
    if do_dedup and not sub.empty:
        sub["_n"] = sub["name"].astype(str).str.casefold().str.strip()
        sub["_u"] = sub["wiki_url"].astype(str).str.casefold().str.strip()
        sub = sub.drop_duplicates(subset=["_n", "_u"], keep="first").drop(columns=["_n", "_u"])

    # Ordenação por nome
    sub.sort_values("name", inplace=True)

    # ---- Paginação estilo Spotify (fixo: 10 por página)
    page_size = 10
    total = len(sub)
    total_pages = (total - 1) // page_size + 1 if total else 1

    # reset quando mudam os filtros (antes de instanciar botões)
    if st.session_state.get("_wiki_last_filter") != (filter_txt, sel_style):
        st.session_state["_wiki_last_filter"] = (filter_txt, sel_style)
        st.session_state["wiki_csv_page"] = 1

    # página atual (em state)
    page = int(st.session_state.get("wiki_csv_page", 1) or 1)
    page = max(1, min(page, total_pages))

    # barra de navegação:  Pag: N  |  ◀ Previous  |  Next ▶
    cpage, cprev, cnext = st.columns([0.20, 0.14, 0.14])
    with cpage:
        st.markdown(
            f"<div style='height:38px;display:flex;align-items:center;'>"
            f"<strong>Pag:</strong>&nbsp;{page}/{total_pages}</div>",
            unsafe_allow_html=True,
        )

    def _wiki_goto(delta: int):
        p = int(st.session_state.get("wiki_csv_page", 1) or 1)
        st.session_state["wiki_csv_page"] = max(1, min(total_pages, p + delta))


    with cprev:
        st.button("◀ Previous", key="wiki_csv_prev", on_click=_wiki_goto, kwargs={"delta": -1}, use_container_width=True)
    with cnext:
        st.button("Next ▶", key="wiki_csv_next", on_click=_wiki_goto, kwargs={"delta": +1}, use_container_width=True)

    st.caption(f"{total} artists • {total_pages} pages")

    # Slice da página
    start = (page - 1) * page_size
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
