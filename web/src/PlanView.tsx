import { useEffect, useMemo, useState } from 'react'
import {
  getStops, getGeocode, getAreas, reachableFor, getPlan, getTripStops, getNearbyOrigins,
  type StopHit, type GeoHit, type ReachableStop, type Endpoint, type PlanOption,
  type PlanDeparture, type TripStop, type NearbyOrigin,
} from './api'
import PlanMap from './PlanMap'
import { PinIcon } from './icons'

const DAY_LABEL: Record<string, string> = {
  WEEKDAY: 'Mon-Fri', SATURDAY: 'Saturday', SUNDAY: 'Sunday',
  PUBLIC_HOLIDAY: 'Public Holiday', OTHER: 'Other',
}
const CORE_DAYS = ['WEEKDAY', 'SATURDAY', 'SUNDAY']

const TIME_GROUPS = [
  { key: 'morning', label: 'Morning, before 12pm', test: (m: number) => m < 720 },
  { key: 'afternoon', label: 'Afternoon, 12 to 5pm', test: (m: number) => m >= 720 && m < 1020 },
  { key: 'evening', label: 'Evening, after 5pm', test: (m: number) => m >= 1020 },
] as const

/** The bus's front sign: the terminus and vias, read from the route name ORIGIN - VIA - TERMINUS. */
function busSign(routeLabel: string) {
  const parts = routeLabel.split(' - ').map((s) => s.trim()).filter(Boolean)
  return {
    origin: parts[0] ?? routeLabel,
    terminus: parts[parts.length - 1] ?? routeLabel,
    via: parts.slice(1, -1).join(', '),
  }
}

function bucketDeps(deps: PlanDeparture[]) {
  const groups: Record<string, { d: PlanDeparture; j: number }[]> =
    { morning: [], afternoon: [], evening: [], other: [] }
  deps.forEach((d, j) => {
    const m = d.board_minutes ?? d.arrive_minutes
    const key = m == null ? 'other' : (TIME_GROUPS.find((g) => g.test(m))?.key ?? 'other')
    groups[key].push({ d, j })
  })
  return groups
}

interface Hit { kind: 'stop' | 'place' | 'area'; id?: number; name: string; lat: number; lon: number; sub?: string }

function useDebounced<T>(v: T, ms: number): T {
  const [s, setS] = useState(v)
  useEffect(() => {
    const t = setTimeout(() => setS(v), ms)
    return () => clearTimeout(t)
  }, [v, ms])
  return s
}

async function mergedSearch(q: string, areas: string[]): Promise<Hit[]> {
  const [s, g] = await Promise.all([
    getStops(q).catch(() => ({ stops: [] as StopHit[] })),
    getGeocode(q).catch(() => ({ results: [] as GeoHit[] })),
  ])
  const ql = q.trim().toLowerCase()
  const areaHits: Hit[] = areas.filter((a) => a.toLowerCase().includes(ql)).slice(0, 3)
    .map((a) => ({ kind: 'area', name: a, lat: 0, lon: 0, sub: 'area with bus service' }))
  const stops: Hit[] = s.stops.slice(0, 6)
    .filter((x) => x.lat != null && x.lon != null)
    .map((x) => ({ kind: 'stop', id: x.id, name: x.name, lat: x.lat as number, lon: x.lon as number }))
  const places: Hit[] = g.results.slice(0, 3)
    .map((x) => ({ kind: 'place', name: x.name, lat: x.lat, lon: x.lon, sub: x.full }))
  return [...areaHits, ...stops, ...places]
}

export default function PlanView() {
  const [from, setFrom] = useState<Endpoint | null>(null)
  const [to, setTo] = useState<Endpoint | null>(null)
  const [fromText, setFromText] = useState('')
  const [toText, setToText] = useState('')
  const debFrom = useDebounced(fromText, 220)
  const debTo = useDebounced(toText, 320)

  const [fromHits, setFromHits] = useState<Hit[]>([])
  const [toHits, setToHits] = useState<Hit[]>([])
  const [areas, setAreas] = useState<string[]>([])

  useEffect(() => { getAreas().then((r) => setAreas(r.areas)).catch(() => {}) }, [])

  async function resolveHit(h: Hit): Promise<Endpoint | null> {
    if (h.kind === 'stop') return { kind: 'stop', id: h.id, name: h.name, lat: h.lat, lon: h.lon }
    if (h.kind === 'place') return { kind: 'pin', name: h.name, lat: h.lat, lon: h.lon }
    const r = await getGeocode(h.name).catch(() => ({ results: [] as GeoHit[] }))
    if (r.results.length) return { kind: 'pin', name: h.name, lat: r.results[0].lat, lon: r.results[0].lon }
    return null
  }
  const [reachable, setReachable] = useState<ReachableStop[] | null>(null)
  const [plan, setPlan] = useState<PlanOption[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [sel, setSel] = useState(0)
  const [armed, setArmed] = useState<'from' | 'to' | null>(null)

  const [openDep, setOpenDep] = useState<{ oi: number; di: number } | null>(null)
  const [tripStops, setTripStops] = useState<TripStop[] | null>(null)
  const [loadingTrip, setLoadingTrip] = useState(false)

  const [dayAlts, setDayAlts] = useState<Record<string, NearbyOrigin[]>>({})

  useEffect(() => {
    if (!debFrom || (from && from.name === debFrom)) { setFromHits([]); return }
    mergedSearch(debFrom, areas).then(setFromHits).catch(() => setFromHits([]))
  }, [debFrom, areas]) // eslint-disable-line

  useEffect(() => {
    if (!from || !debTo || (to && to.name === debTo)) { setToHits([]); return }
    mergedSearch(debTo, areas).then(setToHits).catch(() => setToHits([]))
  }, [debTo, from, areas]) // eslint-disable-line

  function pickFrom(ep: Endpoint) {
    setFrom(ep); setFromText(ep.name); setFromHits([]); setArmed(null)
    setTo(null); setToText(''); setPlan(null); setReachable(null); setDayAlts({})
    setOpenDep(null); setTripStops(null)
    reachableFor(ep).then(setReachable).catch(() => setReachable([]))
  }

  function runPlan(f: Endpoint, t: Endpoint) {
    setPlan(null); setDayAlts({}); setOpenDep(null); setTripStops(null); setLoading(true)
    getPlan(f, t)
      .then((r) => {
        setPlan(r.options)
        if (t.kind === 'stop') {
          const present = new Set(r.options.map((o) => o.day_type))
          CORE_DAYS.filter((d) => !present.has(d)).forEach((day) => {
            getNearbyOrigins(f.lat, f.lon, t.id!, {
              exclude: f.kind === 'stop' ? f.id : undefined, dayType: day, radius: 8000,
            })
              .then((n) => { if (n.origins.length) setDayAlts((p) => ({ ...p, [day]: n.origins.slice(0, 3) })) })
              .catch(() => {})
          })
        }
      })
      .finally(() => setLoading(false))
  }

  function pickTo(ep: Endpoint) {
    setTo(ep); setToText(ep.name); setToHits([]); setArmed(null); setSel(0)
    runPlan(from!, ep)
  }

  function useAlt(o: NearbyOrigin) {
    const f: Endpoint = { kind: 'stop', id: o.id, name: o.name, lat: o.lat, lon: o.lon }
    setFrom(f); setFromText(o.name); setSel(0)
    reachableFor(f).then(setReachable).catch(() => {})
    runPlan(f, to!)
  }

  function onMapClick(lat: number, lon: number) {
    if (armed === 'from') pickFrom({ kind: 'pin', name: 'Dropped pin', lat, lon })
    else if (armed === 'to' && from) pickTo({ kind: 'pin', name: 'Dropped pin', lat, lon })
  }

  function selectDep(oi: number, di: number, d: PlanDeparture) {
    setSel(oi)
    if (openDep && openDep.oi === oi && openDep.di === di) { setOpenDep(null); return }
    setOpenDep({ oi, di }); setTripStops(null); setLoadingTrip(true)
    // fetch the WHOLE trip (origin -> terminus) so we can show official start/end times + every via
    getTripStops(d.schedule_id, d.trip_index, 0, 9999)
      .then((r) => setTripStops(r.stops)).finally(() => setLoadingTrip(false))
  }

  const filteredReach = useMemo(() => {
    if (!reachable) return []
    const q = toText.trim().toLowerCase()
    return q ? reachable.filter((r) => r.name.toLowerCase().includes(q)) : reachable
  }, [reachable, toText])

  const stage = !from ? 'from' : !to ? 'reachable' : 'journeys'
  const segment = stage === 'journeys' && plan && plan[sel] ? plan[sel].segment_stops : undefined
  const roadPath = stage === 'journeys' && plan && plan[sel] ? plan[sel].road_path : undefined
  const altDays = CORE_DAYS.filter((d) => dayAlts[d]?.length)

  return (
    <div className="planwrap">
      <div className="planbar">
        <div className="field">
          <label>Starting point</label>
          <div className="ac">
            <input value={fromText} placeholder="Bus stop, place, or address"
              onChange={(e) => { setFromText(e.target.value); if (from) { setFrom(null); setReachable(null); setPlan(null); setTo(null); setDayAlts({}) } }} />
            <button className={`pinbtn ${armed === 'from' ? 'armed' : ''}`} onClick={() => setArmed(armed === 'from' ? null : 'from')}><PinIcon /> Map</button>
            {fromHits.length > 0 && (
              <div className="acmenu">
                {fromHits.map((h, i) => (
                  <button key={i} className="acitem" onMouseDown={() => resolveHit(h).then((ep) => ep && pickFrom(ep))}>
                    <span className="hittag">{h.kind === 'stop' ? 'Stop' : h.kind === 'area' ? 'Area' : 'Place'}</span>
                    {h.name}{h.sub ? <span className="acsub"> {h.sub}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="arrow">→</div>

        <div className="field">
          <label>Destination</label>
          <div className="ac">
            <input value={toText} disabled={!from}
              placeholder={!from ? 'Choose a starting point first' : 'Where do you want to go?'}
              onChange={(e) => { setToText(e.target.value); if (to) { setTo(null); setPlan(null); setDayAlts({}) } }} />
            <button className={`pinbtn ${armed === 'to' ? 'armed' : ''}`} disabled={!from} onClick={() => setArmed(armed === 'to' ? null : 'to')}><PinIcon /> Map</button>
            {toHits.length > 0 && (
              <div className="acmenu">
                {toHits.map((h, i) => (
                  <button key={i} className="acitem" onMouseDown={() => resolveHit(h).then((ep) => ep && pickTo(ep))}>
                    <span className="hittag">{h.kind === 'stop' ? 'Stop' : h.kind === 'area' ? 'Area' : 'Place'}</span>
                    {h.name}{h.sub ? <span className="acsub"> {h.sub}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="plancontent">
        <section className="planleft">
          {stage === 'from' && (
            <div className="placeholder">
              Type where you want to start. It can be a bus stop, or any place or address,
              even one that is not a listed stop like Woodstock. You can also tap <b>Map</b> and
              pick a point.
            </div>
          )}

          {stage === 'reachable' && (
            <>
              <div className="reachhead">
                {reachable == null ? 'Finding destinations…'
                  : <>You can reach {filteredReach.length} stop{filteredReach.length === 1 ? '' : 's'} from <b>{from!.name}</b> on one bus{from!.kind === 'pin' ? <span className="approxtag"> (near your point)</span> : null}</>}
              </div>
              <div className="browsehint">Popular places you can reach from here. You can also type any stop or place above.</div>
              <div className="reachlist">
                {filteredReach.map((r) => (
                  <button key={r.id} className="reachitem" onClick={() =>
                    pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                    <span className="rname">{r.name}</span>
                    <span className="rtrips">{r.trip_count} trips</span>
                  </button>
                ))}
                {reachable != null && filteredReach.length === 0 && (
                  <div className="empty">No direct bus goes to "{toText}" from here. Pick it from the search above and I will show you nearby options.</div>
                )}
              </div>
            </>
          )}

          {stage === 'journeys' && (
            <>
              <div className="reachhead">
                <b>{from!.name}</b> <span className="arrowin">to</span> <b>{to!.name}</b>
                <button className="link" onClick={() => { setTo(null); setToText(''); setPlan(null); setDayAlts({}) }}>Change destination</button>
              </div>
              {loading && <div className="placeholder">Finding buses…</div>}

              {plan && !loading && plan.length === 0 && (
                <div className="noservice">No <b>direct</b> bus from {from!.name} to {to!.name}.</div>
              )}

              {plan && !loading && plan.map((o, i) => {
                const sign = busSign(o.route_label)
                const groups = bucketDeps(o.departures)
                return (
                  <div key={i} className={`optcard ${i === sel ? 'active' : ''}`}>
                    <div className="opthead" onClick={() => setSel(i)}>
                      <div className="signblock">
                        <div className="signlbl">Look for the bus to</div>
                        <div className="signdest">{sign.terminus}</div>
                        <div className="signroute">Route: {o.route_label}, timetable #{o.timetable_number}</div>
                      </div>
                      <span className="optmeta">
                        {(o.board_approx || o.alight_approx) && <span className="approxpill">Approx times</span>}
                        <span className="daypill">{DAY_LABEL[o.day_type] ?? o.day_type}</span>
                      </span>
                    </div>
                    <div className="depshint">Tap a departure to see where you get on and off.</div>
                    {[...TIME_GROUPS, { key: 'other', label: 'Other times' }].map((g) =>
                      groups[g.key].length > 0 ? (
                        <div key={g.key} className="depgroup">
                          <div className="depgrouplbl">{g.label}</div>
                          <div className="depsgrid">
                            {groups[g.key].map(({ d, j }) => (
                              <button key={j} className={`dep ${openDep?.oi === i && openDep?.di === j ? 'on' : ''}`}
                                onClick={() => selectDep(i, j, d)}>
                                <span className="bt">{d.board_raw}</span>
                                <span className="da">to</span>
                                <span className="at">{d.arrive_raw}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null,
                    )}
                    {openDep?.oi === i && (
                      <TripStrip
                        stops={tripStops} loading={loadingTrip}
                        riderFromSeq={o.departures[openDep.di]?.from_seq ?? 0}
                        riderToSeq={o.departures[openDep.di]?.to_seq ?? 9999}
                        boardPin={from?.kind === 'pin' ? { name: from.name, time: o.departures[openDep.di]?.board_raw } : null}
                        alightPin={to?.kind === 'pin' ? { name: to.name, time: o.departures[openDep.di]?.arrive_raw } : null}
                      />
                    )}
                  </div>
                )
              })}

              {plan && !loading && altDays.length > 0 && (
                <div className="nearbybox">
                  <div className="nearbyhead">
                    {plan.length ? 'On other days, the nearest stop with a direct bus:' : 'Nearest stops with a direct bus there:'}
                  </div>
                  {altDays.map((d) => (
                    <div key={d} className="dayalt">
                      <div className="dayaltlbl">{DAY_LABEL[d]}</div>
                      {dayAlts[d].map((o) => (
                        <button key={o.id} className="nearbyitem" onClick={() => useAlt(o)}>
                          <span className="rname">{o.name}</span>
                          <span className="rtrips">
                            {(o.distance_m / 1000).toFixed(1)} km away{o.earliest ? `, first bus ${o.earliest}` : ''}, {o.trip_count} trips
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}

              {plan && !loading && plan.length === 0 && altDays.length === 0 && (
                <div className="empty">No stop within 8 km has a direct bus there either.</div>
              )}
            </>
          )}
        </section>

        <section className="planright">
          <PlanMap
            from={from} to={to} segment={segment} roadPath={roadPath}
            reachable={stage === 'reachable' && from ? [from, ...(reachable ?? [])] : undefined}
            onMapClick={onMapClick}
            armLabel={armed === 'from' ? 'your starting point' : armed === 'to' ? 'your destination' : null}
          />
        </section>
      </div>
    </div>
  )
}

interface PinEnd { name: string; time?: string }

/**
 * Shows the whole trip the bus makes (its official first stop to terminus), with the
 * real published times and "via" markers straight from the timetable, and your own
 * boarding and alighting points highlighted. Times before you board and after you
 * alight are the bus's official schedule; your unofficial-stop time is approximate.
 */
function TripStrip(
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
