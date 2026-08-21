import { useCallback, useEffect, useState } from 'react'
import type { Endpoint, PlanDeparture, PlanOption } from './api'

/**
 * The journeys a commuter has put on their planner.
 *
 * Saved in localStorage: there are no user accounts, and losing a half-built plan on
 * refresh would be worse than the storage cost.
 *
 * What is stored is deliberately lean. A PlanOption carries `road_path`, which for a
 * cross-city trip is several thousand coordinate pairs — a handful of those would blow
 * the ~5 MB localStorage budget. Everything needed to redraw a journey's detail is
 * re-fetched from /api/trip_stops on demand, exactly as the search page does, so only
 * the identifying fields are kept here.
 */

const STORAGE_KEY = 'commuttr.planner.v1'

export interface SavedEndpoint {
  kind: 'stop' | 'pin'
  id?: number
  name: string
  lat: number
  lon: number
}

export interface SavedJourney {
  /** Stable identity for drag-and-drop and for React keys. */
  id: string
  from: SavedEndpoint
  to: SavedEndpoint
  route: {
    label: string
    timetableNumber: string
    dayType: string
    dayLabel: string
  }
  approx: { board: boolean; alight: boolean }
  departure: {
    boardRaw: string
    arriveRaw: string
    boardMinutes: number | null
    arriveMinutes: number | null
    scheduleId: number
    tripIndex: number
    fromSeq: number
    toSeq: number
  }
  addedAt: number
}

/** Just enough of a departure to identify the ride it refers to. */
export type RideKey = Pick<
  SavedJourney['departure'], 'scheduleId' | 'tripIndex' | 'fromSeq' | 'toSeq'
>

/** Identifies a specific ride, so the same departure cannot be added twice. */
export function rideKey(d: RideKey): string {
  return `${d.scheduleId}:${d.tripIndex}:${d.fromSeq}:${d.toSeq}`
}

export function journeyKey(j: Pick<SavedJourney, 'departure'>): string {
  return rideKey(j.departure)
}

function toSavedEndpoint(ep: Endpoint): SavedEndpoint {
  return { kind: ep.kind, id: ep.id, name: ep.name, lat: ep.lat, lon: ep.lon }
}

export function toEndpoint(ep: SavedEndpoint): Endpoint {
  return { kind: ep.kind, id: ep.id, name: ep.name, lat: ep.lat, lon: ep.lon }
}

export function buildJourney(
  from: Endpoint, to: Endpoint, option: PlanOption, departure: PlanDeparture,
): SavedJourney {
  return {
    id: `${departure.schedule_id}-${departure.trip_index}-${departure.from_seq}-${departure.to_seq}-${Date.now()}`,
    from: toSavedEndpoint(from),
    to: toSavedEndpoint(to),
    route: {
      label: option.route_label,
      timetableNumber: option.timetable_number,
      dayType: option.day_type,
      dayLabel: option.day_label,
    },
    approx: { board: option.board_approx, alight: option.alight_approx },
    departure: {
      boardRaw: departure.board_raw,
      arriveRaw: departure.arrive_raw,
      boardMinutes: departure.board_minutes,
      arriveMinutes: departure.arrive_minutes,
      scheduleId: departure.schedule_id,
      tripIndex: departure.trip_index,
      fromSeq: departure.from_seq,
      toSeq: departure.to_seq,
    },
    addedAt: Date.now(),
  }
}

function read(): SavedJourney[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as SavedJourney[]) : []
  } catch {
    // Corrupt or unavailable storage must never stop the app loading.
    return []
  }
}

/**
 * A connection problem between one journey and the next.
 *
 * Only raised when both legs run on the same day type and the times genuinely overlap.
 * A leg arriving at 23:50 followed by one departing 00:30 is a legitimate overnight
 * connection, not a mistake, so a gap of more than 12 hours is read as crossing midnight
 * rather than as an impossible sequence.
 */
export interface ConnectionIssue {
  index: number
  minutesShort: number
}

export function connectionIssues(journeys: SavedJourney[]): Map<number, ConnectionIssue> {
  const issues = new Map<number, ConnectionIssue>()
  for (let i = 0; i < journeys.length - 1; i++) {
    const a = journeys[i]
    const b = journeys[i + 1]
    if (a.route.dayType !== b.route.dayType) continue

    const arrive = a.departure.arriveMinutes
    const board = b.departure.boardMinutes
    if (arrive == null || board == null) continue

    const shortfall = arrive - board
    if (shortfall > 0 && shortfall < 12 * 60) {
      issues.set(i + 1, { index: i + 1, minutesShort: Math.round(shortfall) })
    }
  }
  return issues
}

/**
 * Planner state, shared across tabs by way of localStorage plus a window event so that
 * adding a journey on the search page updates the Planner tab's badge immediately.
 */
const CHANGED = 'commuttr:planner-changed'

export function usePlanner() {
  const [journeys, setJourneys] = useState<SavedJourney[]>(read)

  useEffect(() => {
    const sync = () => setJourneys(read())
    window.addEventListener(CHANGED, sync)
    window.addEventListener('storage', sync) // another tab changed it
    return () => {
      window.removeEventListener(CHANGED, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  const commit = useCallback((next: SavedJourney[]) => {
    setJourneys(next)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // Full or disabled storage: the planner still works for this session.
    }
    window.dispatchEvent(new Event(CHANGED))
  }, [])

  const add = useCallback((j: SavedJourney) => {
    const current = read()
    if (current.some((x) => journeyKey(x) === journeyKey(j))) return
    commit([...current, j])
  }, [commit])

  const remove = useCallback((id: string) => {
    commit(read().filter((x) => x.id !== id))
  }, [commit])

  /** Swap a journey for a different departure, keeping its place in the list. */
  const replace = useCallback((id: string, next: SavedJourney) => {
    commit(read().map((x) => (x.id === id ? { ...next, id: x.id } : x)))
  }, [commit])

  const reorder = useCallback((from: number, to: number) => {
    const next = read()
    if (from === to || from < 0 || to < 0 || from >= next.length || to >= next.length) return
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    commit(next)
  }, [commit])

  const clear = useCallback(() => commit([]), [commit])

  const has = useCallback(
    (d: RideKey) => journeys.some((x) => journeyKey(x) === rideKey(d)),
    [journeys],
  )

  const find = useCallback(
    (d: RideKey) => journeys.find((x) => journeyKey(x) === rideKey(d)),
    [journeys],
  )

  return { journeys, add, remove, replace, reorder, clear, has, find }
}
