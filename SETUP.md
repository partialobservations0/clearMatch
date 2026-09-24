# Setup & Running

Two ways to run this: Docker (fastest way to try it, no local Python setup) or a local venv
(better if you're actively developing/modifying the code).

## Prerequisites

- An Anthropic API key (console.anthropic.com -> Settings -> API Keys).
- Docker, **or** Python 3.10+ if running locally without Docker.

## Option A: Docker (recommended for a quick check)

```bash
# Build the image (builds the knowledge-base DB from data/dataset.json at build time --
# no network access needed for this step, fully reproducible)
docker build -t namerecognition .

# Run a single match query. Never bake your API key into the image -- pass it at run time.
docker run --rm -e ANTHROPIC_API_KEY=sk-ant-... namerecognition \
    "Simone Biles" "1997-03-14" "https://example.com/some-article"

# Run the local test suite (no API key needed -- pure local logic)
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
# name-variant generator changes). Note: match.py also generates mechanical/nickname variants
# LIVE for any query, cataloged or not -- this offline build only affects people already known
# to the DB (grounding context, collision warnings), not the live per-query fallback coverage.
python3 scripts/migrate_dataset_to_db.py
python3 scripts/fetch_articles_to_db.py   # network calls -- fetches real article text for eval
python3 scripts/add_aliases.py
python3 scripts/add_aliases_2.py
python3 scripts/generate_all_variants.py

# Run a single match query
python3 src/match.py "Simone Biles" "1997-03-14" "https://example.com/some-article"

# Run the local test suite
python3 -m pytest tests/ -v
```

## Running the full eval

```bash
python3 eval/run_eval.py                          # full dataset (272 rows)
python3 eval/run_eval.py --sample 30               # smaller subset
python3 eval/run_eval.py --category 20_roster_namesake_collision_trap  # just one category
```

Re-running after a small code/prompt change re-uses identical `(name, DOB, article, model,
prompt version, db context)` answers already recorded in `src/match_cache.py`, rather than
re-querying the API for rows that were already answered.

## Known open items

- `db/extracted_entities` table exists in the schema but is intentionally unpopulated.
- The systematic name-variant generator (`src/name_variants.py`) assumes Western first/last name
  order and can mis-parse a surname-first name it hasn't seen a hand-curated alias for.
