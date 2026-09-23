"""Extract clean article title/text/date from raw HTML, stripping nav/ads/boilerplate."""

from dataclasses import dataclass

import trafilatura
from bs4 import BeautifulSoup


@dataclass
class ExtractedArticle:
    url: str
    ok: bool
    title: str | None
    text: str | None
    published_date: str | None
    error: str | None


# Phrases/titles that indicate we captured a consent wall, paywall, or bot-check page
# instead of the article -- these can be long enough to pass a naive length check while
# being completely unrelated to the actual article content. Matching one of these MUST
# fail extraction rather than silently hand garbage to the matcher: a matcher reasoning
# over "reject all cookies" text has no real signal and will likely produce a false
# no_match, which is the one error this product is not allowed to make.
_BOILERPLATE_TITLE_MARKERS = {"guce", "just a moment...", "attention required", "access denied"}
_BOILERPLATE_TEXT_MARKERS = [
    "cookie policy",
    "manage privacy settings",
    "reject all",
    "enable javascript",
    "please enable cookies",
    "subscribe to continue reading",
    "sign in to continue reading",
    "verify you are a human",
    "checking your browser",
    "captcha",
    "you have been blocked",
]


def _looks_like_boilerplate(title: str | None, text: str | None) -> str | None:
    """Return a reason string if this looks like a consent/paywall/bot-check page, else None."""
    if title and title.strip().lower() in _BOILERPLATE_TITLE_MARKERS:
        return f"title matches known boilerplate page ({title!r})"
    if text:
        lowered = text.lower()
        hits = [m for m in _BOILERPLATE_TEXT_MARKERS if m in lowered]
        # a short extraction dominated by boilerplate phrases is almost certainly a wall,
        # not an article that happens to mention cookies in passing
        if hits and len(text) < 1500:
            return f"short extraction matches boilerplate phrase(s): {hits}"
    return None


def _fallback_extract(html: str, url: str) -> tuple[str | None, str | None]:
    """Crude fallback when trafilatura finds nothing: title tag + largest <p> cluster."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    text = "\n\n".join(paragraphs) if paragraphs else None
    return title, text


def extract_article(html: str, url: str) -> ExtractedArticle:
    if not html:
        return ExtractedArticle(url, False, None, None, None, "no HTML provided")

    metadata = trafilatura.extract_metadata(html, default_url=url)
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )

    title = metadata.title if metadata else None
    published_date = metadata.date if metadata else None

    if not text:
        fallback_title, fallback_text = _fallback_extract(html, url)
        title = title or fallback_title
        text = fallback_text

    if not text or len(text.strip()) < 100:
        return ExtractedArticle(
            url, False, title, text, published_date,
            f"extracted text too short ({len(text or '')} chars) -- likely paywalled, JS-rendered, or blocked"
        )

    boilerplate_reason = _looks_like_boilerplate(title, text)
    if boilerplate_reason:
        return ExtractedArticle(url, False, title, text.strip(), published_date, f"boilerplate/consent page, not article: {boilerplate_reason}")

    return ExtractedArticle(url, True, title, text.strip(), published_date, None)


if __name__ == "__main__":
    import sys

    from fetch import fetch_url

    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    fetched = fetch_url(url)
    if not fetched.ok:
        print(f"FETCH FAILED: {fetched.error}")
        sys.exit(1)

    article = extract_article(fetched.html, url)
    if article.ok:
        print(f"Title: {article.title}")
        print(f"Date: {article.published_date}")
        print(f"Text ({len(article.text)} chars):\n{article.text[:500]}...")
    else:
        print(f"EXTRACT FAILED: {article.error}")
