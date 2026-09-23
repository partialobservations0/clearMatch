"""Fetch a URL's raw HTML, tolerant of the failure modes real news sites throw at scrapers."""

from dataclasses import dataclass

import requests

DEFAULT_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FetchResult:
    url: str
    ok: bool
    status_code: int | None
    html: str | None
    error: str | None


def fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT) -> FetchResult:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.exceptions.Timeout:
        return FetchResult(url, False, None, None, f"timeout after {timeout}s")
    except requests.exceptions.SSLError as e:
        return FetchResult(url, False, None, None, f"SSL error: {e}")
    except requests.exceptions.ConnectionError as e:
        return FetchResult(url, False, None, None, f"connection error: {e}")
    except requests.exceptions.RequestException as e:
        return FetchResult(url, False, None, None, f"request failed: {e}")

    if resp.status_code >= 400:
        return FetchResult(url, False, resp.status_code, None, f"HTTP {resp.status_code}")

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return FetchResult(url, False, resp.status_code, None, f"non-HTML content-type: {content_type!r}")

    return FetchResult(url, True, resp.status_code, resp.text, None)


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    result = fetch_url(url)
    if result.ok:
        print(f"OK ({result.status_code}), {len(result.html)} chars fetched")
    else:
        print(f"FAILED: {result.error}")
