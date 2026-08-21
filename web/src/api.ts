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

export const getReachable = (id: number) =>
  getJSON<{ origin: StopHit; reachable: ReachableStop[] }>(`${API}/stops/${id}/reachable`)

export const getJourneys = (from: number, to: number) =>
  getJSON<JourneysResponse>(`${API}/journeys?from=${from}&to=${to}`)

// ---- pins / unofficial stops ----

export interface Endpoint {
  kind: 'stop' | 'pin'
  id?: number
  name: string
  lat: number
  lon: number
}

export interface GeoHit {
  name: string
  full: string
  lat: number
  lon: number
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

export const getTripStops = (scheduleId: number, tripIndex: number, fromSeq: number, toSeq: number) =>
  getJSON<{ stops: TripStop[] }>(
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
  day_type: string
  day_label: string
  segment_stops: SegmentStop[]
  road_path: [number, number][]
  departures: PlanDeparture[]
  board_approx: boolean
  alight_approx: boolean
  board_label: string
  alight_label: string
}

export const getGeocode = (q: string) =>
  getJSON<{ results: GeoHit[] }>(`${API}/geocode?q=${encodeURIComponent(q)}`)

export const getAreas = () => getJSON<{ areas: string[] }>(`${API}/areas`)

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

export const reachableFor = (ep: Endpoint) =>
  ep.kind === 'stop'
    ? getReachable(ep.id!).then((r) => r.reachable)
    : getReachablePoint(ep.lat, ep.lon).then((r) => r.reachable)

// ---- connections: journeys that need a change of bus ----

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
}

export interface Connection {
  day_type: string
  change_at: string[]
  legs: ConnectionLeg[]
  wait_minutes: number | null
  total_minutes: number | null
}

export interface ConnectionsResponse {
  from: StopHit
  to: StopHit
  /** How many buses the best answer needs, or null if none was found. */
  legs_required: number | null
  connections: Connection[]
}

export const getConnections = (from: number, to: number) =>
  getJSON<ConnectionsResponse>(`${API}/connections?from=${from}&to=${to}`)
