# Planning: Automated Enrichment via Additional Web Research

**Status: planning only, not implemented.** This describes how `src/match.py` could be
extended to perform additional web research when an article itself doesn't contain enough
disambiguating detail (a DOB, a middle name, an employer, etc.) to confidently resolve a
match -- rather than giving up at `uncertain`. No code in this repository implements it.

## The problem this solves

Today, when `match_person()` can't find enough evidence *within the article itself* to decide
match vs. no_match, it correctly returns `uncertain` rather than guessing (see `README.md` --
this is the one safe failure mode). But some of those cases are genuinely resolvable: the
article might say "the 45-year-old CEO of Acme Corp" with no name-adjacent birth year, while a
quick search for "Acme Corp CEO" would turn up a corporate bio page stating the birth year
directly. The article alone was insufficient; the *person* is not actually ambiguous once you
look one hop further. Automating that extra hop is what this plan covers.

Empirically, this bucket is small on our current dataset (1 genuine `uncertain` case out of 290
in the last full run), but real-world traffic will likely see more of it -- our dataset was
built by people who already know the target's DOB, so under-specified articles were rare by
construction. A production deployment screening arbitrary articles will hit this more often.

## When to trigger it (the gate)

Enrichment should be a **second stage**, invoked only when stage 1 (pure article-based
reasoning, what exists today) can't decide *and* the reason is a genuine gap in available
information -- not every `uncertain` should trigger it:

- **Trigger**: `match == "uncertain"` AND `age_arithmetic_check` reports no usable date/age
  information AND `disambiguating_evidence` is thin/empty. This is the "the article just
  doesn't say enough" case, which is exactly what a targeted search can fill in.
- **Do NOT trigger** when `uncertain` comes from genuine *multi-person* ambiguity the article
  itself can't resolve even in principle -- e.g. our dataset's `C16-a` case, an article
  profiling a family where five real people share one literal legal name, with no way to tell
  which one a given detail refers to. More web research wouldn't fix that; only a human
  reviewing the specific context can. The gate needs to distinguish "missing information that
  probably exists somewhere" from "information that wouldn't disambiguate this even if found."
- This keeps cost bounded to the minority of cases that could plausibly benefit, rather than
  running an extra research pass on every `uncertain`.

## The pipeline (proposed)

```
match_person() returns "uncertain" (missing-info case, gate above passes)
        |
        v
1. Build a search query from the article's own context clues + candidate name
        |
        v
2. Run a web search, get candidate source URLs
        |
        v
3. Fetch + extract each candidate source (reuse src/fetch.py + src/extract.py)
        |
        v
4. Extract the specific missing fact (DOB/middle name/etc.) from each source,
   AND verify the source is actually about the SAME entity as the article
   (not a different same-named person) -- this is the highest-risk step
        |
        v
5. If a sufficiently corroborated fact is found: re-run match_person with the
   original article + the new fact + its source, asking for a final verdict
        |
        v
6. If no reliable fact is found: return "uncertain" anyway -- enrichment
   narrows the uncertain bucket, it never replaces the safety net
```

### Step 1: query construction

Naively searching `"<name>" date of birth` is dangerous for common names -- it risks pulling
back a *different* real person's DOB and confidently misapplying it, which would undo
everything the collision-detection work in this project was built to prevent. The query must
be anchored in context the article *itself* provides, to bias results toward the same
real-world entity:

- Pull out whatever distinguishing context the article already gave (employer, role, location,
  event, timeframe) -- these are exactly the fields the model already extracts into
  `disambiguating_evidence` and `rationale` today, so this is mostly reusing existing output.
- Construct a query combining the name with that context, e.g.
  `"<name>" "<employer or role from article>" biography` rather than a bare name+DOB search.
- Try the candidate's cataloged aliases too (from `db/nameRecognition.db`'s `name_variants`),
  since the best source for the missing fact might use a different name form than the article.

### Step 2-3: search and fetch

- Reuse the existing `src/fetch.py` / `src/extract.py` pipeline unchanged -- no new fetch
  infrastructure needed, just new URLs to feed it.
- Cap the number of candidate sources examined per case (e.g. top 3) to bound cost/latency.

### Step 4: extraction + same-entity verification (the risky step)

This is where a wrong answer would actually be dangerous, so it needs its own explicit
guardrail, not just "ask the model and trust it":

- A dedicated structured call (similar to `VERDICT_TOOL` in `match.py`) that asks the model to
  extract the candidate fact (DOB, middle name, etc.) from the fetched source **and** separately
  assess, as its own field, whether the source page's subject matches the article's subject on
  every corroborating detail already established (role, employer, timeframe, other biographical
  facts) -- not just the name string. This is the same "don't trust a name match alone" principle
  already baked into the core `match.py` prompt, applied one layer earlier.
- Prefer higher-trust source types when multiple candidates are found: Wikipedia/Wikidata
  infoboxes, official government/institutional bio pages, company leadership/investor-relations
  pages, and public records outrank LinkedIn, unsourced blogs, or forums. Record which tier the
  accepted source came from.
- Require some minimum corroboration before trusting an enrichment fact enough to flip a
  decision -- e.g. don't act on a single low-trust source; prefer agreement across at least two
  independent sources, or one clearly authoritative source (official bio, government record).

### Step 5: re-resolution

- Re-run the *existing* `match_person()` logic (or a light variant of it) with the original
  article text, the newly-found fact, and its source explicitly included in the prompt context
  -- structurally similar to how `db_context` already injects known-alias grounding today.
  This reuses the existing reasoning pipeline rather than building a parallel decision path.

### Step 6: fallback

- If no source clears the corroboration bar, the case stays `uncertain`. Enrichment is
  additive -- it should never be able to make the system *less* safe than it is today by forcing
  a decision on weak evidence just because a search was attempted.

## Explainability (this is a regulated context)

Every enrichment step must be logged, not just its outcome:

- The exact query/queries run
- Every source URL examined (not just the one accepted)
- The specific fact extracted and which source it came from
- The same-entity verification result and corroboration level
- Whether the fact changed the final verdict, and how

This extends the same audit-trail principle already in place for the core match decision
(`identified_name_forms`, `age_arithmetic_check`, `disambiguating_evidence`, `rationale`,
cached by `PROMPT_VERSION` in `src/match_cache.py`) one layer earlier -- a human reviewer must
be able to see not just *what* the system concluded, but *what it looked up* to get there, the
same way they can already see *why* today's verdict was reached.

## Cost and safety controls

- Gate condition above already limits this to a minority of cases.
- Cap sources examined per case and total enrichment attempts per case (a bounded budget,
  analogous to the existing `--max-cost` guard on `eval/run_eval.py`).
- Track and cache enrichment results the same way `match_cache.py` already caches verdicts, so
  re-running the eval doesn't re-pay for the same web research on the same case twice.
- A cheaper/faster model could handle query construction and fact-extraction (steps 1 and 4),
  reserving the full reasoning model for the final re-resolution call (step 5) -- similar to how
  this project already reserves the expensive API call for cases the free pre-check can't
  resolve on its own.

## Why this wasn't implemented now

This is a meaningfully larger scope than a prompt or schema change -- it introduces a live web
search dependency, a new verification step with real risk of importing a wrong fact for a
common name, and new audit/logging surface. Per the task, it's scoped as a design exercise
rather than a build.
