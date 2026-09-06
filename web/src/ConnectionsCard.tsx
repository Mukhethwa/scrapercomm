/**
 * Journeys that need a change of bus, drawn the way the direct ones are.
 *
 * The API answers BUH REIN to SCOTTSDENE with six connections. All six change at the
 * same two places on the same three routes; what differs is the wait - 515, 525 or 530
 * minutes - and a few minutes on the last leg. Stacked as six full panels that is the
 * same wall this screen exists to remove, and worse, because six near-identical blocks
 * ask a rider to spot the difference themselves.
 *
 * So they group by how you change, and the itineraries run sideways inside the card,
 * exactly as departures do on a direct journey. Picking one shows its legs underneath.
 */
import { useEffect, useState } from 'react'
import { ArrowRight, Bus, Check, Plus, TriangleAlert } from 'lucide-react'
import { getTripStops, type Connection, type TripNote, type TripStop } from './api'
import { legToJourney } from './ConnectionsPanel'
import { DAY_LABEL, latestBoard } from './results'
import { shortTime } from './times'
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

/** Every connection that changes at the same places, on the same day. */
interface Pattern {
  key: string
  changeAt: string[]
  dayType: string
  legs: number
  options: Connection[]
}

function group(connections: Connection[]): Pattern[] {
  const out = new Map<string, Pattern>()
  for (const c of connections) {
    const key = `${c.day_type}|${c.change_at.join('>')}|${c.legs.length}`
    const found = out.get(key)
    if (found) found.options.push(c)
    else {
      out.set(key, {
        key, changeAt: c.change_at, dayType: c.day_type,
        legs: c.legs.length, options: [c],
      })
    }
  }
  return [...out.values()]
}

/** One whole itinerary, as a block in the carousel. */
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
   * What to put in the big type.
   *
   * Normally the departure - it is what a rider is deciding between. But the first leg
   * often boards at a "via" stop the timetable prints no time for, and BUH REIN is one:
   * every one of these six options then led with "no set time" and they looked identical,
   * which is the exact confusion this card exists to remove. Where the departure is
   * unpublished the arrival leads instead, because it is published and it differs.
   */
  const departs = shortTime(first.board_raw, first.board_raw.toLowerCase().includes('via'))
  const leadsOnArrival = departs.approx
  const lead = leadsOnArrival ? last.arrive_raw : departs.text
  const under = leadsOnArrival ? 'no published departure' : `arrives ${last.arrive_raw}`

  return (
    <div className={`flex w-[150px] shrink-0 flex-col gap-1 rounded-xl p-3 ${
      chosen ? 'bg-accent-soft ring-1 ring-accent ring-inset' : 'bg-bg'}`}>
      <button className="cursor-pointer text-left" onClick={onChoose}
        title="See the buses on this journey">
        {leadsOnArrival && (
          <div className="text-[10px] font-bold tracking-[.06em] text-sub uppercase">arrive</div>
        )}
        <div className="text-[20px] leading-tight font-bold tracking-tight text-ink">
          {lead}
        </div>
        <div className="text-[11px] text-sub">{under}</div>
      </button>
      {fare && <div className="text-[13px] font-bold text-accent">{fare}</div>}
      {/* The number that actually separates these options from one another. */}
      {conn.wait_minutes != null && (
        <div className="flex items-center gap-1 text-[11px] text-sub">
          <TriangleAlert size={11} aria-hidden="true" className="shrink-0" />
          {duration(conn.wait_minutes)} waiting
        </div>
      )}
      <button
        className={`mt-1 cursor-pointer rounded-lg border px-2 py-1.5 text-[11px] font-semibold ${
          planned
            ? 'border-accent bg-accent-soft text-accent'
            : 'border-line bg-panel text-ink hover:border-accent'
        }`}
        onClick={onAdd}
        aria-pressed={planned}
      >
        {planned ? `✓ ${conn.legs.length} legs added` : `+ Add all ${conn.legs.length}`}
      </button>
    </div>
  )
}

/**
 * The latest minute the first bus of a connection could still be caught.
 *
 * A three-bus journey is only available if its first bus is. Reusing the same bound the
 * direct departures use means a connection whose first leg finished this morning stops
 * being offered this evening, which it did not before.
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

export default function ConnectionsCard({ connections, legsRequired }: {
  connections: Connection[]
  legsRequired: number | null
}) {
  const planner = usePlanner()
  const patterns = group(connections)
  const [chosen, setChosen] = useState<Record<string, number>>({})
  /**
   * Which leg is opened, as pattern key plus leg index. Fetched here rather than through
   * the parent's plan state: a connection leg belongs to no plan option, so there is no
   * option index to hang it off.
   */
  const [openLeg, setOpenLeg] = useState<{ key: string; i: number } | null>(null)
  const [stops, setStops] = useState<TripStop[] | null>(null)
  const [notes, setNotes] = useState<TripNote[]>([])
  const [loadingLeg, setLoadingLeg] = useState(false)

  const openConn = openLeg
    ? (patterns.find((p) => p.key === openLeg.key)?.options[chosen[openLeg.key] ?? 0])
    : undefined
  const legOpen = openConn?.legs[openLeg?.i ?? 0]

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

  return (
    <>
      {patterns.map((p) => {
        const pick = chosen[p.key] ?? 0
        const conn = p.options[pick] ?? p.options[0]
        return (
          <div key={p.key} className="rounded-2xl bg-panel p-4 shadow-sm">
            <div className="mb-3 flex items-center gap-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                <Bus size={17} aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <div className="truncate text-[15px] font-bold text-ink">
                  {p.legs} buses{legsRequired != null && p.legs === legsRequired ? '' : ''}
                </div>
                <div className="truncate text-[12px] text-sub">
                  change at {p.changeAt.join(' then ')} · {DAY_LABEL[p.dayType] ?? p.dayType}
                </div>
              </div>
            </div>

            {/* One block per itinerary. Six of these used to be six stacked panels. */}
            <div className="flex snap-x snap-mandatory gap-2 overflow-x-auto py-1">
              {p.options.map((c, i) => (
                <div className="snap-start" key={i}>
                  <OptionBlock
                    conn={c}
                    chosen={i === pick}
                    planned={isPlanned(c)}
                    onChoose={() => setChosen((s) => ({ ...s, [p.key]: i }))}
                    onAdd={() => toggle(c)}
                  />
                </div>
              ))}
            </div>

            {p.options.length > 1 && (
              <div className="mt-1 text-[11px] text-sub">
                {p.options.length} ways to make this journey — they differ by how long you wait.
              </div>
            )}

            {/* The buses on the chosen itinerary. */}
            <div className="mt-3 flex flex-col gap-1.5">
              {conn.legs.map((l, i) => (
                <button
                  key={i}
                  className={`flex cursor-pointer flex-col gap-1 rounded-xl px-3 py-2.5 text-left sm:flex-row sm:items-center sm:gap-3 ${
                    openLeg?.key === p.key && openLeg.i === i
                      ? 'bg-accent-soft ring-1 ring-accent ring-inset'
                      : 'bg-bg hover:bg-accent-soft'
                  }`}
                  onClick={() => setOpenLeg(
                    openLeg?.key === p.key && openLeg.i === i ? null : { key: p.key, i },
                  )}
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[11px] font-bold text-white">
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    {/* Wrapping, not truncating. "CAPE T... to DURBANVI..." on a phone
                        hid the one thing the row exists to say. */}
                    <span className="flex flex-wrap items-center gap-x-1.5 text-[13px] font-bold text-ink">
                      <span>{l.from_name}</span>
                      <ArrowRight size={13} aria-hidden="true" className="shrink-0 text-sub" />
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
            {openLeg?.key === p.key && legOpen && (
              <div className="mt-3">
                {/* On a through ticket the leg has a published price of its own, but it is
                    not what the rider pays - one ticket already covers the journey, and
                    showing it here would read as a second charge. */}
                {conn.fare?.kind === 'through' ? (
                  <div className="mb-2 rounded-xl bg-bg px-3 py-2 text-[12px] text-sub">
                    Covered by the one ticket for the whole journey — nothing extra to pay
                    for this leg.
                  </div>
                ) : legOpen.fare?.per_ride_cents != null ? (
                  <div className="mb-2 rounded-xl bg-bg px-3 py-2 text-[12px] text-sub">
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
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-bg px-3 py-2.5">
                <span className="text-[18px] font-bold text-ink">
                  {rands(conn.fare.per_ride_cents)}
                </span>
                <span className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold text-white">
                  {conn.fare.kind === 'through'
                    ? 'One ticket'
                    : `Pay ${conn.fare.tickets} times`}
                </span>
                <span className="w-full text-[11px] text-sub">
                  for all {conn.legs.length} buses. Golden Arrow Gold Card price. Cash is higher
                  at peak times, lower off-peak.
                </span>
              </div>
            )}

            <button
              className={`mt-3 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-[13px] font-semibold ${
                isPlanned(conn)
                  ? 'bg-accent-soft text-accent'
                  : 'bg-ink text-white hover:bg-accent-fill'
              }`}
              onClick={() => toggle(conn)}
            >
              {isPlanned(conn)
                ? <><Check size={15} aria-hidden="true" /> All {conn.legs.length} legs on your planner</>
                : <><Plus size={15} aria-hidden="true" /> Add all {conn.legs.length} legs to planner</>}
            </button>
          </div>
        )
      })}
    </>
  )
}
