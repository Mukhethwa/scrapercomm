-- The places a rider can name, held locally instead of asked of a stranger.
--
-- Applied on top of schema.sql and operators.sql. Idempotent, and it changes nothing that
-- is already loaded: this is a new table and a new source for one endpoint.
--
-- Why it exists. /api/geocode asked OpenStreetMap Nominatim on every pause in typing.
-- Nominatim's usage policy is one request a second for the whole application, which is
-- fine for one developer and impossible for a public app - ten people typing at once
-- breaches it, and a blocked geocoder does not report itself as blocked. It reports every
-- place in Cape Town as not existing, which is exactly what happened to WOODSTOCK and
-- SALT RIVER during an audit that ran 122 lookups back to back.
--
-- It also cannot do the thing a search box most needs. Nominatim matches whole words, so
-- "woodst" finds nothing at all, while the stop list - which is local - completes it
-- happily. Holding the areas locally makes the two behave alike.
--
-- The rows come from one Overpass query for the place nodes inside the Cape Town bounding
-- box, so this is a few hundred rows fetched once rather than a request per keystroke
-- forever. See gabs_scraper.areas.

CREATE TABLE IF NOT EXISTS area (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,        -- 'Woodstock'
    kind        TEXT NOT NULL,        -- OSM place=: suburb, town, city, village...
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    full_name   TEXT,                 -- 'Woodstock, Cape Town, Western Cape, South Africa'
    -- Every other spelling a rider might type, lowercased and comma-separated.
    -- Golden Arrow and OSM both write GUGULETU; the standard spelling is Gugulethu, and
    -- somebody typing it should not be told their township does not exist.
    aliases     TEXT NOT NULL DEFAULT '',
    -- Whether any service actually reaches it. An area nothing serves is a place, not a
    -- journey, and offering it means a rider chooses it and gets an empty screen.
    served      BOOLEAN NOT NULL DEFAULT FALSE,
    osm_id      BIGINT UNIQUE,
    scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Searching is by prefix and by substring, case-insensitively, over both the name and the
-- aliases - the same way the stop search behaves, because a rider cannot tell which of the
-- two lists a name lives in.
CREATE INDEX IF NOT EXISTS area_name_lower ON area (lower(name));
CREATE INDEX IF NOT EXISTS area_served ON area (served) WHERE served;
