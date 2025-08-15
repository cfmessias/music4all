# Spotify Artist Search — Streamlit

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud
- Main file: `app.py`
- Add secrets in *Settings → Secrets*:
```toml
SPOTIFY_CLIENT_ID = "…"
SPOTIFY_CLIENT_SECRET = "…"
DISCOGS_USER_AGENT = "RepositórioRock/1.0 +https://cfmessias.pt"
DISCOGS_TOKEN = "…"
```
# music4all
# music4all
