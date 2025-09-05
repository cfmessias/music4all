import os, re, unicodedata
from typing import List, Dict, Any, Optional
import urllib.parse as _up

import streamlit as st
from rapidfuzz import fuzz
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", st.secrets.get("SPOTIFY_CLIENT_ID", ""))
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", st.secrets.get("SPOTIFY_CLIENT_SECRET", ""))
SPOTIFY_MARKET = os.getenv("SPOTIFY_MARKET", st.secrets.get("SPOTIFY_MARKET", "US")) or "US"

# ---------------- Parse/embeds ----------------
def _parse_spotify_kind_id(url_or_uri: str) -> tuple[str | None, str | None]:
    """
    Devolve (kind, id) para 'spotify:album:ID' / 'https://open.spotify.com/album/ID' / ...
    kind ∈ {'album','playlist','track'}
    """
    s = (url_or_uri or "").strip()
    if not s:
        return (None, None)
    if s.startswith("spotify:"):
        parts = s.split(":")
        if len(parts) >= 3:
            return (parts[1], parts[2])
        return (None, None)
    if "open.spotify.com" in s:
        path = _up.urlparse(s).path.strip("/")
        segs = [x for x in path.split("/") if x]
        # pode vir 'embed/album/...'
        if segs and segs[0] == "embed" and len(segs) >= 2:
            segs = segs[1:]
        if len(segs) >= 2:
            return (segs[0], segs[1])
    return (None, None)

@st.cache_data(ttl=86400, show_spinner=False)
def compact_embed_url(url_or_uri: str) -> str:
    """
    Se for álbum/playlist: devolve embed do primeiro 'track' (mais baixo).
    Caso contrário: devolve embed correspondente ao input.
    """
    kind, sid = _parse_spotify_kind_id(url_or_uri)
    if not kind or not sid:
        return ""
    sp = _sp_client()

    def _embed_track(tid: str) -> str:
        return f"https://open.spotify.com/embed/track/{tid}"

    try:
        if kind == "album":
            tr = sp.album_tracks(sid, limit=1)
            items = (tr or {}).get("items") or []
            if items:
                return _embed_track(items[0].get("id"))
        elif kind == "playlist":
            pl = sp.playlist_items(sid, limit=1, additional_types=["track"])
            items = (pl or {}).get("items") or []
            if items:
                track = (items[0].get("track") or {})
                tid = track.get("id")
                if tid:
                    return _embed_track(tid)
        elif kind == "track":
            return _embed_track(sid)
    except Exception:
        pass

    # fallback: usar o embed do próprio recurso
    if kind in {"album", "playlist", "track"}:
        return f"https://open.spotify.com/embed/{kind}/{sid}"
    return url_or_uri  # último recurso

# ---------------- Spotify client (cacheado) ----------------
@st.cache_resource(show_spinner=False)
def _sp_client():
    auth = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
    return spotipy.Spotify(client_credentials_manager=auth, requests_timeout=10, retries=2)

# ---------------- Normalização / util ----------------
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[\W_]+", " ", s).strip()

def _safe_year(y) -> Optional[int]:
    if not y: return None
    m = re.search(r"\d{4}", str(y))
    return int(m.group(0)) if m else None

def _year_from_date(d: str) -> Optional[int]:
    try:
        return int((d or "")[:4])
    except Exception:
        return None

def _album_year(alb: dict) -> Optional[int]:
    return _year_from_date(alb.get("release_date") or "")

def _album_artists(alb: dict) -> str:
    return " ".join(a.get("name","") for a in alb.get("artists", []) if a.get("name"))

# tokens distintivos: tudo depois de ":" / "–" / "()", senão palavras após a 1.ª
def _distinct_tokens(title: str) -> set[str]:
    base = title or ""
    parts = re.split(r"[:\-\(\)]", base, maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        tail = parts[1]
        toks = re.split(r"[\s/]+", tail)
    else:
        bits = base.split()
        toks = bits[1:] if len(bits) > 1 else []
    stop = {"the","and","of","season","series","part"}
    return {t.lower() for t in toks if len(t) >= 2 and t.lower() not in stop}

# gerar variantes simples do título: inserir ":" entre SIGLA + resto, e cabeça antes de ":"/"-"
def _title_variants(title: str) -> List[str]:
    title = (title or "").strip()
    out = {title}
    m = re.match(r"^([A-Z]{2,})(?:[\s\-:]+)(.+)$", title)
    if m:
        out.add(f"{m.group(1)}: {m.group(2)}")
    head = re.split(r"[:\-–]", title, maxsplit=1)[0].strip()
    if head and head.lower() != title.lower():
        out.add(head)
    return list(out)

# ---------------- Palavras-chave ----------------
_OST_STRICT_POS = [
    "music from the motion picture",
    "original motion picture soundtrack",
    "motion picture soundtrack",
    "original soundtrack",
    "original score",
    "score from the motion picture",
    "television soundtrack",
    "tv soundtrack",
    "series soundtrack",
]
_OST_POS = [
    "original motion picture soundtrack", "original soundtrack", "motion picture soundtrack",
    "original score", "television soundtrack", "tv soundtrack", "series soundtrack", "soundtrack", "ost",
]
_OST_NEG = [
    "deluxe","expanded","remaster","remastered","karaoke","tribute",
    "mixtape","remix","covers","cover","demo","live at","bonus track"
]

def _has_kw(name: str, kws: List[str]) -> bool:
    n = _norm(name)
    return any(_norm(k) in n for k in kws)

# ---------------- Scoring ----------------
def _score_album_like(name: str, title: str, ref_year: Optional[int], media_kind: str,
                      alb: dict | None = None, must_tokens: set[str] | None = None,
                      hint_artists: Optional[List[str]] = None) -> float:
    name_n = _norm(name)
    title_n = _norm(title)
    fuzzy = max(fuzz.WRatio(name_n, title_n), fuzz.token_set_ratio(name_n, title_n))

    # Palavras de OST: muito fortes > fortes > ausência (penalização grande)
    if _has_kw(name, _OST_STRICT_POS):
        kw_bonus = 30
    elif _has_kw(name, _OST_POS):
        kw_bonus = 20
    else:
        kw_bonus = -50

    neg_pen  = -10 if _has_kw(name, _OST_NEG) else 0

    type_bonus = 0
    tracks_b   = 0
    year_pen   = 0
    hint_bonus = 0
    va_bonus   = 0

    if alb:
        if alb.get("album_type") == "album":
            type_bonus = 8
        tracks = alb.get("total_tracks") or 0
        # OSTs costumam ter muitas faixas; poucas faixas → suspeito
        tracks_b = 10 if tracks >= 12 else (4 if tracks >= 8 else -18)
        rel = _album_year(alb)
        # Para TV não penalizamos por ano (OST pode sair bem depois)
        if ref_year and rel and not media_kind.lower().startswith("tv"):
            year_pen = -4 * min(3, abs(rel - ref_year))
        if hint_artists:
            arts_n = _norm(_album_artists(alb))
            if any(_norm(h) in arts_n for h in hint_artists):
                hint_bonus = 14
        # Compilações típicas de OST
        arts_n2 = _norm(_album_artists(alb))
        if any(k in arts_n2 for k in ["various artists", "orchestra", "ensemble", "score"]):
            va_bonus = 6

    kind_bonus = 0
    if media_kind.lower().startswith("tv") and any(k in name_n for k in ["television","tv","season","series"]):
        kind_bonus = 6

    token_pen = 0
    if must_tokens:
        miss = [t for t in must_tokens if t not in name_n]
        token_pen = -35 if len(miss) == len(must_tokens) else (-15 if miss else 0)

    return float(
        fuzzy + kw_bonus + neg_pen + type_bonus + tracks_b +
        year_pen + hint_bonus + kind_bonus + token_pen + va_bonus
    )


# ---------------- Theme track scoring (fallback) ----------------
def _score_theme_track(trk: dict, title: str, ref_year: Optional[int],
                       hint_artists: Optional[List[str]] = None) -> float:
    """Scoring simples para faixas que sejam 'Theme' do título indicado."""
    try:
        from rapidfuzz import fuzz
    except Exception:
        # fallback mínimo
        fuzz = None

    name = (trk.get("name") or "").strip()
    album = trk.get("album", {}) or {}
    album_name = (album.get("name") or "").strip()
    rel_year = _year_from_date(album.get("release_date") or "")

    base = 0.0
    if fuzz:
        # combinar com variantes do título
        variants = _title_variants(title)
        base = max(fuzz.token_set_ratio(name, v) for v in variants) * 0.6
        base = float(base)
    else:
        base = 50.0 if title.lower() in (name + " " + album_name).lower() else 0.0

    nlow = name.lower()
    alow = album_name.lower()

    # Bónus por palavras-chave de "tema"
    theme_bonus = 0.0
    if "theme" in nlow:
        theme_bonus += 25.0
    if any(k in nlow for k in ["main theme", "opening theme", "ending theme"]):
        theme_bonus += 10.0

    # Título no álbum/na faixa
    title_bonus = 0.0
    t = title.lower()
    if t in alow:
        title_bonus += 15.0
    if t in nlow:
        title_bonus += 10.0

    # Proximidade do ano
    year_bonus = 0.0
    if ref_year and rel_year:
        year_bonus += max(0.0, 10.0 - 3.0 * abs(ref_year - rel_year))

    # Artistas sugeridos
    hint_bonus = 0.0
    if hint_artists:
        names = " ".join(a.get("name","") for a in trk.get("artists", []) if a)
        if any(h.lower() in names.lower() for h in hint_artists if h):
            hint_bonus += 6.0

    return float(base + theme_bonus + title_bonus + year_bonus + hint_bonus)


def search_theme_tracks(title: str, year_txt: str = "", artist: str = "", limit: int = 10,
                        media_kind: str = "movie",
                        hint_artists: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Procura faixas de 'Theme' para o título indicado, como fallback quando não há OST."""
    sp = _sp_client()
    if not title:
        return []

    ref_year = _safe_year(year_txt)
    variants = _title_variants(title)
    # Queries orientadas a "theme"
    base_qs = []
    for v in variants:
        base_qs += [
            f'track:"{v}" theme',
            f'track:"{v}" "main theme"',
        ]
        if media_kind.lower().startswith("tv"):
            base_qs += [
                f'track:"{v}" "opening theme"',
                f'track:"{v}" "ending theme"',
            ]

    # pesquisar com/sem market
    items: List[dict] = []
    seen = set()
    for q in base_qs:
        for mk in (SPOTIFY_MARKET, None):
            try:
                res = _search_sp(sp, q, "track", limit, mk)
            except Exception:
                res = []
            for trk in res or []:
                tid = trk.get("id")
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                items.append(trk)

    # pontuar e ordenar
    scored = [(_score_theme_track(trk, title, ref_year, hint_artists), trk) for trk in items]
    scored.sort(key=lambda t: t[0], reverse=True)

    out: List[Dict[str, Any]] = [{
        "title": trk.get("name") or "",
        "artist": " ".join(a.get("name","") for a in trk.get("artists", []) if a.get("name")),
        "year": _year_from_date((trk.get("album") or {}).get("release_date") or "") or "",
        "url": (trk.get("external_urls") or {}).get("spotify") or "",
        "uri": trk.get("uri") or "",
        "_score": float(sc),
        "_kind": "track",
    } for sc, trk in scored[:limit]]

    return out
# ---------------- Queries ----------------
def _build_queries(title: str, ref_year: Optional[int], media_kind: str,
                   hint_artists: Optional[List[str]]) -> List[str]:
    title = (title or "").strip()
    variants = _title_variants(title)

    common = ['"original soundtrack"', '"original score"', 'soundtrack', 'score']
    tv     = ['"original television"', '"tv series"', 'television', '"original series"']
    movie  = ['"original motion picture"', '"motion picture"', 'film']

    qs: List[str] = []
    for t in variants:
        base = f'album:"{t}"'
        qs.append(base)
        qs += [f"{base} {q}" for q in common]
        qs += [f"{base} {q}" for q in (tv if media_kind.lower().startswith("tv") else movie)]

    # queries com compositor (se houver)
    head = re.split(r"[:\-–]", title, maxsplit=1)[0].strip()
    for comp in (hint_artists or []):
        c = comp.replace('"','')
        qs.append(f'album:"{title}" artist:"{c}"')
        if head and head.lower() != title.lower():
            qs.append(f'album:"{head}" artist:"{c}"')

    # Para filmes, estreitar por ano (±1). Para TV, não restringir por ano.
    if ref_year and not media_kind.lower().startswith("tv"):
        ywin = f" year:{ref_year-1}-{ref_year+1}"
        qs = [q + ywin for q in qs]

    # dedupe mantendo ordem
    seen, out = set(), []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out

# ---------------- Busca principal ----------------
def _search_sp(sp, q: str, typestr: str, limit: int, market: Optional[str]) -> List[dict]:
    """Faz pesquisa com/sem market. Devolve items da resposta (lista)."""
    try:
        res = sp.search(q=q, type=typestr, limit=min(20, limit), market=market) if market else sp.search(q=q, type=typestr, limit=min(20, limit))
        items = res.get(f"{typestr}s", {}).get("items", [])
        return items or []
    except Exception:
        return []

def search_soundtrack_albums(title: str, year_txt: str = "", artist: str = "", limit: int = 25,
                             media_kind: str = "movie",
                             hint_artists: Optional[List[str]] = None) -> List[Dict[str,Any]]:
    sp = _sp_client()
    if not title:
        return []

    ref_year = _safe_year(year_txt)
    must_tokens = _distinct_tokens(title)

    # 1) ÁLBUNS (duas fases: com market, depois sem market se vazio)
    candidates: List[dict] = []
    seen_ids = set()
    for q in _build_queries(title, ref_year, media_kind, hint_artists):
        items = _search_sp(sp, q, "album", limit, SPOTIFY_MARKET)
        if not items:
            items = _search_sp(sp, q, "album", limit, None)  # sem market → mais recall
        for alb in items:
            aid = alb.get("id")
            if not aid or aid in seen_ids:
                continue
            seen_ids.add(aid)
            candidates.append(alb)

    scored = [
        (_score_album_like(alb.get("name",""), title, ref_year, media_kind,
                           alb=alb, must_tokens=must_tokens, hint_artists=hint_artists), alb)
        for alb in candidates
    ]
    scored.sort(key=lambda t: t[0], reverse=True)

    out: List[Dict[str, Any]] = [{
        "title": alb.get("name"),
        "artist": _album_artists(alb),
        "year": _album_year(alb) or "",
        "url": (alb.get("external_urls") or {}).get("spotify") or "",
        "uri": alb.get("uri") or "",
        "_score": float(sc),
    } for sc, alb in scored[:limit]]

    # 2) FALLBACK: PLAYLISTS (muitas OST de TV existem só como playlists oficiais)
    if not out:
        plcands: List[dict] = []
        pseen = set()
        for q in _build_queries(title, ref_year, media_kind, hint_artists):
            items = _search_sp(sp, q, "playlist", 20, SPOTIFY_MARKET)
            if not items:
                items = _search_sp(sp, q, "playlist", 20, None)
            for pl in items:
                pid = pl.get("id")
                if not pid or pid in pseen:
                    continue
                pseen.add(pid)
                plcands.append(pl)

        pscored = [
            (_score_album_like(pl.get("name",""), title, ref_year, media_kind,
                               alb=None, must_tokens=must_tokens, hint_artists=hint_artists), pl)
            for pl in plcands
        ]
        pscored.sort(key=lambda t: t[0], reverse=True)

        out = out + [{
            "title": pl.get("name"),
            "artist": (pl.get("owner",{}) or {}).get("display_name",""),
            "year": "",
            "url": (pl.get("external_urls") or {}).get("spotify") or "",
            "uri": pl.get("uri") or "",
            "_score": float(sc),
        } for sc, pl in pscored[:limit]]

    return out

def pick_best_soundtrack(title: str, year_txt: str = "", artist: Optional[str] = None,
                         media_kind: str = "movie", hint_artists: Optional[List[str]] = None) -> Dict[str,Any]:
    cands = search_soundtrack_albums(title=title, year_txt=year_txt, artist=artist or "",
                                     limit=25, media_kind=media_kind, hint_artists=hint_artists)
    if not cands:
        return {}

    # Preferir candidatos com sinais fortes de OST
    strict = [c for c in cands if _has_kw(c["title"], _OST_STRICT_POS)]
    if strict:
        strict.sort(key=lambda x: x["_score"], reverse=True)
        best = strict[0]
    else:
        best = cands[0]

    # limiar adaptativo; se não tiver sinais de OST, exigir score mais alto
    base_thresh = 68 if media_kind.lower().startswith("tv") else 72
    needs_strong = not _has_kw(best["title"], _OST_POS)
    thresh = base_thresh + (10 if needs_strong else 0)

    return best if best.get("_score", 0) >= thresh else {}
# Back-compat: API antiga
def spotify_soundtrack_search(*args, **kwargs):
    return search_soundtrack_albums(*args, **kwargs)
