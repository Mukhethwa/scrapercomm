import { useState } from 'react'
import { Info } from 'lucide-react'
import type { TripNote, TripStop } from './api'

export interface PinEnd { name: string; time?: string }

/**
 * Shows the whole trip the bus makes (its official first stop to terminus), with the
 * real published times and "via" markers straight from the timetable, and your own
 * boarding and alighting points highlighted. Times before you board and after you
 * alight are the bus's official schedule; your unofficial-stop time is approximate.
 *
 * Shared by the search results and the Planner, so a journey reads identically in both.
 */
/**
 * "about 07:14" only makes sense of a real clock time. An unofficial stop between two
 * timing points can come back as "via" - the timetable simply prints no time there - and
 * "about via" says nothing. Those are left to speak for themselves.
 */
function approxTime(time: string): string {
  return /^\d{1,2}:\d{2}/.test(time) ? `about ${time}` : time
}

export default function TripStrip(
  { stops, loading, boardPin, alightPin, riderFromSeq, riderToSeq, notes,
    boardTime, alightTime }:
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
  },
) {
  if (loading) return <div className="tripstrip"><div className="tsloading">Loading the full trip…</div></div>
  if (!stops || stops.length === 0)
    return <div className="tripstrip"><div className="tsloading">No stop detail for this trip.</div></div>

  type Row = { name: string; time: string; approx: boolean; role: 'board' | 'alight' | 'mid' }
  const rows: Row[] = []
  let boardInserted = false
  stops.forEach((s, i) => {
    // your (unofficial) boarding point goes just before the first stop at/after it
    if (boardPin && !boardInserted && s.stop_sequence >= riderFromSeq) {
      rows.push({ name: boardPin.name, time: boardPin.time ?? '', approx: true, role: 'board' })
      boardInserted = true
    }
    const isBoardStop = !boardPin && s.stop_sequence === riderFromSeq
    const isAlightStop = !alightPin && s.stop_sequence === riderToSeq
    const published = s.cell_type === 'TIME' ? s.raw_value : 'via'
    const chosen = isBoardStop ? boardTime : isAlightStop ? alightTime : undefined
    rows.push({
      name: s.name,
      time: s.cell_type === 'TIME' ? published : chosen ?? published,
      approx: false,
      role: isBoardStop ? 'board' : isAlightStop ? 'alight' : 'mid',
    })
    // your (unofficial) alighting point goes just after the last stop within your segment
    const next = stops[i + 1]
    if (alightPin && s.stop_sequence <= riderToSeq && (!next || next.stop_sequence > riderToSeq)) {
      rows.push({ name: alightPin.name, time: alightPin.time ?? '', approx: true, role: 'alight' })
    }
  })

  const boardIdx = rows.findIndex((r) => r.role === 'board')
  const alightIdx = rows.map((r) => r.role).lastIndexOf('alight')

  return (
    <div className="tripstrip">
      <div className="tsttitle">The whole bus trip. You ride the highlighted part.</div>
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
                {r.approx && <span className="yourstop"> (your stop)</span>}
                {r.role === 'board' && <span className="tstag on">get on here</span>}
                {r.role === 'alight' && <span className="tstag off">get off here</span>}
                {isFirst && before && <span className="tstag ctx">bus starts</span>}
                {isLast && after && <span className="tstag ctx">terminus</span>}
              </span>
              <span className="tstime">{r.approx ? approxTime(r.time) : r.time}</span>
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
 * The letters are not fixed across the network — each timetable defines its own — so the
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
            <b>"From 05:30"</b> means the bus leaves its last timed stop at 05:30 and reaches
            this one after that, so it will not come earlier than 05:30. The timetable does
            not say how much later, so allow a little extra time.
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
                    <b>{n.code}</b> — {n.description}
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
