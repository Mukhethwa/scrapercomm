import type { TripStop } from './api'

export interface PinEnd { name: string; time?: string }

/**
 * Shows the whole trip the bus makes (its official first stop to terminus), with the
 * real published times and "via" markers straight from the timetable, and your own
 * boarding and alighting points highlighted. Times before you board and after you
 * alight are the bus's official schedule; your unofficial-stop time is approximate.
 *
 * Shared by the search results and the Planner, so a journey reads identically in both.
 */
export default function TripStrip(
  { stops, loading, boardPin, alightPin, riderFromSeq, riderToSeq }:
  {
    stops: TripStop[] | null; loading: boolean
    boardPin: PinEnd | null; alightPin: PinEnd | null
    riderFromSeq: number; riderToSeq: number
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
    rows.push({
      name: s.name,
      time: s.cell_type === 'TIME' ? s.raw_value : 'via',
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
              <span className="tstime">{r.approx ? `about ${r.time}`.trim() : r.time}</span>
            </li>
          )
        })}
      </ol>
      <div className="tsfoot">"Via" means the bus passes this stop, but the timetable does not publish an exact time for it. The times shown before you get on, and after you get off, are the bus's official schedule.</div>
    </div>
  )
}
