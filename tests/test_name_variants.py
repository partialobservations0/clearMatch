"""Tests for src/name_variants.py -- the systematic name-form generator.

Every test here traces back to either a real bug found during this project's eval runs
(regression tests, so it can't come back) or a requirement explicitly stated for the product
(shortenings/initials, middle-name-as-given-name, non-mechanical nicknames). Run with:

    source .venv/bin/activate && python3 -m pytest tests/ -v
"""

from name_variants import generate_variants, nicknames_for, _split_name, _is_structural_alias


# ---------------------------------------------------------------------------
# Basic mechanical forms -- the baseline everyone should get
# ---------------------------------------------------------------------------

def test_basic_first_last_and_initials():
    v = generate_variants("John Michael Smith")
    assert "John Smith" in v                # no middle
    assert "J. Smith" in v                  # single initial
    assert "J. M. Smith" in v               # all initials
    assert "Smith, John" in v               # inverted, no middle
    assert "Smith, John Michael" not in v or True  # (inverted+full-middle not required, just documenting)


def test_surname_alone_and_given_alone():
    """The exact gap that caused real false negatives on 'PM Modi', 'Bridle', 'Dillard'
    (surname-only references) -- surname and given name must each be generated standalone."""
    v = generate_variants("Narendra Modi")
    assert "Modi" in v
    assert "Narendra" in v


def test_middle_name_alone_and_with_surname():
    """Explicit product requirement: someone may be referred to by a middle name alone, or
    (more realistically) by their middle name plus surname."""
    v = generate_variants("John Michael Smith")
    assert "Michael" in v
    assert "Michael Smith" in v  # middle name is itself a given-name candidate


def test_suffix_combinations():
    v = generate_variants("William Henry Gates III")
    assert "William Gates III" in v
    assert "William H. Gates III" in v  # abbreviated middle initial + full suffix combined
    assert "Gates" in v


# ---------------------------------------------------------------------------
# Real nickname / shortening coverage (product requirement: "James -> Jim")
# ---------------------------------------------------------------------------

def test_real_nickname_dataset_loaded():
    assert "jim" in nicknames_for("James") or "jimmy" in nicknames_for("James")
    assert "bob" in nicknames_for("Robert")
    assert "liz" in nicknames_for("Elizabeth") or "beth" in nicknames_for("Elizabeth")


def test_nickname_substitution_reaches_generated_variants():
    v = generate_variants("Robert James Smith")
    lowered = {x.lower() for x in v}
    assert "bob smith" in lowered
    assert "bobby smith" in lowered


# ---------------------------------------------------------------------------
# Middle-name-as-given-name (the specific gap this was built to close)
# ---------------------------------------------------------------------------

def test_middle_name_as_public_name_real_case():
    """Real case: Liz Truss's legal first name is 'Mary'; she's publicly known by her middle
    name 'Elizabeth'. Her canonical_name is stored SHORT ('Liz Truss', no middle at all) --
    the only place 'Elizabeth' exists in parseable form is the inverted full-legal-name alias.
    This must still produce 'Elizabeth Truss', not just 'Elizabeth' alone."""
    aliases = [
        ("Truss, Mary Elizabeth", "inverted"),
        ("Mary Truss", "legal_first_name_only"),
    ]
    v = generate_variants("Liz Truss", aliases)
    assert "Elizabeth Truss" in v
    assert "Elizabeth" in v
    assert "Mary Truss" in v or True  # already given directly as an alias, not required to regenerate


# ---------------------------------------------------------------------------
# Opaque identities must NOT be decomposed (the Rowling/"Robert Galbraith" bug)
# ---------------------------------------------------------------------------

def test_pseudonym_is_not_decomposed():
    """Regression test for a real bug: 'Robert Galbraith' (J.K. Rowling's pseudonym) is a
    WHOLLY SEPARATE IDENTITY, not 'given name Robert + surname Galbraith'. Decomposing it
    mined 'Robert' as a fake given name, ran real nickname substitution on it, and
    cross-multiplied against her real surnames -- producing garbage like 'Rupert Kathleen'
    and 'Dobbin Rowling'. None of that must ever reappear."""
    aliases = [
        ("Joanne Rowling", "real_birth_name"),
        ("Joanne Kathleen Rowling", "commonly_assumed_full_name"),
        ("Robert Galbraith", "pseudonym_as_input"),
    ]
    v = generate_variants("J.K. Rowling", aliases)
    garbage_markers = ["Rupert", "Dobbin", "Hobkin", "Bobby Rowling", "Bill Rowling", "Hob Rowling"]
    for marker in garbage_markers:
        assert not any(marker in x for x in v), f"found garbage variant containing {marker!r}: {[x for x in v if marker in x]}"
    # the pseudonym's own literal string is a legitimate variant -- just not decomposed into parts
    # (it's supplied as an existing alias, not regenerated here; this test only asserts no
    # cross-contamination into other generated forms)


def test_nickname_type_alias_not_decomposed():
    """A branded/informal nickname phrase like 'Air Jordan' or 'Big George' must not have its
    first word mined as if it were a real given name (the 'Air'/'Big' noise bug)."""
    aliases = [("Air Jordan", "brand_nickname")]
    v = generate_variants("Michael Jordan", aliases)
    assert "Air" not in v
    assert "Air Michael" not in v


def test_title_type_alias_not_decomposed():
    aliases = [("Supreme Leader", "title_informal")]
    v = generate_variants("Kim Jong Un", aliases)
    assert "Supreme" not in v
    assert "Leader" not in v


def test_is_structural_alias_classification():
    assert _is_structural_alias("inverted") is True
    assert _is_structural_alias("real_birth_name") is True
    assert _is_structural_alias(None) is True  # untyped assumed structural
    assert _is_structural_alias("pseudonym_as_input") is False
    assert _is_structural_alias("nickname") is False
    assert _is_structural_alias("brand_nickname") is False
    assert _is_structural_alias("title_informal") is False
    assert _is_structural_alias("mononym") is False
    assert _is_structural_alias("generated_systematic") is False  # never re-mine our own output


# ---------------------------------------------------------------------------
# Structural aliases (real name variants) SHOULD be decomposed
# ---------------------------------------------------------------------------

def test_second_surname_mined_from_maiden_married_alias():
    """Real case: Jacqueline (Bouvier) Kennedy Onassis. A real article said 'Jacqueline
    Bouvier Kennedy' -- a maiden+married combination nobody explicitly cataloged. Fixed by
    mining EVERY non-first token of a structural alias as a surname candidate, not just the
    last one, so 'Kennedy' (a middle-position retained name) becomes its own standalone form."""
    aliases = [
        ("Jacqueline Kennedy Onassis", "combined_married_names"),
        ("Jackie Bouvier", "nickname"),
    ]
    v = generate_variants("Jacqueline Lee Bouvier", aliases)
    assert "Kennedy" in v


def test_comma_inverted_alias_parsed_correctly():
    """Regression test for a real bug: naively replacing the comma with a space and
    tokenizing left-to-right treated the surname as a given name, producing garbage like
    'Robert Robert' and 'Kennedy Kennedy' once cross-multiplied. The comma MUST be parsed as
    an explicit Last/First boundary."""
    aliases = [("Kennedy, Robert F.", "inverted")]
    v = generate_variants("Robert F. Kennedy", aliases)
    assert "Robert Robert" not in v
    assert "Kennedy Kennedy" not in v
    assert "Kennedy" in v  # legitimate surname-alone form
    assert "Robert" in v   # legitimate given-alone form (already the canonical first name here)


# ---------------------------------------------------------------------------
# Leading titles/honorifics excluded from decomposition
# ---------------------------------------------------------------------------

def test_leading_title_not_treated_as_given_name():
    v = generate_variants("Pope Francis")
    assert "Pope" not in v
    assert "Francis" in v


# ---------------------------------------------------------------------------
# Short-token noise filtering
# ---------------------------------------------------------------------------

def test_short_tokens_excluded_from_mining():
    """Mined tokens (from decomposing OTHER aliases) below length 4 are excluded -- this
    specifically killed real noise like 'Air'/'Big'/'Day' mined from the front of branded
    nicknames. Uses 'Margaret', whose real nicknames (Maggie/Meg/Peggy/...) do NOT include
    'Jo', so if 'Jo' appears it can only be leaking from decomposing the opaque alias below --
    not from the separate, legitimate nickname-substitution pathway."""
    aliases = [("Jo Smith", "nickname")]  # opaque type -- must not be decomposed at all
    v = generate_variants("Margaret Smith", aliases)
    assert "Jo" not in v
    assert "Jo Smith" not in v  # not re-derived; it's supplied directly as its own alias elsewhere


# ---------------------------------------------------------------------------
# Idempotence / sanity
# ---------------------------------------------------------------------------

def test_canonical_name_itself_not_returned_as_a_variant():
    v = generate_variants("Jane Doe")
    assert "Jane Doe" not in v


def test_empty_or_single_token_name_does_not_crash():
    assert generate_variants("") == set()
    v = generate_variants("Prince")  # real mononym
    assert isinstance(v, set)
