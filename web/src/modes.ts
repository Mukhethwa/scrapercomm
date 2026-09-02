import { useCallback, useEffect, useState } from 'react'

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
  { id: 'gabs', name: 'Golden Arrow', available: true, region: 'Cape Town',
    kind: 'bus', note: 'Buses across Cape Town' },
  { id: 'myciti', name: 'MyCiTi', available: false, region: 'Cape Town',
    kind: 'bus', note: 'Cape Town buses - not yet available' },
  { id: 'metrorail', name: 'Metro Rail', available: false, region: 'National',
    kind: 'train', note: 'Trains - not yet available' },
  { id: 'gautrain', name: 'Gautrain', available: false, region: 'Gauteng',
    kind: 'train', note: 'Gauteng trains - not yet available' },
  { id: 'reavaya', name: 'Rea Vaya', available: false, region: 'Johannesburg',
    kind: 'bus', note: 'Johannesburg buses - not yet available' },
  { id: 'metrobus', name: 'Metrobus', available: false, region: 'Johannesburg',
    kind: 'bus', note: 'Johannesburg buses - not yet available' },
  { id: 'aretaxi', name: 'Are Yeng', available: false, region: 'Pretoria',
    kind: 'bus', note: 'Tshwane buses - not yet available' },
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
