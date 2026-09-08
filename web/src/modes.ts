import { useCallback, useEffect, useState } from 'react'
import { getOperators } from './api'

/**
 * The transport a journey can use.
 *
 * Only Golden Arrow is carried today - every timetable, stop and fare in the database
 * came from them - so the others are listed but cannot be chosen. They are shown rather
 * than hidden because a rider looking for a train needs to know the app does not have
 * one yet, not be left wondering whether they searched wrongly.
 */
export interface Mode {
  id: string
  name: string
  /** Whether there is any data behind it. False means listed, not selectable. */
  available: boolean
  /** Where it runs, so somebody outside Cape Town can see themselves on the list. */
  region: string
  kind: 'bus' | 'train'
  note: string
}

export const MODES: Mode[] = [
  // Cape Town
  { id: 'gabs', name: 'Golden Arrow', available: true, region: 'Cape Town',
    kind: 'bus', note: 'Buses across Cape Town' },
  { id: 'myciti', name: 'MyCiTi', available: false, region: 'Cape Town',
    kind: 'bus', note: 'Cape Town buses' },
  { id: 'metrorail', name: 'Metro Rail', available: false, region: 'National',
    kind: 'train', note: 'Passenger trains' },
  // The rest of the Western Cape
  { id: 'gogeorge', name: 'Go George', available: false, region: 'George',
    kind: 'bus', note: 'George buses' },
  // Gauteng
  { id: 'gautrain', name: 'Gautrain', available: false, region: 'Gauteng',
    kind: 'train', note: 'Gauteng trains' },
  { id: 'reavaya', name: 'Rea Vaya', available: false, region: 'Johannesburg',
    kind: 'bus', note: 'Johannesburg buses' },
  { id: 'metrobus', name: 'Metrobus', available: false, region: 'Johannesburg',
    kind: 'bus', note: 'Johannesburg buses' },
  { id: 'putco', name: 'PUTCO', available: false, region: 'Gauteng',
    kind: 'bus', note: 'Gauteng buses' },
  { id: 'areyeng', name: 'A Re Yeng', available: false, region: 'Tshwane',
    kind: 'bus', note: 'Tshwane buses' },
  // The rest of the country
  { id: 'algoa', name: 'Algoa Bus', available: false, region: 'Gqeberha',
    kind: 'bus', note: 'Gqeberha buses' },
  { id: 'peoplemover', name: 'People Mover', available: false, region: 'Durban',
    kind: 'bus', note: 'Durban buses' },
  { id: 'ibl', name: 'Interstate', available: false, region: 'Bloemfontein',
    kind: 'bus', note: 'Bloemfontein buses' },
]

const STORAGE_KEY = 'commuttr:modes'
const CHANGED = 'commuttr:modes-changed'
const DEFAULT: string[] = ['gabs']

function read(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return DEFAULT
    // Only ids we still know about, and only ones with data behind them: a saved choice
    // must never be able to turn on transport the app cannot actually plan.
    const ok = parsed.filter((id) =>
      MODES.some((m) => m.id === id && m.available))
    return ok as string[]
  } catch {
    return DEFAULT
  }
}

/** The chosen transport, shared across the app and remembered between visits. */
export function useModes() {
  const [selected, setSelected] = useState<string[]>(read)

  useEffect(() => {
    const sync = () => setSelected(read())
    window.addEventListener(CHANGED, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(CHANGED, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  const toggle = useCallback((id: string) => {
    const mode = MODES.find((m) => m.id === id)
    if (!mode?.available) return
    const next = read().includes(id)
      ? read().filter((x) => x !== id)
      : [...read(), id]
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // A private window can refuse to store; the choice still applies for this visit.
    }
    setSelected(next)
    window.dispatchEvent(new Event(CHANGED))
  }, [])

  return {
    selected,
    toggle,
    has: (id: string) => selected.includes(id),
    /** Nothing to search. Every result in the app comes from Golden Arrow. */
    none: selected.length === 0,
  }
}


/**
 * Which operators the API can actually plan with.
 *
 * The `available` flags in MODES above say what the app is built to support. This says
 * what is loaded right now, which is not the same thing and is the honest basis for
 * deciding whether a filter chip can be pressed: a chip that returns nothing is worse
 * than one that visibly is not ready.
 *
 * Until the answer arrives, the static flags stand. That keeps Golden Arrow pressable on
 * first paint rather than making every rider wait on a round trip to learn that the app
 * has buses.
 */
export function useLoadedOperators() {
  const [loaded, setLoaded] = useState<Set<string> | null>(null)

  useEffect(() => {
    let live = true
    getOperators()
      .then((r) => {
        if (!live) return
        // An operator with routes but no departures has been half-loaded; it cannot
        // answer a search, so it does not count as ready.
        setLoaded(new Set(r.operators.filter((o) => o.departures > 0).map((o) => o.code)))
      })
      .catch(() => { /* an older API has no such endpoint; the static flags stand */ })
    return () => { live = false }
  }, [])

  return {
    /** Whether this operator can answer a search right now. */
    ready: (id: string) => {
      if (loaded === null) return MODES.find((m) => m.id === id)?.available ?? false
      return loaded.has(id)
    },
    known: loaded !== null,
  }
}
