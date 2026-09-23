"""Run src/name_variants.py's systematic generator for every person in the DB, adding any
new variant not already on file. Run this AFTER migrate_dataset_to_db.py and the hand-curated
add_aliases*.py scripts, since it mines additional surnames/given-names out of whatever
aliases already exist -- the more real aliases already on file, the more surname/nickname
combinations it can derive (e.g. it needs "Jacqueline Kennedy Onassis" already present to
discover "Kennedy" as a second real surname for Jacqueline Bouvier).
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from name_variants import generate_variants

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "nameRecognition.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    people = conn.execute("SELECT id, canonical_name FROM people").fetchall()

    added, skipped_dup = 0, 0
    for person_id, canonical_name in people:
        existing = conn.execute(
            "SELECT variant_name, variant_type FROM name_variants WHERE person_id = ?", (person_id,)
        ).fetchall()

        generated = generate_variants(canonical_name, existing)

        for variant in generated:
            try:
                conn.execute(
                    "INSERT INTO name_variants (person_id, variant_name, variant_type, note) VALUES (?, ?, ?, ?)",
                    (person_id, variant, "generated_systematic",
                     "Mechanically generated (initials/order/surname-alone/nickname substitution) "
                     "from name_variants.py -- see that module for the full generation logic."),
                )
                added += 1
            except sqlite3.IntegrityError:
                skipped_dup += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM name_variants").fetchone()[0]
    print(f"people processed: {len(people)}")
    print(f"new variants added: {added}  (duplicates skipped: {skipped_dup})")
    print(f"total name_variants now: {total}")
    conn.close()


if __name__ == "__main__":
    main()
