"""Orchestrates fetch + extract, with retries for non-deterministic failures.

Some sites (Yahoo's GDPR consent wall is the confirmed case so far) serve a boilerplate
page instead of the article on some requests and the real article on others, for the exact
same URL, with no client-side signal to predict which you'll get. A single attempt is not
reliable enough for a product with a zero-false-negative requirement -- so retry with a
fresh session specifically when the failure looks like boilerplate, since that's the one
failure mode retrying can actually fix (unlike a 403 or a genuinely paywalled article).
"""

from dataclasses import dataclass

from extract import ExtractedArticle, extract_article
from fetch import fetch_url

MAX_BOILERPLATE_RETRIES = 3


@dataclass
class PipelineResult:
    url: str
    ok: bool
    title: str | None
    text: str | None
    published_date: str | None
    error: str | None
    attempts: int


def fetch_and_extract(url: str) -> PipelineResult:
    last_article: ExtractedArticle | None = None

    for attempt in range(1, MAX_BOILERPLATE_RETRIES + 2):
        fetched = fetch_url(url)
        if not fetched.ok:
            return PipelineResult(url, False, None, None, None, fetched.error, attempt)

        article = extract_article(fetched.html, url)
        last_article = article

        if article.ok:
            return PipelineResult(url, True, article.title, article.text, article.published_date, None, attempt)

        if article.error and "boilerplate" not in article.error:
            # a real failure (paywall, JS-rendered, too short) -- retrying won't help
            return PipelineResult(url, False, article.title, article.text, article.published_date, article.error, attempt)

        # boilerplate hit -- worth retrying, the failure has been observed to be non-deterministic

    return PipelineResult(
        url, False,
        last_article.title if last_article else None,
        last_article.text if last_article else None,
        last_article.published_date if last_article else None,
        f"gave up after {MAX_BOILERPLATE_RETRIES + 1} attempts, still hitting boilerplate: {last_article.error if last_article else 'unknown'}",
        MAX_BOILERPLATE_RETRIES + 1,
    )


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    result = fetch_and_extract(url)
    if result.ok:
        print(f"OK (attempt {result.attempts}) -- {result.title}")
        print(f"{len(result.text)} chars:\n{result.text[:500]}...")
    else:
        print(f"FAILED (attempt {result.attempts}): {result.error}")
