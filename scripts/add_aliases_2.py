"""Second pass of real, well-documented aliases -- a broader review across ALL people in the
DB (not just the ones that started with zero aliases), catching well-known nicknames/titles/
branding names missed in the first pass (scripts/add_aliases.py).

Same verification caveat as before: well-established public facts from general knowledge, not
independently re-verified via live web search this session.
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "nameRecognition.db"

ALIASES = [
    ("1942-06-07", [  # Muammar Gaddafi
        ("Muammar Gadhafi", "alt_transliteration", "common AP-style alternate spelling"),
    ]),
    ("1957-03-10", [  # Osama bin Laden
        ("OBL", "initials_acronym", "informal acronym used in security/intelligence and press contexts"),
    ]),
    ("1963-02-17", [  # Michael Jordan, basketball player
        ("Jumpman", "brand_nickname", "nickname tied to his iconic Nike logo/brand"),
    ]),
    ("1981-09-04", [  # Beyonce
        ("Queen Bey", "nickname", "widely used fan/press nickname"),
        ("Bey", "nickname_short", "shorter form of the same nickname"),
    ]),
    ("1953-06-15", [  # Xi Jinping
        ("Uncle Xi", "nickname", "English gloss of the Chinese nickname 'Xi Dada', used in state media/propaganda"),
        ("Xi Dada", "nickname_native", "Chinese original meaning 'Uncle Xi'"),
    ]),
    ("1958-06-07", [  # Prince
        ("The Purple One", "nickname", "well-documented nickname tied to his Purple Rain branding"),
    ]),
    ("1954-07-17", [  # Angela Merkel
        ("Mutti", "nickname", "widely used German nickname meaning 'mommy'"),
    ]),
    ("1984-12-30", [  # LeBron James
        ("The King", "nickname", "shorter common form of 'King James'"),
    ]),
    ("1989-12-13", [  # Taylor Swift
        ("Tay Tay", "nickname_informal", "common fan/press nickname"),
        ("T-Swift", "nickname_informal", "common fan/press nickname"),
    ]),
    ("1950-09-17", [  # Narendra Modi
        ("NaMo", "nickname_brand", "widely used in Indian media and his own campaign branding"),
    ]),
    ("1984-01-08", [  # Kim Jong Un
        ("Supreme Leader", "title_informal", "his official title, commonly used as a name-substitute in press"),
    ]),
    ("1947-10-26", [  # Hillary Rodham Clinton
        ("HRC", "initials_acronym", "widely used initialism, especially 2016 campaign branding"),
    ]),
    ("1924-06-12", [  # George H.W. Bush
        ("Bush 41", "numeric_nickname", "political-press shorthand distinguishing him from his son 'Bush 43'"),
    ]),
    ("1929-01-15", [  # Martin Luther King Jr.
        ("Dr. King", "formal_informal", "extremely common respectful reference"),
    ]),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    dob_to_id = {r[0]: r[1] for r in conn.execute("SELECT date_of_birth, id FROM people").fetchall()}

    added, skipped_dup, skipped_missing = 0, 0, 0
    for dob, aliases in ALIASES:
        person_id = dob_to_id.get(dob)
        if person_id is None:
            print(f"WARNING: no person with DOB {dob} found, skipping {len(aliases)} aliases")
            skipped_missing += len(aliases)
            continue
        for alias, alias_type, note in aliases:
            try:
                conn.execute(
                    "INSERT INTO name_variants (person_id, variant_name, variant_type, note) VALUES (?, ?, ?, ?)",
                    (person_id, alias, alias_type, note),
                )
                added += 1
            except sqlite3.IntegrityError:
                skipped_dup += 1

    conn.commit()
    print(f"added: {added}  duplicates skipped: {skipped_dup}  missing person skipped: {skipped_missing}")
    conn.close()


if __name__ == "__main__":
    main()
