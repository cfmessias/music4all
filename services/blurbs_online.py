# services/blurbs_online.py
import requests
import urllib.parse as _url

UA = {"User-Agent": "music4all/1.0 (+https://github.com/yourorg)"}

def _wiki_summary(title: str, lang: str = "pt", timeout: int = 6) -> str:
    """Wikipedia REST summary (sem HTML). Devolve '' se não existir."""
    if not title:
        return ""
    t = _url.quote(title.replace(" ", "_"))
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{t}"
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.status_code == 200:
            j = r.json()
            # 'extract' já vem limpo em texto simples
            return (j.get("extract") or "").strip()
        return ""
    except Exception:
        return ""

def get_online_summary(genre: str) -> str:
    """PT → fallback EN. Se muito curto (<240), tenta enriquecer com EN."""
    txt_pt = _wiki_summary(genre, "pt")
    if txt_pt and len(txt_pt) >= 240:
        return txt_pt
    txt_en = _wiki_summary(genre, "en")
    # prefere EN se PT vazio ou muito curto
    return txt_en or txt_pt or ""
