"""Read-only lookups against db/nameRecognition.db for match.py to use as grounding context
and as a cheap pre-check before spending an API call.

Two lookups:
  lookup_by_dob(dob)   -- is this exact DOB a person we already have on file? If so, return
                          their canonical name + every known alias, so match.py can recognize
                          name forms it wouldn't otherwise know about (this matters most for
                          the moderate-fame roster, where an obscure alias genuinely isn't in
                          an LLM's training data the way a celebrity nickname is).
  lookup_by_name(name) -- which known people (any DOB) does this exact name string belong to?
                          Used to surface namesake-collision warnings: if the input name is
                          already known to belong to more than one real, distinct person in
                          our records, the model should be extra careful not to assume a match
                          just because the string appears.

Matching is exact after normalization (lowercase, diacritics stripped, whitespace collapsed)
-- deliberately not fuzzy/substring, since a loose match here would risk conflating different
real people, which is exactly the failure mode this whole project is designed against.
"""

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "nameRecognition.db"


# Real bug caught in testing: "Shannon O'Donnell" (straight apostrophe, as stored) failed to
# match "Shannon O'Donnell" (curly apostrophe U+2019, as the live article's HTML actually used)
# even though the name was right there in the title. Different apostrophe/quote characters are
# common in real HTML (smart quotes from CMS software) and must be treated as equivalent.
_QUOTE_VARIANTS = str.maketrans({
    "‘": "'", "’": "'", "ʼ": "'", "´": "'", "`": "'",
    "“": '"', "”": '"',
})


def normalize(s: str) -> str:
    s = s.translate(_QUOTE_VARIANTS)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


@dataclass
class PersonRecord:
    id: int
    date_of_birth: str
    canonical_name: str
    aliases: list[str] = field(default_factory=list)

    @property
    def all_name_forms(self) -> list[str]:
        return [self.canonical_name] + self.aliases


def _connect() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _load_person(conn: sqlite3.Connection, person_id: int) -> PersonRecord:
    row = conn.execute(
        "SELECT id, date_of_birth, canonical_name FROM people WHERE id = ?", (person_id,)
    ).fetchone()
    aliases = [
        r[0] for r in conn.execute(
            "SELECT variant_name FROM name_variants WHERE person_id = ?", (person_id,)
        ).fetchall()
    ]
    return PersonRecord(id=row[0], date_of_birth=row[1], canonical_name=row[2], aliases=aliases)


def lookup_by_dob(dob: str) -> PersonRecord | None:
    conn = _connect()
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT id FROM people WHERE date_of_birth = ?", (dob,)).fetchone()
        if row is None:
            return None
        return _load_person(conn, row[0])
    finally:
        conn.close()


def lookup_by_name(name: str) -> list[PersonRecord]:
    """All known people (any DOB) whose canonical name or any alias normalizes to `name`."""
    conn = _connect()
    if conn is None:
        return []
    try:
        target = normalize(name)
        matched_ids: set[int] = set()

        for person_id, canonical in conn.execute("SELECT id, canonical_name FROM people").fetchall():
            if normalize(canonical) == target:
                matched_ids.add(person_id)

        for person_id, variant in conn.execute("SELECT person_id, variant_name FROM name_variants").fetchall():
            if normalize(variant) == target:
                matched_ids.add(person_id)

        return [_load_person(conn, pid) for pid in matched_ids]
    finally:
        conn.close()


def find_name_forms_in_text(text: str, name_forms: list[str]) -> list[str]:
    """Which of these name forms appear (normalized, substring) anywhere in the text?"""
    norm_text = normalize(text)
    return [form for form in name_forms if normalize(form) and normalize(form) in norm_text]


def _is_latin_letter(c: str) -> bool:
    try:
        return unicodedata.name(c).startswith("LATIN")
    except ValueError:
        return False


def looks_non_latin_script(text: str, sample_size: int = 1000, threshold: float = 0.5) -> bool:
    """Is this text predominantly NOT in Latin script (Chinese, Russian/Cyrillic, Arabic,
    Greek, Korean, Japanese, Devanagari, etc.)?

    All of our stored name_variants are Latin-alphabet strings (even for people whose real
    name is in another script -- we only catalog the romanized form, e.g. "Xi Jinping" not
    "习近平"). Confirmed via a real test against a live Chinese Xinhua news article: our
    pre-check found zero name-form matches in a genuine, clearly-relevant article about Xi
    Jinping, purely because the article never once uses the Latin romanization -- it's 100%
    written in Chinese characters, which is completely normal for native-language news and
    not evidence the article is unrelated. A "not found" result from find_name_forms_in_text
    on non-Latin-script text is NOT trustworthy the way it is on Latin-script text (where
    genuine absence really does mean absence), so match.py must not treat it as grounds to
    skip the API call -- doing so was blocking 100% of non-Latin-script articles from ever
    reaching real analysis, even though the model itself reasons about them just fine (a
    separate real test against Chinese Wikipedia text produced a correct, well-grounded
    verdict with correctly-parsed Chinese-format dates).
    """
    sample = text[:sample_size]
    letters = [c for c in sample if c.isalpha()]
    if len(letters) < 20:
        return False  # not enough signal either way -- don't override on a hunch
    non_latin = sum(1 for c in letters if not _is_latin_letter(c))
    return (non_latin / len(letters)) >= threshold


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 knowledge_base.py <name_or_dob>")
        sys.exit(1)

    query = sys.argv[1]
    by_dob = lookup_by_dob(query)
    if by_dob:
        print(f"Found by DOB: {by_dob.canonical_name} ({by_dob.date_of_birth})")
        print(f"  Aliases: {by_dob.aliases}")

    by_name = lookup_by_name(query)
    if by_name:
        print(f"Found {len(by_name)} people matching name '{query}':")
        for p in by_name:
            print(f"  - {p.canonical_name} ({p.date_of_birth})")

    if not by_dob and not by_name:
        print("No matches found.")
