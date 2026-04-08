-- Initialize the comparisons table in PostgreSQL
-- This script runs automatically when the database container starts

CREATE TABLE IF NOT EXISTS comparisons (
    id SERIAL PRIMARY KEY,
    handles TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_comparisons_created_at ON comparisons(created_at DESC);
