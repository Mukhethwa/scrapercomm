-- Additive ONLY. Nothing here touches a table the Python scraper owns.
-- Mirrored at sql/analytics.sql so it can also be applied out-of-band.
CREATE TABLE IF NOT EXISTS search_analytics (
    id            BIGSERIAL PRIMARY KEY,
    endpoint      TEXT        NOT NULL,          -- '/api/plan' | '/api/journeys'
    from_kind     TEXT,                          -- 'stop' | 'pin'
    from_stop_id  INTEGER,
    from_lat      DOUBLE PRECISION,
    from_lon      DOUBLE PRECISION,
    to_kind       TEXT,
    to_stop_id    INTEGER,
    to_lat        DOUBLE PRECISION,
    to_lon        DOUBLE PRECISION,
    option_count  INTEGER     NOT NULL DEFAULT 0,
    duration_ms   BIGINT,
    searched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_analytics_searched_at ON search_analytics(searched_at);
CREATE INDEX IF NOT EXISTS idx_search_analytics_endpoint    ON search_analytics(endpoint);
