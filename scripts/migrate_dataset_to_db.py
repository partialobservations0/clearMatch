"""Migrate data/dataset.json into db/nameRecognition.db (people, name_variants, articles,
test_cases). Pure data restructuring -- no network calls, no API cost.

Two-pass approach for `people`:
  Pass 1: insert one row per unique date_of_birth from every NON-variant row (i.e. every row
          that represents a directly-sourced real identity, including the deliberate
          false-positive-trap rows -- a trap row's DOB belongs to a real, separately-verified
          person too, e.g. the David Cameron footballer, not a fabricated one).
  Pass 2: for every row (variants included), attach its input_name as a name_variant on the
          person matching its DOB, and record the row itself as a test_case.

Re-running this script is safe: it wipes and rebuilds the DB from dataset.json each time,
since dataset.json is the source of truth for this data, not the DB.
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "dataset.json"
SCHEMA = ROOT / "db" / "schema.sql"
DB_PATH = ROOT / "db" / "nameRecognition.db"


def main():
    dataset = json.loads(DATASET.read_text())

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA.read_text())
    conn.execute("PRAGMA foreign_keys = ON")

    # --- Pass 1: people, one row per unique DOB, from non-variant (anchor) rows ---
    seen_dobs = set()
    people_inserted = 0
    for row in dataset:
        if row["category"] == "22_name_form_variant":
            continue
        dob = row["input_dob"]
        if dob in seen_dobs:
            continue
        seen_dobs.add(dob)
        conn.execute(
            "INSERT INTO people (date_of_birth, canonical_name, source, source_notes) VALUES (?, ?, ?, ?)",
            (dob, row["input_name"], row.get("source"), row.get("source_notes")),
        )
        people_inserted += 1

    # Any DOB that only ever appears on a variant row (shouldn't happen given how the dataset
    # was built, but don't silently drop data if it does) -- insert those too.
    for row in dataset:
        dob = row["input_dob"]
        if dob not in seen_dobs:
            seen_dobs.add(dob)
            conn.execute(
                "INSERT INTO people (date_of_birth, canonical_name, source, source_notes) VALUES (?, ?, ?, ?)",
                (dob, row["input_name"], row.get("source"), row.get("source_notes")),
            )
            people_inserted += 1

    conn.commit()
    dob_to_person_id = {
        r[0]: r[1] for r in conn.execute("SELECT date_of_birth, id FROM people").fetchall()
    }

    # --- articles: one row per unique URL ---
    seen_urls = {}
    for row in dataset:
        url = row["article_url"]
        if url not in seen_urls:
            cur = conn.execute(
                "INSERT INTO articles (url, title) VALUES (?, ?)",
                (url, row.get("article_title")),
            )
            seen_urls[url] = cur.lastrowid
    conn.commit()

    # --- Pass 2: name_variants + test_cases for every row ---
    variants_inserted = 0
    test_cases_inserted = 0
    for row in dataset:
        person_id = dob_to_person_id[row["input_dob"]]
        article_id = seen_urls[row["article_url"]]

        try:
            conn.execute(
                "INSERT INTO name_variants (person_id, variant_name, variant_type, note) VALUES (?, ?, ?, ?)",
                (person_id, row["input_name"], row.get("variant_type", "original"), row.get("why_its_tricky")),
            )
            variants_inserted += 1
        except sqlite3.IntegrityError:
            pass  # duplicate (person_id, variant_name) -- fine, already recorded

        conn.execute(
            """INSERT INTO test_cases
               (id, person_id, article_id, input_name, category, ground_truth_match,
                ground_truth_sentiment, why_its_tricky, variant_of, variant_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id"], person_id, article_id, row["input_name"], row["category"],
                row["ground_truth_match"], row.get("ground_truth_sentiment"),
                row.get("why_its_tricky"), row.get("variant_of"), row.get("variant_type"),
            ),
        )
        test_cases_inserted += 1

    conn.commit()

    n_people = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    n_variants = conn.execute("SELECT COUNT(*) FROM name_variants").fetchone()[0]
    n_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    n_test_cases = conn.execute("SELECT COUNT(*) FROM test_cases").fetchone()[0]

    print(f"people:      {n_people}")
    print(f"name_variants: {n_variants}")
    print(f"articles:    {n_articles}")
    print(f"test_cases:  {n_test_cases}")
    print(f"DB written to {DB_PATH}")

    conn.close()


if __name__ == "__main__":
    main()
