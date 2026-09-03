import { useEffect, useMemo, useState } from 'react'
import {
  getStops, getGeocode, getAreas, reachableFor, connectingFor, getPlan, getTripStops, getNearbyOrigins,
  getConnections,
  type StopHit, type GeoHit, type ReachableStop, type ConnectingStop, type Endpoint, type PlanOption,
  type PlanDeparture, type TripStop, type TripNote, type NearbyOrigin, type Connection,
} from './api'
import PlanMap from './PlanMap'
import TripStrip from './TripStrip'
import FarePanel from './FarePanel'
import ModePicker from './ModePicker'
import { useModes } from './modes'
import { buildJourney, usePlanner } from './planner'
import { shortTime, boundIsUseful, NO_TIME } from './times'
import { rands } from './money'
import { ArrowRight, CircleCheck, CircleX, Info, Lightbulb, TriangleAlert } from 'lucide-react'
import ConnectionsPanel from './ConnectionsPanel'
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

/**
 * The suggestion menu floats over the content below it (position: absolute, up to 280px
 * tall), so leaving it open once the field loses focus hides real information.
 *
 * Visibility is tied to whether the field has focus rather than to clearing the results
 * array: a search started on focus can resolve after the user has already left the
 * field, and clearing the array would simply be undone when that promise lands. Menu
 * items use onMouseDown, which fires before blur, so clicking a suggestion still
 * registers. Escape blurs, which closes the menu by the same rule.
 */
/**
 * Does any departure here carry a time the timetable never printed?
 *
 * The option's own board_approx/alight_approx describe whichever candidate happened to
 * build the group, so a group can show "~05:30" while reporting false. Gating the legend
 * on that flag hid the explanation from the exact rows that needed it.
 */
function hasApprox(o: PlanOption): boolean {
  return o.departures.some((d) => d.board_approx || d.arrive_approx)
}

/**
 * What one end of the ride should say, decided once so the departure button and the trip
 * breakdown can never disagree about the same stop.
 */
function alightOrNone(d: PlanDeparture | undefined, end: 'board' | 'alight'): string | undefined {
  if (!d) return undefined
  const raw = end === 'board' ? d.board_raw : d.arrive_raw
  const approx = end === 'board' ? d.board_approx : d.arrive_approx
  const mins = end === 'board' ? d.board_minutes : d.arrive_minutes
  return boundIsUseful(mins, approx, d.board_minutes) ? raw : NO_TIME
}

/** One end of a departure button: a published time, or a visibly-approximate one. */
function DepTime({ raw, approx, useful = true }:
  { raw: string; approx: boolean; useful?: boolean }) {
  const t = shortTime(useful ? raw : NO_TIME, approx)
  return <span className={t.approx ? 'aprx' : ''}>{t.text}</span>
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
  // Whether each field has focus. The menu renders only while it does, so a search that
  // resolves after the field was left cannot pop it open again.
  const [fromOpen, setFromOpen] = useState(false)
  const [toOpen, setToOpen] = useState(false)
  const [areas, setAreas] = useState<string[]>([])

  useEffect(() => { getAreas().then((r) => setAreas(r.areas)).catch(() => {}) }, [])

  /**
   * Turn a suggestion into somewhere the planner can actually use.
   *
   * An area is a route's endpoint name, not a stop, and it carries no coordinates. It
   * used to be geocoded, which fails on names that are not places - "KHAYELITSHA S A P"
   * means nothing to a map - and the click then did nothing at all, silently.
   *
   * Nearly all of them are a stop under a slightly longer name, so the stop list is
   * asked first, dropping a trailing word at a time. A stop beats a pin: it comes with
   * the timetables, rather than a point the planner has to work out anchors for.
   */
  async function resolveHit(h: Hit): Promise<Endpoint | null> {
    if (h.kind === 'stop') return { kind: 'stop', id: h.id, name: h.name, lat: h.lat, lon: h.lon }
    if (h.kind === 'place') return { kind: 'pin', name: h.name, lat: h.lat, lon: h.lon }

    const words = h.name.split(/\s+/).filter(Boolean)
    for (let n = words.length; n > 0; n--) {
      const r = await getStops(words.slice(0, n).join(' ')).catch(() => ({ stops: [] as StopHit[] }))
      const hit = r.stops.find((x) => x.lat != null && x.lon != null)
      if (hit) {
        return { kind: 'stop', id: hit.id, name: hit.name, lat: hit.lat as number, lon: hit.lon as number }
      }
    }
    const r = await getGeocode(h.name).catch(() => ({ results: [] as GeoHit[] }))
    if (r.results.length) return { kind: 'pin', name: h.name, lat: r.results[0].lat, lon: r.results[0].lon }
    return null
  }

  /** Picking a suggestion must never look like nothing happened. */
  async function choose(h: Hit, pick: (ep: Endpoint) => void) {
    setPickError(null)
    const ep = await resolveHit(h)
    if (ep) pick(ep)
    else setPickError(`Could not find a stop for "${h.name}". Try a nearby stop or place.`)
  }
  const [pickError, setPickError] = useState<string | null>(null)
  const [reachable, setReachable] = useState<ReachableStop[] | null>(null)
  const [connecting, setConnecting] = useState<ConnectingStop[]>([])
  const [plan, setPlan] = useState<PlanOption[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [sel, setSel] = useState(0)
  const [armed, setArmed] = useState<'from' | 'to' | null>(null)

  const [openDep, setOpenDep] = useState<{ oi: number; di: number } | null>(null)
  const [tripStops, setTripStops] = useState<TripStop[] | null>(null)
  const [tripNotes, setTripNotes] = useState<TripNote[]>([])
  const [loadingTrip, setLoadingTrip] = useState(false)

  const [dayAlts, setDayAlts] = useState<Record<string, NearbyOrigin[]>>({})

  const planner = usePlanner()

  // Connections are only consulted once a direct search comes back empty.
  const [conns, setConns] = useState<Connection[] | null>(null)
  const [connLegs, setConnLegs] = useState<number | null>(null)
  const [connLoading, setConnLoading] = useState(false)

  /** Add this departure to the planner, or take it off again if it is already there. */
  function togglePlanned(o: PlanOption, d: PlanDeparture) {
    if (!from || !to) return
    const existing = planner.find({
      scheduleId: d.schedule_id, tripIndex: d.trip_index,
      fromSeq: d.from_seq, toSeq: d.to_seq,
    })
    if (existing) planner.remove(existing.id)
    else planner.add(buildJourney(from, to, o, d))
  }

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
    setTo(null); setToText(''); setPlan(null); setReachable(null); setConnecting([]); setDayAlts({})
    setOpenDep(null); setTripStops(null)
    reachableFor(ep).then(setReachable).catch(() => setReachable([]))
    connectingFor(ep).then(setConnecting).catch(() => setConnecting([]))
  }

  function runPlan(f: Endpoint, t: Endpoint) {
    setPlan(null); setDayAlts({}); setOpenDep(null); setTripStops(null); setLoading(true)
    setConns(null); setConnLegs(null); setConnLoading(false)
    getPlan(f, t)
      .then((r) => {
        setPlan(r.options)
        // No direct bus. Look for one that needs a change, which the connections
        // engine can only work out between named stops.
        if (r.options.length === 0 && f.kind === 'stop' && t.kind === 'stop') {
          setConnLoading(true)
          getConnections(f.id!, t.id!)
            .then((c) => { setConns(c.connections); setConnLegs(c.legs_required) })
            .catch(() => { setConns([]); setConnLegs(null) })
            .finally(() => setConnLoading(false))
        }
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
    connectingFor(f).then(setConnecting).catch(() => {})
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
      .then((r) => { setTripStops(r.stops); setTripNotes(r.notes ?? []) })
      .finally(() => setLoadingTrip(false))
  }

  const modes = useModes()

  const filteredReach = useMemo(() => {
    if (!reachable) return []
    const q = toText.trim().toLowerCase()
    return q ? reachable.filter((r) => r.name.toLowerCase().includes(q)) : reachable
  }, [reachable, toText])

  /**
   * Places near the chosen destination that CAN be reached from here.
   *
   * A stop's name is not its area. KHAYELITSHA is a via point with no published times
   * and a bus to it from four stops in the whole network, while SITE C, MAKHAZA and
   * HARARE - all of them Khayelitsha - are served thousands of times and sit one change
   * away. Somebody who typed "Khayelitsha" and was told it is impossible was being
   * answered about the wrong thing, so the ones that do work are offered by name.
   */
  const nearbyAlternatives = useMemo(() => {
    if (!to || to.lat == null || to.lon == null) return []
    const km = (a: { lat: number; lon: number }, b: { lat: number; lon: number }) => {
      const R = 6371, rad = Math.PI / 180
      const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad
      const h = Math.sin(dLat / 2) ** 2 +
        Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2
      return 2 * R * Math.asin(Math.sqrt(h))
    }
    const here = { lat: to.lat, lon: to.lon }
    const seen = new Set<number>()
    return [
      ...(reachable ?? []).map((r) => ({ ...r, change: false })),
      ...connecting.map((r) => ({ ...r, change: true })),
    ]
      .filter((r) => {
        if (r.id === to.id || r.lat == null || r.lon == null || seen.has(r.id)) return false
        seen.add(r.id)
        return km(here, { lat: r.lat, lon: r.lon }) <= 6
      })
      .map((r) => ({ ...r, km: km(here, { lat: r.lat!, lon: r.lon! }) }))
      .sort((a, b) => a.km - b.km)
      .slice(0, 6)
  }, [to, reachable, connecting])

  /** Buses the best answer to what was actually asked needs. */
  const bestLegs = plan && plan.length > 0 ? 1 : (connLegs ?? Infinity)

  /**
   * Nearby stops that take fewer buses than the stop the rider chose.
   *
   * A stop's name is not its area, and some named stops are barely served. WYNBERG to
   * KHAYELITSHA comes back as three buses and an hour and fifty minutes, because no
   * route lists a stop called KHAYELITSHA at all - the route named "WYNBERG -
   * KHAYELITSHA" calls at MAKHAZA, HARARE and SITE C, and SITE C is one bus away.
   * Answering the letter of the question and hiding the better journey helps nobody.
   */
  const betterNearby = useMemo(
    () => nearbyAlternatives.filter((r) => (r.change ? 2 : 1) < bestLegs),
    [nearbyAlternatives, bestLegs],
  )

  const filteredConnecting = useMemo(() => {
    const q = toText.trim().toLowerCase()
    return q ? connecting.filter((r) => r.name.toLowerCase().includes(q)) : connecting
  }, [connecting, toText])

  const stage = !from ? 'from' : !to ? 'reachable' : 'journeys'
  const segment = stage === 'journeys' && plan && plan[sel] ? plan[sel].segment_stops : undefined
  const roadPath = stage === 'journeys' && plan && plan[sel] ? plan[sel].road_path : undefined

  /**
   * The stop range the rider is actually on, for numbering the map.
   *
   * segment_stops deliberately reaches one timing point past the end, because a leg's
   * road geometry only exists between two of them - so numbering it whole would put a
   * stop after the one they get off at. BUH REIN to CAPE TOWN ends at CAPE TOWN and the
   * segment carries BLOEKOMBOS behind it.
   */
  const ride = useMemo(() => {
    if (stage !== 'journeys' || !plan || !plan[sel]) return undefined
    const d = plan[sel].departures[openDep?.oi === sel ? openDep.di : 0]
    return d ? { fromSeq: d.from_seq, toSeq: d.to_seq } : undefined
  }, [stage, plan, sel, openDep])
  const altDays = CORE_DAYS.filter((d) => dayAlts[d]?.length)

  return (
    <div className="planwrap">
      <div className="planbar">
        <div className="field">
          <label>Starting point</label>
          <div className="ac">
            <input value={fromText} placeholder="Bus stop, place, or address"
              onChange={(e) => { setFromText(e.target.value); if (from) { setFrom(null); setReachable(null); setConnecting([]); setPlan(null); setTo(null); setDayAlts({}) } }}
              onFocus={() => setFromOpen(true)}
              onBlur={() => setFromOpen(false)}
              onKeyDown={(e) => { if (e.key === 'Escape') e.currentTarget.blur() }} />
            <button className={`pinbtn ${armed === 'from' ? 'armed' : ''}`} onClick={() => setArmed(armed === 'from' ? null : 'from')}><PinIcon /> Map</button>
            {fromOpen && fromHits.length > 0 && (
              <div className="acmenu">
                {fromHits.map((h, i) => (
                  <button key={i} className="acitem" onMouseDown={() => choose(h, pickFrom)}>
                    <span className="hittag">{h.kind === 'stop' ? 'Stop' : h.kind === 'area' ? 'Area' : 'Place'}</span>
                    {h.name}{h.sub ? <span className="acsub"> {h.sub}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="arrow"><ArrowRight size={16} aria-hidden="true" /></div>

        <div className="field">
          <label>Destination</label>
          <div className="ac">
            <input value={toText} disabled={!from}
              placeholder={!from ? 'Choose a starting point first' : 'Where do you want to go?'}
              onChange={(e) => { setToText(e.target.value); if (to) { setTo(null); setPlan(null); setDayAlts({}) } }}
              onFocus={() => setToOpen(true)}
              onBlur={() => setToOpen(false)}
              onKeyDown={(e) => { if (e.key === 'Escape') e.currentTarget.blur() }} />
            <button className={`pinbtn ${armed === 'to' ? 'armed' : ''}`} disabled={!from} onClick={() => setArmed(armed === 'to' ? null : 'to')}><PinIcon /> Map</button>
            {toOpen && toHits.length > 0 && (
              <div className="acmenu">
                {toHits.map((h, i) => (
                  <button key={i} className="acitem" onMouseDown={() => choose(h, pickTo)}>
                    <span className="hittag">{h.kind === 'stop' ? 'Stop' : h.kind === 'area' ? 'Area' : 'Place'}</span>
                    {h.name}{h.sub ? <span className="acsub"> {h.sub}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* A toast, not a banner in the flow. Inserted above the picker it pushed the
          whole page - map included - down by its own height, which is a lot of movement
          for a message about one failed click. */}
      {pickError && (
        <div
          role="status"
          className="fixed top-4 left-1/2 z-50 flex -translate-x-1/2 items-start gap-2 rounded-lg border border-bad bg-bad px-3 py-2 text-[13px] text-white shadow-lg"
        >
          <CircleX size={16} aria-hidden="true" className="mt-px shrink-0" />
          <span>{pickError}</span>
          <button
            className="ml-2 cursor-pointer font-bold text-white/80 hover:text-white"
            onClick={() => setPickError(null)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <ModePicker />

      <div className="plancontent">
        <section className="planleft">
          {/* Every timetable, stop and fare here came from Golden Arrow, so turning it
              off leaves nothing to search. Saying so beats an empty result that looks
              like the journey does not exist. */}
          {modes.none && (
            <div className="placeholder">
              No transport selected. Everything this app knows about comes from
              <b> Golden Arrow</b>, so turn it back on above to plan a journey. Metro Rail
              and MyCiTi are not available yet.
            </div>
          )}
          {!modes.none && stage === 'from' && (
            <div className="placeholder">
              Type where you want to start. It can be a bus stop, or any place or address,
              even one that is not a listed stop like Woodstock. You can also tap <b>Map</b> and
              pick a point.
            </div>
          )}

          {!modes.none && stage === 'reachable' && (
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
                  <div className="empty">No direct bus goes to "{toText}" from here.</div>
                )}
              </div>

              {filteredConnecting.length > 0 && (
                <>
                  <div className="reachhead sub">
                    …and {filteredConnecting.length} more with one change of bus
                  </div>
                  <div className="browsehint">
                    No single bus runs the whole way, so these need you to change once. Pick
                    one and I will work out where to change and what time to be there.
                  </div>
                  <div className="reachlist">
                    {filteredConnecting.map((r) => (
                      <button key={r.id} className="reachitem connecting" onClick={() =>
                        pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                        <span className="rname">{r.name}</span>
                        <span className="rtrips">1 change</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </>
          )}

          {!modes.none && stage === 'journeys' && (
            <>
              <div className="reachhead">
                <b>{from!.name}</b> <span className="arrowin">to</span> <b>{to!.name}</b>
                <button className="link" onClick={() => { setTo(null); setToText(''); setPlan(null); setDayAlts({}) }}>Change destination</button>
              </div>
              {loading && <div className="placeholder">Finding buses…</div>}

              {/* Above the results, not below them. A shorter journey is only useful
                  before the rider has read and chosen from the long one. */}
              {!loading && !connLoading && betterNearby.length > 0 && bestLegs < Infinity && (
                <div className="altbox better">
                  <div className="altlbl">
                    <Lightbulb size={15} aria-hidden="true" className="alticon" />
                    <span>
                      <b>Suggestion.</b> {to!.name} needs {bestLegs} bus{bestLegs === 1 ? '' : 'es'},
                      but these stops nearby are quicker to reach.
                    </span>
                  </div>
                  <div className="altlist">
                    {betterNearby.map((r) => (
                      <button key={r.id} className="altitem" onClick={() =>
                        pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                        <span className="altname">{r.name}</span>
                        <span className="altmeta">
                          {r.km < 1 ? `${Math.round(r.km * 1000)} m` : `${r.km.toFixed(1)} km`} from{' '}
                          {to!.name} · {r.change ? '2 buses' : 'direct'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {plan && !loading && plan.length > 0 && (
                <div className="banner good">
                  <CircleCheck size={16} aria-hidden="true" />
                  <span><b>Direct bus.</b> You can travel from {from!.name} to {to!.name} without changing.</span>
                </div>
              )}

              {plan && !loading && plan.length === 0 && connLoading && (
                <div className="banner info">
                  <Info size={16} aria-hidden="true" />
                  <span>No direct bus. Looking for a journey with a change…</span>
                </div>
              )}

              {plan && !loading && plan.length === 0 && !connLoading && conns && conns.length > 0 && (
                <>
                  <div className="banner warn">
                    <TriangleAlert size={16} aria-hidden="true" />
                    <span>
                      <b>No direct bus</b> from {from!.name} to {to!.name}. You can still get there
                      by taking <b>{connLegs} buses</b>, changing at <b>{conns[0].change_at.join(' then ')}</b>.
                    </span>
                  </div>
                  <ConnectionsPanel connections={conns} legsRequired={connLegs} />
                </>
              )}

              {plan && !loading && plan.length === 0 && !connLoading && conns && conns.length === 0 && (
                <div className="banner bad">
                  <CircleX size={16} aria-hidden="true" />
                  <span>
                    <b>No way to get there by bus.</b> There is no direct service from {from!.name} to{' '}
                    {to!.name}, and no combination of up to three buses connects them either.
                  </span>
                </div>
              )}

              {plan && !loading && plan.length === 0 && !connLoading && conns && conns.length === 0
                && nearbyAlternatives.length > 0 && (
                <div className="altbox">
                  <div className="altlbl">
                    You can reach these stops near {to!.name}
                  </div>
                  <div className="altlist">
                    {nearbyAlternatives.map((r) => (
                      <button key={r.id} className="altitem" onClick={() =>
                        pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                        <span className="altname">{r.name}</span>
                        <span className="altmeta">
                          {r.km < 1 ? `${Math.round(r.km * 1000)} m` : `${r.km.toFixed(1)} km`} away
                          {r.change ? ' · 1 change' : ' · direct'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {plan && !loading && plan.length === 0 && !connLoading && conns === null && (
                <div className="banner bad">
                  <CircleX size={16} aria-hidden="true" />
                  <span>
                    <b>No direct bus.</b> Journeys with a change can only be worked out between
                    named bus stops, not dropped pins.
                  </span>
                </div>
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
                        {hasApprox(o) && <span className="approxpill">Approx times</span>}
                        <span className="daypill">{DAY_LABEL[o.day_type] ?? o.day_type}</span>
                      </span>
                    </div>
                    <FarePanel fare={o.fare} />
                    <div className="depshint">Tap a departure to see where you get on and off.</div>
                    {hasApprox(o) && (
                      <div className="aprxlegend">
                        The timetable prints no time for one of your stops.
                        <b>~05:20</b> means the bus cannot get there before 05:20 — be there
                        by then and allow extra. <b>no set time</b> means even that much is
                        not known; tap the departure to see the timed stops either side.
                      </div>
                    )}
                    {[...TIME_GROUPS, { key: 'other', label: 'Other times' }].map((g) =>
                      groups[g.key].length > 0 ? (
                        <div key={g.key} className="depgroup">
                          <div className="depgrouplbl">{g.label}</div>
                          <div className="depsgrid">
                            {groups[g.key].map(({ d, j }) => {
                              const planned = planner.has({
                                scheduleId: d.schedule_id, tripIndex: d.trip_index,
                                fromSeq: d.from_seq, toSeq: d.to_seq,
                              })
                              return (
                                <div key={j} className={`depwrap ${planned ? 'planned' : ''}`}>
                                  <button className={`dep ${openDep?.oi === i && openDep?.di === j ? 'on' : ''}`}
                                    onClick={() => selectDep(i, j, d)}>
                                    <span className="deptimes">
                                      <DepTime raw={d.board_raw} approx={d.board_approx} />
                                      <span className="da">to</span>
                                      <DepTime raw={d.arrive_raw} approx={d.arrive_approx}
                                        useful={boundIsUseful(d.arrive_minutes, d.arrive_approx, d.board_minutes)} />
                                    </span>
                                    {o.fare?.per_ride_cents != null && (
                                      <span className="depfare">{rands(o.fare.per_ride_cents)}</span>
                                    )}
                                  </button>
                                  <button
                                    className={`addbtn ${planned ? 'on' : ''}`}
                                    onClick={() => togglePlanned(o, d)}
                                    title={planned ? 'Remove from your planner' : 'Add to your planner'}
                                    aria-pressed={planned}
                                  >
                                    {planned ? '✓ Added' : '+ Add'}
                                  </button>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ) : null,
                    )}
                    {openDep?.oi === i && (
                      <TripStrip
                        stops={tripStops} loading={loadingTrip} notes={tripNotes}
                        riderFromSeq={o.departures[openDep.di]?.from_seq ?? 0}
                        riderToSeq={o.departures[openDep.di]?.to_seq ?? 9999}
                        boardPin={from?.kind === 'pin' ? { name: from.name, time: o.departures[openDep.di]?.board_raw } : null}
                        alightPin={to?.kind === 'pin' ? { name: to.name, time: o.departures[openDep.di]?.arrive_raw } : null}
                        boardTime={alightOrNone(o.departures[openDep.di], 'board')}
                        alightTime={alightOrNone(o.departures[openDep.di], 'alight')}
                        onClose={() => setOpenDep(null)}
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
            from={from} to={to} segment={segment} roadPath={roadPath} ride={ride}
            reachable={stage === 'reachable' && from ? [from, ...(reachable ?? [])] : undefined}
            onMapClick={onMapClick}
            armLabel={armed === 'from' ? 'your starting point' : armed === 'to' ? 'your destination' : null}
          />
        </section>
      </div>
    </div>
  )
}
