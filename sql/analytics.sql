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

-- ---------------------------------------------------------------------------
-- Who asked, and what we could not see before.
--
-- Additive, and nothing here identifies a person. device_id is a random value the app
-- makes on first launch and can throw away; it answers "how many people" rather than
-- "how many searches", which is the first question any operator or planner asks. client
-- says which front end asked. cached marks a search the app answered from its own saved
-- copy and told us about afterwards - without it a commuter checking the same trip every
-- morning looks like one search ever, which biases exactly the number worth selling.
ALTER TABLE search_analytics ADD COLUMN IF NOT EXISTS device_id TEXT;
ALTER TABLE search_analytics ADD COLUMN IF NOT EXISTS client    TEXT;
ALTER TABLE search_analytics ADD COLUMN IF NOT EXISTS cached    BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_search_analytics_device ON search_analytics(device_id);

-- What people look for, including what they never found.
--
-- Stop and place search runs against the copy of the stop list on the phone, so none of
-- it reached us: "most searched places" could only count places that got as far as a
-- journey search. What somebody typed and abandoned is the more interesting half - it is
-- where the network is missing, or where our names do not match what people call things.
CREATE TABLE IF NOT EXISTS place_search (
    id             BIGSERIAL PRIMARY KEY,
    device_id      TEXT,
    client         TEXT,
    query          TEXT        NOT NULL,   -- what was typed, trimmed to 40 characters
    result_count   INTEGER     NOT NULL DEFAULT 0,
    chosen_stop_id INTEGER,                -- null when nothing was picked
    searched_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_place_search_at    ON place_search(searched_at);
CREATE INDEX IF NOT EXISTS idx_place_search_query ON place_search(lower(query));
