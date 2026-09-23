"""Entity-resolution + sentiment reasoning: is this article about this specific person?

Product requirement (see top-level README): zero false negatives, minimize false positives.
That asymmetry drives the design here, not just the prompt wording:

  - "uncertain" is a first-class output, not a fallback. The model is explicitly told to
    prefer "uncertain" over guessing "no_match" whenever the article doesn't clearly rule
    the person out. A wrong "no_match" is the one output this product cannot tolerate; a
    wrong "uncertain" just costs a human reviewer a few seconds.
  - "no_match" requires a specific, stated reason (a contradicting DOB/age, or explicit
    evidence it's a different named individual) -- never just "the name wasn't obviously
    confirmed."
  - Pure string/fuzzy name matching cannot pass this product's hardest real cases by
    construction (e.g. J.K. Rowling publishing as "Robert Galbraith" -- zero string overlap
    with her real name). So identity reasoning is delegated to the LLM with the article's
    actual biographical content as grounding, not to a name-similarity heuristic.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

import knowledge_base as kb
import match_cache

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODEL = os.environ.get("MATCH_MODEL", "claude-sonnet-5")

VERDICT_TOOL = {
    "name": "report_verdict",
    "description": "Report whether the article is about the specified person, and if so, the sentiment toward them.",
    "input_schema": {
        "type": "object",
        "properties": {
            # Field order here is deliberate and load-bearing: Claude fills tool-call fields
            # in the order they're declared, so reasoning fields MUST come before the verdict
            # fields they're supposed to inform. Putting 'match' first (as an earlier version
            # of this schema did) let the model commit to a verdict before doing the age
            # arithmetic, so the arithmetic became a post-hoc rationalization that couldn't
            # actually change an already-decided answer -- confirmed via a real test case
            # (David Cameron PM vs. a namesake) where the model correctly computed a
            # discrepancy and then still output 'match' anyway. Reason first, decide last.
            "identified_name_forms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The specific name form(s) actually found in the article text that you believe refer to the candidate person (e.g. a nickname, initials, a pseudonym, a birth name).",
            },
            "age_arithmetic_check": {
                "type": "string",
                "description": (
                    "REQUIRED if the article states or implies an age, a birth year, or a date "
                    "from which age can be computed (e.g. 'graduated in 1998', 'the 57-year-old'). "
                    "Show the actual arithmetic: (article's reference year) - (input DOB's year) = "
                    "computed age, then state whether that computed age matches what the article "
                    "says. Do this explicitly and numerically -- do not eyeball it. If the article "
                    "gives no age/date information at all, write 'no age information in article'. "
                    "IMPORTANT if the article discusses MULTIPLE people who share this name or are "
                    "closely related (e.g. a family profile, several same-named relatives, a group "
                    "of people with the same surname): first identify WHICH specific individual the "
                    "age/date reference is actually about before treating it as contradicting "
                    "evidence. An age that belongs to a different person mentioned in the same "
                    "article (e.g. a parent's age in an anecdote, within an article otherwise about "
                    "their child) is NOT evidence against the candidate -- it's simply about someone "
                    "else in the same text. If the article doesn't clearly anchor the age/date to "
                    "one specific one of several same-named individuals, say so explicitly here "
                    "rather than assuming it applies to the candidate."
                ),
            },
            "disambiguating_evidence": {
                "type": "string",
                "description": "Any age/DOB/biographical detail found in the article that supports OR contradicts the identity match, informed by age_arithmetic_check above. Empty string if the article contains no such detail at all.",
            },
            "rationale": {
                "type": "string",
                "description": "One to three sentences explaining the verdict BEFORE you state it below, referencing the specific evidence used. Reach your conclusion here first -- the match/sentiment/confidence fields below must follow from this, not the other way around.",
            },
            "match": {
                "type": "string",
                "enum": ["match", "no_match", "uncertain"],
                "description": (
                    "'match' only if reasonably confident this is the same real individual, AND "
                    "age_arithmetic_check (if applicable) shows no unresolved numeric contradiction. "
                    "'no_match' if there is a SPECIFIC, STATED reason to believe it's a different "
                    "real person -- including an unresolved age/DOB arithmetic contradiction, even "
                    "if the name and other biographical details otherwise strongly suggest a "
                    "well-known person. 'uncertain' whenever you cannot confidently decide either "
                    "way -- required when the name could plausibly refer to the input person AND "
                    "you lack enough disambiguating detail to be sure, or lack enough detail to "
                    "rule them out. This includes articles discussing multiple people who share "
                    "the candidate's name (e.g. several relatives with the same name) where the "
                    "article doesn't clearly anchor its details to one specific one of them -- output "
                    "'uncertain', not 'no_match', when you can't tell which same-named individual a "
                    "given detail is about. Never guess 'no_match' out of mere uncertainty, and never "
                    "guess 'match' to preserve consistency with a famous person you recognize by name."
                ),
            },
            "sentiment_evidence": {
                "type": "string",
                "description": (
                    "Quote or closely paraphrase the SPECIFIC words/phrasing in the article "
                    "that establish how this person is portrayed. Ground this ONLY in what the "
                    "article's text actually says -- do not rely on this person's general "
                    "reputation, or on whether the news itself sounds celebratory or grim in "
                    "the abstract. A purely factual/informational article about a controversial "
                    "figure is 'neutral' unless the text itself uses evaluative language about "
                    "them; a celebratory-sounding event (a record, a promotion, a win) is only "
                    "'positive' if the article's own framing of THIS PERSON is favorable, not "
                    "merely because the event sounds good. 'not_applicable' if match is not 'match'."
                ),
            },
            "sentiment": {
                "type": "string",
                "enum": ["positive", "negative", "neutral", "not_applicable"],
                "description": (
                    "Sentiment of how the article portrays THIS SPECIFIC PERSON, not the "
                    "article's overall topic or tone, and not your own general impression of "
                    "them -- must follow directly from sentiment_evidence above. 'not_applicable' "
                    "only when match is 'no_match' or 'uncertain'."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
        },
        "required": ["identified_name_forms", "age_arithmetic_check", "disambiguating_evidence", "rationale", "match", "sentiment_evidence", "sentiment", "confidence"],
    },
}

SYSTEM_PROMPT = """You are an entity-resolution and sentiment analyst. Given a person's name \
and date of birth, and the text of a news article, you must determine whether the article is \
about that specific real individual, and if so, whether the article portrays them positively \
or negatively.

Real-world names are messy. The article may refer to the person using:
- a nickname or short form (Bill for William, Liz for Elizabeth)
- initials, or a first-initial-plus-surname form
- a middle name used or dropped, or a suffix (Jr., Sr., III)
- a maiden or married name, or a name in "Last, First" order
- a native-language name order (surname-first) or an alternate transliteration/romanization
- a title, regnal name, or mononym instead of their legal name
- a pseudonym or pen name with NO string overlap to their real name at all
- their historical birth name, if it differs from the name they are now known by

None of these should cause you to miss a true match. Conversely, an identical or similar name \
string is NOT sufficient for a match if the article's biographical details (age, birth year, \
explicit DOB, career timeline, or other identifying facts) contradict the given date of birth, \
or clearly indicate a different named individual (e.g. a different profession, a family member \
of the target rather than the target themselves).

If the article states or implies an age, birth year, or any date you can compute an age from, \
you MUST do the actual arithmetic explicitly in age_arithmetic_check before deciding 'match' -- \
do not approximate or eyeball whether an age "roughly fits" the given date of birth. A name \
string matching is not sufficient evidence on its own if the numbers don't check out: compute \
first, then decide.

The input date of birth is GIVEN and AUTHORITATIVE -- it is not a claim for you to fact-check \
against your own background knowledge of what some famous person's "real" DOB is. Treat it as: \
"there exists a specific real individual with exactly this DOB; determine whether they are who \
the article is about." You must NEVER resolve a numeric discrepancy by concluding the input DOB \
is probably a typo/error so that a match with a famous person can be preserved -- that reasoning \
is exactly backwards and is a known failure mode you must avoid. If your background knowledge of \
a famous person's actual DOB differs from the input DOB, and the article's own stated age/date \
evidence is consistent with YOUR background knowledge rather than the input DOB, the correct \
conclusion is that the input DOB identifies a DIFFERENT real individual who happens to share \
the same name as the famous person in the article (this is common -- politicians, athletes, and \
executives frequently share names with other real people) -- so the verdict is 'no_match', full \
stop, regardless of how much career/biographical detail otherwise "obviously" points to the \
famous person. Do not let the strength of a name match talk you out of a clear numeric \
contradiction. If the arithmetic doesn't check out, this is not the person, even when everything \
else about the article screams "obviously this famous person."

Call report_verdict exactly once with your structured verdict. Follow the field descriptions \
in the tool schema precisely, especially the distinction between 'no_match' (specific \
contradicting evidence) and 'uncertain' (insufficient evidence either way) -- this system must \
never miss a true match, so an unjustified 'no_match' is the single worst possible error you \
can make. When genuinely unsure, say so."""


@dataclass
class MatchResult:
    match: str
    sentiment: str | None
    confidence: str
    identified_name_forms: list[str] = field(default_factory=list)
    age_arithmetic_check: str = ""
    disambiguating_evidence: str = ""
    sentiment_evidence: str = ""
    rationale: str = ""
    raw_error: str | None = None
    used_api: bool = True  # False when the pre-check short-circuited before any API call
    from_cache: bool = False  # True when served from match_cache instead of a fresh (billed) API call
    known_person_hit: bool = False  # True when input_dob matched a person already in db/
    known_collisions: int = 0  # count of OTHER real people (different DOB) sharing this name
    input_tokens: int = 0  # 0 for pre-check skips and cache hits -- only a real API call costs anything
    output_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.raw_error is None


def _build_db_context(input_name: str, input_dob: str) -> tuple[str, "kb.PersonRecord | None", list["kb.PersonRecord"]]:
    """Look up our knowledge base for (a) a known person with this exact DOB, whose known
    aliases can help recognize name forms an LLM wouldn't otherwise know, and (b) any OTHER
    real people (different DOB) who share this name string, so the model gets an explicit
    warning rather than having to infer a collision risk on its own."""
    known_person = kb.lookup_by_dob(input_dob)
    same_name_people = kb.lookup_by_name(input_name)
    collisions = [p for p in same_name_people if known_person is None or p.id != known_person.id]

    parts = []
    if known_person:
        other_aliases = [a for a in known_person.aliases if normalize_for_display(a) != normalize_for_display(input_name)]
        if other_aliases:
            parts.append(
                f"DATABASE CONTEXT: We already have a verified profile for someone with exactly "
                f"this date of birth ({input_dob}): canonical name \"{known_person.canonical_name}\", "
                f"also known by: {', '.join(other_aliases)}. If the article uses any of these name "
                f"forms instead of \"{input_name}\", that is still strong identity evidence for this "
                f"same candidate -- treat it as such."
            )
    if collisions:
        collision_desc = "; ".join(f"\"{p.canonical_name}\" (DOB {p.date_of_birth})" for p in collisions)
        parts.append(
            f"DATABASE COLLISION WARNING: The name \"{input_name}\" is also a known name/alias for "
            f"{len(collisions)} OTHER real, distinct people in our records with DIFFERENT dates of "
            f"birth: {collision_desc}. This is a documented real-world namesake collision -- do NOT "
            f"assume a match merely because this name string appears in the article. Verify carefully "
            f"against the specific candidate DOB given ({input_dob}), not just the name."
        )

    return ("\n\n".join(parts), known_person, collisions)


def normalize_for_display(s: str) -> str:
    return kb.normalize(s)


def _build_user_message(
    input_name: str, input_dob: str, article_title: str | None, article_text: str, db_context: str = ""
) -> str:
    db_block = f"\n{db_context}\n" if db_context else ""
    return f"""CANDIDATE PERSON
Name: {input_name}
Date of birth: {input_dob}
{db_block}
ARTICLE
Title: {article_title or "(no title extracted)"}
Text:
{article_text}

Determine whether this article is about the candidate person above, and if so, the sentiment \
toward them specifically. Call report_verdict."""


def match_person(
    input_name: str,
    input_dob: str,
    article_title: str | None,
    article_text: str,
    model: str = DEFAULT_MODEL,
    use_db: bool = True,
    use_cache: bool = True,
) -> MatchResult:
    db_context, known_person, collisions = _build_db_context(input_name, input_dob) if use_db else ("", None, [])

    # Cheap pre-check: does the candidate's name, or any KNOWN alias of theirs, appear
    # anywhere in the article text at all? If genuinely none of them do, that's strong enough
    # evidence to skip the API call -- but we route to 'uncertain', never 'no_match', because
    # our alias list is necessarily incomplete (a real alias we haven't cataloged could still
    # be the reason for a true match) and a wrong 'no_match' is the one error this product
    # cannot make. This is deliberately NOT the inverse check (name found => confirmed match):
    # every false-positive trap in the dataset (e.g. David Cameron PM vs. a namesake) has the
    # candidate's exact name string present in the article, and only DOB/context reasoning
    # disambiguates them -- so a name being present must still go through full verification.
    name_forms = [input_name] + (known_person.aliases if known_person else [])
    # Search title + body together -- a real bug caught in testing: a UN Women speech
    # transcript by Malala Yousafzai never once says her name in the body text (it's a
    # first-person quote), but the title "Malala Yousafzai's remarks on..." unambiguously
    # identifies her. The title is legitimate identifying content (match_person's prompt
    # already includes it), so the pre-check must consider it too.
    searchable_text = f"{article_title or ''}\n{article_text}"
    found_forms = kb.find_name_forms_in_text(searchable_text, name_forms)

    # All of our name_forms are Latin-alphabet strings (even for people whose real name is in
    # another script -- we only catalog the romanization, e.g. "Xi Jinping" not "习近平"). A
    # "not found" result is only trustworthy evidence of absence when the article is ALSO in
    # Latin script; on genuine native-language text it just means our Latin-only list could
    # never have matched, regardless of relevance. Confirmed with a real test: a live Chinese
    # Xinhua news article, 100% written in Chinese characters and genuinely about Xi Jinping,
    # produced zero pre-check matches and would have been silently routed to 'uncertain'
    # without ever reaching the model -- even though a separate real test proved the model
    # itself reads Chinese text (including Chinese-format dates) and reasons about it
    # correctly when actually given the chance. So: skip the cost-saving shortcut specifically
    # when the text doesn't look Latin-script, and fall through to a real API call instead.
    if not found_forms and not kb.looks_non_latin_script(searchable_text):
        return MatchResult(
            match="uncertain",
            sentiment=None,
            confidence="low",
            rationale=(
                f"Pre-check (no API call): none of the candidate's known name forms "
                f"({name_forms}) appear anywhere in the article text. Routed to 'uncertain' "
                f"per policy rather than 'no_match', since our alias list may be incomplete."
            ),
            used_api=False,
            known_person_hit=known_person is not None,
            known_collisions=len(collisions),
        )

    # Cache hit: identical (name, DOB, article, model, prompt) has already been verified by
    # the API before -- serve it for free instead of re-paying for a guaranteed-identical answer.
    cache_key = match_cache.make_key(input_name, input_dob, article_title, article_text, model, db_context)
    if use_cache:
        cached = match_cache.get(cache_key)
        if cached is not None:
            return MatchResult(
                **cached, from_cache=True,
                known_person_hit=known_person is not None, known_collisions=len(collisions),
            )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return MatchResult(
            match="uncertain",
            sentiment=None,
            confidence="low",
            raw_error="ANTHROPIC_API_KEY not set -- cannot call the model. "
                      "Create a .env file with ANTHROPIC_API_KEY=... in the project root.",
            known_person_hit=known_person is not None,
            known_collisions=len(collisions),
        )

    client = Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "report_verdict"},
            messages=[
                {"role": "user", "content": _build_user_message(input_name, input_dob, article_title, article_text, db_context)}
            ],
        )
    except Exception as e:
        # An API failure is a "could not verify" outcome, same as a fetch failure -- it must
        # NOT be interpreted as no_match by any caller. Surfacing it as uncertain + raw_error
        # keeps that distinction explicit for eval.py and any future caller.
        return MatchResult(
            match="uncertain",
            sentiment=None,
            confidence="low",
            raw_error=f"API call failed: {e}",
            known_person_hit=known_person is not None,
            known_collisions=len(collisions),
        )

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        return MatchResult(
            match="uncertain",
            sentiment=None,
            confidence="low",
            raw_error="model did not call report_verdict (unexpected)",
            known_person_hit=known_person is not None,
            known_collisions=len(collisions),
        )

    verdict = tool_use_block.input
    sentiment = verdict.get("sentiment")
    if sentiment == "not_applicable":
        sentiment = None

    # Only cache fields that don't depend on this specific eval run (not known_person_hit/
    # known_collisions, which are re-derived from the DB fresh on every cache hit above, in
    # case the knowledge base has since been extended with new aliases/collisions).
    cacheable_fields = {
        "match": verdict.get("match", "uncertain"),
        "sentiment": sentiment,
        "confidence": verdict.get("confidence", "low"),
        "identified_name_forms": verdict.get("identified_name_forms", []),
        "age_arithmetic_check": verdict.get("age_arithmetic_check", ""),
        "disambiguating_evidence": verdict.get("disambiguating_evidence", ""),
        "sentiment_evidence": verdict.get("sentiment_evidence", ""),
        "rationale": verdict.get("rationale", ""),
    }
    if use_cache:
        match_cache.put(cache_key, cacheable_fields)

    return MatchResult(
        **cacheable_fields,
        known_person_hit=known_person is not None,
        known_collisions=len(collisions),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pipeline import fetch_and_extract

    if len(sys.argv) != 4:
        print("Usage: python3 match.py '<name>' '<YYYY-MM-DD>' '<article_url>'")
        sys.exit(1)

    name, dob, url = sys.argv[1], sys.argv[2], sys.argv[3]

    fetched = fetch_and_extract(url)
    if not fetched.ok:
        print(f"COULD NOT FETCH/EXTRACT ARTICLE: {fetched.error}")
        print("-> treat as: uncertain (route to human review), NOT no_match")
        sys.exit(1)

    result = match_person(name, dob, fetched.title, fetched.text)
    print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
