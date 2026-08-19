-- GABS timetable scraper — PostgreSQL schema
-- Normalized (GTFS-flavored) model. Idempotent: safe to re-apply.

CREATE TABLE IF NOT EXISTS route (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,      -- 'AIRPORT IND-BELLVILLE'
    origin        TEXT,
    destination   TEXT,
    letter_group  TEXT,                       -- 'A'..'W'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per PDF "version" (unique filename encodes route + dates + number + PH).
CREATE TABLE IF NOT EXISTS timetable (
    id                SERIAL PRIMARY KEY,
    route_id          INTEGER NOT NULL REFERENCES route(id) ON DELETE CASCADE,
    timetable_number  TEXT,                   -- '004401'
    is_public_holiday BOOLEAN NOT NULL DEFAULT FALSE,
    effective_from    DATE,
    effective_to      DATE,                   -- NULL = open-ended (99999999)
    pdf_url           TEXT,
    pdf_filename      TEXT NOT NULL UNIQUE,
    pdf_sha256        TEXT,
    page_count        INTEGER,
    raw_text          TEXT,                   -- fallback / re-parse source
    parse_status      TEXT NOT NULL DEFAULT 'pending',  -- pending|parsed|failed
    parse_error       TEXT,
    scraped_at        TIMESTAMPTZ,
    parsed_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS stop (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,      -- 'NYANGA TERM', 'BELLVILLE'
    lat            DOUBLE PRECISION,          -- filled by gabs_scraper.geocode
    lon            DOUBLE PRECISION,
    geocoded_at    TIMESTAMPTZ,
    geocode_source TEXT
);

-- A (direction, day-type) block within a timetable.
CREATE TABLE IF NOT EXISTS schedule (
    id                     SERIAL PRIMARY KEY,
    timetable_id           INTEGER NOT NULL REFERENCES timetable(id) ON DELETE CASCADE,
    page_number            INTEGER,
    direction_index        INTEGER,
    direction_label        TEXT,             -- 'NYANGA - AIRPORT IND - BELLVILLE'
    day_type               TEXT,             -- WEEKDAY|SATURDAY|SUNDAY|PUBLIC_HOLIDAY|OTHER
    day_label              TEXT,             -- raw header e.g. 'MONDAYS TO FRIDAYS'
    section_timetable_number TEXT,           -- per-page TT number (PH PDFs bundle routes)
    section_effective_date DATE,
    no_service             BOOLEAN NOT NULL DEFAULT FALSE
);

-- Ordered stops (grid rows) of a schedule.
CREATE TABLE IF NOT EXISTS schedule_stop (
    id             SERIAL PRIMARY KEY,
    schedule_id    INTEGER NOT NULL REFERENCES schedule(id) ON DELETE CASCADE,
    stop_id        INTEGER NOT NULL REFERENCES stop(id),
    stop_sequence  INTEGER NOT NULL,
    UNIQUE (schedule_id, stop_sequence)
);

-- A trip (grid column = one bus run) of a schedule.
CREATE TABLE IF NOT EXISTS trip (
    id           SERIAL PRIMARY KEY,
    schedule_id  INTEGER NOT NULL REFERENCES schedule(id) ON DELETE CASCADE,
    trip_index   INTEGER NOT NULL,
    note_codes   TEXT[],
    UNIQUE (schedule_id, trip_index)
);

-- A cell: the time (or via/none) for a (trip, stop).
CREATE TABLE IF NOT EXISTS stop_time (
    id               SERIAL PRIMARY KEY,
    trip_id          INTEGER NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
    schedule_stop_id INTEGER NOT NULL REFERENCES schedule_stop(id) ON DELETE CASCADE,
    cell_type        TEXT NOT NULL,          -- TIME|VIA|NONE
    departure_time   TIME,                    -- set when cell_type='TIME'
    note_code        TEXT,
    raw_value        TEXT,
    UNIQUE (trip_id, schedule_stop_id)
);

-- Footnote codes (a -> 'Mondays,Tuesdays,...').
CREATE TABLE IF NOT EXISTS timetable_note (
    id            SERIAL PRIMARY KEY,
    timetable_id  INTEGER NOT NULL REFERENCES timetable(id) ON DELETE CASCADE,
    code          TEXT NOT NULL,
    description   TEXT,
    UNIQUE (timetable_id, code)
);

-- Real road path of each leg (consecutive timing-point pair), for matching
-- "unofficial" stops a bus passes. Populated by gabs_scraper.geometry.
CREATE TABLE IF NOT EXISTS leg_geometry (
    from_stop_id INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    to_stop_id   INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    path         JSONB,               -- [[lat,lon], ...] real driving path
    length_m     DOUBLE PRECISION,
    min_lat DOUBLE PRECISION, min_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION, max_lon DOUBLE PRECISION,
    source       TEXT,
    fetched_at   TIMESTAMPTZ,
    PRIMARY KEY (from_stop_id, to_stop_id)
);

CREATE INDEX IF NOT EXISTS idx_route_name           ON route(name);
CREATE INDEX IF NOT EXISTS idx_timetable_route      ON timetable(route_id);
CREATE INDEX IF NOT EXISTS idx_timetable_number     ON timetable(timetable_number);
CREATE INDEX IF NOT EXISTS idx_timetable_status     ON timetable(parse_status);
CREATE INDEX IF NOT EXISTS idx_schedule_timetable   ON schedule(timetable_id);
CREATE INDEX IF NOT EXISTS idx_schedule_daytype     ON schedule(day_type);
CREATE INDEX IF NOT EXISTS idx_sched_stop_schedule  ON schedule_stop(schedule_id);
CREATE INDEX IF NOT EXISTS idx_sched_stop_stop      ON schedule_stop(stop_id);
CREATE INDEX IF NOT EXISTS idx_trip_schedule        ON trip(schedule_id);
CREATE INDEX IF NOT EXISTS idx_stop_time_trip       ON stop_time(trip_id);
CREATE INDEX IF NOT EXISTS idx_stop_time_schedstop  ON stop_time(schedule_stop_id);
CREATE INDEX IF NOT EXISTS idx_stop_time_departure  ON stop_time(departure_time);
