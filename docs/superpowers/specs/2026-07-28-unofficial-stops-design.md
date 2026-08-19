# Unofficial Stops (road-geometry corridor matching) — Design

**Date:** 2026-07-28
**Status:** Approved

## Problem

Timetables list only **timing points**. Between two consecutive timing points a bus
drives real roads and passes many physical stops that are absent from the data (no
coords, no names, no road path). A rider boarding at such an "unofficial" stop (e.g.
Woodstock, on the Cape Town↔Mowbray leg) can't currently be served.

## Approach (approved)

Infer "a bus passes near point P" using the **real road path** of each leg (pair of
consecutive timing points), obtained once from **Google Directions** (driving). Match a
rider's pin to legs whose road path passes within a tight threshold, interpolate an
**approximate** time, and only ever match between consecutive timing points on trips
that already run — never inventing a route.

Runtime pin input uses **map-click or OpenStreetMap/Nominatim place search** (no Google
at runtime). Google is used **only** for the one-time geometry precompute; the key is
deleted afterward and never stored in the project/DB/dump/git.

## Scale

1,041 distinct ordered legs → 1,041 Directions calls (one-time, cached). Well within the
user's free quota.

## Data model

```
leg_geometry(
  from_stop_id int REFERENCES stop(id),
  to_stop_id   int REFERENCES stop(id),
  path         jsonb,               -- [[lat,lon], ...] real road path (driving)
  length_m     double precision,
  min_lat, min_lon, max_lat, max_lon double precision,  -- bbox for prefilter
  source       text,                -- 'google:directions'
  fetched_at   timestamptz,
  PRIMARY KEY (from_stop_id, to_stop_id)
)
```

Stored as plain JSON (no PostGIS) so the shared dump still restores on stock postgres:16.

## Components

- `geometry.py` — `precompute()`: distinct legs → Google Directions → decode polyline →
  store path + length + bbox. Skips already-fetched; re-runnable.
- `geo.py` — pure geo math: `haversine_m`, `point_to_segment_m`, `locate_on_path(path,
  length_m, lat, lon) -> (distance_m, fraction_f)`.
- `api.py`:
  - `locate_point(conn, lat, lon, threshold_m=250)` — legs whose road path passes within
    threshold, with fraction f.
  - Anchor model: an endpoint (a named stop OR a pin) resolves to a set of trip
    touch-points `(schedule_id, trip_index, position, time, exact|approx)`. A stop →
    position = stop_sequence, exact time. A pin on leg (A,B) with fraction f → position =
    seq_A + f, time = interpolate(time_A, time_B, f), approx.
  - A journey exists on a trip when board.position < alight.position and times are
    consistent. Grouped by physical service (timetable number + direction + day-type),
    departures deduped — same as the existing planner.
  - Endpoints accept `from`/`to` as a stop id OR `from_lat,from_lon`/`to_lat,to_lon`.
  - `GET /api/reachable_point?lat=&lon=` — destinations reachable when boarding at a pin.

## UI (Plan a trip)

From/To each gain a "📍 place/pin" mode: search a place (Nominatim) or click the map to
drop a pin. Matched unofficial points show a "≈ passes near here, ~HH:MM" label; the map
shows the pin snapped onto the real road line.

## Guarantee & honesty

- Only match within ~250 m of a road a bus already drives, between consecutive timing
  points, on trips that already run.
- Unofficial times are interpolated and clearly labeled approximate (≈).
- Still **direct buses only** (no transfers), consistent with the current planner.

## Testing

- `geo.py` unit tests: point-to-segment distance; `locate_on_path` on the Cape
  Town→Mowbray leg with a Woodstock point → small distance + plausible fraction.
- Endpoint smoke test: a pin near Woodstock yields Cape Town→Mowbray-corridor services
  with approximate board times, and reachable destinations toward Mowbray/Makhaza.

## Key handling

Same discipline as prior geocoding: key from `GOOGLE_MAPS_API_KEY` env only, stored
out-of-tree during the run, deleted when the precompute finishes; verified absent from
the project tree and git.
