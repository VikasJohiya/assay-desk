"""Minimal HTTP helpers.

Two transports because they are not interchangeable from every host:
 - `urllib_get` — stdlib, used where it works (Yahoo chart API).
 - `curl_get`  — shells out to the system `curl`, used for hosts where urllib's
   TLS/HTTP stack stalls (observed: fred.stlouisfed.org times out under urllib
   but responds fine under curl on this machine).

Neither swallows failure: on transport error both raise, so the caller can turn
it into an explicit SourceUnavailableError (Section 6.2, fail visibly).
"""

import subprocess
import urllib.error
import urllib.request


class HttpError(Exception):
    pass


def urllib_get(url: str, timeout: int = 20, user_agent: str = "gold-engine/0.1") -> str:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpError(str(exc)) from exc


def curl_get(url: str, timeout: int = 25, user_agent: str = "gold-engine/0.1") -> str:
    try:
        proc = subprocess.run(
            # --http1.1: FRED's HTTP/2 intermittently resets the stream
            # (curl err 92). --retry: ride out transient 5xx/28 without faking data.
            ["curl", "-sS", "--fail", "--http1.1",
             "--retry", "2", "--retry-delay", "1",
             "--max-time", str(timeout),
             "-H", f"User-Agent: {user_agent}", url],
            capture_output=True, text=True, timeout=timeout * 3 + 5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise HttpError(f"curl failed: {exc}") from exc
    if proc.returncode != 0:
        raise HttpError(f"curl exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout
