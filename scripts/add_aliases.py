"""Add additional real, well-documented aliases to name_variants, keyed by date_of_birth.

Priority: the people who came out of the dataset with only their bare input name and zero
aliases -- mostly the "trap"/decoy identities (Michael Jordan the athlete, RFK Sr., George
Foreman Sr., Bill Gates Sr., the footballer David Cameron) that the original name-form
augmentation pass didn't cover, since that pass only ran against the 47 primary "match" people.
Plus a handful of well-known aliases spot-checked as missing elsewhere.

Same verification caveat as the original augmentation pass (see data/DATASET.md): these are
well-established public facts from general knowledge, not independently re-verified via live
web search this session. Mechanical forms (initials, inverted order) need no such caveat.
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "nameRecognition.db"

# (date_of_birth, [(alias, alias_type, note), ...])
ALIASES = [
    ("1963-02-17", [  # Michael Jordan, basketball player
        ("MJ", "nickname_acronym", "universal press initialism"),
        ("Air Jordan", "nickname", "iconic nickname, also his signature shoe brand"),
        ("His Airness", "nickname", "well-documented press nickname"),
        ("M. Jordan", "initials", "single initial"),
        ("Jordan, Michael", "inverted", "surname-first"),
    ]),
    ("1925-11-20", [  # Robert F. Kennedy Sr.
        ("RFK", "initials_acronym", "universal press initialism"),
        ("Bobby Kennedy", "nickname", "his common everyday name, used by family/press/historically"),
        ("Bobby", "nickname_informal", "informal first-name-only form"),
        ("R. F. Kennedy", "initials", "all-initials form"),
        ("Kennedy, Robert F.", "inverted", "surname-first"),
    ]),
    ("1949-01-10", [  # George Foreman Sr.
        ("Big George", "nickname", "well-documented nickname, also his 2023 biopic title 'Big George Foreman'"),
        ("Big George Foreman", "nickname", "fuller form of the same nickname"),
        ("G. Foreman", "initials", "single initial"),
        ("Foreman, George", "inverted", "surname-first"),
    ]),
    ("1983-01-23", [  # George Foreman III
        ("Monk", "nickname", "his real nickname among the 5 identically-named Foreman sons, per real press coverage"),
        ("George Foreman III", "full_with_suffix", "full form with generational suffix"),
        ("G. Foreman III", "initials", "single initial with suffix"),
        ("Foreman, George III", "inverted", "surname-first with suffix"),
    ]),
    ("1925-11-30", [  # Bill Gates Sr.
        ("William H. Gates Sr.", "full_legal_name", "formal form with middle initial and suffix"),
        ("Bill Gates Sr.", "nickname_with_suffix", "common short form with disambiguating suffix"),
        ("W. H. Gates Sr.", "initials", "all-initials form with suffix"),
        ("Gates, William Sr.", "inverted", "surname-first"),
    ]),
    ("1964-04-04", [  # David Cameron, Australian rules footballer
        ("D. Cameron", "initials", "single initial"),
        ("Cameron, David", "inverted", "surname-first"),
    ]),
    ("1933-05-03", [  # James Brown, CBS sportscaster (not the singer)
        ("J. Brown", "initials", "single initial"),
        ("Brown, James", "inverted", "surname-first"),
    ]),
    # A few well-known aliases spot-checked as missing from already-covered people:
    ("1977-12-21", [  # Emmanuel Macron
        ("Manu Macron", "nickname_informal", "colloquial diminutive used in French media/social discourse"),
    ]),
    ("1971-06-28", [  # Elon Musk
        ("Technoking", "self_appointed_title", "his real, briefly self-appointed Tesla title (2021), documented in SEC filings"),
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
