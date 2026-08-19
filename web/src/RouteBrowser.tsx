import { useEffect, useMemo, useState } from 'react'
import {
  getRoutes,
  getRoute,
  getTimetable,
  type RouteSummary,
  type RouteDetail,
  type Timetable,
  type TimetableDetail,
  type Schedule,
} from './api'
import MapView from './MapView'

const DAY_ORDER = ['WEEKDAY', 'SATURDAY', 'SUNDAY', 'PUBLIC_HOLIDAY', 'OTHER']
const DAY_LABEL: Record<string, string> = {
  WEEKDAY: 'Mon-Fri',
  SATURDAY: 'Saturday',
  SUNDAY: 'Sunday',
  PUBLIC_HOLIDAY: 'Public holiday',
  OTHER: 'Other',
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export default function RouteBrowser() {
  const [query, setQuery] = useState('')
  const debQuery = useDebounced(query, 250)
  const [routes, setRoutes] = useState<RouteSummary[]>([])

  const [routeId, setRouteId] = useState<number | null>(null)
  const [routeData, setRouteData] = useState<RouteDetail | null>(null)

  const [ttId, setTtId] = useState<number | null>(null)
  const [ttData, setTtData] = useState<TimetableDetail | null>(null)
  const [loadingTt, setLoadingTt] = useState(false)

  const [dirIndex, setDirIndex] = useState<number | null>(null)
  const [dayType, setDayType] = useState<string | null>(null)

  useEffect(() => {
    getRoutes(debQuery).then((r) => setRoutes(r.routes)).catch(() => setRoutes([]))
  }, [debQuery])

  useEffect(() => {
    if (routeId == null) return
    setRouteData(null)
    setTtId(null)
    setTtData(null)
    getRoute(routeId).then((rd) => {
      setRouteData(rd)
      if (rd.timetables.length) setTtId(rd.timetables[0].id)
    })
  }, [routeId])

  useEffect(() => {
    if (ttId == null) return
    setLoadingTt(true)
    getTimetable(ttId)
      .then((td) => {
        setTtData(td)
        const first = [...td.schedules].sort(sortSchedule)[0]
        setDirIndex(first ? first.direction_index : null)
        setDayType(first ? first.day_type : null)
      })
      .finally(() => setLoadingTt(false))
  }, [ttId])

  const directions = useMemo(() => {
    if (!ttData) return []
    const seen = new Map<number, string>()
    for (const s of ttData.schedules) if (!seen.has(s.direction_index)) seen.set(s.direction_index, s.direction_label)
    return [...seen.entries()].sort((a, b) => a[0] - b[0]).map(([index, label]) => ({ index, label }))
  }, [ttData])

  const dayTypesForDir = useMemo(() => {
    if (!ttData || dirIndex == null) return []
    const set = new Set(ttData.schedules.filter((s) => s.direction_index === dirIndex).map((s) => s.day_type))
    return DAY_ORDER.filter((d) => set.has(d))
  }, [ttData, dirIndex])

  const current: Schedule | null = useMemo(() => {
    if (!ttData || dirIndex == null || dayType == null) return null
    return ttData.schedules.find((s) => s.direction_index === dirIndex && s.day_type === dayType) ?? null
  }, [ttData, dirIndex, dayType])

  useEffect(() => {
    if (dayTypesForDir.length && (dayType == null || !dayTypesForDir.includes(dayType))) {
      setDayType(dayTypesForDir[0])
    }
  }, [dayTypesForDir]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="layout">
      <aside className="sidebar">
        <input
          className="search"
          placeholder="Search routes, for example Nyanga or Cape Town"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="routelist">
          {routes.map((r) => (
            <button
              key={r.id}
              className={`routeitem ${r.id === routeId ? 'active' : ''}`}
              onClick={() => setRouteId(r.id)}
            >
              <span className="rname">{r.name}</span>
              <span className="rcount">{r.timetable_count}</span>
            </button>
          ))}
          {!routes.length && <div className="empty">No routes match.</div>}
        </div>
      </aside>

      <main className="main">
        {!routeData && <div className="placeholder">Select a route to view its timetables.</div>}

        {routeData && (
          <>
            <h1 className="routetitle">{routeData.route.name}</h1>

            <div className="ttbar">
              {routeData.timetables.map((t: Timetable) => (
                <button
                  key={t.id}
                  className={`chip ${t.id === ttId ? 'active' : ''} ${t.is_public_holiday ? 'ph' : ''}`}
                  onClick={() => setTtId(t.id)}
                  title={`${t.pdf_filename}\nEffective ${t.effective_from ?? '?'}${t.effective_to ? ' to ' + t.effective_to : ''}`}
                >
                  #{t.timetable_number}
                  {t.is_public_holiday && <span className="phbadge">PH</span>}
                </button>
              ))}
            </div>

            {loadingTt && <div className="placeholder">Loading timetable…</div>}

            {ttData && !loadingTt && (
              <>
                <div className="toggles">
                  <div className="toggle-group">
                    <span className="tlabel">Direction</span>
                    {directions.map((d) => (
                      <button
                        key={d.index}
                        className={`toggle ${d.index === dirIndex ? 'active' : ''}`}
                        onClick={() => setDirIndex(d.index)}
                      >
                        {d.label}
                      </button>
                    ))}
                  </div>
                  <div className="toggle-group">
                    <span className="tlabel">Days</span>
                    {dayTypesForDir.map((d) => (
                      <button
                        key={d}
                        className={`toggle ${d === dayType ? 'active' : ''}`}
                        onClick={() => setDayType(d)}
                      >
                        {DAY_LABEL[d] ?? d}
                      </button>
                    ))}
                  </div>
                </div>

                {current && (
                  <div className="content">
                    <section className="gridpane">
                      <div className="daylabel">{current.day_label}</div>
                      {current.no_service ? (
                        <div className="noservice">No service.</div>
                      ) : (
                        <Grid schedule={current} />
                      )}
                      {ttData.notes.length > 0 && (
                        <div className="notes">
                          {ttData.notes.map((n) => (
                            <span key={n.code} className="notechip">
                              <b>{n.code}</b> {n.description}
                            </span>
                          ))}
                        </div>
                      )}
                    </section>
                    <section className="mappane">
                      <MapView key={current.id} stops={current.stops} />
                    </section>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}

function sortSchedule(a: Schedule, b: Schedule) {
  if (a.direction_index !== b.direction_index) return a.direction_index - b.direction_index
  return DAY_ORDER.indexOf(a.day_type) - DAY_ORDER.indexOf(b.day_type)
}

function Grid({ schedule }: { schedule: Schedule }) {
  const stops = schedule.stops
  const trips = schedule.trips
  return (
    <div className="gridscroll">
      <table className="grid">
        <thead>
          <tr>
            <th className="stopcol">Stop</th>
            {trips.map((t) => (
              <th key={t.trip_index} className="tripcol">
                {t.trip_index + 1}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stops.map((s) => (
            <tr key={s.stop_sequence}>
              <td className="stopcol">{s.name}</td>
              {trips.map((t) => {
                const cell = t.cells.find((c) => c.stop_sequence === s.stop_sequence)
                if (!cell || cell.cell_type === 'NONE') return <td key={t.trip_index} className="c none" />
                if (cell.cell_type === 'VIA') return <td key={t.trip_index} className="c via">via</td>
                return (
                  <td key={t.trip_index} className="c time">
                    {cell.departure_time}
                    {cell.note_code && <sup>{cell.note_code}</sup>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
