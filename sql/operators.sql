-- Multi-operator support: who runs a route, and which places are the same place.
--
-- Applied on top of schema.sql against a database that already holds Golden Arrow, so
-- every statement is idempotent and every existing row is backfilled to Golden Arrow
-- before anything is made NOT NULL. Nothing here changes what the planner returns for
-- the data already loaded.

CREATE TABLE IF NOT EXISTS operator (
    id    SERIAL PRIMARY KEY,
    code  TEXT NOT NULL UNIQUE,        -- 'gabs', 'metrorail' - matches the web app's mode ids
    name  TEXT NOT NULL,               -- 'Golden Arrow Buses'
    kind  TEXT NOT NULL                -- 'bus' | 'train'
);

INSERT INTO operator (code, name, kind) VALUES
    ('gabs',      'Golden Arrow Buses', 'bus'),
    ('metrorail', 'Metrorail',          'train')
ON CONFLICT (code) DO NOTHING;

-- Every route belongs to an operator. Existing routes are Golden Arrow by definition:
-- they are the only ones that have ever been loaded.
ALTER TABLE route ADD COLUMN IF NOT EXISTS operator_id INTEGER REFERENCES operator(id);
UPDATE route SET operator_id = (SELECT id FROM operator WHERE code = 'gabs')
 WHERE operator_id IS NULL;

-- Same for stops. A train station and a bus stop are different places even when they
-- share a name, so the operator has to be part of what makes a stop unique.
ALTER TABLE stop ADD COLUMN IF NOT EXISTS operator_id INTEGER REFERENCES operator(id);
UPDATE stop SET operator_id = (SELECT id FROM operator WHERE code = 'gabs')
 WHERE operator_id IS NULL;

-- Swap UNIQUE(name) for UNIQUE(name, operator_id).
--
-- Without this, loading Metrorail would collide on the day it reached a station sharing a
-- name with a bus stop - CAPE TOWN, BELLVILLE, RETREAT and a dozen others - and the
-- collision would be silent: ON CONFLICT (name) DO UPDATE would quietly hand the train
-- the bus stop's id and hang train times off a bus stop.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'stop_name_key') THEN
        ALTER TABLE stop DROP CONSTRAINT stop_name_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'stop_name_operator_key') THEN
        ALTER TABLE stop ADD CONSTRAINT stop_name_operator_key UNIQUE (name, operator_id);
    END IF;
END $$;

-- Places you can walk between.
--
-- Cape Town station and the Cape Town bus terminus are a few minutes apart on foot. They
-- are not the same stop - merging them would imply stepping off a train straight onto a
-- bus, and there is only one place to put the map pin - but a journey planner has to know
-- the walk exists or it can never join a train to a bus.
--
-- Stored once per pair, lower id first, so there is exactly one row for a link.
CREATE TABLE IF NOT EXISTS stop_interchange (
    a_stop_id     INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    b_stop_id     INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    walk_minutes  INTEGER,             -- NULL where nobody has measured it yet
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (a_stop_id, b_stop_id),
    CHECK (a_stop_id < b_stop_id)
);

-- A route belongs to an operator too.
--
-- Stops were made unique per operator above, and routes were left globally unique, which
-- is an inconsistency with teeth: the loader upserts a route by name, so the day a train
-- line and a bus route are called the same thing, the bus route is silently reassigned to
-- the train operator and 793 becomes 792. Nothing collides today - Golden Arrow writes
-- "AIRPORT IND-BELLVILLE" and Metrorail writes "RETREAT - CAPE TOWN" - but "nothing
-- collides today" is not a constraint, and MyCiTi is the next operator to arrive.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'route_name_key') THEN
        ALTER TABLE route DROP CONSTRAINT route_name_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'route_name_operator_key') THEN
        ALTER TABLE route ADD CONSTRAINT route_name_operator_key UNIQUE (name, operator_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS stop_operator_idx ON stop (operator_id);
CREATE INDEX IF NOT EXISTS route_operator_idx ON route (operator_id);

-- A train has a number printed against its column ("0100"), and a rider looking at a
-- platform indicator wants it. Golden Arrow trips carry no equivalent, so this is null
-- for every bus and the planner simply shows nothing where there is nothing.
ALTER TABLE trip ADD COLUMN IF NOT EXISTS label TEXT;

-- Which networks actually reach a place, by operator rather than by kind.
--
-- The search box narrows its suggestions to the operator a rider has chosen, and until
-- now that question was answered per KIND: served_bus and served_train. Two bus operators
-- make that answer wrong in both directions. A place in Atlantis that only MyCiTi reaches
-- is served_bus, so choosing Golden Arrow offers it and then finds no journey; a place
-- only Golden Arrow reaches is offered under MyCiTi for the same reason. It is the fault
-- the kind columns were added to prevent, reappearing one operator later.
--
-- So the fact is stored as what it is: this place, that operator. The kind columns stay,
-- derived from this, because /api/areas and the loaders still read them.
CREATE TABLE IF NOT EXISTS area_service (
    area_id     INTEGER NOT NULL REFERENCES area(id) ON DELETE CASCADE,
    operator_id INTEGER NOT NULL REFERENCES operator(id) ON DELETE CASCADE,
    PRIMARY KEY (area_id, operator_id)
);

CREATE INDEX IF NOT EXISTS area_service_operator_idx ON area_service (operator_id);
