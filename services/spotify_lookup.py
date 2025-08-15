# services/spotify_lookup.py
import requests
import streamlit as st
from streamlit import components
from services.spotify import get_spotify_token, fmt

# ---------------------------
# Utils
# ---------------------------
def _normalize_term(term: str) -> str:
    """Normaliza termos comuns e sinónimos (prog rock, fusion jazz, etc.)."""
    t = (term or "").strip().lower()
    if not t:
        return t
    synonyms = {
        "prog rock": "progressive rock",
        "prog-rock": "progressive rock",
        "progressive-rock": "progressive rock",
        "fusion jazz": "jazz fusion",
        "fusion-jazz": "jazz fusion",
        "garage-rock": "garage rock",
        "hard-rock": "hard rock",
        "bossa-nova": "bossa nova",
    }
    return synonyms.get(t, t)

def _ctx_terms(path_ctx: list[str]) -> list[str]:
    """Baixa e normaliza contexto; devolve até 2 ancestrais além do leaf."""
    if not path_ctx:
        return []
    normed = [_normalize_term(x) for x in path_ctx if x]
    # leaf é path_ctx[0] pelo nosso protocolo
    # devolve leaf + até 2 ancestrais
    if len(normed) == 1:
        return normed
    return [normed[0]] + normed[1:3]

# ---------------------------
# Token cache
# ---------------------------
def get_spotify_token_cached() -> str | None:
    tok = st.session_state.get("spotify_token")
    if tok:
        return tok
    client_id = st.secrets.get("client_id") or st.secrets.get("SPOTIFY_CLIENT_ID")
    client_secret = st.secrets.get("client_secret") or st.secrets.get("SPOTIFY_CLIENT_SECRET")
    if client_id and client_secret:
        tok = get_spotify_token(client_id, client_secret)
        if tok:
            st.session_state["spotify_token"] = tok
            return tok
    return None

# ---------------------------
# Low-level search helpers
# ---------------------------
def _call_search(token: str, q: str, type_: str, limit: int = 20, market: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": q, "type": type_, "limit": max(1, min(50, limit)), "offset": 0}
    if market:
        params["market"] = market
    try:
        r = requests.get("https://api.spotify.com/v1/search", headers=headers, params=params, timeout=12)
    except Exception as e:
        st.write("[spotify search error]", e)
        return {}
    if r.status_code != 200:
        try:
            st.write("[spotify search error]", r.status_code, r.json())
        except Exception:
            st.write("[spotify search error]", r.status_code, r.text)
        return {}
    return r.json() or {}

def _related_artists(token: str, artist_id: str) -> list[dict]:
    """Expansão por artistas relacionados (para enriquecer ramos com poucos resultados)."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.spotify.com/v1/artists/{artist_id}/related-artists"
    try:
        r = requests.get(url, headers=headers, timeout=12)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    j = r.json() or {}
    return j.get("artists") or []

# ---------------------------
# ARTISTS – pesquisa progressiva + expansão
# ---------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def spotify_genre_top_artists(token: str, leaf: str, path_ctx: list[str], limit: int = 10) -> list[dict]:
    """
    Pesquisa progressiva por ARTISTAS (com normalização + expansão):
      P1) (genre:"leaf" OR genre:"brazil") + contexto + NOT termos indianos + market=BR
      P2) (genre:"leaf") + contexto (sem NOT/market)
      P3) (genre:"leaf") simples
      EXP) se < limit: expandir com related-artists dos primeiros resultados
    """
    leaf = _normalize_term(leaf)
    ctx_list = _ctx_terms(path_ctx)
    if not token or not leaf:
        return []

    # contexto (até 2 ancestrais além do leaf). Por protocolo: path_ctx[0] == leaf
    # ex.: ["progressive rock", "rock", "europe"] → ['progressive rock', 'rock', 'europe'][:3]
    # Já filtrado em _ctx_terms
    ctx_clause = " ".join(f'genre:"{t}"' for t in ctx_list[1:])  # exclui leaf

    def _ok_genres(gs: list[str]) -> bool:
        if not gs:
            return False
        low = " | ".join(gs).lower()
        # ruído frequente (indian classical)
        if any(bad in low for bad in ["hindustani", "carnatic", "raga", "raag", "sitar", "gharana"]):
            return False
        # géneros-âncora para os ramos pedidos
        anchors = {
            "progressive rock": ["progressive rock", "prog"],
            "jazz fusion": ["jazz fusion", "fusion", "jazz-rock"],
            "garage rock": ["garage rock", "garage"],
            "hard rock": ["hard rock", "rock"],
        }
        anchor_terms = []
        if leaf in anchors:
            anchor_terms = anchors[leaf]
        # fallback genérico
        anchor_terms = anchor_terms or [leaf.split()[0]]
        return any(a in low for a in anchor_terms)

    def _format_items(items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            if not it:
                continue
            out.append({
                "id": it.get("id"),
                "name": it.get("name"),
                "url": (it.get("external_urls") or {}).get("spotify"),
                "followers": fmt((it.get("followers") or {}).get("total", 0)),
                "popularity": it.get("popularity", 0),
                "image": (it.get("images") or [{}])[0].get("url"),
                "type": "artist",
                "genres": it.get("genres") or [],
            })
        return out

    # Passo 1 (estrito)
    not_clause  = 'NOT hindustani NOT "indian classical" NOT carnatic NOT raga NOT ragas NOT sitar'
    base_clause = f'(genre:"{leaf}" OR genre:"brazil")'
    q1 = " ".join(x for x in [base_clause, ctx_clause, not_clause] if x.strip())
    j1 = _call_search(token, q1, "artist", limit=limit*2, market="BR")
    items1 = (j1.get("artists") or {}).get("items") or []
    items1 = [it for it in items1 if it]  # protege de None
    filtered = [it for it in items1 if _ok_genres(it.get("genres") or []) or (leaf in (it.get("name","").lower()))]

    # Passo 2 (moderado)
    if len(filtered) < limit:
        q2 = " ".join(x for x in [f'genre:"{leaf}"', ctx_clause] if x.strip())
        j2 = _call_search(token, q2, "artist", limit=limit*2)
        items2 = (j2.get("artists") or {}).get("items") or []
        items2 = [it for it in items2 if it]
        for it in items2:
            gs = it.get("genres") or []
            if (leaf in " | ".join(gs).lower()) or (leaf in (it.get("name", "").lower())):
                if it not in filtered:
                    filtered.append(it)
            if len(filtered) >= limit:
                break

    # Passo 3 (simples)
    if len(filtered) < limit:
        j3 = _call_search(token, f'genre:"{leaf}"', "artist", limit=limit*2)
        items3 = (j3.get("artists") or {}).get("items") or []
        items3 = [it for it in items3 if it]
        for it in items3:
            gs = it.get("genres") or []
            if (leaf in " | ".join(gs).lower()) or (leaf in (it.get("name", "").lower())):
                if it not in filtered:
                    filtered.append(it)
            if len(filtered) >= limit:
                break

    # EXPANSÃO com related-artists (melhora Progressive Rock / Jazz Fusion / Garage Rock)
    if filtered and len(filtered) < limit:
        try:
            seen_ids = {it.get("id") for it in filtered if it and it.get("id")}
            for seed in filtered[:3]:  # expande a partir dos 3 primeiros
                rid = seed.get("id")
                for rel in _related_artists(token, rid):
                    if not rel or rel.get("id") in seen_ids:
                        continue
                    # mantém coerência de género
                    if _ok_genres(rel.get("genres") or []):
                        filtered.append(rel)
                        seen_ids.add(rel.get("id"))
                        if len(filtered) >= limit:
                            break
                if len(filtered) >= limit:
                    break
        except Exception:
            pass

    return _format_items(filtered[:limit])

# ---------------------------
# PLAYLISTS – fallback robusto
# ---------------------------
@st.cache_data(ttl=900, show_spinner=False)
def spotify_genre_playlists(token: str, leaf: str, path_ctx: list[str], limit: int = 10) -> list[dict]:
    """
    Fallback por PLAYLISTS, cada vez mais amplo:
      P1) "<leaf> mix <anc1> <anc2>"
      P2) "<leaf> <anc1> <anc2>"
      P3) "<leaf> brazil"
      P4) "<leaf>"
    Protegido contra itens None vindos da API.
    """
    leaf = _normalize_term(leaf)
    ctx_list = _ctx_terms(path_ctx)
    if not token or not leaf:
        return []

    ctx = " ".join(ctx_list[1:]) if len(ctx_list) > 1 else ""
    queries = []
    if ctx:
        queries += [f"{leaf} mix {ctx}", f"{leaf} {ctx}"]
    queries += [f"{leaf} brazil", f"{leaf}"]

    headers = {"Authorization": f"Bearer {token}"}
    for q in queries:
        try:
            r = requests.get(
                "https://api.spotify.com/v1/search", headers=headers,
                params={"q": q, "type": "playlist", "limit": max(1, min(50, limit)), "offset": 0},
                timeout=12,
            )
        except Exception:
            continue
        if r.status_code != 200:
            continue
        j = r.json() or {}
        items = ((j.get("playlists") or {}).get("items")) or []
        if not items:
            continue

        out = []
        for it in items:
            if not it:
                continue  # <-- protege it=None (corrige o teu erro)
            images = it.get("images") or []
            image = images[0]["url"] if images else None
            out.append({
                "id": it.get("id"),
                "name": it.get("name"),
                "url": (it.get("external_urls") or {}).get("spotify"),
                "image": image,
                "owner": (it.get("owner") or {}).get("display_name") or "—",
                "type": "playlist",
            })
        if out:
            return out
    return []

# ---------------------------
# Embed
# ---------------------------
def embed_spotify(kind: str, _id: str, height: int = 80):
    if not kind or not _id:
        return
    src = f"https://open.spotify.com/embed/{kind}/{_id}"
    components.v1.iframe(src, height=height, width=380)
