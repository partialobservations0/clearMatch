"""Populate articles.full_text/published_date/fetched_at for every row in the DB using the
existing fetch/extract pipeline (src/pipeline.py). Network calls only -- no API cost.

Safe to re-run: only fetches rows where full_text IS NULL (i.e. not yet fetched), unless
--refetch is passed.
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pipeline import fetch_and_extract

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "nameRecognition.db"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refetch", action="store_true", help="re-fetch rows that already have full_text")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    if args.refetch:
        rows = conn.execute("SELECT id, url FROM articles").fetchall()
    else:
        rows = conn.execute("SELECT id, url FROM articles WHERE full_text IS NULL").fetchall()

    print(f"Fetching {len(rows)} articles...")

    ok, failed = 0, 0
    for i, (article_id, url) in enumerate(rows, 1):
        result = fetch_and_extract(url)
        now = datetime.now(timezone.utc).isoformat()

        if result.ok:
            conn.execute(
                "UPDATE articles SET full_text = ?, title = COALESCE(?, title), "
                "published_date = ?, fetched_at = ?, fetch_error = NULL WHERE id = ?",
                (result.text, result.title, result.published_date, now, article_id),
            )
            ok += 1
            print(f"[{i}/{len(rows)}] OK ({len(result.text)} chars)  {url}")
        else:
            conn.execute(
                "UPDATE articles SET fetch_error = ?, fetched_at = ? WHERE id = ?",
                (result.error, now, article_id),
            )
            failed += 1
            print(f"[{i}/{len(rows)}] FAIL  {url}\n         {result.error}")

        conn.commit()
        time.sleep(0.2)

    print()
    print(f"OK: {ok}  FAIL: {failed}")
    conn.close()


if __name__ == "__main__":
    main()
