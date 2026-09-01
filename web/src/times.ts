/**
 * How a time reads when the timetable does not publish one.
 *
 * Most Golden Arrow stops are printed as "via": the bus passes, but no time is given.
 * The most that can honestly be said is that it cannot get there before it left the last
 * stop that does have a time, so the API sends "from 05:20".
 *
 * Printed as-is that looks exactly like a real departure, and beside the word "to" it
 * came out as "05:20 to from 05:20" - which reads like a bug and tells a rider nothing.
 * Everything here exists to keep a guess visibly a guess.
 */

/** Shown wherever a bound would only repeat a time the rider already has. */
export const NO_TIME = 'no set time'

/** A time ready to show, and whether it is a real published one. */
export interface ShownTime {
  text: string
  approx: boolean
}

/** "05:20", "16:45b" - a real clock time, possibly with a footnote letter. */
const CLOCK = /\d{1,2}:\d{2}[a-z]?/i

function clockIn(raw: string): string | null {
  const m = raw.match(CLOCK)
  return m ? m[0] : null
}

/**
 * The short form, for a departure button where there is room for a few characters.
 *
 * A tilde is the shortest thing a reader already understands as "about". It is paired
 * everywhere with muted styling and a one-line legend, because a symbol alone is not an
 * explanation.
 */
export function shortTime(raw: string, approx: boolean): ShownTime {
  if (!approx) return { text: raw, approx: false }
  const clock = clockIn(raw)
  return clock ? { text: `~${clock}`, approx: true } : { text: NO_TIME, approx: true }
}

/**
 * The long form, for the trip breakdown, where whole words fit.
 *
 * "after 05:20" is what the data actually supports - a floor, not an estimate - and it
 * cannot be mistaken for a published departure.
 */
export function longTime(raw: string, approx: boolean): ShownTime {
  if (!approx) return { text: raw, approx: false }
  const clock = clockIn(raw)
  // No clock in it means the caller already chose the words - "via" for a stop the bus
  // merely passes, NO_TIME for one whose bound said nothing. Both are left alone.
  return clock ? { text: `after ${clock}`, approx: true } : { text: raw, approx: true }
}

/**
 * Does this bound actually tell the rider anything?
 *
 * Getting off at a via stop, the floor is the last timed stop before it - which is often
 * the very stop they got on at. "05:20 to after 05:20" is true and useless, and worse,
 * it hints the ride is instant. When the bound adds nothing beyond the boarding time,
 * say plainly that no time is published rather than repeat a number.
 */
export function boundIsUseful(
  bound: number | null,
  approx: boolean,
  boardMinutes: number | null,
): boolean {
  if (!approx) return true
  if (bound == null || boardMinutes == null) return true
  return bound > boardMinutes
}
