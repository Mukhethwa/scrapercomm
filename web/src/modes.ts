import { useCallback, useEffect, useState } from 'react'
import { getOperators } from './api'

/**
 * The transport a journey can use.
 *
 * Three are carried: Golden Arrow, Metrorail and MyCiTi. The rest are listed but cannot
 * be chosen - shown rather than hidden, because somebody in Gqeberha looking for Algoa
 * needs to know the app does not have it yet, not be left wondering whether they searched
 * wrongly.
 *
 * `available` is only the static fallback. What a chip can actually do is decided by
 * useLoadedOperators below, which asks the API what has departures behind it - so a clone
 * of this repository with no MyCiTi data greys the chip out without anyone editing this
 * list.
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
  { id: 'myciti', name: 'MyCiTi', available: true, region: 'Cape Town',
    kind: 'bus', note: 'Cape Town bus rapid transit' },
  { id: 'metrorail', name: 'Metro Rail', available: true, region: 'National',
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
/**
 * What was loaded last time this browser asked.
 *
 * /api/operators is a network round trip, and until it answers the chips fall back to the
 * static list - where Metrorail is false, because that list is what a clone with no train
 * data should believe. So every refresh greyed the Metro Rail chip out and lit it again a
 * moment later, which reads as the app deciding whether trains work.
 *
 * Remembering the last answer removes the flicker without lying: a browser that has seen
 * trains starts by assuming trains, and the fetch corrects it either way. A browser that
 * has never seen them still starts from the static list, so a deployment without train
 * data never shows a chip that would return nothing.
 */
const REMEMBERED = 'commuttr.operators'

function remembered(): Set<string> | null {
  try {
    const raw = localStorage.getItem(REMEMBERED)
    return raw ? new Set(JSON.parse(raw) as string[]) : null
  } catch {
    return null      // private window, cleared storage, a browser that refuses
  }
}

export function useLoadedOperators() {
  const [loaded, setLoaded] = useState<Set<string> | null>(remembered)
  const [names, setNames] = useState<Record<string, string>>({})

  useEffect(() => {
    let live = true
    getOperators()
      .then((r) => {
        if (!live) return
        try {
          localStorage.setItem(REMEMBERED, JSON.stringify(
            r.operators.filter((o) => o.departures > 0).map((o) => o.code)))
        } catch { /* storage is a convenience here, never a requirement */ }
        // An operator with routes but no departures has been half-loaded; it cannot
        // answer a search, so it does not count as ready.
        setLoaded(new Set(r.operators.filter((o) => o.departures > 0).map((o) => o.code)))
        setNames(Object.fromEntries(r.operators.map((o) => [o.code, o.name])))
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
    /**
     * What to call an operator on screen.
     *
     * From the API rather than a table in here, so a card headed with an operator's name
     * is headed with the name that operator is loaded under - and adding MyCiTi is still
     * a matter of loading its timetables.
     */
    nameOf: (id: string | undefined) =>
      (id && names[id]) || MODES.find((m) => m.id === id)?.name || 'Golden Arrow Buses',
    known: loaded !== null,
  }
}
