-- CF Compare v2 — Full database schema with authentication
-- Runs automatically on first DB container start

-- ─── Authenticated Users ────────────────────────────────────────────────
-- Renamed from "users" to "cf_users" to avoid confusion with CF handles.
CREATE TABLE IF NOT EXISTS cf_users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ─── Tracked CF Handles (optional catalog) ──────────────────────────────
CREATE TABLE IF NOT EXISTS cf_handles (
    id SERIAL PRIMARY KEY,
    handle TEXT UNIQUE NOT NULL,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ─── Comparisons (each comparison session, tied to a user) ──────────────
CREATE TABLE IF NOT EXISTS comparisons (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES cf_users(id) ON DELETE CASCADE,
    handles TEXT NOT NULL,                    -- comma-separated handles
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ─── Comparison Results (per-user stats per comparison) ──────────────────
CREATE TABLE IF NOT EXISTS comparison_results (
    id SERIAL PRIMARY KEY,
    comparison_id INTEGER NOT NULL REFERENCES comparisons(id) ON DELETE CASCADE,
    handle TEXT NOT NULL,
    rating INTEGER,
    rank TEXT,
    max_rating INTEGER,
    max_rank TEXT,
    solved_count INTEGER DEFAULT 0,
    -- Rating history stored as JSON array: [{"contestName":"...", "newRating":1500, ...}]
    rating_history JSONB DEFAULT '[]'::jsonb,
    -- Tag analysis stored as JSON object: {"dp": 20, "graphs": 15}
    tag_stats JSONB DEFAULT '{}'::jsonb
);

-- ─── LLM Insights ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS insights (
    id SERIAL PRIMARY KEY,
    comparison_id INTEGER NOT NULL REFERENCES comparisons(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ─── Indexes ─────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_comparisons_user_id ON comparisons(user_id);
CREATE INDEX IF NOT EXISTS idx_comparisons_created_at ON comparisons(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comparison_results_comparison_id ON comparison_results(comparison_id);
CREATE INDEX IF NOT EXISTS idx_insights_comparison_id ON insights(comparison_id);
CREATE INDEX IF NOT EXISTS idx_comparison_results_handle ON comparison_results(handle);
