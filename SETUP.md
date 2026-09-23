# Setup & Running

Two ways to run this: Docker (fastest way to try it, no local Python setup) or a local venv
(better if you're actively developing/modifying the code).

## Prerequisites

- An Anthropic API key with available credits (console.anthropic.com -> Settings -> Billing).
  This is billed separately from a Claude.ai/Claude Code subscription -- see "API costs" below.
- Docker, **or** Python 3.10+ if running locally without Docker.

## Option A: Docker (recommended for a quick check)

```bash
# Build the image (builds the knowledge-base DB from data/dataset.json at build time --
# no network access needed for this step, fully reproducible)
docker build -t namerecognition .

# Run a single match query. Never bake your API key into the image -- pass it at run time.
docker run --rm -e ANTHROPIC_API_KEY=sk-ant-... namerecognition \
    "Simone Biles" "1997-03-14" "https://example.com/some-article"

# Run the local test suite (no API key needed, no API cost -- pure local logic)
docker run --rm --entrypoint python3 namerecognition -m pytest tests/ -v
```

The container fetches whatever article URL you pass at query time fresh over the network, same
as running locally -- only the knowledge-base DB (people/name aliases) is baked in at build
time.

## Option B: Local Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create .env with your API key -- do NOT type the key directly into a chat/terminal session
# you don't control; create the file yourself.
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Build the knowledge-base DB (run once, and again any time data/dataset.json or the
# name-variant generator changes)
python3 scripts/migrate_dataset_to_db.py
python3 scripts/fetch_articles_to_db.py   # network calls -- fetches real article text for eval
python3 scripts/add_aliases.py
python3 scripts/add_aliases_2.py
python3 scripts/generate_all_variants.py

# Run a single match query
python3 src/match.py "Simone Biles" "1997-03-14" "https://example.com/some-article"

# Run the local test suite (no API cost)
python3 -m pytest tests/ -v
```

## Running the full eval (costs real money)

```bash
python3 eval/run_eval.py                          # full 290-row dataset, ~$3-5, has a
                                                    # --max-cost $10 default safety cap
python3 eval/run_eval.py --sample 30               # cheap sanity check first (~$0.30-0.50)
python3 eval/run_eval.py --category 20_roster_namesake_collision_trap  # just one category
```

Re-running after a small code/prompt change is much cheaper than the first run -- identical
`(name, DOB, article, model, prompt version, db context)` inputs are served from
`src/match_cache.py`'s cache for $0. See `README.md` -> "Cost controls" for details, and set a
hard spend limit in the Anthropic Console as a backstop independent of this code.

## API costs

The Anthropic **API** (what this project calls) is billed separately from a Claude.ai/Claude
Code chat subscription -- a Pro/Max plan does not include API credits. Add credits at
console.anthropic.com -> Settings -> Billing.

## Known open items (see README.md for full detail)

- The foreign-language pre-check fix (`knowledge_base.looks_non_latin_script`) is logic-verified
  but has not yet been tested against a live API call -- do this first with a small `--sample`
  run before trusting it at scale.
- `db/extracted_entities` table exists in the schema but is intentionally unpopulated --
  populating it requires its own API-cost decision (not yet made).
- See `ENRICHMENT_PLAN.md` for a planning-only (not implemented) design for automatically
  researching missing disambiguating details via additional web search.
