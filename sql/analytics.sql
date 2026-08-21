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

-- One row per journey option a search returned, so route demand is answerable:
-- search_analytics alone records HOW MANY options came back, not WHICH.
CREATE TABLE IF NOT EXISTS search_analytics_option (
    id               BIGSERIAL PRIMARY KEY,
    search_id        BIGINT NOT NULL REFERENCES search_analytics(id) ON DELETE CASCADE,
    timetable_number TEXT,               -- '004401', the physical service
    route_label      TEXT,               -- 'NYANGA - AIRPORT IND - BELLVILLE'
    day_type         TEXT,               -- WEEKDAY|SATURDAY|SUNDAY|PUBLIC_HOLIDAY|OTHER
    departure_count  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sao_search    ON search_analytics_option(search_id);
CREATE INDEX IF NOT EXISTS idx_sao_timetable ON search_analytics_option(timetable_number);
CREATE INDEX IF NOT EXISTS idx_sao_label     ON search_analytics_option(route_label);
