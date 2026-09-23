"""Run fetch+extract against every unique article URL in the dataset and report success rate.

This is a smoke test for src/fetch.py and src/extract.py, not the full matching/sentiment
eval (that comes later once src/match.py exists). Writes a JSON report to results/.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pipeline import fetch_and_extract

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "dataset.json"
OUT = ROOT / "results" / "fetch_extract_smoke_test.json"


def main():
    dataset = json.loads(DATASET.read_text())
    urls = sorted({r["article_url"] for r in dataset if r.get("article_url")})

    results = []
    for i, url in enumerate(urls, 1):
        result = fetch_and_extract(url)
        if not result.ok:
            results.append({"url": url, "status": "FAIL", "detail": result.error, "attempts": result.attempts})
            print(f"[{i}/{len(urls)}] FAIL (attempt {result.attempts})  {url}")
            print(f"               {result.error}")
            time.sleep(0.3)
            continue

        results.append({
            "url": url,
            "status": "OK",
            "detail": f"{len(result.text)} chars",
            "title": result.title,
            "attempts": result.attempts,
        })
        print(f"[{i}/{len(urls)}] OK ({len(result.text)} chars, attempt {result.attempts})  {url}")

        time.sleep(0.3)  # be polite

    ok = sum(1 for r in results if r["status"] == "OK")
    fail = sum(1 for r in results if r["status"] == "FAIL")

    summary = {
        "total": len(results),
        "ok": ok,
        "fail": fail,
        "success_rate": round(ok / len(results), 3) if results else 0,
        "results": results,
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print()
    print(f"Total: {len(results)}  OK: {ok}  FAIL: {fail}")
    print(f"Success rate: {summary['success_rate']:.1%}")
    print(f"Report written to {OUT}")


if __name__ == "__main__":
    main()
