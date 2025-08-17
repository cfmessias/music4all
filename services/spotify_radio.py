# services/spotify_radio.py
# Resolve playlists "This Is <Artist>" e "<Artist> Radio" (inclui PT: "Rádio de <Artista>")
# com validação forte:
#   - preferência por títulos exatos (owner=Spotify)
#   - validação por faixas do próprio artista (>=40% ou ~=10/80 analisadas)
#   - filtros anti-ruído (blacklist e exclusão de *mix/remix*)
#   - cache simples em memória (v3)

from __future__ import annotations
from typing import Optional, Dict, List, Tuple
import unicodedata
import re
import time
import requests

# ================== Cache simples (só acertos) ==================
_cache: Dict[str, Tuple[float, dict | None]] = {}
_CACHE_TTL = 6 * 3600  # 6 horas

def _cache_get(key: str) -> Optional[dict]:
    ts, val = _cache.get(key, (0.0, None))
    if (val is not None) and ((time.time() - ts) < _CACHE_TTL):
        return val
    return None

def _cache_set(key: str, val: dict | None):
    _cache[key] = (time.time(), val)
    # proteção contra crescimento
    if len(_cache) > 512:
        _cache.clear()

def clear_spotify_radio_cache():
    """Limpa o cache interno deste módulo (útil em testes)."""
    _cache.clear()

# ================== Utils ==================
def _norm(s: str) -> str:
    """Remove acentos (útil para equivalências PT/EN)."""
    if s is None:
        return ""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")

def _cf(s: str) -> str:
    """casefold sobre texto sem acentos."""
    return _norm(s).casefold()

def _word_in_text(word: str, text: str) -> bool:
    """Match por palavra inteira (casefold + sem acentos)."""
    if not word or not text:
        return False
    w = re.escape(_cf(word))
    return re.search(rf"\b{w}\b", _cf(text)) is not None

# Nomes comuns/curtos: evitar matches pela descrição (ex.: "Yes")
_COMMON_STRICT = {
    "yes", "no", "go", "up", "low", "war", "pop", "fun", "life", "love", "art", "air",
    "jam", "sun", "moon", "rock", "hit", "hot", "top", "mix"
}
def _needs_title_only_match(artist_name: str) -> bool:
    n = _cf(artist_name)
    return (len(n) <= 3) or (n in _COMMON_STRICT)

def _auth_headers(token: Optional[str]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}

def _search_playlists(
    token: str,
    q: str,
    limit: int = 50,
    offset: int = 0,
    market: Optional[str] = None,
) -> List[Dict]:
    """Wrapper do /v1/search para playlists (com market opcional)."""
    if not token:
        return []
    try:
        params = {"q": q, "type": "playlist", "limit": limit, "offset": offset}
        if market:
            params["market"] = market
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers=_auth_headers(token),
            params=params,
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return ((r.json().get("playlists") or {}).get("items") or [])
    except Exception:
        return []

def _playlist_tracks_match_ratio(token: str, playlist_id: str, artist_id: str, max_items: int = 80) -> float:
    """
    Lê até max_items faixas e calcula a proporção de faixas que incluem o artist_id.
    Usado para validar que a playlist é mesmo do artista (>=40% OU ~=10 de 80).
    """
    if not token or not playlist_id or not artist_id:
        return 0.0
    headers = _auth_headers(token)
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    params = {"fields": "items(track(artists(id))),next", "limit": 100, "offset": 0}
    total = 0
    hits = 0
    try:
        while url and total < max_items:
            r = requests.get(url, headers=headers, params=params, timeout=12)
            if r.status_code != 200:
                break
            j = r.json() or {}
            items = j.get("items") or []
            for it in items:
                tr = (it or {}).get("track") or {}
                arts = tr.get("artists") or []
                a_ids = [a.get("id") for a in arts if isinstance(a, dict)]
                total += 1
                if artist_id in a_ids:
                    hits += 1
                if total >= max_items:
                    break
            url = j.get("next")
            params = None  # após a 1ª página, a API usa 'next'
    except Exception:
        return 0.0
    return (hits / total) if total else 0.0

# ================== Filtros anti-ruído ==================
_BLACKLIST = {
    "top 40", "hits", "best of", "cidade fm", "rádio cidade", "globalradios",
    "summer", "party", "dance hits", "viral", "hot hits", "top ", "fm ",
}
def _looks_like_unrelated(artist_name: str, title: str, desc: str) -> bool:
    nn = _cf(title); nd = _cf(desc)
    if any(b in nn or b in nd for b in _BLACKLIST):
        if not _word_in_text(artist_name, nn) and not _word_in_text(artist_name, nd):
            return True
    return False

# ================== THIS IS ==================
def find_artist_this_is_playlist(
    token: Optional[str],
    artist_name: str,
    artist_id: Optional[str] = None,
    market: Optional[str] = None,   # compat (não é necessário aqui)
) -> Optional[Dict]:
    """
    Procura a melhor playlist 'This Is <Artist>'.
    Prioridade:
      A) Título EXATO "This Is <Artist>" (case-insensitive; não remove acentos)
      B) Senão, melhor candidato que comece por "This Is " e mencione o artista (palavra).
         Para nomes curtos/comuns (ex.: "Yes"), a menção tem de estar no TÍTULO (não vale descrição).
    Se 'artist_id' for dado, valida candidatos por faixas (>= 40% ou ~=10/80).
    """
    artist_name = (artist_name or "").strip()
    if not token or not artist_name:
        return None

    cache_key = f"thisis.v3::{_cf(artist_name)}::{artist_id or ''}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    exact_title_cf = f"this is {artist_name}".casefold()
    queries = [f"\"This Is {artist_name}\"", f"This Is {artist_name}"]

    exact_candidates: List[Dict] = []
    general_candidates: List[Tuple[int, Dict]] = []

    for q in queries:
        for off in (0, 50):
            for pl in _search_playlists(token, q, limit=50, offset=off, market=None):
                if not isinstance(pl, dict):
                    continue
                name = (pl.get("name") or "")
                desc = (pl.get("description") or "")
                owner = pl.get("owner") or {}
                owner_is_spotify = ((owner.get("id") or "").lower() == "spotify") or (_cf(owner.get("display_name")) == "spotify")

                name_cf = name.casefold()
                is_exact = (name_cf == exact_title_cf)  # “Génesis” ≠ “Genesis”
                starts_with_thisis = name_cf.startswith("this is ")

                if _needs_title_only_match(artist_name):
                    has_artist = _word_in_text(artist_name, name)   # título apenas
                else:
                    has_artist = _word_in_text(artist_name, name) or _word_in_text(artist_name, desc)

                # excluir playlists com “mix/remix/...”
                if _has_mixish(name) or _has_mixish(desc):
                    continue

                cand = {
                    "type": "playlist",
                    "id": pl.get("id"),
                    "name": name,
                    "external_url": (pl.get("external_urls") or {}).get("spotify"),
                    "image": ((pl.get("images") or [{}])[0] or {}).get("url"),
                    "owner_is_spotify": bool(owner_is_spotify),
                    "description": desc,
                    "kind": "this_is",
                }

                if is_exact:
                    exact_candidates.append(cand)
                elif starts_with_thisis and has_artist:
                    score = 0
                    if owner_is_spotify: score += 3
                    if (pl.get("id") or "").startswith("37i9dQZF"): score += 1
                    general_candidates.append((score, cand))

    # Exatos primeiro (validados por faixas, se possível)
    if exact_candidates:
        exact_candidates.sort(key=lambda c: (not c.get("owner_is_spotify"), c.get("name") or ""))
        if artist_id:
            best = None; best_ratio = -1.0
            for c in exact_candidates:
                ratio = _playlist_tracks_match_ratio(token, c.get("id"), artist_id, max_items=80)
                if ratio >= 0.40 or ratio * 80 >= 10:
                    if ratio > best_ratio:
                        best, best_ratio = c, ratio
            if best:
                _cache_set(cache_key, best); return best
        _cache_set(cache_key, exact_candidates[0]); return exact_candidates[0]

    # Senão, melhores candidatos gerais (com validação por faixas)
    if general_candidates:
        general_candidates.sort(key=lambda t: (-t[0], not t[1].get("owner_is_spotify"), t[1].get("name") or ""))
        if artist_id:
            best = None; best_ratio = -1.0
            for _, c in general_candidates[:5]:
                ratio = _playlist_tracks_match_ratio(token, c.get("id"), artist_id, max_items=80)
                if ratio >= 0.40 or ratio * 80 >= 10:
                    if ratio > best_ratio:
                        best, best_ratio = c, ratio
            if best:
                _cache_set(cache_key, best); return best
        _cache_set(cache_key, general_candidates[0][1]); return general_candidates[0][1]

    _cache_set(cache_key, None)
    return None

# ================== RADIO ==================
def _validate_radio_title(artist_name: str, title: str, desc: str) -> bool:
    """Tem de mencionar o artista (palavra) e referir 'radio/rádio' no título ou descrição.
       Exclui 'mix/remix/megamix/dj mix/radio mix' para evitar listas não-oficiais."""
    # filtros de ruído “genérico”
    if _looks_like_unrelated(artist_name, title, desc):
        return False
    # excluir qualquer playlist que diga “mix”
    if _has_mixish(title) or _has_mixish(desc):
        return False

    nn = _cf(title); nd = _cf(desc)

    if _needs_title_only_match(artist_name):
        has_artist = _word_in_text(artist_name, title)    # título apenas
    else:
        has_artist = _word_in_text(artist_name, title) or _word_in_text(artist_name, desc)

    has_radio  = ("radio" in nn) or ("radio" in nd) or ("radio de " in nn) or ("radio de " in nd)
    if not has_artist:
        return False
    if not has_radio:
        return False
    return True

def find_artist_radio_playlist(
    token: Optional[str],
    artist_name: str,
    artist_id: Optional[str] = None,
    market: Optional[str] = None,   # usar "PT" para priorizar resultados PT
) -> Optional[Dict]:
    """
    Procura a melhor playlist de rádio do artista.
    Estratégia:
      1) Search API com queries PT e EN (ordem: PT→EN), com market opcional.
      2) Exact match (case-insensitive, sem acentos): 
         - "<artist> radio", "radio <artist>", "radio de <artist>"
         - owner=Spotify preferido.
      3) Senão, melhores candidatos por score (owner Spotify, ids 37i9dQZF, título a começar com o artista ou contendo 'radio de <artist>').
      4) Se houver artist_id, validação por faixas (>=40% ou ~=10/80).
    """
    artist_name = (artist_name or "").strip()
    if not token or not artist_name:
        return None

    cache_key = f"radio.v3::{_cf(artist_name)}::{artist_id or ''}::{(market or '').upper()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    exact1 = f"{_cf(artist_name)} radio"      # '<artist> radio'
    exact2 = f"radio {_cf(artist_name)}"      # 'radio <artist>'
    exact3 = f"radio de {_cf(artist_name)}"   # 'radio de <artist>' (PT)

    # PT primeiro para priorizar resultados locais; depois EN
    queries = [
        f"\"Rádio de {artist_name}\"",
        f"Rádio de {artist_name}",
        f"\"Rádio {artist_name}\"",
        f"Rádio {artist_name}",
        f"\"{artist_name} Radio\"",
        f"{artist_name} Radio",
        f"Radio {artist_name}",
    ]

    exact_candidates: List[Dict] = []
    general_candidates: List[Tuple[int, Dict]] = []

    for q in queries:
        for off in (0, 50):  # leve: duas páginas
            for pl in _search_playlists(token, q, limit=50, offset=off, market=market):
                if not isinstance(pl, dict):
                    continue
                name = (pl.get("name") or "")
                desc = (pl.get("description") or "")
                owner = pl.get("owner") or {}
                owner_is_spotify = ((owner.get("id") or "").lower() == "spotify") or (_cf(owner.get("display_name")) == "spotify")
                pid = pl.get("id") or ""
                name_cf = _cf(name)

                # filtros de título/descrição (inclui exclusão de 'mix')
                if not _validate_radio_title(artist_name, name, desc):
                    continue

                # candidato
                cand = {
                    "type": "playlist",
                    "id": pid,
                    "name": name,
                    "external_url": (pl.get("external_urls") or {}).get("spotify"),
                    "image": ((pl.get("images") or [{}])[0] or {}).get("url"),
                    "owner_is_spotify": bool(owner_is_spotify),
                    "description": desc,
                    "kind": "radio",
                }

                is_exact = (name_cf == exact1) or (name_cf == exact2) or (name_cf == exact3)
                if is_exact:
                    exact_candidates.append(cand)
                else:
                    score = 0
                    if owner_is_spotify: score += 3
                    if pid.startswith("37i9dQZF"): score += 1
                    if name_cf.startswith(_cf(artist_name)) or (f"radio de {_cf(artist_name)}" in name_cf):
                        score += 1
                    general_candidates.append((score, cand))

    # Preferir EXATO (validar por faixas se possível)
    if exact_candidates:
        exact_candidates.sort(key=lambda c: (not c.get("owner_is_spotify"), c.get("name") or ""))
        if artist_id:
            best = None; best_ratio = -1.0
            for c in exact_candidates:
                ratio = _playlist_tracks_match_ratio(token, c.get("id"), artist_id, max_items=80)
                if ratio >= 0.40 or ratio * 80 >= 10:
                    if ratio > best_ratio:
                        best, best_ratio = c, ratio
            if best:
                _cache_set(cache_key, best); return best
        _cache_set(cache_key, exact_candidates[0]); return exact_candidates[0]

    # Senão, melhor geral (validar por faixas se possível)
    if general_candidates:
        general_candidates.sort(key=lambda t: (-t[0], not t[1].get("owner_is_spotify"), t[1].get("name") or ""))
        if artist_id:
            best = None; best_ratio = -1.0
            for _, c in general_candidates[:5]:
                ratio = _playlist_tracks_match_ratio(token, c.get("id"), artist_id, max_items=80)
                if ratio >= 0.40 or ratio * 80 >= 10:
                    if ratio > best_ratio:
                        best, best_ratio = c, ratio
            if best:
                _cache_set(cache_key, best); return best
        _cache_set(cache_key, general_candidates[0][1]); return general_candidates[0][1]

    _cache_set(cache_key, None)
    return None

# ================== Exclusão de "mix/remix" (pode ficar no fim) ==================
def _has_mixish(text: str) -> bool:
    """Detecta termos tipo MIX/REMIX/MEGAMIX/DJ MIX/RADIO MIX (sem acentos, case-insensitive)."""
    if not text:
        return False
    t = _cf(text)
    # \b garante palavra isolada; aceita mega mix / dj mix / radio mix
    return re.search(r'\b(remix|mega\s*mix|dj\s*mix|radio\s*mix|mix|mixes)\b', t) is not None

# --- CANDIDATOS / PICKER MANUAL ---

def playlist_artist_ratio(token: str, playlist_id: str, artist_id: str, max_items: int = 80) -> float:
    """Wrapper público para a percentagem de faixas do artista numa playlist."""
    return _playlist_tracks_match_ratio(token, playlist_id, artist_id, max_items=max_items)

def get_thisis_candidates(token: str, artist_name: str, market: str | None = None, max_pages: int = 2) -> list[dict]:
    """
    Candidatos a 'This Is <Artist>' (mais permissivo):
    - aceita 'This Is: <Artist>' / 'This Is – <Artist>' / etc.
    - para nomes curtos/comuns, exige presença no TÍTULO (não só na descrição)
    - ordena por owner Spotify / id oficial / título a começar por 'This Is'
    """
    artist_name = (artist_name or "").strip()
    if not token or not artist_name:
        return []

    # queries razoáveis; 2 páginas para ter 100 resultados no total
    queries = [
        f"\"This Is {artist_name}\"",
        f"This Is {artist_name}",
        f"This Is: {artist_name}",
        f"This Is - {artist_name}",
    ]
    rows: list[tuple[int, dict]] = []
    pages = (0, 50) if max_pages > 1 else (0,)

    for q in queries:
        for off in pages:
            for pl in _search_playlists(token, q, limit=50, offset=off, market=market):
                if not isinstance(pl, dict):
                    continue
                name = (pl.get("name") or "")
                desc  = (pl.get("description") or "")
                if _has_mixish(name) or _has_mixish(desc):
                    continue

                owner = pl.get("owner") or {}
                owner_is_spotify = ((owner.get("id") or "").lower() == "spotify") or (_cf(owner.get("display_name")) == "spotify")
                pid = pl.get("id") or ""
                name_cf = (name or "").casefold()

                # 1) título com "this is" no início (aceitando pontuação)
                starts_like_thisis = name_cf.startswith("this is")  # "this is", "this is:", "this is –", etc.

                # 2) presença do artista
                if _needs_title_only_match(artist_name):
                    has_artist = _word_in_text(artist_name, name)  # só título
                else:
                    has_artist = _word_in_text(artist_name, name) or _word_in_text(artist_name, desc)

                if not (starts_like_thisis and has_artist):
                    continue

                cand = {
                    "id": pid,
                    "name": name,
                    "url": (pl.get("external_urls") or {}).get("spotify"),
                    "owner_is_spotify": bool(owner_is_spotify),
                    "image": ((pl.get("images") or [{}])[0] or {}).get("url"),
                }

                score = 0
                if owner_is_spotify: score += 3
                if pid.startswith("37i9dQZF"): score += 1
                if name_cf.startswith("this is"): score += 1
                if _word_in_text(artist_name, name): score += 1
                rows.append((score, cand))

    rows.sort(key=lambda t: (-t[0], t[1].get("name") or ""))
    return [c for _, c in rows]

def get_radio_candidates(token: str, artist_name: str, market: str | None = None, max_pages: int = 1) -> list[dict]:
    """Devolve candidatos a '<Artist> Radio' / 'Rádio de <Artista>' (ordenados)."""
    artist_name = (artist_name or "").strip()
    if not token or not artist_name:
        return []
    queries = [
        f"\"Rádio de {artist_name}\"", f"Rádio de {artist_name}",
        f"\"Rádio {artist_name}\"",     f"Rádio {artist_name}",
        f"\"{artist_name} Radio\"",     f"{artist_name} Radio", f"Radio {artist_name}",
    ]
    rows: list[tuple[int, dict]] = []
    pages = (0, 50) if max_pages > 1 else (0,)
    for q in queries:
        for off in pages:
            for pl in _search_playlists(token, q, limit=50, offset=off, market=market):
                if not isinstance(pl, dict):
                    continue
                name = pl.get("name") or ""
                desc  = pl.get("description") or ""
                if not _validate_radio_title(artist_name, name, desc):
                    continue
                owner = pl.get("owner") or {}
                owner_is_spotify = ((owner.get("id") or "").lower() == "spotify") or (_cf(owner.get("display_name")) == "spotify")
                pid = pl.get("id") or ""
                cand = {
                    "id": pid,
                    "name": name,
                    "url": (pl.get("external_urls") or {}).get("spotify"),
                    "owner_is_spotify": bool(owner_is_spotify),
                    "image": ((pl.get("images") or [{}])[0] or {}).get("url"),
                }
                score = 0
                if owner_is_spotify: score += 3
                if pid.startswith("37i9dQZF"): score += 1
                name_cf = _cf(name)
                if name_cf.startswith(_cf(artist_name)) or (f"radio de {_cf(artist_name)}" in name_cf):
                    score += 1
                rows.append((score, cand))
    rows.sort(key=lambda t: (-t[0], t[1].get("name") or ""))
    return [c for _, c in rows]
