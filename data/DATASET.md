# Name/DOB/Article Entity-Resolution Test Dataset

Real-world-anchored test set for the MVP tool that takes (name, date of birth, article URL)
and must determine (a) whether the article is about that specific person, and (b) if so,
whether the article is positive or negative about them.

## File

`dataset.json` -- a JSON array of 290 test cases, from three sources plus a name-form
augmentation pass, then filtered to only articles the fetch pipeline (`src/`) can actually
retrieve (see "URL reachability filtering" below):

- **28 hand-curated cases** (`source: "hand_curated"`) -- built to deliberately target 16
  specific messy-data failure modes (nicknames, transliteration, name-order, decoy relatives,
  etc.), one category at a time. See the category table below.
- **102 cases from a designed Wikipedia roster** (`source: "wikipedia_roster"`) -- 25 real
  public figures deliberately chosen to cover transliteration, native name order, pseudonyms,
  regnal/religious names, and common-name collisions, each with ~4 real, live-URL news
  articles pulled and confirmed via WebFetch. See the category table below.

An earlier third source (55 cases mined from a 2005 BBC business-news text corpus) was built
and then **dropped**: those articles were local `.txt` files with no live URL, which doesn't
exercise the tool's actual input contract (it takes a URL, not raw text). If you want that
data back for a text-only ingestion path later, it can be regenerated from
`/Users/yashsatsangi/Documents/business/` the same way -- it is not preserved here.

- **160 name-form-variant cases** (`category: "22_name_form_variant"`, originally 164 -- see
  filtering below) -- for each of the 47 unique real people anchoring a `match` row above, the
  same real article/DOB was re-paired with multiple alternate ways of writing that person's
  name: nicknames, middle initials, all-initials forms, inverted "Last, First" order,
  dropped/added diacritics, alternate transliterations, historical birth names, and (hardest
  case) a pseudonym used as the raw input with zero string overlap to the real name.
  `ground_truth_match` is always `match` for these rows -- it's the same real person and
  article, only the typed-in name differs. Each row carries a `variant_of` field pointing back
  to its anchor row's `id`.

## URL reachability filtering

Once `src/fetch.py` + `src/extract.py` existed, every unique `article_url` in the dataset
(128 at the time) was actually run through the pipeline (`eval/smoke_test_fetch_extract.py`,
results in `results/fetch_extract_smoke_test.json`). 16 URLs turned out to be permanently
unreachable -- bot-blocking (403/406 from France24, Arab News, Forbes, MarketScreener, Time,
Euronews), JS-rendered pages the fetcher can't see (ESPN, PBS, rishisunak.com), or timeouts.
This affected 28 rows total (some articles were reused across multiple name-form-variant rows).

Rather than just deleting everything:
- **8 rows re-pointed, not dropped**: `R-truss-1` and `R-merkel-1` were unreachable, but both
  people had 3 other real, working articles in the roster. Their 8 dependent name-variant rows
  (`R-truss-1-v1..v4`, `R-merkel-1-v1..v4`) were re-pointed to `R-truss-2` / `R-merkel-2`
  instead of being lost -- same person, same DOB, same variant-name testing intent, just a
  different (working) real article. `source_notes` on those rows documents the substitution.
- **20 rows dropped, no fallback available**: the 16 directly-unreachable rows themselves, plus
  `C03-a` (Bill Clinton nickname case) and its 4 variant rows (`C03-a-v1..v4`) -- this was a
  one-off hand-curated case with no sibling article to fall back to.

Net effect: **category 3 (nickname) now has only 1 example** (Ted Kennedy) instead of 2, and
**category 8 (common-name-different-DOB trap) now has only 1 example** (James Brown) instead
of 2 -- both are gaps worth filling if you need that coverage back (either find a new live
Bill Clinton article, or accept the single remaining example per category).

After filtering, a fresh full run confirmed 110/112 unique URLs (98.2%) fetch successfully on
a single pass -- the remaining ~2% is Yahoo's GDPR consent wall, which is genuinely
non-deterministic per-request (the same URL succeeds or hits the wall unpredictably) rather
than a hard block, and the pipeline retries automatically for exactly this case
(`src/pipeline.py`, `MAX_BOILERPLATE_RETRIES = 3`) -- see the pipeline section below.

## Schema

```
{
  "id":                    string, e.g. "C08-a" (hand-curated) or "R-zelenskyy-1" (roster)
  "category":              which real-world messy-data failure mode this case stresses
  "input_name":            the name as it would be typed into the tool
  "input_dob":             ISO date (YYYY-MM-DD)
  "article_title":         real headline
  "article_url":           real, live URL (every row in this dataset has one)
  "source":                "hand_curated" | "wikipedia_roster"
  "source_file":           always null in this dataset (reserved for future text-only sources)
  "article_snippet":       factual excerpt/paraphrase of the real article content
  "ground_truth_match":    "match" | "no_match" | "uncertain"
  "ground_truth_sentiment":"positive" | "negative" | "neutral" | null (null when no_match),
                           scoped specifically to the named individual, not overall article tone
  "why_its_tricky":        what specifically stresses the matcher/sentiment logic
  "source_notes":          where the DOB/identity facts were verified
  "variant_type":          (name-form-variant rows only) which kind of name variation this is
  "variant_of":            (name-form-variant rows only) the anchor row id this reuses the article/DOB from
}
```

## How ground truth was derived

Every person, DOB, and article in this set is real and was verified via web search
(primarily Wikipedia/Wikidata for biographical facts, WebFetch on the live article for
content) -- nothing here is synthetic. For `no_match` rows, the `input_dob` is a *different
real person's* real, verified DOB (documented in `source_notes`) -- a genuine identity
collision, not a fabricated one. `ground_truth_match`/`ground_truth_sentiment` reflect the
reasoning a careful human reviewer would reach -- this is the answer key the tool should be
evaluated against, not a model's own output.

## Category coverage: hand-curated set (16 categories, 26 cases)

| # | Category | Cases | Ground truth |
|---|----------|-------|---------------|
| 1 | Exact match, positive sentiment | 2 | match |
| 2 | Exact match, negative sentiment | 2 | match |
| 3 | Nickname / short form (Ted Kennedy) | 1 (was 2 -- Bill Clinton dropped, URL unreachable) | match |
| 4 | Middle name used/omitted (Obama, G.H.W. Bush) | 2 | match |
| 5 | Maiden vs. married name (H. Rodham Clinton, Jackie Bouvier Kennedy Onassis) | 2 | match |
| 6 | Transliteration variants (Gaddafi, bin Laden) | 2 | match |
| 7 | Name-order swap, native vs. Western order (Puskás, Abe Shinzo) | 2 | match |
| 8 | Common name + different real DOB -- false-positive trap (James Brown x2) | 1 (was 2 -- Chris Evans dropped, URL unreachable) | **no_match** |
| 9 | Common name, different profession entirely (Michael Jordan vs. Michael I. Jordan) | 1 | **no_match** |
| 10 | Diacritics/accents (Beyoncé) | 1 | match |
| 11 | Initials-only reference (JFK, AOC) | 2 | match |
| 12 | Suffix/title noise, should NOT block a true match (MLK Jr., Robert Downey Jr.) | 2 | match |
| 13 | Decoy relative -- input identifies the wrong family member (RFK Sr./Jr., George Foreman Sr./III) | 2 | **no_match** |
| 14 | DOB never stated, only age or birth year -- indirect reasoning required (Machado, Krasznahorkai) | 2 | match |
| 15 | Person mentioned but not the article's subject/focus -- sentiment must be scoped to them, not the article (Tim Cook/Foxconn) | 1 | match, sentiment neutral despite negative-toned article |
| 16 | Genuinely ambiguous: multiple real people share the identical literal name in the same family (George Foreman's 5 sons all named "George Edward Foreman") | 1 | **uncertain** |

Categories 8, 9, and 13 are the false-positive traps: identical or near-identical name
strings where the DOB proves it's a different person. Category 16 validates the "never
silently say no-match, route real ambiguity to human review" requirement.

## Category coverage: roster set (3 categories, 88 cases)

| # | Category | Cases | Ground truth |
|---|----------|-------|---------------|
| 19 | Roster organic match -- real person, real DOB, real live article | 84 (was 98 -- 14 dropped, URLs unreachable) | match |
| 20 | Roster namesake-collision trap -- a real different person shares the name, different real DOB | 3 | **no_match** |
| 21 | Pseudonym match -- article never uses the person's canonical name at all | 1 | match |

**The 25-person roster**, chosen to deliberately spread coverage:
- **Transliteration**: Volodymyr Zelenskyy, Recep Tayyip Erdoğan, Bashar al-Assad, Roman Abramovich
- **Native/surname-first name order**: Xi Jinping, Kim Jong Un
- **Patronymic/short-form naming**: Mohammed bin Salman ("MBS"), Jeff Bezos (Jeffrey), Bill Gates (William Henry Gates III)
- **Unusual own-name usage**: Liz Truss (legal first name is actually "Mary"), J.K. Rowling (also publishes as "Robert Galbraith"), Prince (mononym vs. legal name "Prince Rogers Nelson")
- **Regnal/religious name change**: Pope Francis (born Jorge Mario Bergoglio), King Charles III (born Charles Philip Arthur George)
- **Maiden/married name**: Angela Merkel (born Angela Dorothea Kasner)
- **Baseline heavy pos/neg coverage**: Elon Musk, Kamala Harris, Rishi Sunak, Malala Yousafzai, David Cameron, LeBron James, Taylor Swift, Vladimir Putin, Narendra Modi, Emmanuel Macron

Each person got 4 real articles pulled and WebFetch-confirmed live, deliberately varied
across positive/negative tone and formal/informal name usage where the real press coverage
allowed it (some figures, e.g. Putin/Abramovich, skew heavily negative in real coverage --
that skew was kept rather than forced into artificial balance).

**Namesake collision traps found (category 20)** -- all real, none constructed:
- **Bill Gates** (Microsoft founder, b. 1955-10-28) vs. **Bill Gates Sr.**, his real father,
  born ~30 years earlier
- **David Cameron** (UK PM, b. 1966-10-09) vs. a real Australian rules footballer of the same
  name (Geelong/Brisbane Bears), b. 1964-04-04
- One more real-namesake trap from the roster batches (see `dataset.json` rows tagged
  category 20 for the third)

Collision checks were also attempted for Erdoğan, Bashar al-Assad, and Narendra Modi but
**no clean real namesake was found** for any of them after real search effort -- skipped
rather than fabricated (documented as a gap below).

**Pseudonym case (category 21)**: J.K. Rowling -- two real, live articles about her Cormoran
Strike crime novels refer to the author only as "Robert Galbraith," never "Rowling" or "J.K.,"
while unambiguously being about the same real person (input DOB 1965-07-31, her real birth
name is Joanne Rowling). This is arguably the single hardest case in the dataset: zero lexical
overlap between input name and article name.

## Category coverage: name-form-variant set (1 category, 160 cases)

Purpose: the hand-curated and roster sets each test ONE specific messy-name challenge per
person (e.g. exactly one nickname case, one initials case). This pass instead asks, per
person: *how many different ways could someone plausibly type this person's name into the
tool, and does the matcher still recognize all of them as the same real person?* That's a much
closer match to real input variance than one example per category.

Variant types generated (not evenly distributed -- driven by what's actually real/documented
for each specific person):
- **Mechanical forms**: middle initial ("William J. Clinton"), all-initials ("W. J. Clinton"),
  no-middle-name ("Barack Obama"), inverted "Last, First" order, dropped/added diacritics
- **Real nicknames**: press nicknames (Bill, Ted, Jack, AOC, MLK, RDJ, King James), childhood
  nicknames (Barry Obama, Trey Gates, Poppy Bush)
- **Alternate transliterations**: Zelensky/Zelenskyy/Zelenskiy, Erdogan/Erdoğan,
  Gaddafi/al-Qaddafi/Khadafy, Kim Jong-un/Jong Eun/Jong Woon
- **Historical/birth names**: Michael King (MLK's birth name before 1934), Jeffrey Preston
  Jorgensen (Bezos's birth name before adoption), Jorge Mario Bergoglio (Pope Francis),
  Charles Philip Arthur George (King Charles III), Joanne Rowling (J.K. Rowling's real name)
- **Married/maiden combinations**: Hillary Rodham Clinton, Jacqueline Kennedy Onassis, Angela
  Kasner
- **Titles/mononyms**: Prince, Malala, President Xi, Prince Charles (his pre-2022 title)
- **The hardest case in the whole dataset**: `R-rowling-1-v4` pairs J.K. Rowling's real DOB
  with the input name **"Robert Galbraith"** (her actual pen name) against a real article that
  refers to her as "J.K. Rowling" throughout -- zero string overlap between input and article
  name in either direction, only resolvable by knowing the pseudonym connection.

**Verification caveat, distinct from the rest of this dataset**: DOBs and articles were
web-verified per-row as described above. The *name-form facts* in this augmentation pass
(middle names, nicknames, birth names) were **not independently re-verified via live web
search this session** -- they were generated from general biographical knowledge as
well-established public facts (e.g. "Bill Clinton" as a nickname for "William Jefferson
Clinton" needs no citation). This is a reasonable trade-off given the volume (164 rows), but
it is a lower verification bar than the rest of the dataset. If any specific variant will be
used in a way where being wrong matters (e.g. quoted in the exec demo as a "fact"), spot-check
it first -- `source_notes` on each row states the specific claim being relied on.

## Category coverage: moderate-fame set (1 category, 15 cases)

`category: "23_moderate_fame_organic_match"`, `source: "moderate_fame_roster"`. Added after a
validity concern was raised: the rest of the dataset is all globally famous people, and an LLM
matcher already has rich memorized biographical knowledge (often including the exact DOB) for
someone that famous -- so a correct verdict doesn't cleanly prove the pipeline reasoned from
the article's actual evidence rather than recalling training-data knowledge. This tier is
people notable enough for a real, live news article, but obscure enough that their DOB had to
be genuinely researched. Built in two passes (8 people, then 8 more requested to reach a
target of 20 -- research friction meant only 8 landed, see gap note below):

Marty Small Sr. (mayor, Atlantic City NJ), Reynaldo Aligada Jr. (MN Supreme Court
justice-designate), Bronna Kahle (nonprofit foundation president, former state legislator),
Milan Momcilovic (college basketball), Shannon O'Donnell (regional TV meteorologist), Aydar
Suniev (minor-league hockey prospect), Ashten Prechtel (WNBA role player), Kazumi Matsui
(mayor of Hiroshima, Japan), Dakota Luther (college swimmer), Ted Gonder (nonprofit CEO), Sarah
Gorham (poet/publisher), Stephen Dillard (Georgia Court of Appeals judge), Aristo Sham
(classical pianist, 2025 Van Cliburn Gold Medal), Scott Baker (former TV anchor, media
executive), Angie Paccione (Colorado state agency executive director).

Each row's `source_notes` documents the actual research trail (Wikipedia infobox, Ballotpedia,
a sports-roster page, etc.) as evidence against recall. Two rows (Baker, Paccione) use the
person's own Wikipedia article as the "article" source rather than third-party news, because
the original news sources Wikipedia cites were blocked or archive-only during research -- a
minor quality tradeoff (Wikipedia is more neutral/encyclopedic than news framing) worth knowing
if stress-testing sentiment on those two specifically.

Dropped candidates, none forced: a tenth original pick (Joshua Báez, a Cardinals rookie --
notable partly because MLB.com spells his name with the accent while ESPN's own headline drops
it, a real organic diacritics case) was dropped because the only article found for him doesn't
survive the fetch pipeline (ESPN is JS-rendered). An eleventh (Nicholas Bridle, NH state
representative) made it in initially but was later removed entirely: the only real article
about him is paywalled, and the fetch pipeline can only retrieve a short preview that cuts off
before his name -- the same "permanently unreachable, so drop it" reasoning already applied
elsewhere in this dataset (see "URL reachability filtering" above). Many other candidates (a
community bank CEO, an early-stage startup founder, an indie musician, several international
business executives, additional judges/officials) were dropped after real search effort found
no verifiable exact DOB, rather than approximating one -- international coverage in particular
stayed thin as a result (only 1 of an intended 4 non-US/UK picks survived).

## Gaps / what was skipped

- Reasonable search effort found **no real namesake collision** for Erdoğan, Bashar al-Assad,
  or Narendra Modi -- these remain match-only in the roster set. If you need more `no_match`
  density on foreign/transliterated names specifically, that's the gap to fill next, likely
  via constructed (not organic) examples since real collisions didn't turn up.
- A second authentic **diacritics** example and a second **"mentioned but not the subject"**
  example (hand-curated set) were not included for the same reason -- no clean second real
  case found, and fabricating one would violate the "real facts only" rule.
- Only one dedicated **"uncertain"** row (C16, the George Foreman sons) exists in the whole
  dataset. Genuine unresolvable real-world ambiguity is intrinsically rare among people
  notable enough to have public DOB records.
- **Disputed/inconsistent real-world DOBs**, documented rather than silently resolved:
  - Sam Bankman-Fried: sources disagree on March 5 vs. March 6, 1992
  - Muammar Gaddafi: year certain, exact day disputed
  - Kim Jong Un: North Korea says 1982-01-08, South Korean intelligence says 1983, US
    government/his aunt say 1984 -- the row uses 1984-01-08 (Wikipedia's listed value) with
    the full disagreement recorded in `source_notes`
  This is a useful reminder that "ground truth DOB" is not always a single clean value even
  for extremely well-documented public figures -- your matcher may need tolerance logic for
  near-miss DOBs (off by a year, or by a day) rather than exact-match-only.

## Suggested use

Run the actual matching/sentiment tool against each row's `input_name` + `input_dob` +
`article_url`, and score its output against `ground_truth_match` / `ground_truth_sentiment`.
Given the product requirement (zero false negatives, minimize false positives), pay special
attention to:
- Categories 8, 9, 13, 20: any "match" output here is a false positive.
- Category 16: an output of "match" or "no_match" (instead of routing to review) fails the
  spirit of the requirement even if it happens to guess right.
- Categories 3-7, 10-12, 14, 19, 21, 22: any "no_match" or "uncertain" output here is a false
  negative on identity resolution, which the product spec says must never happen. Categories
  19 and 22 are your largest volume categories (84 and 160 cases) and the closest to real
  deployment traffic -- category 22 in particular is the best signal on whether name
  normalization actually works across realistic input variance, not just the one example per
  failure mode the other categories give you.
- Category 21 (the Rowling/Galbraith case) and `R-rowling-1-v4` within category 22 (Rowling's
  real DOB paired with the input "Robert Galbraith") specifically test whether the matcher
  over-relies on name-string similarity vs. reasoning about identity from context -- a pure
  fuzzy-matching approach will fail both by construction, since there's zero string overlap to
  exploit.
