/**
 * Journeys that need a change of bus, drawn the way the direct ones are.
 *
 * One card, and every way of making the journey inside it as a block in one carousel.
 *
 * An earlier version grouped them - by where you change, which day it runs, how many
 * buses - and gave each group its own card. That put "2 buses via Cape Town, Saturday"
 * and "2 buses via Cape Town, Weekdays" one above the other, which is the stacking this
 * whole screen exists to remove. It only looked tolerable because there is one operator
 * today; with MyCiTi and Metrorail beside it the page would scroll forever.
 *
 * So nothing groups. What used to separate the cards - the change points, the day, the
 * number of buses - now rides on each block, because those are exactly what a rider is
 * choosing between.
 */
import { useEffect, useState } from 'react'
import { ArrowRight, Check, Plus, Warning } from '@phosphor-icons/react'
import OperatorLogo from './OperatorLogo'
import { getTripStops, type Connection, type TripNote, type TripStop } from './api'
import { legToJourney } from './ConnectionsPanel'
import { DAY_LABEL, latestBoard } from './results'
import { rands } from './money'
import { usePlanner } from './planner'
import TripStrip from './TripStrip'

/** "8 h 35" reads better than "515 minutes" for a wait this long. */
function duration(minutes: number | null): string {
  if (minutes == null) return 'time not published'
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${h} h` : `${h} h ${m}`
}

/**
 * The latest minute the first bus of a connection could still be caught.
 *
 * A journey with changes is only available if its first bus is. Reusing the bound the
 * direct departures use means a connection whose first leg finished this morning stops
 * being offered this evening.
 */
export function connectionStart(c: Connection): number | null {
  const first = c.legs[0]
  if (!first) return null
  return latestBoard({
    board_raw: first.board_raw,
    board_approx: first.board_minutes == null,
    board_minutes: first.board_minutes,
    arrive_raw: first.arrive_raw,
    arrive_approx: first.arrive_minutes == null,
    arrive_minutes: first.arrive_minutes,
    schedule_id: first.schedule_id,
    trip_index: first.trip_index,
    from_seq: first.from_seq,
    to_seq: first.to_seq,
    stop_count: 0,
  })
}

/** The connections that could still be started at a given time. */
export function connectionsFrom(connections: Connection[], minutes: number | null): Connection[] {
  if (minutes == null) return connections
  return connections.filter((c) => {
    const start = connectionStart(c)
    return start == null || start >= minutes
  })
}

/** One whole itinerary, carrying everything that used to separate one card from another. */
function OptionBlock({ conn, chosen, planned, onChoose, onAdd }: {
  conn: Connection
  chosen: boolean
  planned: boolean
  onChoose: () => void
  onAdd: () => void
}) {
  const first = conn.legs[0]
  const last = conn.legs[conn.legs.length - 1]
  const fare = rands(conn.fare?.per_ride_cents)
  /**
   * What goes in the big type.
   *
   * Normally the departure, since that is what a rider is deciding between. But the first
   * leg often boards at a "via" stop the timetable prints no time for, and then every
   * option reads "no set time" and they all look identical. Where the departure is
   * unpublished the arrival leads instead, because it is published and it differs.
   */
  const departureKnown = first.board_minutes != null
  const lead = departureKnown ? first.board_raw : last.arrive_raw
  const under = departureKnown ? `arrives ${last.arrive_raw}` : 'no published departure'

  return (
    /* The same solid tile the direct departures use, so the two carousels read as one
       system rather than two. */
    <div className={`flex h-full w-[172px] shrink-0 flex-col gap-1 p-3 text-white ${
      chosen ? 'bg-accent-fill ring-2 ring-white ring-inset' : 'bg-accent'}`}>
      <button className="flex cursor-pointer flex-col items-start gap-1 text-left" onClick={onChoose}
        title="See the buses on this journey">
        {/* How many buses, which day, and where you change. These used to be the card
            heading; they belong to the individual journey, not to a group of them. */}
        <span className="flex flex-wrap items-center gap-1">
          <span className="bg-white px-1.5 py-px text-[10px] font-bold text-accent-fill">
            {conn.legs.length} buses
          </span>
          <span className="text-[10px] font-bold tracking-[.05em] text-white/90 uppercase">
            {DAY_LABEL[conn.day_type] ?? conn.day_type}
          </span>
        </span>
        <span className="line-clamp-1 text-[11px] text-white/90" title={conn.change_at.join(', ')}>
          via {conn.change_at.join(', ')}
        </span>
        <span>
          <span className="block text-[10px] font-bold tracking-[.06em] text-white/90 uppercase">
            {departureKnown ? 'depart' : 'arrive'}
          </span>
          <span className="block text-[20px] leading-tight font-bold tracking-tight text-white">
            {lead}
          </span>
          <span className="block text-[11px] text-white/90">{under}</span>
        </span>
      </button>
      {fare && <div className="text-[13px] font-bold text-white">{fare}</div>}
      {/* Between two journeys through the same places, this is the whole difference. */}
      {conn.wait_minutes != null && (
        <div className="flex items-center gap-1 text-[11px] text-white/90">
          <Warning size={12} weight="fill" aria-hidden="true" className="shrink-0" />
          {duration(conn.wait_minutes)} waiting
        </div>
      )}
      <button
        className={`mt-auto cursor-pointer border px-2 py-1.5 text-[11px] font-semibold ${
          planned
            ? 'border-white bg-white text-accent-fill'
            : 'border-white/60 text-white hover:bg-white/15'
        }`}
        onClick={onAdd}
        aria-pressed={planned}
      >
        {planned ? `✓ ${conn.legs.length} legs added` : `+ Add all ${conn.legs.length}`}
      </button>
    </div>
  )
}

export default function ConnectionsCard({ connections, onChoose }: {
  connections: Connection[]
  /** Tells the map which journey to draw. */
  onChoose?: (c: Connection) => void
}) {
  const planner = usePlanner()
  const [pick, setPick] = useState(0)
  const [openLeg, setOpenLeg] = useState<number | null>(null)
  const [stops, setStops] = useState<TripStop[] | null>(null)
  const [notes, setNotes] = useState<TripNote[]>([])
  const [loadingLeg, setLoadingLeg] = useState(false)

  /**
   * Least waiting first.
   *
   * The direct carousel is ordered by departure, because that is what a rider picks
   * between there. Here the options often run through the same places for the same money
   * and the wait is the whole difference, so the least painful one leads.
   */
  const options = [...connections].sort(
    (a, b) => (a.wait_minutes ?? Infinity) - (b.wait_minutes ?? Infinity),
  )
  const conn = options[pick] ?? options[0]
  const legOpen = openLeg == null ? undefined : conn?.legs[openLeg]

  // The map lives outside this card, so it has to be told which journey is showing.
  useEffect(() => { if (conn) onChoose?.(conn) }, [conn]) // eslint-disable-line

  useEffect(() => {
    if (!legOpen) { setStops(null); return }
    let live = true
    setLoadingLeg(true)
    // The whole trip, origin to terminus, so the leg is shown in the context of the bus
    // it is on - the stops before boarding and after alighting included.
    getTripStops(legOpen.schedule_id, legOpen.trip_index, 0, 9999)
      .then((r) => { if (live) { setStops(r.stops); setNotes(r.notes ?? []) } })
      .catch(() => { if (live) { setStops([]); setNotes([]) } })
      .finally(() => { if (live) setLoadingLeg(false) })
    return () => { live = false }
  }, [legOpen?.schedule_id, legOpen?.trip_index]) // eslint-disable-line

  function isPlanned(c: Connection) {
    return c.legs.every((l) => planner.has({
      scheduleId: l.schedule_id, tripIndex: l.trip_index,
      fromSeq: l.from_seq, toSeq: l.to_seq,
    }))
  }

  function toggle(c: Connection) {
    if (isPlanned(c)) {
      c.legs.forEach((l) => {
        const found = planner.find({
          scheduleId: l.schedule_id, tripIndex: l.trip_index,
          fromSeq: l.from_seq, toSeq: l.to_seq,
        })
        if (found) planner.remove(found.id)
      })
      return
    }
    // In travel order, so they land on the planner numbered 1, 2, 3.
    c.legs.forEach((l) => planner.add(legToJourney(l, c.day_type, DAY_LABEL[c.day_type] ?? c.day_type)))
  }

  if (!conn) return null

  return (
    <div className="border border-line bg-panel p-4">
      <div className="mb-3 flex items-center gap-2.5">
        <OperatorLogo id="gabs" name="Golden Arrow Buses" kind="bus" size={36} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-[15px] font-bold text-ink">Golden Arrow Buses</span>
            <span className="inline-flex shrink-0 items-center bg-warn px-2 py-0.5 text-[10px] font-bold tracking-[.04em] text-white uppercase">
              Needs a change
            </span>
          </div>
          <div className="text-[12px] text-sub">
            {options.length} {options.length === 1 ? 'way' : 'ways'} to make this journey
          </div>
        </div>
      </div>

      <div className="flex snap-x snap-mandatory gap-2 overflow-x-auto py-1">
        {options.map((c, i) => (
          <div className="flex snap-start" key={i}>
            <OptionBlock
              conn={c}
              chosen={i === pick}
              planned={isPlanned(c)}
              onChoose={() => { setPick(i); setOpenLeg(null) }}
              onAdd={() => toggle(c)}
            />
          </div>
        ))}
      </div>

      {options.length > 1 && (
        <div className="mt-1 text-[11px] text-sub">
          Ordered by least waiting. They differ in where you change and how long you wait.
        </div>
      )}

      {/* The buses on the chosen journey. */}
      <div className="mt-3 flex flex-col gap-1.5">
        {conn.legs.map((l, i) => (
          <button
            key={i}
            className={`flex cursor-pointer flex-col gap-1 border px-3 py-2.5 text-left sm:flex-row sm:items-center sm:gap-3 ${
              openLeg === i ? 'border-accent bg-accent-soft' : 'border-line bg-block hover:border-accent'
            }`}
            onClick={() => setOpenLeg(openLeg === i ? null : i)}
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[11px] font-bold text-onink">
              {i + 1}
            </span>
            <span className="min-w-0 flex-1">
              {/* Wrapping, not truncating. "CAPE T... to DURBANVI..." on a phone hid the
                  one thing the row exists to say. */}
              <span className="flex flex-wrap items-center gap-x-1.5 text-[13px] font-bold text-ink">
                <span>{l.from_name}</span>
                <ArrowRight size={13} weight="bold" aria-hidden="true" className="shrink-0 text-sub" />
                <span>{l.to_name}</span>
              </span>
              <span className="block text-[11px] text-sub">{l.route_label}</span>
            </span>
            <span className="flex shrink-0 items-baseline gap-2 sm:flex-col sm:items-end sm:gap-0 sm:text-right">
              <span className="text-[12px] font-semibold text-ink">
                {l.board_raw} to {l.arrive_raw}
              </span>
              {l.fare?.per_ride_cents != null && (
                <span className="text-[11px] text-sub">{rands(l.fare.per_ride_cents)}</span>
              )}
            </span>
          </button>
        ))}
      </div>

      {/* The chosen leg, stop by stop. */}
      {legOpen && (
        <div className="mt-3">
          {/* On a through ticket the leg has a published price of its own, but it is not
              what the rider pays: one ticket already covers the journey, and showing it
              here would read as a second charge. */}
          {conn.fare?.kind === 'through' ? (
            <div className="mb-2 border border-line bg-block px-3 py-2 text-[12px] text-sub">
              Covered by the one ticket for the whole journey, so there is nothing extra to
              pay for this leg.
            </div>
          ) : legOpen.fare?.per_ride_cents != null ? (
            <div className="mb-2 border border-line bg-block px-3 py-2 text-[12px] text-sub">
              This leg costs <b className="text-ink">{rands(legOpen.fare.per_ride_cents)}</b> a
              ride on a Golden Arrow Gold Card.
            </div>
          ) : null}
          <TripStrip
            stops={stops}
            loading={loadingLeg}
            notes={notes}
            riderFromSeq={legOpen.from_seq}
            riderToSeq={legOpen.to_seq}
            boardPin={null}
            alightPin={null}
            boardTime={legOpen.board_raw}
            alightTime={legOpen.arrive_raw}
            onClose={() => setOpenLeg(null)}
          />
        </div>
      )}

      {/* What the whole journey costs, once, rather than a price on every leg. */}
      {conn.fare && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border border-line bg-block px-3 py-2.5">
          <span className="text-[18px] font-bold text-ink">{rands(conn.fare.per_ride_cents)}</span>
          <span className="inline-flex items-center gap-1 bg-accent px-2 py-0.5 text-[11px] font-bold text-white">
            {conn.fare.kind === 'through' ? 'One ticket' : `Pay ${conn.fare.tickets} times`}
          </span>
          <span className="w-full text-[11px] text-sub">
            for all {conn.legs.length} buses. Golden Arrow Gold Card price. Cash is higher at
            peak times, lower off-peak.
          </span>
        </div>
      )}

      <button
        className={`mt-3 flex w-full cursor-pointer items-center justify-center gap-1.5 px-3 py-2.5 text-[13px] font-semibold ${
          isPlanned(conn) ? 'bg-accent-soft text-accent-deep' : 'bg-ink text-onink hover:bg-accent-fill'
        }`}
        onClick={() => toggle(conn)}
      >
        {isPlanned(conn)
          ? <><Check size={15} weight="bold" aria-hidden="true" /> All {conn.legs.length} legs on your planner</>
          : <><Plus size={15} weight="bold" aria-hidden="true" /> Add all {conn.legs.length} legs to planner</>}
      </button>
    </div>
  )
}
