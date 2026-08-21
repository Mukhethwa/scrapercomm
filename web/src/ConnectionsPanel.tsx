import { ArrowRight, Check, Plus, TriangleAlert } from 'lucide-react'
import type { Connection, ConnectionLeg } from './api'
import { rideKey, usePlanner, type SavedJourney } from './planner'

const DAY_LABEL: Record<string, string> = {
  WEEKDAY: 'Mon-Fri', SATURDAY: 'Saturday', SUNDAY: 'Sunday',
  PUBLIC_HOLIDAY: 'Public Holiday', OTHER: 'Other',
}

/** "3 h 40" reads better than "220 minutes" for a journey this long. */
function duration(minutes: number | null): string {
  if (minutes == null) return 'time not published'
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${h} h` : `${h} h ${m}`
}

function legToJourney(leg: ConnectionLeg, dayType: string, dayLabel: string): SavedJourney {
  return {
    id: `${leg.schedule_id}-${leg.trip_index}-${leg.from_seq}-${leg.to_seq}-${Date.now()}-${Math.random()}`,
    from: { kind: 'stop', id: leg.from_stop_id, name: leg.from_name,
            lat: leg.from_lat ?? 0, lon: leg.from_lon ?? 0 },
    to: { kind: 'stop', id: leg.to_stop_id, name: leg.to_name,
          lat: leg.to_lat ?? 0, lon: leg.to_lon ?? 0 },
    route: { label: leg.route_label, timetableNumber: '', dayType, dayLabel },
    approx: { board: false, alight: false },
    departure: {
      boardRaw: leg.board_raw, arriveRaw: leg.arrive_raw,
      boardMinutes: leg.board_minutes, arriveMinutes: leg.arrive_minutes,
      scheduleId: leg.schedule_id, tripIndex: leg.trip_index,
      fromSeq: leg.from_seq, toSeq: leg.to_seq,
    },
    addedAt: Date.now(),
  }
}

/**
 * Journeys that need a change of bus, shown when no direct one exists.
 *
 * Adding a connection puts each leg on the planner as its own numbered journey, which is
 * exactly what the planner is for: leg 1, then leg 2, in the order you travel.
 */
export default function ConnectionsPanel(
  { connections, legsRequired }: { connections: Connection[]; legsRequired: number | null },
) {
  const planner = usePlanner()

  function alreadyPlanned(c: Connection) {
    return c.legs.every((l) => planner.has({
      scheduleId: l.schedule_id, tripIndex: l.trip_index,
      fromSeq: l.from_seq, toSeq: l.to_seq,
    }))
  }

  function addWholeConnection(c: Connection) {
    if (alreadyPlanned(c)) {
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
    <div className="connlist">
      {connections.map((c, i) => {
        const planned = alreadyPlanned(c)
        return (
          <div key={i} className={`conncard ${planned ? 'planned' : ''}`}>
            <div className="connhead">
              <div className="connsummary">
                <b>{legsRequired} buses</b>
                <span className="connvia">change at {c.change_at.join(' then ')}</span>
                <span className="daypill">{DAY_LABEL[c.day_type] ?? c.day_type}</span>
              </div>
              <div className="conntotals">
                <span className="conntotal">{duration(c.total_minutes)}</span>
                {c.wait_minutes != null && (
                  <span className={`connwait ${c.wait_minutes > 60 ? 'long' : ''}`}>
                    {c.wait_minutes > 60 && <TriangleAlert size={12} aria-hidden="true" />}
                    {duration(c.wait_minutes)} waiting
                  </span>
                )}
              </div>
            </div>

            <ol className="connlegs">
              {c.legs.map((l, j) => (
                <li key={j} className="connleg">
                  <span className="connlegno">{j + 1}</span>
                  <span className="connlegbody">
                    <span className="connlegstops">
                      {l.from_name} <ArrowRight size={12} aria-hidden="true" /> {l.to_name}
                    </span>
                    <span className="connlegroute">{l.route_label}</span>
                  </span>
                  <span className="connlegtimes">
                    <b>{l.board_raw}</b>
                    <span className="connlegdash">to</span>
                    <b>{l.arrive_raw}</b>
                  </span>
                </li>
              ))}
            </ol>

            <button className={`addbtn wide ${planned ? 'on' : ''}`} onClick={() => addWholeConnection(c)}>
              {planned
                ? <><Check size={13} aria-hidden="true" /> All {c.legs.length} legs on your planner</>
                : <><Plus size={13} aria-hidden="true" /> Add all {c.legs.length} legs to planner</>}
            </button>
          </div>
        )
      })}
    </div>
  )
}

export { rideKey }
