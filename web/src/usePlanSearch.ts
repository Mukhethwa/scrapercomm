/**
 * The search behind the planner: two endpoints, and everything that follows from them.
 *
 * This was the top third of PlanView. It moved out when a second results layout was
 * started, because the searching is not what differs between the two - the drawing is.
 * Duplicating it would have meant every fix to the connection fallback, the day
 * alternatives or the nearby-stop suggestions landing twice, or more likely once.
 *
 * It returns its whole surface rather than a curated slice, so a view can destructure
 * exactly the names it used to declare and its own markup needs no rewriting.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  getStops, getGeocode, getAreas, reachableFor, connectingFor, getPlan, getTripStops,
  getNearbyOrigins, getConnections,
  type StopHit, type GeoHit, type ReachableStop, type ConnectingStop, type Endpoint,
  type PlanOption, type PlanDeparture, type TripStop, type TripNote, type NearbyOrigin,
  type Connection,
} from './api'
import { useModes } from './modes'
import { buildJourney, usePlanner } from './planner'

/** A suggestion in either endpoint field: a real stop, a geocoded place, or an area. */
export interface Hit {
  kind: 'stop' | 'place' | 'area'
  id?: number
  name: string
  lat: number | null
  lon: number | null
  sub?: string
  /** For a stop: 'bus' or 'train'. RETREAT is both, and they are different places. */
  mode?: 'bus' | 'train'
  /** Which operator serves it, so a card can be headed with their name. */
  operator?: string
}

/** The three day types every journey is published for. */
export const CORE_DAYS = ['WEEKDAY', 'SATURDAY', 'SUNDAY']

export function useDebounced<T>(v: T, ms: number): T {
  const [s, setS] = useState(v)
  useEffect(() => {
    const t = setTimeout(() => setS(v), ms)
    return () => clearTimeout(t)
  }, [v, ms])
  return s
}

/** Stops, places and areas for one query, in the order the menu shows them. */
export async function mergedSearch(q: string, areas: string[],
                                   railAreas: Set<string> = new Set(),
                                   operator: string | null = null): Promise<Hit[]> {
  const [s, g] = await Promise.all([
    getStops(q).catch(() => ({ stops: [] as StopHit[] })),
    getGeocode(q).catch(() => ({ results: [] as GeoHit[] })),
  ])
  const ql = q.trim().toLowerCase()
  /*
   * An area says which networks a rider will actually find in it.
   *
   * Only where it can be shown: an area is a name no stop carries, so nothing about the
   * name says whether there is a station, and the API answers it from geography instead.
   * Where it cannot be shown the line stays as it was, because "bus service" understates
   * an area and "bus and train" in one that has no station sends somebody looking for a
   * platform that is not there.
   */
  // An area is a name Golden Arrow uses for a part of the city, so under a train filter
  // it belongs in the list only where a station stands in it - which is the one thing
  // railAreas already knows.
  const areaHits: Hit[] = areas
    .filter((a) => a.toLowerCase().includes(ql))
    .filter((a) => !operator || operator === 'gabs' || railAreas.has(a))
    .slice(0, 3)
    .map((a) => ({
      kind: 'area', name: a, lat: 0, lon: 0,
      sub: railAreas.has(a) ? 'area with bus and train service' : 'area with bus service',
    }))
  /*
   * Every stop the API returned, whether or not it has been geocoded.
   *
   * This used to drop any stop with no coordinates, which quietly hid 247 of the 527
   * stops in the network - Steenberg among them - from the search box. The stops were
   * never the problem: a plan is requested by stop id, so STEENBERG to CAPE TOWN
   * resolves six routes and twenty-three departures whether or not we know where
   * Steenberg is. Only the map needs a position, and a missing pin is a far smaller
   * failure than an unreachable destination.
   */
  // Only the operator the rider has chosen. RETREAT is a bus stop and a station, and
  // offering both under a Metro Rail filter means one of the two answers leads to an
  // empty screen - the results are filtered even though the suggestion was not.
  const stops: Hit[] = s.stops
    .filter((x) => !operator || x.operator_code === operator)
    .slice(0, 6)
    .map((x) => ({ kind: 'stop', id: x.id, name: x.name, lat: x.lat, lon: x.lon,
                   mode: x.operator_kind, operator: x.operator_code }))
  const places: Hit[] = g.results.slice(0, 3)
    .map((x) => ({ kind: 'place', name: x.name, lat: x.lat, lon: x.lon, sub: x.full }))
  return [...areaHits, ...stops, ...places]
}

/**
 * @param operator when a rider has narrowed the screen to one operator, its code. The
 *        chip is not a filter on the results alone: choosing Metro Rail and then being
 *        offered a Golden Arrow stop, whose journeys are then filtered away to nothing,
 *        is the app disagreeing with itself. Null means All.
 */
export function usePlanSearch(operator: string | null = null) {
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
  const [railAreas, setRailAreas] = useState<Set<string>>(new Set())

  useEffect(() => {
    getAreas().then((r) => {
      setAreas(r.areas)
      setRailAreas(new Set(r.railAreas ?? []))
    }).catch(() => {})
  }, [])

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
    if (h.kind === 'stop') {
      return { kind: 'stop', id: h.id, name: h.name, lat: h.lat, lon: h.lon,
               mode: h.mode, operator: h.operator }
    }
    if (h.kind === 'place') return { kind: 'pin', name: h.name, lat: h.lat, lon: h.lon }

    const words = h.name.split(/\s+/).filter(Boolean)
    for (let n = words.length; n > 0; n--) {
      const r = await getStops(words.slice(0, n).join(' ')).catch(() => ({ stops: [] as StopHit[] }))
      // A located stop is preferable - it can be drawn - but an unlocated one still
      // plans, so it beats falling through to a geocoded guess at the area's name.
      const hit = r.stops.find((x) => x.lat != null && x.lon != null) ?? r.stops[0]
      if (hit) {
        return { kind: 'stop', id: hit.id, name: hit.name, lat: hit.lat, lon: hit.lon,
                 mode: hit.operator_kind, operator: hit.operator_code }
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
  /**
   * On a phone the map used to take a fixed 360px of a 640px screen, leaving the times
   * in a letterbox above it. It is a view you switch to now, so whichever one you are
   * reading gets the whole screen. Desktop is unaffected - there is room for both.
   */
  const [mapOpen, setMapOpen] = useState(false)
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
    mergedSearch(debFrom, areas, railAreas, operator).then(setFromHits)
      .catch(() => setFromHits([]))
  }, [debFrom, areas]) // eslint-disable-line

  useEffect(() => {
    if (!from || !debTo || (to && to.name === debTo)) { setToHits([]); return }
    mergedSearch(debTo, areas, railAreas, operator).then(setToHits)
      .catch(() => setToHits([]))
  }, [debTo, from, areas, operator]) // eslint-disable-line

  /** Empty the starting point and everything that depended on it. */
  function clearFrom() {
    setFrom(null); setFromText(''); setFromHits([]); setArmed(null); setPickError(null)
    setTo(null); setToText(''); setToHits([])
    setPlan(null); setReachable(null); setConnecting([]); setDayAlts({})
    setConns(null); setConnLegs(null); setOpenDep(null); setTripStops(null); setSel(0)
  }

  /** Empty the destination. The starting point, and what it can reach, stay. */
  function clearTo() {
    setTo(null); setToText(''); setToHits([]); setArmed(null); setPickError(null)
    setPlan(null); setDayAlts({}); setConns(null); setConnLegs(null)
    setOpenDep(null); setTripStops(null); setSel(0)
  }

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
        // Nothing direct. Look for a journey with a change.
        //
        // Asked for whatever the endpoints are now. This used to be skipped unless both
        // were named stops, so a rider who searched a place was told a journey with a
        // change could not be worked out - a statement about the endpoint, not about the
        // network. They walk to a stop like anybody else.
        if (r.options.length === 0) {
          setConnLoading(true)
          getConnections(f, t)
            .then((c) => { setConns(c.connections); setConnLegs(c.legs_required) })
            .catch(() => { setConns([]); setConnLegs(null) })
            .finally(() => setConnLoading(false))
        }
        // The "on other days" suggestions are distance-based, so they need a located
        // origin. Without one the plan still stands; only this extra is skipped.
        if (t.kind === 'stop' && f.lat != null && f.lon != null) {
          const fromLat = f.lat
          const fromLon = f.lon
          const present = new Set(r.options.map((o) => o.day_type))
          CORE_DAYS.filter((d) => !present.has(d)).forEach((day) => {
            getNearbyOrigins(fromLat, fromLon, t.id!, {
              exclude: f.kind === 'stop' ? f.id : undefined, dayType: day, radius: 8000,
            })
              .then((n) => { if (n.origins.length) setDayAlts((p) => ({ ...p, [day]: n.origins.slice(0, 3) })) })
              .catch(() => {})
          })
        }
      })
      .finally(() => setLoading(false))
  }

  /**
   * Turn the journey around.
   *
   * Not pickFrom followed by pickTo: pickFrom clears the destination, because choosing a
   * new starting point normally invalidates it. Here both ends are known and only their
   * order changes, so they are set together and the search is run once.
   *
   * Both ends or nothing. The destination field is disabled until a starting point
   * exists, so swapping with only one end set would leave a filled box the rider cannot
   * edit and an empty one above it.
   */
  function swapEnds() {
    if (!from || !to) return
    const nextFrom = to
    const nextTo = from
    const nextFromText = toText
    const nextToText = fromText

    setFrom(nextFrom); setTo(nextTo)
    setFromText(nextFromText); setToText(nextToText)
    setFromHits([]); setToHits([]); setArmed(null); setSel(0)
    setPlan(null); setDayAlts({}); setOpenDep(null); setTripStops(null)
    setConns(null); setConnLegs(null); setPickError(null)
    setReachable(null); setConnecting([])

    if (nextFrom) {
      reachableFor(nextFrom).then(setReachable).catch(() => setReachable([]))
      connectingFor(nextFrom).then(setConnecting).catch(() => setConnecting([]))
    }
    if (nextFrom && nextTo) runPlan(nextFrom, nextTo)
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
  /**
   * The stops the map marks.
   *
   * segment_stops belongs to the OPTION, and an option groups every bus on that route
   * and day - so it lists every stop any of them might serve. A given departure is one
   * trip, and trips skip stops: the 05:30 out of BUH REIN calls at N1 FREEWAY and CAPE
   * TOWN and nothing else, while the option lists seven. Numbering the option's stops
   * put four on the map that the selected bus drives straight past.
   *
   * So once a departure is open the map follows that trip, which is the same list the
   * breakdown underneath is showing. The road line stays the option's: every trip on the
   * route drives the same road, it just does not stop everywhere along it.
   */
  const segment = useMemo(() => {
    if (stage !== 'journeys' || !plan || !plan[sel]) return undefined
    if (openDep?.oi === sel && tripStops) return tripStops
    return plan[sel].segment_stops
  }, [stage, plan, sel, openDep, tripStops])
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

  return {
    // endpoints and their fields
    from, setFrom, to, setTo, fromText, setFromText, toText, setToText,
    fromHits, setFromHits, toHits, setToHits,
    fromOpen, setFromOpen, toOpen, setToOpen,
    areas, debFrom, debTo,
    // results
    plan, setPlan, loading, sel, setSel,
    reachable, setReachable, connecting, setConnecting,
    conns, connLegs, connLoading,
    dayAlts, setDayAlts, altDays,
    // the open departure and its trip breakdown
    openDep, setOpenDep, tripStops, tripNotes, loadingTrip,
    // map
    mapOpen, setMapOpen, armed, setArmed, onMapClick, segment, roadPath, ride,
    // errors and stage
    pickError, setPickError, stage,
    // derived suggestions
    filteredReach, filteredConnecting, nearbyAlternatives, betterNearby, bestLegs,
    // actions
    choose, resolveHit, pickFrom, pickTo, clearFrom, clearTo, swapEnds, runPlan,
    useAlt, selectDep, togglePlanned,
    // shared services
    modes, planner,
  }
}
