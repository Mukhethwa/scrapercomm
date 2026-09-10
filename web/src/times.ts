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
 *
 * A guess also has a DIRECTION, and getting that wrong is worse than showing no time at
 * all. There are three, and the API names each one rather than sending a bare clock:
 *
 *     "from 05:20"    a floor    the bus has left 05:20 behind; your stop comes later
 *     "by 06:30"      a ceiling  it reaches 06:30 further on; your stop comes sooner
 *     "about 07:12"   an estimate, timed stops on both sides, interpolated between them
 *
 * This file used to read every one of them as a floor and print "after". On the leg into
 * town that is precisely backwards - "Woodstock (your stop) after 06:30" above "CAPE TOWN
 * (terminus) 06:30" tells a rider to wait for a bus that has already gone past.
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
 * A published time, as a rider reads a clock.
 *
 * PRASA times its weekend trains to the half minute and prints it, so the sheets say
 * 05:32:30 and that is what the database keeps - the train really does pass at thirty
 * seconds past, and rounding it away in the scraper would be discarding source data.
 *
 * Nobody catches a train to the second. Shown in full it is noise in the largest type on
 * the card, and it reads like a stopwatch rather than a timetable, so the seconds are
 * dropped here at the point of display and nowhere earlier. A footnote letter survives,
 * because 16:45b and 16:45 are different departures.
 */
export function clockFace(raw: string): string {
  return clockIn(raw) ?? raw
}

/**
 * The short form, for a departure button where there is room for a few characters.
 *
 * A tilde is the shortest thing a reader already understands as "about". It is paired
 * everywhere with muted styling and a one-line legend, because a symbol alone is not an
 * explanation.
 *
 * One symbol for all three kinds of bound, deliberately. A tilde overstates nothing: a
 * floor, a ceiling and an interpolation are all approximate, and "about 06:30" is true of
 * each. Which way it leans is a sentence, and a sentence does not fit on a chip - it is
 * in the breakdown, one tap away, where longTime says it in words.
 */
export function shortTime(raw: string, approx: boolean): ShownTime {
  if (!approx) return { text: clockFace(raw), approx: false }
  const clock = clockIn(raw)
  return clock ? { text: `~${clock}`, approx: true } : { text: NO_TIME, approx: true }
}

/** The word the API put in front of a bound, if it put one there. */
const BOUND = /^(from|by|about)\s/i

/**
 * Is this a bound rather than a published time?
 *
 * For the two places that show a time without being handed a flag beside it: a
 * connection leg carries no approx field, and the value itself is the only thing that
 * knows. Both used to pull the clock out of "from 05:20" with a regex and print "05:20"
 * in the largest type on the card - the same overstatement as "after 06:30", made by
 * dropping the word instead of choosing the wrong one.
 */
export function isBound(raw: string | null | undefined): boolean {
  return !!raw && BOUND.test(raw)
}

/** How each bound reads in a sentence, where there is room for the whole word. */
const IN_WORDS: Record<string, string> = {
  from: 'after',
  by: 'before',
  about: 'about',
}

/**
 * The long form, for the trip breakdown, where whole words fit.
 *
 * The direction comes from the value, not from an assumption about it. A bound with no
 * word on it is a floor, which is what the connections queries send ("from 05:20" is
 * built in SQL) and what every published time is not; anything the API has already put
 * words around keeps them, translated into the ones a rider reads.
 */
export function longTime(raw: string, approx: boolean): ShownTime {
  if (!approx) return { text: clockFace(raw), approx: false }
  const clock = clockIn(raw)
  // No clock in it means the caller already chose the words - "via" for a stop the bus
  // merely passes, NO_TIME for one whose bound said nothing. Both are left alone.
  if (!clock) return { text: raw, approx: true }
  const m = raw.match(BOUND)
  const word = m ? IN_WORDS[m[1].toLowerCase()] : 'after'
  return { text: `${word} ${clock}`, approx: true }
}

/**
 * Does this bound actually tell the rider anything?
 *
 * Getting off at a via stop, the floor is the last timed stop before it - which is often
 * the very stop they got on at. "05:20 to after 05:20" is true and useless, and worse,
 * it hints the ride is instant. When the bound adds nothing beyond the boarding time,
 * say plainly that no time is published rather than repeat a number.
 *
 * The same test holds for the other two directions, for a different reason: a ceiling or
 * an estimate at or before the moment you board describes a bus arriving before it left,
 * which is not a weak answer but a wrong one, and is better not shown.
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
