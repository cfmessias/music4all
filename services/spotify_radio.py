# services/spotify_radio.py
# Resolve playlists "This Is <Artist>" e "<Artist> Radio" com validação forte.
# Regras principais:
#   - Preferência por títulos EXATOS (case-insensitive, mas distinguindo acentos).
#   - Verificação por faixas: uma % mínima das tracks tem de ser do artist_id (se fornecido).
#   - Filtros anti-falsos positivos (evitar playlists de rádios comerciais / genéricas).
#   - Nunca devolvemos links de estação (.../artist/<id>/radio): se não houver playlist válida → None.

from __future__ import annotations
from typing import Optional, Dict, List, Tuple
import unicodedata
import re
import time
import requests

# ================== Cache simples (só acertos) ==================
_cache: Dict[str, Tuple[float, dict]] = {}
_CACHE_TTL = 6 * 3600  # 6 horas

def _cache_get(key: str) -> Optional[dict]:
    ts, val = _cache.get(key, (0.0, None))
    if val is not None and (time.time() - ts) < _CACHE_TTL:
        return val
    return None

def _cache_set(key: str, val: dict):
    _cache[key] = (time.time(), val)
    if len(_cache) > 512:
        _cache.clear()

# ================== Utils ==================
def _norm(s: str) -> str:
    """Normaliza e REMOVE acentos (útil p/ matching por palavras)."""
    if s is None:
        return ""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")

def _cf(s: str) -> str:
    # casefold sobre a versão sem acentos
    return _norm(s).casefold()

def _word_in_text(word: str, text: str) -> bool:
    """Match por palavra inteira (casefold + sem acentos)."""
    if not word or not text:
        return False
    w = re.escape(_cf(word))
    return re.search(rf"\b{w}\b", _cf(text)) is not None

def _auth_headers(token: Optional[str]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}

def _search_playlists(token: str, q: str, limit: int = 50, offset: int = 0) -> List[Dict]:
    if not token:
        return []
    try:
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers=_auth_headers(token),
            params={"q": q, "type": "playlist", "limit": limit, "offset": offset},
            timeout=8,
        )
        if r.status_code != 200:
            return []
        return ((r.json().get("playlists") or {}).get("items") or [])
    except Exception:
        return []

def _playlist_tracks_match_ratio(token: str, playlist_id: str, artist_id: str, max_items: int = 80) -> float:
    """
    Lê até max_items faixas e calcula a proporção de faixas que incluem o artist_id.
    Usado para validar que a playlist é mesmo do artista (>=40% OU >=10 faixas).
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
            r = requests.get(url, headers=headers, params=params, timeout=10)
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
            params = None
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
        # rejeita playlists de estações/rádios genéricas que não referem o artista como palavra
        if not _word_in_text(artist_name, nn) and not _word_in_text(artist_name, nd):
            return True
    return False

# ================== THIS IS ==================
def find_artist_this_is_playlist(
    token: Optional[str],
    artist_name: str,
    artist_id: Optional[str] = None,
    market: Optional[str] = None,   # compat
) -> Optional[Dict]:
    """
    Procura a melhor playlist 'This Is <Artist>'.
    Prioridade:
      A) Título EXATO "This Is <Artist>" (case-insensitive; distingue acentos).
      B) Senão, melhor candidato que comece por "This Is " e mencione o artista (palavra).
    Se 'artist_id' for dado, valida candidatos por faixas (>= 40% ou >= 10).
    """
    artist_name = (artist_name or "").strip()
    if not token or not artist_name:
        return None

    cache_key = f"thisis.v2::{_cf(artist_name)}::{artist_id or ''}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    exact_title_cf = f"this is {artist_name}".casefold()  # sensível a acento
    queries = [f"\"This Is {artist_name}\"", f"This Is {artist_name}"]

    exact_candidates: List[Dict] = []
    general_candidates: List[Tuple[int, Dict]] = []

    for q in queries:
        for off in (0, 50):
            for pl in _search_playlists(token, q, limit=50, offset=off):
                if not isinstance(pl, dict):
                    continue
                name = (pl.get("name") or "")
                desc = (pl.get("description") or "")
                owner = pl.get("owner") or {}
                owner_is_spotify = ((owner.get("id") or "").lower() == "spotify") or (_cf(owner.get("display_name")) == "spotify")

                name_cf = name.casefold()
                is_exact = (name_cf == exact_title_cf)  # "Génesis" ≠ "Genesis" (bom)
                starts_with_thisis = name_cf.startswith("this is ")
                has_artist = _word_in_text(artist_name, name) or _word_in_text(artist_name, desc)

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

    # Preferir exato (validar por faixas se possível)
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

# ================== RADIO ==================
def _validate_radio_title(artist_name: str, title: str, desc: str) -> bool:
    """Tem de mencionar o artista (palavra) e referir 'radio/rádio' no título ou descrição."""
    if _looks_like_unrelated(artist_name, title, desc):
        return False
    nn = _cf(title); nd = _cf(desc)
    has_artist = _word_in_text(artist_name, title) or _word_in_text(artist_name, desc)
    has_radio = ("radio" in nn) or ("rádio" in nn) or ("radio" in nd) or ("rádio" in nd)
    if not has_artist:
        return False
    if not has_radio:
        return False
    return True

def find_artist_radio_playlist(
    token: Optional[str],
    artist_name: str,
    artist_id: Optional[str] = None,
    market: Optional[str] = None,   # compat
) -> Optional[Dict]:
    """
    Procura a melhor playlist '<Artist> Radio'.
    Estratégia:
      1) Search API apenas para 'radio' (rápido, poucos offsets), filtrando por título/descrição.
         Preferência por:
           - título EXATO: '<artist> radio' ou 'radio <artist>' (sem acentos, case-insensitive)
           - owner=Spotify
           - ids que parecem oficiais (37i9dQZF…)
      2) Verificação por faixas (se houver artist_id): >= 40% ou >=10 faixas do artista.
      3) Nunca devolve station link; se não houver playlist válida, retorna None.
    """
    artist_name = (artist_name or "").strip()
    if not token or not artist_name:
        return None

    cache_key = f"radio.v2::{_cf(artist_name)}::{artist_id or ''}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    exact1 = f"{_cf(artist_name)} radio"      # '<artist> radio'
    exact2 = f"radio {_cf(artist_name)}"      # 'radio <artist>'

    queries = [
        f"\"{artist_name} Radio\"",
        f"{artist_name} Radio",
        f"Radio {artist_name}",
        f"Rádio {artist_name}",
        f"Rádio de {artist_name}",
    ]

    exact_candidates: List[Dict] = []
    general_candidates: List[Tuple[int, Dict]] = []

    for q in queries:
        for off in (0, 50):  # manter leve
            for pl in _search_playlists(token, q, limit=50, offset=off):
                if not isinstance(pl, dict):
                    continue
                name = (pl.get("name") or "")
                desc = (pl.get("description") or "")
                owner = pl.get("owner") or {}
                owner_is_spotify = ((owner.get("id") or "").lower() == "spotify") or (_cf(owner.get("display_name")) == "spotify")
                pid = pl.get("id") or ""
                name_cf = _cf(name)

                # filtros de título/descrição
                if not _validate_radio_title(artist_name, name, desc):
                    continue

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

                is_exact = (name_cf == exact1) or (name_cf == exact2)
                if is_exact:
                    exact_candidates.append(cand)
                else:
                    score = 0
                    if owner_is_spotify: score += 3
                    if pid.startswith("37i9dQZF"): score += 1
                    # leve estímulo a títulos que começam pelo artista
                    if name_cf.startswith(_cf(artist_name)): score += 1
                    general_candidates.append((score, cand))

    # Preferir EXATO (validar por faixas se possível)
    if exact_candidates:
        # Spotify primeiro
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

# ===== Compat se algo ainda chamar nome antigo (delegamos p/ THIS IS) =====
def find_artist_radio_playlist_legacy(token, artist_name, artist_id=None, market=None, **_):
    # Se houver código antigo que importava a versão legacy, pode chamar isto.
    return find_artist_radio_playlist(token, artist_name, artist_id=artist_id, market=market)

def clear_spotify_radio_cache():
    """Limpa o cache interno deste módulo (útil após alterações)."""
    _cache.clear()
