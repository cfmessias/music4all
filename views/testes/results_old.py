# views/spotify/results.py
from __future__ import annotations

import re
import requests
import streamlit as st

from services.spotify.lookup import embed_spotify
from services.spotify.radio import (
    find_artist_this_is_playlist,
    find_artist_radio_playlist,
    get_thisis_candidates,
    get_radio_candidates,
    playlist_artist_ratio,
)
from services.spotify import get_auth_header, fetch_all_albums, fmt
from services.ui_helpers import ui_mobile, ui_audio_preview, ms_to_mmss
from services.playlist import list_playlists, add_tracks_to_playlist
from services.spotify.search_service import (
    coerce_query_to_genre_if_applicable,  # vamos usar só quando NÃO há nome
)
from services.genres_bridge import resolve_genre_canon_and_aliases, norm_label

OV_KEY = "artist_playlist_overrides"
if OV_KEY not in st.session_state:
    st.session_state[OV_KEY] = {}   # { artist_id: {"thisis": {...}, "radio": {...}} }

# =========================
#   Wikipedia helpers
# =========================
WIKI_API = "https://{lang}.wikipedia.org/w/api.php"


@st.cache_data(ttl=86400, show_spinner=False)
def _wiki_api_search(query: str, lang: str = "pt", limit: int = 6) -> list[dict]:
    try:
        r = requests.get(
            WIKI_API.format(lang=lang),
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": limit,
                "utf8": 1,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return (r.json().get("query") or {}).get("search") or []
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_wikipedia_title(name: str, lang: str = "pt", hints: list[str] | None = None) -> tuple[str | None, str | None]:
    """
    Resolve título/URL na Wikipédia com heurística leve:
    - tenta name + (cantor|música|singer|music) + pistas
    - pontua candidatos por proximidade do título ao nome e presença das pistas no snippet
    """
    if not name:
        return None, None
    hints = [h for h in (hints or []) if h]
    base = name.strip()
    qset = [
        base,
        f'{base} (cantor)' if lang == "pt" else f"{base} (singer)",
        f"{base} música" if lang == "pt" else f"{base} music",
    ]
    for h in hints[:3]:
        qset.append(f"{base} {h}")
    target = _norm_txt(base)
    best = (0.0, None)
    for q in qset:
        for cand in _wiki_api_search(q, lang=lang, limit=6):
            title = str(cand.get("title") or "").strip()
            snippet = _norm_txt(cand.get("snippet") or "")
            tnorm = _norm_txt(title)
            score = 0.0
            if tnorm == target: score += 3.0
            if target in tnorm: score += 1.5
            score += sum(0.5 for h in hints if _norm_txt(h) in snippet)
            if score > best[0]:
                best = (score, (title, f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"))
    return best[1] if best[0] > 0 else (None, None)


def _norm_txt(s: str) -> str:
    # normaliza texto p/ comparação: lower, sem acentos, espaços compactados
    import unicodedata
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s)


# --- NOVO: resumo curto (2–3 frases) da Wikipédia ---
@st.cache_data(ttl=86400, show_spinner=False)
def _wiki_summary_from_title(title: str, lang: str = "en") -> str:
    """Obtém 2–3 frases do resumo da Wikipédia para 'title'."""
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '%20')}"
        r = requests.get(
            url,
            timeout=8,
            headers={
                "accept": "application/json",
                "user-agent": "music4all/1.0 (+https://example.com)",
            },
        )
        if r.status_code != 200:
            return ""
        data = r.json()
        if (data.get("type") or "").lower() == "disambiguation":
            return ""
        txt = (data.get("extract") or "").strip()
        if not txt:
            return ""
        import re as _re
        sents = _re.split(r"(?<=[.!?])\s+", txt)
        return " ".join(sents[:3])
    except Exception:
        return ""


@st.cache_data(ttl=86400, show_spinner=False)
def _artist_wiki_blurb(name: str, hints: list[str] | None = None, lang: str = "en") -> tuple[str, str]:
    """Devolve (blurb, url) para o artista a partir da Wikipédia."""
    title, url = resolve_wikipedia_title(name, lang=lang, hints=hints or [])
    if not title:
        return "", ""
    txt = _wiki_summary_from_title(title, lang=lang)
    if not url:
        url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
    return txt, url


def _parse_spotify_playlist_id(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    m = re.search(r'playlist/([A-Za-z0-9]+)', s)
    if m:
        return m.group(1)
    m = re.search(r'spotify:playlist:([A-Za-z0-9]+)', s)
    if m:
        return m.group(1)
    if re.fullmatch(r'[A-Za-z0-9]+', s):
        return s  # parece ID
    return None


# =========================
#   Wildcards & Search
# =========================
def _parse_wildcard(raw: str) -> tuple[str, str]:
    """Return (core, mode) from input with '*' at start/end."""
    s = (raw or "").strip()
    if not s:
        return "", "all"
    starts = s.startswith("*")
    ends = s.endswith("*")
    core = s.strip("*").strip()
    if not core:
        return "", "all"
    if starts and ends:
        return core, "contains"
    if starts:
        return core, "suffix"
    if ends:
        return core, "prefix"
    return core, "exact"


def _match_name(name: str, core: str, mode: str) -> bool:
    n = (name or "").strip().casefold()
    c = (core or "").strip().casefold()
    if not c:
        return True
    if mode == "exact":
        return n == c
    if mode == "prefix":
        return n.startswith(c)
    if mode == "suffix":
        return n.endswith(c)
    if mode == "contains":
        return c in n
    return True


@st.cache_data(ttl=900, show_spinner=False)
def _search_artists_api(token: str, q: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Single page call to /v1/search for artists."""
    if not token or not q:
        return []
    headers = get_auth_header(token)
    params = {"q": q, "type": "artist", "limit": limit, "offset": offset}
    try:
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params=params,
            timeout=12,
        )
        if r.status_code != 200:
            return []
        return ((r.json().get("artists") or {}).get("items") or [])
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def search_artists_wildcard(token: str, raw_query: str, max_pages: int = 4) -> list[dict]:
    """
    Search artists honoring user wildcards.
    - Scans up to 4 pages (offsets 0/50/100/150).
    - For 'exact', try artist:"<name>" first and then fallback.
    - Dedup by id and filter locally.
    """
    core, mode = _parse_wildcard(raw_query)
    if not core:
        return []

    seen, out = set(), []
    primary_q = core
    exact_q = f'artist:"{core}"' if mode == "exact" else None

    # 1) Exact first (if applicable)
    if exact_q:
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, exact_q, limit=50, offset=off):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                if _match_name(a.get("name", ""), core, mode):
                    out.append(a)

    # 2) Normal / fallback
    if (not exact_q) or (exact_q and not out):
        for off in (0, 50, 100, 150)[:max_pages]:
            for a in _search_artists_api(token, primary_q, limit=50, offset=off):
                if not isinstance(a, dict):
                    continue
                aid = a.get("id")
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                if _match_name(a.get("name", ""), core, mode):
                    out.append(a)

    return out


def _extract_user_query() -> str:
    """
    Read the user's query from common keys to avoid UI mismatches.
    """
    for k in [
        "query",
        "artist",
        "artist_query",
        "search",
        "artist_name",
        "spotify_artist",
        "spotify_search",
        "name_input",
    ]:
        v = st.session_state.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


# ======== Genre-only support (para quando o campo Artist está vazio) ========
def _parse_genre_only(raw_q: str) -> str | None:
    """
    If raw_q is exactly of the form genre:"<value>", return <value>; else None.
    """
    if not isinstance(raw_q, str):
        return None
    m = re.match(r'^\s*genre\s*:\s*"([^"]+)"\s*$', raw_q.strip(), flags=re.IGNORECASE)
    return (m.group(1).strip() if m else None)


@st.cache_data(ttl=900, show_spinner=False)
def search_artists_by_genre(token: str, genre: str, max_pages: int = 4) -> list[dict]:
    """
    Genre-first search: query Spotify for artists, then filter locally by artist.genres.
    This is robust even when the API's 'genre:' operator doesn't behave consistently.
    """
    if not (token and genre):
        return []
    g = genre.strip().casefold()
    seen, out = set(), []
    # Use the plain genre as search text to broaden recall, then local-filter
    for off in (0, 50, 100, 150)[:max_pages]:
        for a in _search_artists_api(token, genre, limit=50, offset=off):
            if not isinstance(a, dict):
                continue
            aid = a.get("id")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            glist = [str(x).casefold() for x in (a.get("genres") or [])]
            # Accept 'contains' both ways (handles cases like "symphonic prog" vs "symphonic progressive rock")
            if any((g in gg) or (gg in g) for gg in glist):
                out.append(a)
    return out


# =========================
#   Albums / Tracks
# =========================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_album_tracks_api(token: str, album_id: str) -> list[dict]:
    """Fetch album tracks via Spotify API."""
    if not album_id:
        return []
    items = []
    url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
    params = {"limit": 50, "offset": 0}
    headers = get_auth_header(token)
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code == 401:
            return []
        if r.status_code != 200:
            break
        j = r.json() or {}
        items.extend(j.get("items") or [])
        url = j.get("next")
        params = None
    return items


@st.cache_data(ttl=86400, show_spinner=False)
def cached_fetch_all_albums(token: str, artist_id: str):
    return fetch_all_albums(token, artist_id)


# =========================
#   UI
# =========================

def render_spotify_results(token: str):
    """
    Pesquisa de artistas **prioriza o campo Artist**:
      • Se o utilizador escreveu em Artist → pesquisa por ARTISTA (sem '*' automáticos).
      • Se Artist estiver vazio e existir género → pesquisa por GÉNERO.
      • Se ambos vazios mas a query for genre:"…" → trata como GÉNERO.
      • Caso contrário → pesquisa por nome (wildcard permitido pelo utilizador).
    """
    mobile = ui_mobile()

    # --- Guard: se TODOS os inputs estão vazios, limpa qualquer query “antiga” ---
    no_artist = not (st.session_state.get("query") or "").strip()
    no_seed   = not (st.session_state.get("genre_input") or "").strip()
    no_free   = not (st.session_state.get("genre_free_input") or "").strip()
    if no_artist and no_seed and no_free:
        st.session_state.pop("query_effective", None)

    # 1) Lê o que o utilizador acabou de escrever (prioridade absoluta)
    raw_q_direct = _extract_user_query().strip()
    # fallback para algum 'query_effective' herdado de cliques / atalhos
    raw_q = raw_q_direct or (st.session_state.get("query_effective") or "").strip()
    if not raw_q:
        return  # nada a pesquisar ainda

    # 2) Inputs da UI
    name_typed = raw_q_direct                      # ← usa SEMPRE o que o utilizador escreveu
    genre_seed = (st.session_state.get("genre_input") or "").strip()
    genre_free = (st.session_state.get("genre_free_input") or "").strip()
    genre_filter = genre_free or genre_seed

    # 3) Termo de género (apenas se NÃO houver nome digitado)
    explicit_genre = _parse_genre_only(raw_q_direct)
    coerced_genre  = None
    if not raw_q_direct:
        # só tentamos coerção quando o utilizador não escreveu nada
        try:
            coerced_genre = coerce_query_to_genre_if_applicable(raw_q, token=token)
        except Exception:
            coerced_genre = None
    genre_term = explicit_genre or coerced_genre or genre_filter

    # 4) Helpers de normalização/aliases (bridge opcional)
    try:
        _norm_label = norm_label
        _resolve_aliases = resolve_genre_canon_and_aliases
    except Exception:
        def _norm_label(s: str) -> str:
            import unicodedata, re as _re
            s0 = (s or "").strip().lower()
            s0 = unicodedata.normalize("NFKD", s0).encode("ascii","ignore").decode("ascii")
            return _re.sub(r"\s+", " ", s0)
        def _resolve_aliases(label: str):
            n = _norm_label(label)
            return n, [n]

    def _tokenize_label(s: str) -> set[str]:
        return {t for t in re.split(r"[^\w]+", _norm_label(s)) if t}

    def _accept_by_alias_tokens(artist: dict, aliases_norm: list[str]) -> bool:
        if not artist:
            return False
        aliases = set(aliases_norm)
        gl = artist.get("genres") or []
        for gg in gl:
            toks = _tokenize_label(gg)
            if aliases & toks:
                return True
        return False

    # 5) Pesquisa (ARTISTA → GÉNERO → fallback)
    if name_typed:
        by_name = search_artists_wildcard(token, name_typed, max_pages=4) or []

        core = name_typed.strip()

        # 1) match literal estrito (case-insensitive, MAS sem remover acentos)
        def _eq_literal(a):
            return (a.get("name", "").strip().lower() == core.lower())

        exacts = [a for a in by_name if _eq_literal(a)]

        if exacts:
            all_matched = exacts
            mode_caption = "🔎 Mode: artist name (exact)"
        else:
            # 2) fallback: fronteira de palavra (evita “qualquer sítio no meio”)
            import re as _re
            pat = _re.compile(rf"\b{_re.escape(core)}\b", flags=_re.IGNORECASE)
            boundary = [a for a in by_name if pat.search(a.get("name", ""))]

            if boundary:
                all_matched = boundary
                mode_caption = "🔎 Mode: artist name (word boundary)"
            else:
                # 3) último recurso: o que a API devolveu (pode ter nomes “parecidos”)
                all_matched = by_name
                mode_caption = "🔎 Mode: artist name (broad)"

        # filtro opcional por género (se o utilizador preencheu)
        if genre_term:
            gnorm = genre_term.lower()
            all_matched = [a for a in all_matched if any(gnorm in g.lower() for g in (a.get("genres") or []))]
            mode_caption += f" ∩ genre"

#...................
    elif genre_term:
        canon, aliases_norm = _resolve_aliases(genre_term)
        base = search_artists_by_genre(token, genre_term, max_pages=4) or []
        all_matched = [a for a in base if _accept_by_alias_tokens(a, aliases_norm)]
        mode_caption = f"🔎 Mode: genre «{canon}» · artists: {len(all_matched)}"

    else:
        all_matched = search_artists_wildcard(token, raw_q, max_pages=4) or []
        mode_caption = "🔎 Mode: artist name"

    # 6) Ordenar e paginar
    all_matched.sort(key=lambda a: -((a.get("followers") or {}).get("total") or 0))
    per_page = 10
    total_filtered = len(all_matched)
    total_pages = (total_filtered - 1) // per_page + 1 if total_filtered else 0

    page = int(st.session_state.get("page", 1) or 1)
    page = 0 if total_pages == 0 else max(1, min(page, total_pages))
    st.session_state["page"] = page
    st.session_state["page_input"] = page
    st.session_state["sp_total_pages"] = max(total_pages, 1)

    start = (page - 1) * per_page if total_filtered else 0
    end   = start + per_page
    items = all_matched[start:end] if total_filtered else []

    if mode_caption:
        st.caption(mode_caption)

    if not items:
        if name_typed:
            st.info(f'No artists found for "{name_typed}".')
        elif genre_term:
            st.info(f'No artists found for genre "{genre_term}".')
        else:
            st.info("No artist matches your pattern. Try adjusting the * (e.g., Genesis, Yes*, *Yes).")
        return

    # ---- Artists list
    for artist in items:
        followers_fmt = fmt((artist.get("followers") or {}).get("total", 0))
        with st.expander(f"{artist.get('name','—')} ({followers_fmt} followers)"):

            # -------- First-level columns
            col_a, col_b = st.columns([2, 1]) if not mobile else st.columns([1, 1])

            # -------- Column A: meta + links + actions ▶ / ⭐ / 📻
            with col_a:
                st.write(f"**Popularity:** {artist.get('popularity', 0)}/100")
                genres_list = artist.get("genres") or []
                st.write(f"**Genres:** {', '.join(genres_list) if genres_list else '—'}")

                spotify_url = (artist.get("external_urls") or {}).get("spotify")
                wiki_title, wiki_url = resolve_wikipedia_title(
                    artist.get("name", ""),
                    lang="en",
                    hints=(artist.get("genres") or [])[:3],
                )
                links = []
                if spotify_url:
                    links.append(f"[Open in Spotify]({spotify_url})")
                if wiki_url:
                    links.append(f"[Wikipedia]({wiki_url})")
                if links:
                    st.markdown(" • ".join(links) + f" • Followers: {followers_fmt}")
                else:
                    st.write(f"Followers: {followers_fmt}")

                # --- NOVO: About (resumo curto da Wikipédia) ---
                try:
                    bio_en, bio_url = _artist_wiki_blurb(
                        artist.get("name", ""),
                        hints=genres_list,
                        lang="en",
                    )
                except Exception:
                    bio_en, bio_url = "", ""
                if bio_en:
                    st.markdown(f"**About:** {bio_en}")
                    st.caption(f"[Wikipedia]({bio_url})")

                # -------- Actions (one nesting level only)
                act_play, act_thisis, act_radio = st.columns([1, 1, 1])

                # ▶ Embed artist
                with act_play:
                    embed_key = f"artist_{artist['id']}_embed"
                    if st.button("▶", key=f"btn_{artist['id']}_embed", help="Embed artist player"):
                        st.session_state[embed_key] = True
                    if st.session_state.get(embed_key):
                        try:
                            embed_spotify("artist", artist["id"], height=80)
                        except Exception:
                            pass

                # estado único por artista: 'thisis' | 'radio' | None
                open_key        = f"artist_open_panel_{artist['id']}"
                thisis_data_key = f"artist_thisis_result_{artist['id']}"
                radio_data_key  = f"artist_radio_result_{artist['id']}"

                # (migração defensiva: se flags antigas existirem, normaliza uma vez)
                legacy_thisis = st.session_state.pop(f"artist_thisis_open_{artist['id']}", None)
                legacy_radio  = st.session_state.pop(f"artist_radio_open_{artist['id']}", None)
                if legacy_thisis:
                    st.session_state[open_key] = "thisis"
                elif legacy_radio:
                    st.session_state[open_key] = "radio"

                # ⭐ This Is
                with act_thisis:
                    if st.button("⭐ This Is", key=f"btn_thisis_{artist['id']}", help="Find 'This Is <artist>' playlist"):
                        curr = st.session_state.get(open_key)
                        if curr == "thisis":
                            st.session_state[open_key] = None  # toggle off
                        else:
                            try:
                                pl = find_artist_this_is_playlist(
                                    token=token,
                                    artist_name=artist.get("name", ""),
                                    artist_id=artist.get("id"),
                                )
                            except Exception:
                                pl = None
                            st.session_state[thisis_data_key] = pl if pl else {"type": "none"}
                            st.session_state[open_key] = "thisis"

                # 📻 <Artist> Radio
                with act_radio:
                    if st.button("📻 Radio", key=f"btn_radio_{artist['id']}", help="Find '<artist> Radio' playlist"):
                        curr = st.session_state.get(open_key)
                        if curr == "radio":
                            st.session_state[open_key] = None  # toggle off
                        else:
                            try:
                                pl = find_artist_radio_playlist(
                                    token=token,
                                    artist_name=artist.get("name", ""),
                                    artist_id=artist.get("id"),
                                )
                            except Exception:
                                pl = None
                            st.session_state[radio_data_key] = pl if pl else {"type": "none"}
                            st.session_state[open_key] = "radio"

                # --- Painel ativo (This Is / Radio) ---
                panel = st.session_state.get(open_key)

                if panel == "thisis":
                    _pl = st.session_state.get(thisis_data_key)
                    if _pl is None:
                        try:
                            _pl = find_artist_this_is_playlist(
                                token=token,
                                artist_name=artist.get("name", ""),
                                artist_id=artist.get("id"),
                            )
                        except Exception:
                            _pl = {"type": "none"}
                        st.session_state[thisis_data_key] = _pl

                    url = (
                        (_pl or {}).get("url")
                        or (_pl or {}).get("external_url")
                        or ((_pl or {}).get("external_urls") or {}).get("spotify")
                    )
                    pname = (_pl or {}).get("name") or f"This Is {artist.get('name','')}"
                    pid = (_pl or {}).get("id") or (_pl or {}).get("playlist_id")

                    if url:
                        st.markdown(f'[Open “{pname}” on Spotify]({url})')
                    if pid:
                        try:
                            embed_spotify("playlist", pid, height=80)
                        except Exception:
                            pass
                    if not url and not pid:
                        st.info("No 'This Is' playlist found.")

                        # ----- Picker simples (sem rerun) -----
                        cands = get_thisis_candidates(token, artist.get("name", ""), market="PT", max_pages=2)[:12]
                        if cands:
                            labels = [
                                f"{i+1}. {c.get('name')}{' · Spotify' if c.get('owner_is_spotify') else ''}"
                                for i, c in enumerate(cands)
                            ]
                            idx = st.selectbox(
                                "Pick a playlist manually",
                                options=list(range(len(cands))),
                                format_func=lambda i: labels[i],
                                key=f"pick_thisis_idx_{artist['id']}",
                            )
                            if st.button("Use selected", key=f"apply_thisis_{artist['id']}"):
                                choice = cands[idx]
                                st.session_state[thisis_data_key] = choice
                                st.session_state[open_key] = "thisis"
                                _pl = choice
                                url = (_pl or {}).get("url")
                                pid = (_pl or {}).get("id")
                                pname = (_pl or {}).get("name") or f"This Is {artist.get('name','')}"

                        if url or pid:
                            if url:
                                st.markdown(f'[Open “{pname}” on Spotify]({url})')
                            if pid:
                                try:
                                    embed_spotify("playlist", pid, height=80)
                                except Exception:
                                    pass

                            if not cands:
                                st.caption("No candidates found.")
                            else:
                                for i, c in enumerate(cands, start=1):
                                    cols = st.columns([0.70, 0.15, 0.15])
                                    with cols[0]:
                                        owner_tag = " · Spotify" if c.get("owner_is_spotify") else ""
                                        link = c.get("url")
                                        st.markdown(f"{i}. [{c.get('name')}]({link}){owner_tag}")
                                    with cols[1]:
                                        if st.button("Use this", key=f"use_thisis_{artist['id']}_{i}"):
                                            st.session_state[OV_KEY].setdefault(artist['id'], {})["thisis"] = c
                                            st.session_state[f"artist_thisis_result_{artist['id']}"] = c
                                            st.session_state[f"artist_open_panel_{artist['id']}"] = "thisis"
                                            st.experimental_rerun()
                                    with cols[2]:
                                        if artist.get("id"):
                                            if st.button("% artist", key=f"ratio_thisis_{artist['id']}_{i}"):
                                                r = playlist_artist_ratio(token, c.get("id"), artist['id'], max_items=80)
                                                st.toast(f"{int(round(r*100))}% of tracks from this artist", icon="🎵")

                elif panel == "radio":
                    _pl = st.session_state.get(radio_data_key)
                    if _pl is None:
                        try:
                            _pl = find_artist_radio_playlist(
                                token=token,
                                artist_name=artist.get("name", ""),
                                artist_id=artist.get("id"),
                            )
                        except Exception:
                            _pl = {"type": "none"}
                        st.session_state[radio_data_key] = _pl

                    url = (
                        (_pl or {}).get("url")
                        or (_pl or {}).get("external_url")
                        or ((_pl or {}).get("external_urls") or {}).get("spotify")
                    )
                    pname = (_pl or {}).get("name") or f"{artist.get('name','')} Radio"
                    pid = (_pl or {}).get("id") or (_pl or {}).get("playlist_id")

                    if url:
                        st.markdown(f'[Open “{pname}” on Spotify]({url})')
                    if pid:
                        try:
                            embed_spotify("playlist", pid, height=80)
                        except Exception:
                            pass
                    if not url and not pid:
                        st.info("No radio playlist found.")

                        # ----- Picker simples (sem rerun) -----
                        cands = get_radio_candidates(token, artist.get("name", ""), market="PT", max_pages=2)[:12]
                        if cands:
                            labels = [
                                f"{i+1}. {c.get('name')}{' · Spotify' if c.get('owner_is_spotify') else ''}"
                                for i, c in enumerate(cands)
                            ]
                            idx = st.selectbox(
                                "Pick a playlist manually",
                                options=list(range(len(cands))),
                                format_func=lambda i: labels[i],
                                key=f"pick_radio_idx_{artist['id']}",
                            )
                            if st.button("Use selected", key=f"apply_radio_{artist['id']}"):
                                choice = cands[idx]
                                st.session_state[radio_data_key] = choice
                                st.session_state[open_key] = "radio"
                                _pl = choice
                                url = (_pl or {}).get("url")
                                pid = (_pl or {}).get("id")
                                pname = (_pl or {}).get("name") or f"{artist.get('name','')} Radio"

                        if url or pid:
                            if url:
                                st.markdown(f'[Open “{pname}” on Spotify]({url})')
                            if pid:
                                try:
                                    embed_spotify("playlist", pid, height=80)
                                except Exception:
                                    pass

                            if not cands:
                                st.caption("No candidates found.")
                            else:
                                for i, c in enumerate(cands, start=1):
                                    cols = st.columns([0.70, 0.15, 0.15])
                                    with cols[0]:
                                        owner_tag = " · Spotify" if c.get("owner_is_spotify") else ""
                                        link = c.get("url")
                                        st.markdown(f"{i}. [{c.get('name')}]({link}){owner_tag}")
                                    with cols[1]:
                                        if st.button("Use this", key=f"use_radio_{artist['id']}_{i}"):
                                            st.session_state[OV_KEY].setdefault(artist['id'], {})["radio"] = c
                                            st.session_state[f"artist_radio_result_{artist['id']}"] = c
                                            st.session_state[f"artist_open_panel_{artist['id']}"] = "radio"
                                            st.experimental_rerun()
                                    with cols[2]:
                                        if artist.get("id"):
                                            if st.button("% artist", key=f"ratio_radio_{artist['id']}_{i}"):
                                                r = playlist_artist_ratio(token, c.get("id"), artist['id'], max_items=80)
                                                st.toast(f"{int(round(r*100))}% of tracks from this artist", icon="📻")

            # -------- Column B: image
            with col_b:
                imgs = artist.get("images") or []
                if imgs:
                    st.image(imgs[0].get("url"), width=120 if not mobile else 96)

            # -------- Releases (albums/singles/compilations)
            releases = cached_fetch_all_albums(token, artist["id"]) or []

            def _atype(it):
                return (it.get("album_group") or it.get("album_type") or "").lower()

            albums = [x for x in releases if _atype(x) == "album"]
            singles = [x for x in releases if _atype(x) == "single"]
            compilations = [x for x in releases if _atype(x) == "compilation"]

            def _year(it):
                d = it.get("release_date") or ""
                return d[:4] if len(d) >= 4 else None

            years = sorted([y for y in {_year(x) for x in releases} if y])

            # Overview (esq.) + About (dir.) lado a lado
            col_over, col_about = st.columns([1.8, 1])

            with col_over:
                st.markdown("**📖 Overview (Spotify releases):**")
                if years:
                    st.write(f"• First release on Spotify: {years[0]}")
                    st.write(f"• Latest release on Spotify: {years[-1]}")
                else:
                    st.write("• First/Latest release: —")
                st.write(
                    f"• Releases: {len(releases)}  |  "
                    f"Albums: {len(albums)}  |  "
                    f"Singles/EPs: {len(singles)}  |  "
                    f"Compilations: {len(compilations)}"
                )

            with col_about:
                st.markdown("**ℹ️ About**")
                # tenta EN; se falhar, tenta PT
                genres_list = artist.get("genres") or []
                bio, bio_url = _artist_wiki_blurb(artist.get("name", ""), hints=genres_list, lang="en")
                if not bio:
                    bio, bio_url = _artist_wiki_blurb(artist.get("name", ""), hints=genres_list, lang="pt")
                if bio:
                    st.write(bio)
                    if bio_url:
                        st.caption(f"[Wikipedia]({bio_url})")
                else:
                    st.caption("—")


            # -------- Albums panel (top-level columns inside expander)
            cbtn, calist = st.columns([1, 2]) if not mobile else st.columns([1, 1])
            with cbtn:
                if st.button(f"🗂 Albums ({len(albums)})", key=f"alb_btn_{artist['id']}"):
                    st.session_state["open_albums_for"] = artist["id"]
                    st.session_state["albums_data"] = {
                        "artist_name": artist["name"],
                        "albums": sorted(
                            albums, key=lambda x: x.get("release_date", ""), reverse=True
                        ),
                        "singles": sorted(
                            singles, key=lambda x: x.get("release_date", ""), reverse=True
                        )[:30],
                        "comps": sorted(
                            compilations, key=lambda x: x.get("release_date", ""), reverse=True
                        )[:20],
                    }

            with calist:
                if st.session_state.get("open_albums_for") == artist["id"]:
                    ad = st.session_state.get("albums_data", {})
                    artist_name = ad.get("artist_name", artist["name"])
                    st.markdown(f"#### Albums — {artist_name}")

                    # One nesting level of columns (allowed)
                    left, right = st.columns([1.2, 1.8], gap="large") if not mobile else st.columns([1, 1])

                    # LEFT: dropdown + all releases toggle
                    with left:
                        album_opts = []
                        for it in (ad.get("albums") or []):
                            y = (it.get("release_date") or "")[:4]
                            album_opts.append((f"{it.get('name', '—')} ({y})", it.get("id")))
                        if album_opts:
                            labels = [lbl for lbl, _ in album_opts]
                            ids = [aid for _, aid in album_opts]
                            sel = st.selectbox(
                                "Select album",
                                options=list(range(len(labels))),
                                format_func=lambda i: labels[i],
                                key=f"select_album_idx_{artist['id']}",
                            )
                            st.session_state[f"selected_album_id_{artist['id']}"] = ids[sel]

                        show_all = st.toggle(
                            "All releases (albums / singles / compilations)",
                            value=False,
                            key=f"all_releases_{artist['id']}",
                        )
                        if show_all:
                            def _mk(items, title):
                                if not items:
                                    return ""
                                out = [f"<b>{title}</b><ul>"]
                                for it in items:
                                    y = (it.get("release_date") or "")[:4]
                                    url = (it.get("external_urls") or {}).get("spotify")
                                    name = it.get("name", "—")
                                    if url:
                                        out.append(f'<li><a href="{url}" target="_blank">{name}</a> ({y})</li>')
                                    else:
                                        out.append(f"<li>{name} ({y})</li>")
                                out.append("</ul>")
                                return "\n".join(out)

                            html = "<div style='max-height:40vh; overflow:auto;'>"
                            html += _mk(ad.get("albums") or [], "Albums")
                            html += _mk(ad.get("singles") or [], "Singles / EPs")
                            html += _mk(ad.get("comps") or [], "Compilations")
                            html += "</div>"
                            st.markdown(html, unsafe_allow_html=True)

                        if st.button("Close albums", key=f"close_albums_{artist['id']}_panel"):
                            for k in ["open_albums_for", "albums_data", f"selected_album_id_{artist['id']}"]:
                                st.session_state.pop(k, None)

                    # RIGHT: tracks of selected album
                    with right:
                        aid = st.session_state.get(f"selected_album_id_{artist['id']}")
                        if not aid:
                            st.info("Select an album to view its tracks.")
                        else:
                            meta = next((a for a in ad.get("albums", []) if a.get("id") == aid), {})
                            album_name = meta.get("name", "Album")
                            album_url = (meta.get("external_urls") or {}).get("spotify")

                            st.markdown(f"**Tracks — {album_name}**")
                            if album_url:
                                st.markdown(f"[Open album in Spotify]({album_url})")

                            # ---------- TOP controls (target + Add ALL)
                            names = list_playlists() or []
                            dest_choice = st.selectbox(
                                "Target playlist",
                                options=(names + ["➕ Create new…"]) if names else ["➕ Create new…"],
                                key=f"pick_dest_{artist['id']}",
                            )
                            if dest_choice == "➕ Create new…":
                                newn = st.text_input("New playlist name", key=f"pick_dest_new_{artist['id']}")
                                target_name = (newn or "").strip() or "My Playlist"
                            else:
                                target_name = dest_choice

                            if st.button("➕ Add ALL tracks", key=f"add_all_{aid}__top"):
                                rows_all = fetch_album_tracks_api(token, aid) or []
                                rows = []
                                for tr in rows_all:
                                    rows.append(
                                        {
                                            "id": tr.get("id"),
                                            "uri": tr.get("uri"),
                                            "name": tr.get("name"),
                                            "artists": ", ".join([a.get("name", "") for a in (tr.get("artists") or []) if a]),
                                            "album": album_name,
                                            "album_id": aid,
                                            "album_url": album_url,
                                            "disc_number": tr.get("disc_number"),
                                            "track_number": tr.get("track_number"),
                                            "duration_ms": tr.get("duration_ms"),
                                            "preview_url": tr.get("preview_url"),
                                            "external_url": (tr.get("external_urls") or {}).get("spotify"),
                                        }
                                    )
                                if rows:
                                    add_tracks_to_playlist(target_name, rows)
                                    st.success(f"Added {len(rows)} tracks to '{target_name}'.")
                                    for r in rows:
                                        st.session_state[f"chk_{aid}_{r['id']}"] = True
                                else:
                                    st.info("No tracks to add.")

                            # ---------- Build rows for listing (once)
                            rows = []
                            for tr in (fetch_album_tracks_api(token, aid) or []):
                                rows.append(
                                    {
                                        "id": tr.get("id"),
                                        "uri": tr.get("uri"),
                                        "name": tr.get("name"),
                                        "artists": ", ".join([a.get("name", "") for a in (tr.get("artists") or []) if a]),
                                        "album": album_name,
                                        "album_id": aid,
                                        "album_url": album_url,
                                        "disc_number": tr.get("disc_number"),
                                        "track_number": tr.get("track_number"),
                                        "duration_ms": tr.get("duration_ms"),
                                        "preview_url": tr.get("preview_url"),
                                        "external_url": (tr.get("external_urls") or {}).get("spotify"),
                                    }
                                )

                            added_key = f"auto_added_ids__{target_name}"
                            if added_key not in st.session_state:
                                st.session_state[added_key] = set()

                            st.markdown(
                                "<div style='max-height:50vh; overflow:auto; border:1px solid #ddd; padding:8px; border-radius:8px'>",
                                unsafe_allow_html=True,
                            )
                            st.markdown("**To play on Spotify, click the track name.**")

                            for r in rows:
                                base = f"#{r['track_number']} — {r['name']} — {r['artists']} ({ms_to_mmss(r['duration_ms'])})"
                                label_md = f"[{base}]({r['external_url']})" if r.get("external_url") else base

                                ckey = f"chk_{aid}_{r['id']}"
                                checked = st.checkbox(label_md, key=ckey)

                                # Auto-add when toggled on (once)
                                if checked and (r["id"] not in st.session_state[added_key]):
                                    add_tracks_to_playlist(target_name, [r])
                                    st.session_state[added_key].add(r["id"])

                                if r.get("preview_url") and ui_audio_preview():
                                    st.audio(r["preview_url"])

                                st.markdown("<hr style='margin:8px 0; opacity:0.15;'>", unsafe_allow_html=True)

                            st.markdown("</div>", unsafe_allow_html=True)
