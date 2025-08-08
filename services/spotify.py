# services/spotify.py
import os
import requests
import base64
import pandas as pd

def get_spotify_token(client_id: str, client_secret: str) -> str | None:
    if not client_id or not client_secret:
        return None
    auth = f"{client_id}:{client_secret}".encode("utf-8")
    b64 = base64.b64encode(auth).decode("utf-8")
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {b64}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json().get("access_token")
    return None

def get_auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

def search_artists(token: str, q: str, limit: int = 20, offset: int = 0) -> dict:
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        headers=get_auth_header(token),
        params={"q": q, "type": "artist", "limit": limit, "offset": offset},
        timeout=15,
    )
    return resp.json().get("artists", {}) if resp.status_code == 200 else {}

def fetch_available_genres(token: str, client_id: str | None = None, client_secret: str | None = None) -> list[str]:
    def _call(tok: str):
        r = requests.get(
            "https://api.spotify.com/v1/recommendations/available-genre-seeds",
            headers=get_auth_header(tok),
            timeout=10,
        )
        return r

    r = _call(token)
    if r.status_code == 401 and client_id and client_secret:
        fresh = get_spotify_token(client_id, client_secret)
        if fresh:
            r = _call(fresh)
    if r.status_code == 200:
        return sorted(set(r.json().get("genres", [])))
    try:
        msg = r.json()
    except Exception:
        msg = r.text
    print("[genre-seeds] HTTP", r.status_code, msg)
    return []

def save_genres_csv(genres: list[str], path: str = "spotify_genres.csv") -> None:
    pd.DataFrame({"genre": genres}).to_csv(path, index=False, sep=';')

def load_genres_csv() -> list[str]:
    if os.path.exists("spotify_genres.csv"):
        df = pd.read_csv("spotify_genres.csv", sep=';')
        col = None
        for c in df.columns:
            if c.lower() == 'genre':
                col = c
                break
        if col:
            return sorted(pd.Series(df[col]).dropna().astype(str).unique().tolist())
    if os.path.exists("generos.csv"):
        df = pd.read_csv("generos.csv", sep=';')
        key = None
        for c in df.columns:
            if c.strip().lower() in ("genero", "género", "genre"):
                key = c
                break
        if key:
            return sorted(pd.Series(df[key]).dropna().astype(str).unique().tolist())
    return []

def fetch_all_albums(token: str, artist_id: str) -> list[dict]:
    out: dict[str, dict] = {}
    url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"
    params = {"limit": 50, "include_groups": "album,single,compilation"}
    headers = get_auth_header(token)
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code != 200:
            break
        j = r.json()
        for it in j.get("items", []):
            out[it["id"]] = it
        url = j.get("next")
        params = None
    return list(out.values())

def fmt(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)
