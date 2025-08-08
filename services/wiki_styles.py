"""
services/wiki_styles.py
-----------------------
Panel + helpers to show "Wikipedia styles — Top 50 by followers".

Como integrar:
1) Guardar este ficheiro em: services/wiki_styles.py
2) No app.py: from services.wiki_styles import render_wikipedia_styles_panel
3) Chamar ANTES da secção de resultados: render_wikipedia_styles_panel(TOKEN)

Notas:
- NÃO toca em st.session_state["page_input"] (evita erro de mutação do Streamlit).
- Filtro "Strict by Spotify genres" por defeito para evitar classificações erradas
  (ex.: Selena Gomez não aparece em Progressive Rock).
- Cache por nome (14 dias) para ser muito mais rápido depois da 1.ª execução.
"""

from __future__ import annotations

import os
import re
import streamlit as st
import pandas as pd
from typing import Iterable, Optional, List, Dict, Any

from services.spotify import search_artists, fmt


# -----------------------------
# CSV loading / normalization
# -----------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def load_wiki_styles_csv(candidates: Optional[Iterable[str]] = None) -> Optional[pd.DataFrame]:
    """
    Lê CSV com mapeamento artista->estilo.
    Colunas esperadas (PT/EN):  Artista;Genero;URL  OU  Artist;Genre;URL
    Aceita ';' ou ','.
    Devolve DataFrame normalizado: columns = name | style | wiki_url
    """
    if candidates is None:
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
# Spotify best match + filters
# -----------------------------

def _norm_name(n: str) -> str:
    """Remove sufixos tipo '(band)' / '(musician)', normaliza traços, trim."""
    n = re.sub(r"\s*\([^)]*\)$", "", n).strip()
    n = n.replace("–", "-").replace("—", "-")
    return n


def _genre_synonyms(style: str) -> List[str]:
    """Sinónimos/aliases para melhorar o match de géneros do Spotify."""
    s = (style or "").lower().strip()
    if s in ("progressive rock", "prog rock", "prog"):
        return [
            "progressive rock", "prog rock", "symphonic prog", "neo-prog",
            "canterbury", "krautrock", "space rock", "art rock", "zeuhl",
        ]
    if s in ("latin pop", "pop latino", "latino pop"):
        return ["latin pop", "latino pop"]
    if s in ("dance-pop", "dance pop"):
        return ["dance-pop", "dance pop"]
    # fallback
    return [s] if s else []


def _genre_match(artist_genres: Optional[List[str]], style: str) -> bool:
    """Pelo menos um sinónimo do estilo aparece em algum género do artista."""
    gs = [(g or "").lower() for g in (artist_genres or [])]
    synonyms = _genre_synonyms(style)
    return any(any(syn in g for syn in synonyms) for g in gs)


@st.cache_data(ttl=14 * 86400, show_spinner=False)
def spotify_best_match_cached(token: str, qname: str) -> Optional[Dict[str, Any]]:
    """
    Melhor correspondência no Spotify para um nome (1) query com quotes; (2) query simples.
    Ordena por followers e prefere nome quase-exato. Cache 14 dias.
    """
    for q in (f'artist:"{qname}"', qname):
        data = search_artists(token, q, limit=10, offset=0) or {}
        items = data.get("items") or []
        if not items:
            continue
        # por followers desc
        items.sort(key=lambda a: (a.get("followers", {}).get("total", 0)), reverse=True)
        # prefer near-exact
        ql = qname.lower()
        pick = None
        for cand in items:
            nm_l = (cand.get("name") or "").lower()
            if nm_l == ql or nm_l.startswith(ql + " "):
                pick = cand
                break
        return pick or items[0]
    return None


@st.cache_data(ttl=86400, show_spinner=True)
def wiki_style_top_followers(style: str, token: str,
                             max_artists: int = 50,
                             strict_by_spotify: bool = True,
                             cap_names: int = 300) -> List[Dict[str, Any]]:
    """
    Constrói o Top-N (50) de artistas Spotify para um estilo da Wikipedia.
    - Faz resolve de cada nome -> artista Spotify (com cache).
    - (Opcional) Filtra por artist.genres do Spotify (strict=True).
    - Ordena por followers desc.
    """
    df = load_wiki_styles_csv()
    if df is None:
        return []
    names = df[df["style"].str.lower() == style.lower()]["name"].dropna().astype(str).tolist()[:cap_names]

    seen_ids: set[str] = set()
    results: List[Dict[str, Any]] = []

    for nm in names:
        qname = _norm_name(nm)
        pick = spotify_best_match_cached(token, qname)
        if not pick:
            continue
        if strict_by_spotify and not _genre_match(pick.get("genres"), style):
            continue
        if pick.get("id") and pick["id"] not in seen_ids:
            seen_ids.add(pick["id"])
            results.append(pick)
        if len(results) >= max_artists:  # early stop
            break

    results.sort(key=lambda a: (a.get("followers", {}).get("total", 0)), reverse=True)
    return results[:max_artists]


# -----------------------------
# UI
# -----------------------------

def render_wikipedia_styles_panel(token: str,
                                  title: str = "📚 Wikipedia styles — Top 50 by followers",
                                  default_style: Optional[str] = "progressive rock") -> None:
    """
    Renderiza o painel expansível com selector de estilo e Top-50.
    O botão "Open detail" muda a pesquisa sem tocar no widget page_input.
    """
    wiki_df = load_wiki_styles_csv()
    if wiki_df is None:
        st.info("To enable 'Wikipedia styles', place a CSV named 'lista_artistas.csv' (or 'wikipedia_styles.csv') with columns Artista;Genero;URL in the app folder.")
        return

    with st.expander(title, expanded=False):
        styles = sorted(wiki_df["style"].dropna().astype(str).unique().tolist())
        try:
            default_idx = styles.index(default_style) if default_style in styles else 0
        except Exception:
            default_idx = 0

        sel_style = st.selectbox("Style", options=styles, index=default_idx, key="wiki_style_select")
        strict = st.checkbox("Strict by Spotify genres", value=True, key="wiki_style_strict")

        if sel_style:
            with st.spinner(f"Building Top 50 for '{sel_style}'…"):
                top_items = wiki_style_top_followers(sel_style, token, max_artists=50, strict_by_spotify=strict)

            if not top_items:
                st.info("No artists found for this style yet. Check your CSV columns and values.")
                return

            for i, a in enumerate(top_items, start=1):
                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                name = a.get("name") or "—"
                spotify_url = (a.get("external_urls") or {}).get("spotify")
                followers_n = (a.get("followers") or {}).get("total", 0)
                followers = fmt(followers_n)
                popularity = a.get("popularity", 0)
                with c1:
                    if spotify_url:
                        st.markdown(f"**{i}. [{name}]({spotify_url})**")
                    else:
                        st.markdown(f"**{i}. {name}**")
                c2.markdown(f"Followers: **{followers}**")
                c3.markdown(f"Pop: **{popularity}**")
                if c4.button("Open detail", key=f"wiki_open_{a.get('id','_')}_{i}"):
                    # NÃO mexer em 'page_input' (widget). Só no estado "page" normal.
                    st.session_state['query'] = f'artist:"{name}"'
                    st.session_state['page'] = 1
                    st.session_state.pop('deep_items', None)
                    st.rerun()
