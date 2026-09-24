# clearMatch
Full setup detail (prerequisites, Docker vs. local venv): see `SETUP.md`.

## Quick start (Docker)

```bash
docker build -t namerecognition .
docker run --rm -e ANTHROPIC_API_KEY=sk-ant-... namerecognition \
    "Simone Biles" "1997-03-14" "https://example.com/some-article"
```

## 5 example commands

```bash
# 1. Build the knowledge-base DB from data/dataset.json (run once, or after changing the dataset)
python3 scripts/migrate_dataset_to_db.py

# 2. Run a single match query against a real article
python3 src/match.py "Elon Musk" "1971-06-28" "https://www.aljazeera.com/economy/2026/6/12/spacex-ipo-debuts-in-us-markets-musk-becomes-worlds-first-trillionaire"

# 3. Run the same query via Docker instead (no local Python setup needed)
docker run --rm -e ANTHROPIC_API_KEY=sk-ant-... namerecognition \
    "Narendra Modi" "1950-09-17" "https://www.newsonair.gov.in/pm-narendra-modi-says-2025-to-be-remembered-as-year-of-reforms-for-india"

# 4. Run the local test suite (no API key needed)
python3 -m pytest tests/ -v

# 5. Run a small sample of the eval harness against the labeled dataset
python3 eval/run_eval.py --sample 20
```

See `SETUP.md` for the full setup guide, including the local (non-Docker) environment setup, the
full DB-build pipeline, and running the complete eval.
