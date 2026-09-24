"""Systematically GENERATE name-form variants for a person, rather than hand-curating them.

Replaces the earlier approach (scripts/add_aliases.py, add_aliases_2.py: an LLM manually
picking aliases it happened to think of) with a deterministic generator, because manual
curation is fundamentally incomplete -- a full eval run surfaced 10 real false negatives
where the article used a name form nobody thought to add by hand: surname-only references
("PM Modi", "Bridle", "Dillard"), an abbreviated middle initial ("William H. Gates III"
instead of "Henry"), and a maiden+married surname combination ("Jacqueline Bouvier Kennedy").

Generates, from a person's canonical name plus every name form already on file for them
(mining additional known surnames/given names out of existing aliases, e.g. picking up both
"Bouvier" and "Kennedy" as surnames for Jacqueline from her existing maiden/married aliases):
  - mechanical forms: first/middle/last permutations, initials, inverted order, with/without
    suffix
  - first name ALONE, middle name ALONE, surname ALONE (the specific gap that caused the
    false negatives above)
  - real nickname substitutions for the given name, via a real public dataset
    (data/reference/nicknames.csv, github.com/carltonnorthern/nicknames) rather than guessing

This does not replace scripts/add_aliases.py's real documented aliases (nicknames like "Mutti"
or "NaMo" aren't derivable from name components alone) -- it's a supplementary, systematic
pass that runs for every person in the database, closing gaps the manual pass inevitably left.
"""

import csv
import re
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"
NICKNAMES_CSV = REFERENCE_DIR / "nicknames.csv"

SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
# Titles/honorifics that sometimes lead a canonical name (e.g. "Pope Francis", "King Charles
# III") -- excluded from being treated as a "first name" for nickname lookup or as a
# standalone surname-alone variant (they're not distinguishing on their own).
LEADING_TITLES = {"pope", "king", "queen", "prince", "president", "judge", "senator",
                   "governor", "mayor", "justice", "dr", "dr.", "mr", "mr.", "mrs", "ms"}

# An alias's `variant_type` decides whether it's safe to DECOMPOSE into given/surname parts
# for cross-multiplication, or whether it must be treated as an opaque whole string. This
# distinction is the fix for a real bug: J.K. Rowling's alias "Robert Galbraith" (type
# pseudonym_as_input) is a WHOLLY SEPARATE IDENTITY, not "this person's given name + surname"
# -- decomposing it mined "Robert" as if it were one of her real given names, then ran real
# nickname substitution on it (Bob/Bobby/Rupert/Dobbin/...) cross-multiplied against her real
# surnames, producing garbage ("Rupert Kathleen", "Dobbin Rowling"). By contrast, an alias like
# "Truss, Mary Elizabeth" (type inverted) genuinely IS the same person's real name structure
# just reordered -- decomposing THAT is not only safe, it's necessary: it's the only place
# "Elizabeth" (the middle name she actually goes by) exists in machine-readable form, since her
# canonical_name is stored as the shorter "Liz Truss" with no middle name at all.
#
# This is an ALLOWLIST, not a denylist, deliberately -- a real second bug (found via the same
# investigation) showed why. Prince's alias "The Artist Formerly Known As Prince" was typed
# "historical_alt_name", which a denylist of opaque-marker substrings didn't catch, so it was
# decomposed as if "Artist"/"Formerly"/"Known" were given/surname parts -- fabricating dozens of
# nonsense two-word "names" like "Formerly Nelson" and "Artist Prince", common enough English
# words to inflate false-positive risk on the pre-check. An allowlist fails SAFE: any type not
# explicitly known to represent "this person's real name, just reordered/abbreviated/
# transliterated" is treated as opaque by default, at worst costing some missed coverage --
# never fabricated ones. Extend this set deliberately when a genuinely new structural alias
# type is introduced; do not widen it with a substring/pattern match.
_STRUCTURAL_TYPES = {
    "original", "inverted", "inverted_labeled",
    "real_birth_name", "historical_birth_name", "commonly_assumed_full_name",
    "full_formal_name", "full_legal_name", "full_middle_initial", "full_middle_initials",
    "full_patronymic_name", "full_with_suffix",
    "maiden_name", "married_name", "married_name_only",
    "combined_maiden_married", "combined_married_names",
    "alt_romanization", "alt_transliteration", "historical_alt_romanization",
    "alt_surname_form", "surname_form",
    "diacritic_added", "diacritic_dropped",
    "hyphenated_form", "no_hyphen",
    "incorrectly_reordered", "native_name_order", "western_name_order",
    "initials", "spaced_initials", "middle_initial", "middle_initials",
    "given_name_dropped", "no_middle_name", "middle_name_as_public_name",
    "particle_dropped", "capitalization_variant", "no_nickname",
    "suffix_disambiguator", "legal_first_name_only",
}


def _is_structural_alias(variant_type: str | None) -> bool:
    if not variant_type:
        return True  # untyped/plain aliases (e.g. from dataset.json rows) are assumed structural
    return variant_type.lower() in _STRUCTURAL_TYPES


def _load_nickname_map() -> dict[str, set[str]]:
    """Bidirectional closure: name -> every other name connected to it by a has_nickname edge."""
    if not NICKNAMES_CSV.exists():
        return {}
    edges: dict[str, set[str]] = {}
    with open(NICKNAMES_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a, b = row["name1"].strip().lower(), row["name2"].strip().lower()
            edges.setdefault(a, set()).add(b)
            edges.setdefault(b, set()).add(a)
    return edges


_NICKNAME_MAP = _load_nickname_map()


def nicknames_for(given_name: str) -> set[str]:
    return _NICKNAME_MAP.get(given_name.strip().lower(), set())


def _split_name(full_name: str) -> tuple[list[str], list[str], list[str]]:
    """Returns (leading_titles, name_tokens, trailing_suffixes)."""
    tokens = full_name.replace(",", " ").split()
    leading = []
    while tokens and tokens[0].lower().rstrip(".") in LEADING_TITLES:
        leading.append(tokens.pop(0))
    trailing = []
    while tokens and tokens[-1].lower().rstrip(".") in SUFFIXES:
        trailing.insert(0, tokens.pop())
    return leading, tokens, trailing


def _initial(token: str) -> str:
    return f"{token[0]}." if token else ""


def generate_variants(
    canonical_name: str,
    existing_aliases: list[str] | list[tuple[str, str | None]] | None = None,
) -> set[str]:
    """All systematically-derivable name forms for this person.

    `existing_aliases` lets the generator mine additional known surnames/given-name spellings
    out of hand-curated data already on file (e.g. both "Bouvier" and "Kennedy" as surnames
    for someone with both a maiden-name and married-name alias already recorded), rather than
    only ever parsing the single canonical_name string. Each entry may be a plain string
    (treated as structurally minable, e.g. a raw name from dataset.json) or a
    `(variant_name, variant_type)` tuple -- pass tuples whenever you have the type on hand
    (the DB always does) so opaque identities (pseudonyms, nicknames, titles) are correctly
    excluded from decomposition. See `_is_structural_alias` for why this distinction matters.
    """
    existing_aliases = existing_aliases or []
    typed_aliases = [(a, None) if isinstance(a, str) else a for a in existing_aliases]
    variants: set[str] = set()

    leading, tokens, suffixes = _split_name(canonical_name)
    if not tokens:
        return variants

    first, middles, last = tokens[0], tokens[1:-1], tokens[-1]
    suffix_str = " ".join(suffixes)

    # Every middle name is ALSO a given-name candidate, not just the first token -- someone
    # can legally/publicly go by a middle name instead of their first (Liz Truss's actual
    # legal first name is "Mary"; she's known by her middle name "Elizabeth"). A middle name
    # parsed from the person's OWN canonical name always genuinely belongs to them.
    surname_candidates = {last}
    given_candidates = {first} | {m for m in middles if len(m) > 3}
    # Subset of given_candidates trusted enough for NICKNAME substitution specifically.
    # Nickname expansion compounds one guess (this string IS a given name this person uses)
    # into many more (and THIS is what they'd be called informally) -- fine when the given
    # name is unambiguous, but a real bug when it's already a speculative guess. The clearest
    # case: Rowling's alias "Joanne Kathleen Rowling" makes "Kathleen" a dual-interpretation
    # middle token (below) so combination forms like "Kathleen Rowling" get generated -- but
    # nickname-substituting it too produced "Cassie", "Trina", "Kittie" etc. cross-multiplied
    # against her surnames, fabricated aliases with zero real-world connection to her. Only
    # names we're actually confident ARE a real given name for this person -- the canonical
    # name's own tokens, and unambiguous given-side tokens from real aliases -- get expanded.
    nickname_eligible_givens = set(given_candidates)

    for alias, alias_type in typed_aliases + [(canonical_name, "original")]:
        if not _is_structural_alias(alias_type):
            # An opaque identity (pseudonym, nickname, title, mononym, ...) is NOT "this
            # person's given name + surname" and must never be decomposed into parts -- that
            # was the exact cause of the Rowling/"Robert Galbraith" garbage (see module
            # docstring and _OPAQUE_TYPE_MARKERS above). Its own literal string is already
            # stored as its own variant elsewhere; nothing further to do with it here.
            continue

        if "," in alias:
            # "Last, First Middle" inverted format -- MUST be parsed comma-aware. Naively
            # replacing the comma with a space and tokenizing left-to-right would treat the
            # surname as if it were a given name -- a real bug that corrupted output for
            # nearly every person in the dataset (e.g. "Kennedy, Robert F." produced garbage
            # like "Robert Robert" and "Kennedy Kennedy" once cross-multiplied).
            surname_part, _, given_part = alias.partition(",")
            surname_part = surname_part.strip()
            if len(surname_part) > 3:
                surname_candidates.add(surname_part)
            # ALL given-part tokens are given-name candidates, not just the first -- this is
            # what actually fixes the middle-name-as-given-name gap for someone whose
            # canonical_name is stored short (e.g. "Liz Truss" with no middle name at all):
            # the only place her real middle name "Elizabeth" exists in parseable form is the
            # hand-curated inverted alias "Truss, Mary Elizabeth". Unlike the non-comma branch
            # below, there's no given/surname ambiguity here -- the comma already tells us
            # unambiguously which side is which.
            for tok in given_part.strip().split():
                if len(tok) > 3:
                    given_candidates.add(tok)
                    nickname_eligible_givens.add(tok)  # comma tells us unambiguously: given side
            continue

        _, alias_tokens, _ = _split_name(alias)
        if len(alias_tokens) >= 2:
            # The FINAL token of a space-separated multi-word name is unambiguously the
            # surname (standard Western convention) -- only genuinely middle-positioned
            # tokens (between first and last) are ambiguous between "a second surname"
            # (Jacqueline "Kennedy" Onassis: a retained prior-married name) and "a middle
            # given name someone goes by". Treating the FINAL token as ambiguous too was a
            # real bug: for "Kennedy, Robert F." (parsed here as alias_tokens =
            # ["Robert","F.","Kennedy"] once un-inverted upstream), it added "Kennedy" to
            # given_candidates as well as surname_candidates, producing "Kennedy Kennedy" in
            # the output once cross-multiplied.
            last_tok = alias_tokens[-1]
            if len(last_tok) > 3:
                surname_candidates.add(last_tok)
            for tok in alias_tokens[1:-1]:
                # Genuinely ambiguous (Jacqueline "Kennedy" Onassis-style) -- try both
                # interpretations for direct combination, but do NOT trust it enough for
                # nickname expansion (see nickname_eligible_givens comment above).
                if len(tok) > 3:
                    surname_candidates.add(tok)
                    given_candidates.add(tok)
            # The FIRST token of a real structural alias is unambiguously a given name
            # (standard Western convention) -- safe for nickname substitution.
            given_candidates.add(alias_tokens[0])
            nickname_eligible_givens.add(alias_tokens[0])
        elif len(alias_tokens) == 1 and len(alias_tokens[0]) > 3:
            # A single-word alias (a mononym-shaped structural form, or a short real name) has
            # no given/surname split to get wrong -- safe to add directly, safe to expand.
            given_candidates.add(alias_tokens[0])
            nickname_eligible_givens.add(alias_tokens[0])

    def add(s: str):
        s = s.strip()
        if s and s.lower() not in {t.lower() for t in leading}:  # don't emit bare titles
            variants.add(s)

    for surname in surname_candidates:
        for given in given_candidates:
            add(f"{given} {surname}")
            add(f"{_initial(given)} {surname}")
            add(f"{surname}, {given}")
            if suffix_str:
                add(f"{given} {surname} {suffix_str}")
        # surname alone -- the specific gap that caused real false negatives (e.g. "Modi",
        # "Bridle", "Dillard", "Kennedy" as a standalone reference)
        if len(surname) > 3:
            add(surname)

    # given name alone, and middle name alone (explicitly requested: some people are known
    # by their middle name, e.g. Liz Truss's legal first name is "Mary")
    for given in given_candidates:
        if len(given) > 3:
            add(given)
    for middle in middles:
        if len(middle) > 3:
            add(middle)

    # full forms with middle name/initial, all surname candidates
    for surname in surname_candidates:
        if middles:
            middle_full = " ".join(middles)
            middle_initials = " ".join(_initial(m) for m in middles)
            add(f"{first} {middle_full} {surname}")
            add(f"{first} {middle_initials} {surname}")
            add(f"{_initial(first)} {middle_initials} {surname}")
            if suffix_str:
                add(f"{first} {middle_full} {surname} {suffix_str}")
                add(f"{first} {middle_initials} {surname} {suffix_str}")  # e.g. "William H. Gates III"

    # nickname substitutions -- only for given names we're actually confident about, not
    # every speculative dual-interpretation guess (see nickname_eligible_givens above)
    for given in nickname_eligible_givens:
        for nickname in nicknames_for(given):
            nickname_cap = nickname.capitalize()
            for surname in surname_candidates:
                add(f"{nickname_cap} {surname}")
            add(nickname_cap)

    variants.discard(canonical_name)
    return variants


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "Robert James Smith Jr."
    aliases = sys.argv[2:] if len(sys.argv) > 2 else []
    for v in sorted(generate_variants(name, aliases)):
        print(v)
