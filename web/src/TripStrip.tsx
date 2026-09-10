import { useState } from 'react'
import { Info, X } from 'lucide-react'
import type { TripNote, TripStop } from './api'
import { longTime } from './times'

/**
 * The rider's own point on the road, where the timetable names no stop.
 *
 * `approx` is the departure's own flag and not a constant. It used to be hardcoded true
 * here, so a published 05:10 walked onto the screen as "after 05:10" - a real departure
 * dressed as a guess, one row above the same 05:10 printed plainly.
 */
export interface PinEnd { name: string; time?: string; approx?: boolean }

/**
 * Shows the whole trip the vehicle makes (its official first stop to terminus), with the
 * real published times and "via" markers straight from the timetable, and your own
 * boarding and alighting points highlighted. Times before you board and after you
 * alight are the bus's official schedule; your unofficial-stop time is approximate.
 *
 * Shared by the search results and the Planner, so a journey reads identically in both.
 */
/** A stop's time in the breakdown: published, or plainly marked as a guess. */
function TripTime({ time, approx }: { time: string; approx: boolean }) {
  const t = longTime(time, approx)
  return <span className={`tstime ${t.approx ? 'aprx' : ''}`}>{t.text}</span>
}

export default function TripStrip(
  { stops, loading, boardPin, alightPin, riderFromSeq, riderToSeq, notes,
    boardTime, alightTime, kind = 'bus', onClose }:
  {
    stops: TripStop[] | null; loading: boolean
    boardPin: PinEnd | null; alightPin: PinEnd | null
    riderFromSeq: number; riderToSeq: number
    notes?: TripNote[]
    /**
     * What the departure the rider tapped says about their own two stops. The trip list
     * is the timetable verbatim, so a stop printed as "via" shows "via" here - but the
     * departure they chose may carry a lower bound like "from 05:30". Showing the row as
     * "via" right after they tapped "from 05:30" reads as a contradiction, so the
     * departure's own wording wins on those two rows.
     */
    boardTime?: string; alightTime?: string
    /**
     * Bus or train, for the words around the list.
     *
     * The list itself is the same either way - stops, times, where you get on - but
     * "the whole bus trip" over a Metrorail schedule, and "bus starts" against RETREAT
     * on the Southern Line, tell a rider the app has not understood what they asked.
     */
    kind?: 'bus' | 'train'
    /**
     * Collapses the breakdown. Tapping the same departure again already closed it, but
     * that means aiming at the chip you came from after scrolling past a long list of
     * stops; a close button sits where the reader's eye already is.
     */
    onClose?: () => void
  },
) {
  if (loading) return <div className="tripstrip"><div className="tsloading">Loading the full trip…</div></div>
  if (!stops || stops.length === 0)
    return <div className="tripstrip"><div className="tsloading">No stop detail for this trip.</div></div>

  // `approx` is about the TIME being a guess; `pin` is about the STOP being the
  // rider's own unofficial one. They used to be the same flag, which meant every
  // via row started claiming to be "your stop".
  type Row = { name: string; time: string; approx: boolean; pin: boolean
               role: 'board' | 'alight' | 'mid' }
  const rows: Row[] = []
  let boardInserted = false
  stops.forEach((s, i) => {
    // your (unofficial) boarding point goes just before the first stop at/after it
    if (boardPin && !boardInserted && s.stop_sequence >= riderFromSeq) {
      rows.push({ name: boardPin.name, time: boardPin.time ?? '',
                  approx: boardPin.approx ?? true, pin: true, role: 'board' })
      boardInserted = true
    }
    const isBoardStop = !boardPin && s.stop_sequence === riderFromSeq
    const isAlightStop = !alightPin && s.stop_sequence === riderToSeq
    const printed = s.cell_type === 'TIME' ? s.raw_value : 'via'
    const chosen = isBoardStop ? boardTime : isAlightStop ? alightTime : undefined
    rows.push({
      name: s.name,
      time: s.cell_type === 'TIME' ? printed : chosen ?? printed,
      approx: s.cell_type !== 'TIME',
      pin: false,
      role: isBoardStop ? 'board' : isAlightStop ? 'alight' : 'mid',
    })
    // your (unofficial) alighting point goes just after the last stop within your segment
    const next = stops[i + 1]
    if (alightPin && s.stop_sequence <= riderToSeq && (!next || next.stop_sequence > riderToSeq)) {
      rows.push({ name: alightPin.name, time: alightPin.time ?? '',
                  approx: alightPin.approx ?? true, pin: true, role: 'alight' })
    }
  })

  const boardIdx = rows.findIndex((r) => r.role === 'board')
  const alightIdx = rows.map((r) => r.role).lastIndexOf('alight')

  return (
    <div className="tripstrip">
      <div className="tsthead">
        <span className="tsttitle">
          The whole {kind === 'train' ? 'train' : 'bus'} trip. You ride the highlighted part.
        </span>
        {onClose && (
          <button className="tsclose" onClick={onClose} aria-label="Hide the trip breakdown">
            <X size={13} aria-hidden="true" />
            <span>Hide</span>
          </button>
        )}
      </div>
      <ol className="tslist">
        {rows.map((r, i) => {
          const before = boardIdx >= 0 && i < boardIdx
          const after = alightIdx >= 0 && i > alightIdx
          const isFirst = i === 0
          const isLast = i === rows.length - 1
          return (
            <li key={i} className={`tsrow ${r.role === 'board' ? 'get-on' : ''} ${r.role === 'alight' ? 'get-off' : ''} ${before || after ? 'context' : ''}`}>
              <span className="tsdot" />
              <span className="tsname">
                {r.name}
                {r.pin && <span className="yourstop"> (your stop)</span>}
                {r.role === 'board' && <span className="tstag on">get on here</span>}
                {r.role === 'alight' && <span className="tstag off">get off here</span>}
                {isFirst && before && (
                  <span className="tstag ctx">{kind === 'train' ? 'train' : 'bus'} starts</span>
                )}
                {isLast && after && <span className="tstag ctx">terminus</span>}
              </span>
              <TripTime time={r.time} approx={r.approx} />
            </li>
          )
        })}
      </ol>
      <TripNotes notes={notes} />
    </div>
  )
}

/**
 * Reading a timetable cell: what "via" means, and what a letter after a time means.
 * Worth reading once and then never again, so it sits behind an info button rather than
 * taking up room under every trip a commuter opens.
 *
 * The letters are not fixed across the network, because each timetable defines its own, so the
 * meanings come from the trip's own footnotes rather than being hardcoded.
 */
function TripNotes({ notes }: { notes?: TripNote[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="tsnote">
      <button className="infobtn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Info size={13} aria-hidden="true" />
        <span>How to read these times</span>
      </button>
      {open && (
        <div className="tsfoot" role="note">
          <p>
            <b>"Via"</b> means the bus passes this stop, but the timetable does not publish
            an exact time for it. The times shown before you get on, and after you get off,
            are the bus's official schedule.
          </p>
          <p>
            Where your own stop is not one the timetable names, the time is worked out
            from the timed stops around it, and says which way it leans:
          </p>
          <ul className="notelist">
            <li>
              <b>after 05:30</b> - the bus has left 05:30 behind, so it reaches you later
              than that. Be there by 05:30 and allow extra.
            </li>
            <li>
              <b>before 06:30</b> - it is timed at 06:30 further along, so it passes you
              sooner than that. Be there well before.
            </li>
            <li>
              <b>about 07:12</b> - stops are timed on both sides of you, so this is the
              middle of the two, give or take.
            </li>
          </ul>
          <p>
            On a departure button there is no room for the words, and all three read
            <b> ~07:12</b>: approximate, without saying which way.
          </p>
          <p>
            <b>"No set time"</b> means even that much is not known for your stop. The timed
            stops either side of it, above and below, are the best guide.
          </p>
          {notes && notes.length > 0 ? (
            <>
              <p>
                <b>A letter after a time</b>, like <code>16:20b</code>, means that departure
                only runs on certain days:
              </p>
              <ul className="notelist">
                {notes.map((n) => (
                  <li key={n.code}>
                    <b>{n.code}</b>: {n.description}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>
              <b>A letter after a time</b>, like <code>16:20b</code>, means that departure
              only runs on certain days. This trip does not use any.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
