"""HTTP utility — GET/POST with retry and connection-reset handling, stdlib only.

Proxy support: set HTTPS_PROXY=http://host:port in .env (or system env).
urllib respects this automatically via ProxyHandler installed at module load.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"
_ACCEPT = "application/json, */*"
_TIMEOUT = 20
_RETRIES = 3


def _install_proxy() -> None:
    """Install system proxy from HTTPS_PROXY env var if set."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        handler = urllib.request.ProxyHandler({"https": proxy, "http": proxy})
        urllib.request.install_opener(urllib.request.build_opener(handler))


_install_proxy()


def get(url: str, timeout: int = _TIMEOUT, retries: int = _RETRIES) -> Any:
    """GET url, return parsed JSON. Retries on connection resets and timeouts."""
    last_exc: Exception = RuntimeError("no attempts")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": _UA, "Accept": _ACCEPT, "Accept-Language": "en-US,en;q=0.9"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (ConnectionResetError, ConnectionAbortedError, OSError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))  # 3s, 6s, 9s
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                last_exc = exc
            else:
                raise
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2)
    raise ConnectionError(f"GET {url} failed after {retries} attempts: {last_exc}") from last_exc


def post_json(url: str, payload: dict, timeout: int = 10) -> Any | None:
    """POST JSON payload, return parsed response or None on error."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"User-Agent": _UA, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
