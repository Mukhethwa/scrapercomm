export interface RouteSummary {
  id: number
  name: string
  origin: string
  destination: string
  letter_group: string
  timetable_count: number
}

export interface Timetable {
  id: number
  timetable_number: string
  is_public_holiday: boolean
  effective_from: string | null
  effective_to: string | null
  pdf_filename: string
  pdf_url: string
  page_count: number
  parse_status?: string
}

export interface Stop {
  stop_sequence: number
  name: string
  lat: number | null
  lon: number | null
}

export interface Cell {
  stop_sequence: number
  cell_type: 'TIME' | 'VIA' | 'NONE'
  departure_time: string | null
  note_code: string | null
  raw_value: string
}

export interface Trip {
  trip_index: number
  note_codes: string[] | null
  cells: Cell[]
}

export interface Schedule {
  id: number
  page_number: number
  direction_index: number
  direction_label: string
  day_type: string
  day_label: string
  section_timetable_number: string | null
  no_service: boolean
  stops: Stop[]
  trips: Trip[]
}

export interface Note {
  code: string
  description: string
}

export interface RouteDetail {
  route: RouteSummary
  timetables: Timetable[]
}

export interface TimetableDetail {
  timetable: Record<string, unknown>
  notes: Note[]
  schedules: Schedule[]
}

const API = '/api'

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${url}`)
  return res.json() as Promise<T>
}

export const getRoutes = (q: string) =>
  getJSON<{ routes: RouteSummary[] }>(`${API}/routes?q=${encodeURIComponent(q)}`)

export const getRoute = (id: number) => getJSON<RouteDetail>(`${API}/routes/${id}`)

export const getTimetable = (id: number) =>
  getJSON<TimetableDetail>(`${API}/timetables/${id}`)

// ---- Journey planner ----

export interface StopHit {
  /** Who serves it. Two stops can share a name across operators. */
  operator_code?: string
  operator_kind?: 'bus' | 'train'

  id: number
  name: string
  lat: number | null
  lon: number | null
}

export interface ReachableStop extends StopHit {
  trip_count: number
  route_count: number
}

export interface Departure {
  board_time: string | null
  board_raw: string
  board_type: string
  note_code: string | null
  arrive_time: string | null
  arrive_raw: string
  arrive_type: string
}

export interface SegmentStop {
  name: string
  lat: number | null
  lon: number | null
  stop_sequence: number
}

export interface JourneyOption {
  timetable_number: string
  route_label: string
  day_type: string
  day_label: string
  timetable_ids: number[]
  segment_stops: SegmentStop[]
  departures: Departure[]
}

export interface JourneysResponse {
  from: StopHit
  to: StopHit
  options: JourneyOption[]
}

export const getStops = (q: string) =>
  getJSON<{ stops: StopHit[] }>(`${API}/stops?q=${encodeURIComponent(q)}`)

/** A destination that needs one change of bus; change_count is how many stops you could change at. */
export interface ConnectingStop extends StopHit {
  change_count: number
}

export const getReachable = (id: number) =>
  getJSON<{ origin: StopHit; reachable: ReachableStop[]; connecting: ConnectingStop[] }>(
    `${API}/stops/${id}/reachable`)

export const getJourneys = (from: number, to: number) =>
  getJSON<JourneysResponse>(`${API}/journeys?from=${from}&to=${to}`)

// ---- pins / unofficial stops ----

export interface Endpoint {
  kind: 'stop' | 'pin'
  id?: number
  name: string
  /**
   * Bus stop or railway station, when it is a named stop.
   *
   * Not sent to the API - a stop is planned by its id alone. It is here so the screen can
   * say "on one train" to somebody standing at RETREAT station, rather than telling every
   * rider about buses whichever network they are on.
   */
  mode?: 'bus' | 'train'
  /** Which operator serves it, e.g. 'gabs', 'metrorail'. Not sent to the API. */
  operator?: string
  /**
   * Where it is, if we know.
   *
   * Nullable because a named stop does not need coordinates to be planned with: epParams
   * sends a stop as its id alone, and the API resolves the timetables from that. Only the
   * map and the distance sums need a position, and both can say nothing instead.
   *
   * A dropped pin always has both - it is defined by them.
   */
  lat: number | null
  lon: number | null
}

export interface GeoHit {
  name: string
  full: string
  lat: number
  lon: number
}

/** What a ride costs, or absent where the operator publishes no fare for it. */
export interface Fare {
  code: string | null
  per_ride_cents: number | null
  five_ride_cents: number | null
  weekly_cents: number | null
  monthly_cents: number | null
  transfers: string | null
  /** exact | section | route - where the number came from. */
  basis: string
  basis_from: string | null
  basis_to: string | null
  /** The stop is not named on the fare page; the fare is the one for its area. */
  zone_approx: boolean
  /**
   * What a cash passenger pays, for the 21 routes Golden Arrow publishes a cash fare
   * for. Null everywhere else - it is published nowhere else, and cannot be worked out
   * from the card price: one card fare covers both Atlantis and Darling to Cape Town,
   * which cost R52.50 and R85.50 in cash.
   */
  cash_cents: number | null
  /** The date that cash fare took effect, so the app can say how old it is. */
  cash_effective_from: string | null
}

export interface PlanDeparture {
  board_raw: string
  board_approx: boolean
  board_minutes: number | null
  arrive_raw: string
  arrive_approx: boolean
  arrive_minutes: number | null
  schedule_id: number
  trip_index: number
  from_seq: number
  to_seq: number
  /** Stops between getting on and off, both ends excluded. */
  stop_count: number
}

export interface TripStop {
  name: string
  lat: number | null
  lon: number | null
  stop_sequence: number
  raw_value: string
  cell_type: string
  departure_time: string | null
}

export interface TripNote {
  code: string
  description: string
}

export const getTripStops = (scheduleId: number, tripIndex: number, fromSeq: number, toSeq: number) =>
  getJSON<{ stops: TripStop[]; notes: TripNote[] }>(
    `${API}/trip_stops?schedule_id=${scheduleId}&trip_index=${tripIndex}&from_seq=${fromSeq}&to_seq=${toSeq}`,
  )

export interface NearbyOrigin {
  id: number
  name: string
  lat: number
  lon: number
  distance_m: number
  trip_count: number
  earliest: string | null
}

export const getNearbyOrigins = (
  lat: number, lon: number, to: number,
  opts: { exclude?: number; dayType?: string; radius?: number } = {},
) => {
  const q = new URLSearchParams({ lat: String(lat), lon: String(lon), to: String(to) })
  if (opts.exclude != null) q.set('exclude', String(opts.exclude))
  if (opts.dayType) q.set('day_type', opts.dayType)
  if (opts.radius) q.set('radius', String(opts.radius))
  return getJSON<{ origins: NearbyOrigin[] }>(`${API}/nearby_origins?${q.toString()}`)
}

export interface PlanOption {
  timetable_number: string
  route_label: string
  /** Who runs it: 'gabs', 'metrorail'. Matches the ids in modes.ts. */
  operator_code?: string
  operator_name?: string
  operator_kind?: 'bus' | 'train'
  day_type: string
  day_label: string
  segment_stops: SegmentStop[]
  road_path: [number, number][]
  departures: PlanDeparture[]
  board_approx: boolean
  alight_approx: boolean
  board_label: string
  alight_label: string
  /** Metres from the searched place to the boarding point, or null if you are on it. */
  board_away_m: number | null
  alight_away_m: number | null
  fare: Fare | null
}

export const getGeocode = (q: string) =>
  getJSON<{ results: GeoHit[] }>(`${API}/geocode?q=${encodeURIComponent(q)}`)

export const getAreas = () =>
  getJSON<{ areas: string[]; railAreas?: string[] }>(`${API}/areas`)

/** An operator the API can actually plan with, and how much of it is loaded. */
export interface OperatorInfo {
  code: string
  name: string
  kind: 'bus' | 'train'
  routes: number
  departures: number
}

export const getOperators = () =>
  getJSON<{ operators: OperatorInfo[] }>(`${API}/operators`)

export const getReachablePoint = (lat: number, lon: number) =>
  getJSON<{ reachable: ReachableStop[] }>(`${API}/reachable_point?lat=${lat}&lon=${lon}`)

function epParams(prefix: string, ep: Endpoint): string {
  return ep.kind === 'stop'
    ? `${prefix}=${ep.id}`
    : `${prefix}_lat=${ep.lat}&${prefix}_lon=${ep.lon}`
}

export const getPlan = (from: Endpoint, to: Endpoint) =>
  getJSON<{ from: unknown; to: unknown; options: PlanOption[] }>(
    `${API}/plan?${epParams('from', from)}&${epParams('to', to)}`,
  )

/** Destinations needing one change. Only stops have them; a pin falls back to none. */
export const connectingFor = (ep: Endpoint) =>
  ep.kind === 'stop' && ep.id != null
    ? getReachable(ep.id).then((r) => r.connecting ?? [])
    : Promise.resolve([] as ConnectingStop[])

export const reachableFor = (ep: Endpoint) =>
  ep.kind === 'stop'
    ? getReachable(ep.id!).then((r) => r.reachable)
    : getReachablePoint(ep.lat!, ep.lon!).then((r) => r.reachable)

// ---- connections: journeys that need a change of bus ----

/** What a whole multi-bus journey costs: one through-ticket, or one per bus. */
export interface ConnectionFare {
  kind: 'through' | 'per_leg'
  tickets: number
  per_ride_cents: number | null
  five_ride_cents: number | null
  weekly_cents: number | null
  monthly_cents: number | null
  /** The whole journey in cash, and when that fare was published. Null unless every
   *  leg has one - a sum missing a leg is not a total. */
  cash_cents: number | null
  cash_effective_from: string | null
  code: string | null
  transfers: string | null
  basis: string
  basis_from: string | null
  basis_to: string | null
  zone_approx: boolean
}

export interface ConnectionLeg {
  from_stop_id: number
  from_name: string
  from_lat: number | null
  from_lon: number | null
  to_stop_id: number
  to_name: string
  to_lat: number | null
  to_lon: number | null
  route_label: string
  timetable_number: string | null
  board_raw: string
  /** The literal timetable cell: "via" where no arrival time is published. */
  arrive_raw: string
  board_minutes: number | null
  arrive_minutes: number | null
  schedule_id: number
  trip_index: number
  from_seq: number
  to_seq: number
  fare: Fare | null
}

export interface Connection {
  day_type: string
  change_at: string[]
  legs: ConnectionLeg[]
  wait_minutes: number | null
  total_minutes: number | null
  fare: ConnectionFare | null
}

export interface ConnectionsResponse {
  from: StopHit
  to: StopHit
  /** How many buses the best answer needs, or null if none was found. */
  legs_required: number | null
  connections: Connection[]
}

/**
 * A journey with a change, between two endpoints of any kind.
 *
 * A stop goes as its id and a dropped point as its coordinates, the same way /api/plan
 * takes them - the engine walks a point to the nearest stop that can make the journey.
 */
export const getConnections = (from: Endpoint, to: Endpoint) =>
  getJSON<ConnectionsResponse>(
    `${API}/connections?${epParams('from', from)}&${epParams('to', to)}`)

/** Whose timetables these are, and when they were last read. */
export interface AboutResponse {
  operators: { code: string; name: string; kind: string; routes: number; timetables: number }[]
  last_scraped: string | null
  oldest_timetable: string | null
  newest_timetable: string | null
  stops: number
}

export const getAbout = () => getJSON<AboutResponse>(`${API}/about`)
