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

-- ---------------------------------------------------------------------------
-- What the admin dashboard needs: when a reload last ran, and when one is wanted.
--
-- The refresh scripts write a run row so "when was this last loaded, and did it work"
-- is a question the dashboard can answer rather than a log somebody has to find. The
-- button on the dashboard writes a request; the scheduled script picks it up at its next
-- run and marks it done. Nothing here executes anything by itself - a web page that can
-- start a process on the server is a bigger door than this needs.
CREATE TABLE IF NOT EXISTS refresh_run (
    id          BIGSERIAL PRIMARY KEY,
    operators   TEXT        NOT NULL,          -- 'gabs myciti metrorail'
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    ok          BOOLEAN,                       -- null while running
    detail      TEXT,                          -- which steps failed, or what was stale
    log_path    TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_run_started ON refresh_run(started_at DESC);

CREATE TABLE IF NOT EXISTS refresh_request (
    id           BIGSERIAL PRIMARY KEY,
    operators    TEXT        NOT NULL,         -- 'all', or one operator's code
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    requested_by TEXT,                         -- whoever was signed in to the dashboard
    done_at      TIMESTAMPTZ,
    run_id       BIGINT REFERENCES refresh_run(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_refresh_request_pending
    ON refresh_request(requested_at) WHERE done_at IS NULL;

-- ---------------------------------------------------------------------------
-- Crashes and errors, reported to us rather than to somebody else.
--
-- The privacy policy promises riders "no third-party trackers and no analytics SDKs",
-- which rules out Sentry, Crashlytics and the rest - and they are how most apps learn
-- they are broken. Without something, the first news of a crash is a one-star review.
--
-- So the app reports its own uncaught errors here, through the same switch and the same
-- anonymous id as everything else: no name, no account, and nothing from the screen the
-- rider was on beyond where in the code it broke.
CREATE TABLE IF NOT EXISTS app_error (
    id          BIGSERIAL PRIMARY KEY,
    device_id   TEXT,
    client      TEXT,                          -- 'app' | 'web'
    app_version TEXT,
    platform    TEXT,                          -- 'android' | 'ios' | 'web'
    kind        TEXT        NOT NULL,          -- 'flutter' | 'zone' | 'api'
    message     TEXT        NOT NULL,
    where_at    TEXT,                          -- the top frames, trimmed
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_error_at      ON app_error(happened_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_error_message ON app_error(left(message, 120));
