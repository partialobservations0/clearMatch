# nameRecognition -- entity resolution + sentiment matcher
#
# Builds the knowledge-base DB (people/name_variants) from data/dataset.json at image build
# time -- this needs no network access (pure local generation + inserts), so it's fully
# reproducible. It does NOT pre-fetch article full_text (that requires live network calls and
# is only needed for eval/run_eval.py's dataset scoring, not for a live single-query match) --
# real usage fetches whatever URL you pass at query time, fresh, same as running locally.
#
# Build:
#   docker build -t namerecognition .
# Run a single match (requires ANTHROPIC_API_KEY -- never bake this into the image):
#   docker run --rm -e ANTHROPIC_API_KEY=sk-ant-... namerecognition \
#       "Simone Biles" "1997-03-14" "https://example.com/article"
# Run the local test suite (no API key needed):
#   docker run --rm --entrypoint python3 namerecognition -m pytest tests/ -v

FROM python:3.12-slim

WORKDIR /app

# Install Python deps first so this layer caches across code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code and data
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY db/schema.sql ./db/schema.sql
COPY eval/ ./eval/
COPY tests/ ./tests/

# Build the knowledge base (people + name_variants) at image build time. No network calls --
# pure local generation from data/dataset.json, so this is fully reproducible.
RUN python3 scripts/migrate_dataset_to_db.py \
    && python3 scripts/add_aliases.py \
    && python3 scripts/add_aliases_2.py \
    && python3 scripts/generate_all_variants.py

ENTRYPOINT ["python3", "src/match.py"]
