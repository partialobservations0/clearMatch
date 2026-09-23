-- Normalized knowledge base of real people, their name variants, articles we've fetched,
-- entities extracted from those articles, and the eval test cases that link them together.
--
-- Identity key: date_of_birth. Two different real people with the same name string (e.g. the
-- UK PM David Cameron vs. the Australian footballer David Cameron) get two separate `people`
-- rows because their DOBs differ -- DOB, not name, is what actually identifies a person here,
-- which is the whole premise of the product this database supports.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS people (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date_of_birth   TEXT NOT NULL UNIQUE,   -- ISO date YYYY-MM-DD; the true identity key
    canonical_name  TEXT NOT NULL,          -- the most formal/complete name we have on file
    source          TEXT,                   -- hand_curated | wikipedia_roster
    source_notes    TEXT,                   -- how the DOB/identity was originally verified
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS name_variants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    variant_name    TEXT NOT NULL,
    variant_type    TEXT,                   -- nickname, initials, inverted, transliteration,
                                             -- pseudonym, historical_birth_name, original, etc.
    note            TEXT,
    UNIQUE(person_id, variant_name)
);

CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,
    title           TEXT,
    full_text       TEXT,                   -- populated by scripts/fetch_articles_to_db.py
    published_date  TEXT,
    fetched_at      TEXT,
    fetch_error     TEXT                    -- non-null if the fetch failed (see src/pipeline.py);
                                             -- NEVER treat a row with fetch_error set as if it
                                             -- had no content -- that's a pipeline failure, not
                                             -- evidence about the article itself
);

CREATE TABLE IF NOT EXISTS extracted_entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    entity_name     TEXT NOT NULL,
    entity_type     TEXT NOT NULL,          -- PERSON, ORGANIZATION, LOCATION, DATE, OTHER
    note            TEXT,                   -- brief context, e.g. "co-founder mentioned alongside subject"
    extracted_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_cases (
    id                      TEXT PRIMARY KEY,   -- original dataset.json row id, e.g. "R-truss-1-v2"
    person_id               INTEGER REFERENCES people(id),   -- resolved via input_dob
    article_id              INTEGER NOT NULL REFERENCES articles(id),
    input_name              TEXT NOT NULL,      -- exact name string used as input for this case
    category                TEXT,
    ground_truth_match      TEXT,               -- match | no_match | uncertain
    ground_truth_sentiment  TEXT,
    why_its_tricky          TEXT,
    variant_of              TEXT,               -- original dataset field, nullable
    variant_type            TEXT
);

-- Caches every Claude verdict call by the exact inputs that produced it (name, DOB, article
-- text, model, prompt version). Re-running the eval (e.g. after fixing an unrelated fetch bug)
-- must not re-pay for API calls whose answer can't have changed -- only rows with no cache
-- entry, or whose prompt/model version changed, actually hit the API again.
CREATE TABLE IF NOT EXISTS match_cache (
    cache_key       TEXT PRIMARY KEY,      -- sha256 of (input_name, input_dob, article_title,
                                            -- article_text, model, prompt_version)
    response_json   TEXT NOT NULL,         -- serialized MatchResult fields
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_name_variants_person ON name_variants(person_id);
CREATE INDEX IF NOT EXISTS idx_name_variants_name ON name_variants(variant_name);
CREATE INDEX IF NOT EXISTS idx_entities_article ON extracted_entities(article_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_person ON test_cases(person_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_article ON test_cases(article_id);
