import time
import requests
from typing import Any, Dict, Optional
from .errors import SpotifyHTTPError, SpotifyRateLimited

DEFAULT_TIMEOUT = 15
RETRY_STATUS = {429, 500, 502, 503, 504}

class SpotifyClient:
    def __init__(self, token: str, timeout: int = DEFAULT_TIMEOUT):
        self._token = token
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tries = 0
        while True:
            resp = self._session.get(url, params=params, timeout=self._timeout)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                time.sleep(min(retry_after, 5))
                tries += 1
                if tries > 5:
                    raise SpotifyRateLimited(retry_after)
                continue
            if resp.status_code >= 400:
                raise SpotifyHTTPError(resp.status_code, resp.text)
            return resp.json()
