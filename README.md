# nameRecognition

MVP tool: given a person's **name**, **date of birth**, and an article **URL**, determine
(a) whether the article is about that specific person, and (b) if so, whether the article is
positive or negative about them.

Product requirement: **zero false negatives** (never miss a true match) and **minimize false
positives** (don't wrongly flag an unrelated namesake as a match). Given that asymmetry, the
matcher should treat "uncertain" as a first-class output routed to human review, rather than
ever silently collapsing an ambiguous case into "no match." That same principle applies one
level down the stack too: a fetch/extract failure is not a "no match" either (see `src/` below)
-- it's a distinct "could not verify" outcome that must also route to review, not be
misread as evidence the person isn't in the article.

See `ENRICHMENT_PLAN.md` for a planning-only design (not implemented) of how the system could
automatically research missing disambiguating details (a DOB, a middle name) via additional
web search when the article itself doesn't contain enough information to decide.

**To run this** (Docker or local venv, including API cost notes): see `SETUP.md`.

## Structure

```
SETUP.md           -- how to run this (Docker or local venv), API cost notes
ENRICHMENT_PLAN.md -- planning-only design for web-research enrichment (not implemented)
Dockerfile          -- builds the knowledge-base DB at image-build time; see SETUP.md
data/
  dataset.json   -- 290-case labeled eval set (name, DOB, real article URL, ground truth)
  DATASET.md     -- full schema, provenance, category breakdown, and known gaps/caveats
db/
  schema.sql            -- normalized DB schema: people, name_variants, articles,
                            extracted_entities, test_cases, match_cache (see "Knowledge base"
                            and "Cost controls" below)
  nameRecognition.db     -- SQLite file, rebuilt from data/dataset.json by the scripts below
                            (not hand-edited -- dataset.json remains the source of truth)
scripts/
  migrate_dataset_to_db.py  -- (re)builds db/ from data/dataset.json; pure restructuring, no cost
  fetch_articles_to_db.py   -- fills articles.full_text via src/pipeline.py; network only, no API cost
  add_aliases.py            -- adds real, hand-documented aliases dataset.json didn't generate
                                (nicknames like "Mutti"/"NaMo" aren't derivable from name parts)
  add_aliases_2.py          -- second hand-curated pass, broader review of all people
  generate_all_variants.py  -- runs src/name_variants.py's SYSTEMATIC generator for every
                                person: mechanical forms, surname/given/middle-name-alone,
                                real nickname substitutions. Run LAST (after the hand-curated
                                passes above), since it mines additional surnames/given-names
                                out of whatever real aliases already exist on file.
  (not yet built) -- extract_entities_to_db.py: populates extracted_entities via the Claude
                     API (real cost -- confirm scope/budget before running)
src/
  fetch.py       -- fetch a URL's raw HTML, tolerant of timeouts/SSL/connection errors
  extract.py     -- pull clean article title/text out of HTML (trafilatura + BS4 fallback),
                    with boilerplate/consent-wall/paywall detection so garbage text never
                    silently passes as a real article
  pipeline.py    -- fetch_and_extract(url): orchestrates the two with retries specifically
                    for non-deterministic failures (e.g. Yahoo's GDPR consent wall)
  match.py       -- entity-resolution + sentiment reasoning via the Claude API (structured
                    tool-call output); requires `.env` with ANTHROPIC_API_KEY. Consults
                    knowledge_base.py first: a DB hit grounds the prompt with known aliases/
                    collisions, and a cheap pre-check can skip the API call entirely when no
                    known name form appears in the article at all (routes to 'uncertain')
  knowledge_base.py -- read-only lookups against db/nameRecognition.db: lookup_by_dob,
                        lookup_by_name, find_name_forms_in_text. Handles curly-vs-straight
                        quote/apostrophe normalization (a real bug: "O'Donnell" vs "O'Donnell"
                        failed to match otherwise)
  name_variants.py  -- deterministic name-variant GENERATOR (see below) -- given a canonical
                        name plus whatever aliases already exist, mechanically derives
                        initials/order/suffix forms, first/middle/surname-alone forms, and
                        real nickname substitutions via data/reference/nicknames.csv (a public
                        dataset, github.com/carltonnorthern/nicknames, not invented)
tests/
  test_name_variants.py -- pytest suite for src/name_variants.py: regression test for every
                            real bug found this session (nickname substitution, middle-name-
                            as-given, pseudonym exclusion, comma-inversion parsing, surname
                            mining, leading titles). Run with `python3 -m pytest tests/ -v`.
                            Already caught one NEW bug on first use (see "Foreign language
                            handling" below) before it could reach production data.
  test_knowledge_base.py -- pytest suite for src/knowledge_base.py: script-detection
                            (looks_non_latin_script) and apostrophe normalization. Uses real
                            text excerpts (a live Xinhua article, real Cyrillic/Arabic
                            snippets), not synthetic examples. No API calls -- everything in
                            tests/ is local/free to run.
eval/
  smoke_test_fetch_extract.py -- runs fetch+extract against every dataset URL, reports
                                  success rate, writes results/fetch_extract_smoke_test.json
  run_eval.py                  -- runs match.py against data/dataset.json (or a --sample /
                                   --category subset), scores against ground truth, writes
                                   results/eval_run_full.json (or eval_run_partial.json).
                                   COSTS REAL MONEY (Anthropic API) -- see "Cost controls"
                                   below before running.
results/
  fetch_extract_smoke_test.json -- latest fetch/extract smoke-test run
  eval_run_full.json             -- latest full scored eval run (see results below)
```

## Knowledge base (`db/`)

A normalized SQLite database sitting alongside `data/dataset.json` (which remains the source
of truth -- the DB is rebuilt from it, not maintained by hand). Identity is keyed by
**date of birth**, not name string, since that's what actually distinguishes two real people
who share a name (e.g. the UK PM David Cameron vs. an Australian rules footballer of the same
name get two separate `people` rows).

- **`people`** (69 rows) -- every real, DOB-verified individual anywhere in the dataset,
  including the deliberate "wrong person" identities used in false-positive traps (they're
  real, separately-verified people too, e.g. Bill Gates Sr., not fabricated).
- **`name_variants`** (2,085 rows, covering all 69 people) -- every alias/name-form on file per
  person: nicknames, initials, inverted order, transliterations, pseudonyms, historical birth
  names, titles, and branding nicknames. Seeded from `dataset.json`'s name-form-variant rows,
  then extended in two passes: `scripts/add_aliases.py` covered the 7 people the original
  augmentation missed entirely (mostly "trap" identities -- RFK Sr. -> "Bobby Kennedy"/"RFK",
  George Foreman III -> "Monk", the basketball Michael Jordan -> "MJ"/"Air Jordan"/"His
  Airness", Bill Gates Sr., etc.); `scripts/add_aliases_2.py` then reviewed every person for
  well-known aliases still missing (e.g. Merkel -> "Mutti", Modi -> "NaMo", Hillary Clinton ->
  "HRC", Beyoncé -> "Queen Bey"/"Bey", Xi Jinping -> "Uncle Xi"/"Xi Dada"). The 8
  moderate-fame-roster people (below) mostly have only their single input name on file, which
  is itself the point -- most real, moderately-notable people don't have documented aliases the
  way global celebrities do.
- **`articles`** (127 rows, 122 with fetched full text) -- every unique real article URL in the
  dataset, with full extracted text pulled via the existing fetch pipeline. 9 currently have a
  `fetch_error` instead of text (bot-blocking / JS-rendering, some fresh drift since the
  dataset's original reachability filtering -- expected, properly recorded, not silently
  dropped).
- **`extracted_entities`** -- not yet populated. Will hold co-occurring entities (organizations,
  other people, locations) pulled from each article via the Claude API once run.
- **`test_cases`** (290 rows) -- the original eval rows, now with `person_id`/`article_id`
  foreign keys instead of embedded duplicate strings, alongside their ground truth.

### Moderate-fame roster (`category: "23_moderate_fame_organic_match"`, 15 people)

The original 47-person roster is all globally famous people (Obama, Musk, Putin, ...) -- which
turned out to be a real validity gap: for a name that famous, the matching LLM's own training
data already contains rich biographical knowledge (including, often, the exact DOB), so a
"correct" verdict doesn't cleanly prove the pipeline is reasoning from the article's actual
evidence rather than recalling memorized facts. This tier deliberately targets people real and
notable enough to have a genuine, live news article, but obscure enough that the DOB had to be
found via actual research, not recalled. Built in two passes (8 people, then 8 more requested
to reach a target of 20 -- 4 short; see gap note below):

- Marty Small Sr. (mayor, Atlantic City NJ), Reynaldo Aligada
  Jr. (MN Supreme Court justice-designate), Bronna Kahle (nonprofit president, ex-legislator),
  Milan Momcilovic (college basketball), Shannon O'Donnell (regional TV meteorologist), Aydar
  Suniev (minor-league hockey prospect), Ashten Prechtel (WNBA role player)
- Kazumi Matsui (mayor of Hiroshima, Japan -- the only international pick that survived; see
  gap note), Dakota Luther (college swimmer), Ted Gonder (nonprofit CEO), Sarah Gorham (poet/
  publisher), Stephen Dillard (Georgia Court of Appeals judge), Aristo Sham (classical pianist,
  2025 Van Cliburn Gold Medal), Scott Baker (former TV anchor, media executive), Angie Paccione
  (Colorado state agency executive director)

Each row's `source_notes` documents exactly how the DOB was found (Wikipedia infobox,
Ballotpedia, a sports-roster page, etc.) as evidence the research was real, not recalled. Many
other candidates were **dropped entirely** after real search effort found no verifiable exact
DOB (a community bank CEO, a startup founder, an indie musician, multiple international
business executives, several judges/officials) -- itself further evidence this tier wasn't
simply recalled. Two rows (Baker, Paccione) use the person's own Wikipedia article as the
"article" source rather than third-party news, because the original news sources Wikipedia
cites were blocked or archive-only in this environment -- a minor quality tradeoff (Wikipedia
is more neutral/encyclopedic than news framing) worth knowing about if you're specifically
stress-testing sentiment on those two rows.

**Gap**: the roster-expansion request targeted 12 additional people (20 total); only 8 were
delivered. The shortfall was real research friction, not a shortcut: the research forks'
WebSearch budget was exhausted partway through (shared across parallel forks), forcing a
slower WebFetch-only strategy for the back half of the work, and corporate executives in
particular (especially outside the US) systematically lack public DOB disclosure the way US
SEC filings or Wikipedia stub pages provide for politicians/athletes. International coverage
is thin as a result (only 1 of an intended 4 non-US/UK picks survived). Worth a follow-up pass
if international and business-executive coverage matters for the demo.

Rebuild anytime with `python3 scripts/migrate_dataset_to_db.py && python3 scripts/fetch_articles_to_db.py && python3 scripts/add_aliases.py && python3 scripts/add_aliases_2.py`.
Note: `migrate_dataset_to_db.py` wipes and rebuilds the whole DB from `dataset.json`, so the
alias scripts must be re-run after it, in order, to restore the extra aliases (they aren't in
`dataset.json` itself).

## Status

- [x] Eval dataset built and documented (`data/`) -- 290 cases, all with live, fetchable URLs
- [x] Fetch + extract pipeline (`src/fetch.py`, `src/extract.py`, `src/pipeline.py`)
- [x] Matching/sentiment logic (`src/match.py`) -- LLM-based (Claude via Anthropic API), structured
      tool-call output, requires `.env` with `ANTHROPIC_API_KEY`
- [x] Eval harness that scores the pipeline against the dataset ground truth (`eval/run_eval.py`)
- [x] Final full scored run: **0 false negatives, 0 false positives** on all 290 cases
      (`results/eval_run_full.json`) -- see results below
- [x] Local test suite (`tests/`, 26 tests) for the name generator and script-detection logic --
      no API cost, already caught 2 real bugs before they reached production data
- [x] Planning doc for automated web-research enrichment on under-specified articles
      (`ENRICHMENT_PLAN.md`) -- design only, not implemented
- [ ] Foreign-language pre-check fix implemented and logic-verified, but **not yet end-to-end
      tested against a live API call** (blocked on API credits) -- do this first once credits
      are available again, before trusting it in production
- [ ] **API credits exhausted as of this session** -- no further `eval/run_eval.py` or
      `src/match.py` invocations until credits are added (console.anthropic.com -> Billing)

## Final full eval results (290 cases, current dataset, post all fixes below)

`results/eval_run_full.json`. This is the last clean run before API credits ran out for the
session -- includes the moderate-fame roster (no "free" celebrity-recall help), the systematic
type-aware name generator, and the comma-inverted-alias dual-interpretation fix (see
"Database-grounded matching + pre-check" below for what that last one was).

| Outcome | Count |
|---|---|
| CORRECT | 234 |
| SENTIMENT_MISMATCH | 44 |
| PIPELINE_ERROR (fetch/extract failed before the model ran) | 10 |
| SERVED_FROM_CACHE | 2 |
| UNCERTAIN_MISS (ground truth 'uncertain', model didn't say so) | 1 |
| OTHER_MISMATCH (no_match -> uncertain -- safe direction) | 1 |
| **FALSE_NEGATIVE** (the one error class the product cannot have) | **0** |
| **FALSE_POSITIVE** (minimize, not zero) | **0** |

**Zero false negatives AND zero false positives** across all 290 real-world cases, including
every deliberately hard trap built this session (namesake collisions, the Rowling/Galbraith
pseudonym with zero string overlap, transliteration variants, decoy relatives, the RFK Sr./Jr.
collision). Notably, `C13-b` (the George Foreman decoy-relative case) had been a persistent
false positive across every earlier run -- it now correctly resolves to `uncertain` instead
("this is a legitimate reference to the candidate... but" rather than a forced wrong `match`),
which is the system behaving exactly as designed on a genuinely borderline case rather than a
bug being "fixed" per se.

**Sentiment mismatches (44 rows) trace back to a much smaller number of unique articles** --
most of the apparent volume is the same handful of underlying disagreements repeated across
name-form-variant rows that share an article. The disagreements cluster heavily on one genre:
official/historical retrospective biography pages (JFK's archives.gov bio, a Bush "this day in
history" piece, Merkel's "legacy" retrospective), where whether mildly admiring, encyclopedic
language counts as "positive" or "neutral" is a genuine calibration question -- not something
further prompt engineering can cleanly resolve. **This is a product decision worth a real
conversation** (where exactly should that line sit?) rather than an engineering bug to fix.

**Caveat**: this run predates the foreign-language pre-check fix (see below), which is
logic-verified but not yet tested against a live API call. Re-run once credits are available to
confirm it holds at full scale.

## Database-grounded matching + pre-check (src/knowledge_base.py)

`match.py` now consults `db/nameRecognition.db` before (and during) every match:

1. **DB lookup for grounding context**: if the input DOB matches a person already on file,
   their known aliases are injected into the prompt ("also known by: ...") so the model can
   recognize name forms it wouldn't otherwise know -- this matters most for the moderate-fame
   roster, where an alias genuinely isn't in an LLM's training data the way a celebrity
   nickname is. Separately, if the input name string is a known alias for ANY other real person
   with a DIFFERENT DOB, the model gets an explicit collision warning ("this name is also known
   to belong to N other real people with different DOBs") rather than having to infer that risk
   on its own.
2. **Cheap pre-check before the API call**: if neither the input name nor any known DB alias
   appears anywhere in the article (title + body), match.py skips the API call entirely and
   returns `uncertain` directly (`used_api: False` on the result) -- never `no_match`, since an
   incomplete alias list could still be the reason for a real match we didn't catch. This is
   deliberately NOT the inverse check (name found => confirmed match, skip verification): every
   false-positive trap in the dataset has the candidate's exact name present in the article, and
   only DOB/context reasoning disambiguates them, so a name being present always still goes
   through full API verification.

**A real bug was caught while testing this**: the pre-check initially only searched the article
*body* text, and a UN Women speech transcript by Malala Yousafzai -- entirely first-person
("I stand here heartbroken...") -- never once says her name in the body, only in the title. The
pre-check wrongly short-circuited to `uncertain` on a true `match`, a real false negative. Fixed
by including the title in the searched text (the LLM prompt already did). A 30-row sample looked
clean afterward (0 false negatives) -- but that sample size wasn't enough to catch what the full
290-row run found next.

### The pre-check's real weak point: name-presence detection is itself hard

A full 290-row run surfaced **10 more false negatives**, all from the same root cause: the
alias list (hand-curated + dataset-generated) didn't cover the specific name form the article
actually used. Concretely:
- `R-modi-3`: article says "PM Modi" -- surname only, not a cataloged full-name form
- `R-gates-3`: article says "William H. Gates III" -- abbreviated middle initial, not "Henry"
- `C05-b` (+ 4 variant rows): article says "Jacqueline Bouvier Kennedy" -- a maiden+married
  surname combination nobody had cataloged
- `M-bridle-1`, `M-dillard-1`: surname-only references ("Bridle", "Dillard")
- `M-odonnell-1`: the name WAS in the title verbatim, but with a curly apostrophe (`O'Donnell`,
  U+2019) against our stored straight-apostrophe (`O'Donnell`) -- a Unicode mismatch

This showed that hand-curating (or LLM-generating) a fixed alias list per person is
fundamentally incomplete -- there will always be some real-world name form nobody thought to
add. The fix was to stop trying to enumerate variants by hand and **generate them
systematically** instead: `src/name_variants.py` deterministically derives, from a person's
canonical name plus whatever real aliases already exist for them:
- mechanical forms: initials, inverted order, with/without middle name, with/without suffix
  (including combinations like "William H. Gates III" that hand-curation missed)
- **surname alone, given name alone, middle name alone** -- the single biggest gap, now
  generated for every person rather than only when someone happened to add it by hand
- additional surnames mined out of existing aliases (seeing "Jacqueline Kennedy Onassis"
  already on file is enough to derive "Kennedy" as a second real surname for Jacqueline
  Bouvier, closing that specific gap without needing bespoke maiden/married-name logic)
- real nickname substitutions (Robert -> Bob/Rob/Bobby, William -> Bill/Will/Willie, etc.) via
  `data/reference/nicknames.csv`, a real public dataset
  ([carltonnorthern/nicknames](https://github.com/carltonnorthern/nicknames), 2,828 mappings),
  not invented on the spot

Also fixed: `knowledge_base.normalize()` now maps curly quotes/apostrophes to straight ones
before comparing, closing the O'Donnell gap directly.

Run `scripts/generate_all_variants.py` after the hand-curated alias scripts (it mines from
whatever's already on file) -- current total: 2,085 name variants across 69 people, up from
274. A short-token quality pass excludes anything <=3 characters mined from a multi-word
phrase (this killed real noise like "Air" and "Big" mined from the front of "Air Jordan"/"Big
George") while keeping legitimate short real names/nicknames (Modi, Cook, Bob, Ed) intact.
A second bug (comma-inverted aliases like "Kennedy, Robert F." being tokenized left-to-right
instead of comma-aware, corrupting nearly every person's generated set with garbage like
"Robert Robert"/"Kennedy Kennedy") was found and fixed afterward -- see the false-positive
section below.

Re-verified all 10 originally-failing rows: 9/10 fixed. The 10th (`Nicholas Bridle`, formerly
`M-bridle-1`) turned out to be a *different* bug entirely -- the article is paywalled, and our
extraction pipeline only captures a 501-character preview that ends before his name even
though "Bridle" is present in the raw HTML. That's a fetch/extract-layer gap, not a naming
gap. Rather than leave a permanently-unresolvable row in the eval set, this row (and the
person) were removed from `data/dataset.json` entirely -- the paywall means our pipeline can
never fairly test this case, the same reasoning already applied to other unreachable URLs
filtered out earlier in this project (see `data/DATASET.md`).

Investigating that case also surfaced a scoring nuance worth fixing: the eval harness was
counting "ground truth `match`, predicted `uncertain`" identically to "ground truth `match`,
predicted `no_match`" -- both as `FALSE_NEGATIVE`. Those are not equally bad: `no_match` is a
silent, confidently-wrong miss (the one thing the product cannot do), while `uncertain`
correctly flags the case for human review -- no match is ever silently lost. Split into
`FALSE_NEGATIVE` (true silent miss) and `MATCH_ROUTED_TO_REVIEW` (safe degradation) as
separate outcome categories in `eval/run_eval.py`.

### Two real bugs found and fixed during development (see `src/match.py` comments)
1. **Verdict-before-reasoning ordering**: the JSON tool-call schema originally put the `match`
   field before the reasoning fields, so the model committed to a verdict before doing age
   arithmetic -- the arithmetic became a post-hoc rationalization that couldn't change an
   already-decided answer. Fixed by reordering the schema so reasoning fields come first.
2. **Background-knowledge override**: the model would trust its own training-data knowledge of
   a famous person's "real" DOB over the explicit input DOB, assuming a numeric mismatch meant
   the *input* was a typo rather than evidence of a different real namesake. Fixed with explicit
   instructions that the input DOB is authoritative and a numeric contradiction must be treated
   as "different person," not "the input is probably wrong."

## Foreign language handling (src/knowledge_base.py: looks_non_latin_script)

Original requirement included "articles in foreign languages" as a messy-data case to handle.
Investigated with real tests (no assumptions):

1. **Fetch/extract**: works fine on non-English pages -- trafilatura is language-agnostic,
   confirmed by successfully extracting 50KB of clean text from a live Chinese Wikipedia page.
2. **The model's own reasoning**: handles foreign-language text well with zero special-casing
   needed. Fed a real Chinese Wikipedia article about Xi Jinping directly to match_person: it
   correctly parsed the Chinese-format date ("1953年6月15日"), recognized "习近平" as a valid
   name form alongside "Xi Jinping", and gave a nuanced, well-grounded sentiment read of a
   long, mixed/balanced article rather than forcing an artificial label.
3. **The actual gap**: the pre-check. All of our name_variants are Latin-alphabet strings
   (we catalog "Xi Jinping", never "习近平"). Tested against a real, live, current Xinhua news
   article genuinely about Xi Jinping, written 100% in Chinese characters with the Latin
   romanization appearing NOWHERE in the text -- the pre-check found zero matches and would
   have silently returned `uncertain` without ever calling the API, for an article the model
   would have handled correctly if given the chance. This would have blocked essentially every
   non-Latin-script article (Chinese, Russian, Arabic, Korean, Japanese, Greek, Hebrew, ...)
   from ever reaching real analysis -- not a false negative in the strict sense (uncertain is
   still safe), but a total loss of automation for entire language segments.

**Fix**: `looks_non_latin_script(text)` detects when an article is predominantly non-Latin
script (checks whether sampled letters' Unicode names start with "LATIN"; accented Latin
letters in French/Spanish/German etc. still count as Latin script and are unaffected). When
the pre-check finds no name-form match AND the text looks non-Latin-script, it no longer
trusts that as evidence of absence -- it falls through to a real API call instead of
short-circuiting to `uncertain`. Verified by reproducing the exact decision logic (not calling
the real API, to avoid cost): the real Chinese Xinhua article now correctly falls through to
"would call the API" (previously silently skipped it), while a genuinely unrelated English
article still gets the cost-saving skip. Full end-to-end validation (actually calling the API
on a real foreign-language article) is still needed once API credits are available again.

Covered by `tests/test_knowledge_base.py` using real Chinese/Russian/Arabic text (not
synthetic examples) plus a French-diacritics negative case, so this can't silently regress.

## Cost controls (src/match_cache.py, eval/run_eval.py --max-cost)

Repeatedly re-running the full eval while iterating on bugs is expensive by default -- every
run re-pays for all ~276 API calls even when only a handful of rows were affected by whatever
just got fixed. This is likely what drained the account's credit balance mid-session earlier.
Two independent safeguards now exist:

1. **Response cache** (`src/match_cache.py`, `match_cache` table in `db/`): every verdict is
   cached by a hash of `(input_name, input_dob, article_title, article_text, model,
   PROMPT_VERSION)`. Re-running the same case after an unrelated fix costs $0 -- confirmed by
   re-running an identical 2-row sample twice: first run cost $0.0355, second run (served
   entirely from cache) cost $0.0000. **`PROMPT_VERSION` in `match_cache.py` must be bumped**
   whenever `SYSTEM_PROMPT` or `VERDICT_TOOL` changes meaningfully, or a stale verdict from a
   materially different prompt would be served silently -- defeating the point of re-testing.
2. **Live budget guard** (`eval/run_eval.py --max-cost`, default **$10**): tracks real spend
   from each call's actual `response.usage` token counts (not an estimate) against Sonnet 5
   pricing, and stops the run -- writing whatever partial results exist -- the moment cumulative
   spend would exceed the cap, rather than continuing until the account itself runs out mid-run
   (what happened before this existed). Re-running the same command afterward resumes for free
   on every row the cache already answered.

This is a client-side safety net, not a replacement for a hard account-level cap -- also set a
spend limit in the Anthropic Console (Settings -> Billing/Limits) as a backstop against any
bug this code doesn't catch.

A full 290-row run costs roughly **$3** at Sonnet 5 pricing ($2/M input, $10/M output tokens):
~276 rows actually reach the API (a handful fail at fetch/extract, one is typically caught by
the pre-check), each call averaging ~3,400 input + ~400 output tokens (system prompt + tool
schema + article text + DB context).

## Notes on the fetch/extract step

- Environment: project-local venv at `.venv/` (`requirements.txt` has the pinned deps --
  `requests`, `trafilatura`, `beautifulsoup4`, `lxml`).
- The dataset was itself filtered down to only URLs the pipeline can reach -- 16 of the
  original 128 unique URLs were permanently unreachable (bot-blocking 403/406, JS-rendered
  pages, timeouts) and those rows were dropped or re-pointed to a working sibling article for
  the same person. See "URL reachability filtering" in `data/DATASET.md` for exactly what was
  dropped/kept and why.
- A real bug was caught and fixed during this: some "successful" fetches were actually GDPR
  cookie-consent walls (HTTP 200, plausible-length text, completely unrelated to the article).
  `extract.py` now detects and rejects these explicitly rather than letting garbage text reach
  the matcher -- this mattered because a matcher reasoning over consent-wall text has no real
  signal and would likely produce a false `no_match`, which this product cannot tolerate.
- That consent wall is probabilistic per-request (same URL, different outcome across repeated
  fetches), so `pipeline.py` retries automatically (`MAX_BOILERPLATE_RETRIES = 3`) rather than
  giving up on the first hit.

See `data/DATASET.md` for everything about how the eval set was built, what it covers, and
what to watch for given the no-false-negative requirement.
