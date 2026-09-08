/**
 * Turning a plan into the operator-grouped, time-ordered blocks the results screen shows.
 *
 * The API answers a plan as one option per route, each holding that route's whole day of
 * departures. Stacked down the page that is a wall: three operators running four routes
 * each is twelve cards before a rider has compared a single time. So the screen inverts
 * it - one card per operator, and inside it a single run of departures drawn from every
 * route that operator runs, in time order, so "what leaves next" is one glance and not
 * twelve.
 *
 * Flattening loses the route each departure belongs to, which matters twice: a rider
 * needs to know which bus to look for, and the map draws the road the chosen one takes.
 * Every block therefore carries its option's index home again.
 */
import type { Fare, PlanDeparture, PlanOption } from './api'
import { NO_TIME, boundIsUseful } from './times'

/** One departure, lifted out of its route and ready to stand on its own. */
export interface DepartureBlock {
  /** Index into the original plan array. The map reads road_path through this. */
  optionIndex: number
  /** Index within that option's departures, which is what the planner keys on. */
  departureIndex: number
  departure: PlanDeparture
  /** "KHAYELITSHA - HARARE - BELLVILLE". There is no short route number in the data. */
  routeLabel: string
  /** "006201". The only number the operator actually prints against a route. */
  timetableNumber: string
  /** Belongs to the route, not the departure: no published fare varies by time of day. */
  fare: Fare | null
  /**
   * WEEKDAY, SATURDAY or SUNDAY.
   *
   * A plan comes back covering every day the route runs, and flattening them into one
   * time-ordered row put a Saturday bus beside a Tuesday one with nothing to tell them
   * apart. The day has to travel with the departure.
   */
  dayType: string
  /** Minutes past midnight, or null where the timetable publishes no boarding time. */
  boardMinutes: number | null
}

export interface OperatorGroup {
  id: string
  name: string
  kind: 'bus' | 'train'
  blocks: DepartureBlock[]
  /**
   * The fare for riding with this operator, which is one price across the group because
   * every route in it is priced between the same two places.
   */
  fare: Fare | null
  /** How long the ride takes, where the timetable says. Null when it does not. */
  travel: TravelRange | null
}

/** Minutes, as a range because different routes take different roads. */
export interface TravelRange {
  min: number
  max: number
}

/**
 * Which operator ran a plan option.
 *
 * This was the seam left for a second operator, and it is now load-bearing: the API sends
 * the operator with every option, so a Metrorail service groups into its own card beside
 * Golden Arrow's without the screen above changing at all.
 *
 * The fallback is not defensive padding. Everything loaded before operators existed is
 * Golden Arrow, and an older API that does not send the field would otherwise leave every
 * card unlabelled.
 */
export function operatorOf(option: PlanOption): { id: string; name: string; kind: 'bus' | 'train' } {
  return {
    id: option.operator_code ?? 'gabs',
    name: option.operator_name ?? 'Golden Arrow Buses',
    kind: option.operator_kind ?? 'bus',
  }
}

/**
 * Every departure in the plan, each still knowing where it came from.
 *
 * Order is by boarding time. Departures the timetable gives no time for sort last rather
 * than being dropped - the bus does run, and a rider heading for a "via" stop still needs
 * to see it - but they cannot be placed among the timed ones without inventing a time.
 */
export function flatten(options: PlanOption[]): DepartureBlock[] {
  const blocks: DepartureBlock[] = []
  options.forEach((option, optionIndex) => {
    option.departures.forEach((departure, departureIndex) => {
      blocks.push({
        optionIndex,
        departureIndex,
        departure,
        routeLabel: option.route_label,
        timetableNumber: option.timetable_number,
        fare: option.fare,
        dayType: option.day_type,
        boardMinutes: departure.board_minutes,
      })
    })
  })
  return sortByBoard(blocks)
}

function sortByBoard(blocks: DepartureBlock[]): DepartureBlock[] {
  return [...blocks].sort((a, b) => {
    if (a.boardMinutes == null && b.boardMinutes == null) return 0
    if (a.boardMinutes == null) return 1
    if (b.boardMinutes == null) return -1
    return a.boardMinutes - b.boardMinutes
  })
}

/**
 * How long the ride takes, from the departures that actually say.
 *
 * Only departures with a published time at both ends count. Most Golden Arrow stops are
 * printed as "via" - the bus passes but no time is given - and the API sends a floor
 * ("from 05:20") for those. Subtracting a floor from a real time yields a duration that
 * is not the journey's, and shown as "12 min travel time" a rider would plan around it.
 * Where nothing qualifies this returns null and the screen says nothing.
 */
export function travelRange(blocks: DepartureBlock[]): TravelRange | null {
  const spans: number[] = []
  for (const b of blocks) {
    const { board_minutes, arrive_minutes, board_approx, arrive_approx } = b.departure
    if (board_approx || arrive_approx) continue
    if (board_minutes == null || arrive_minutes == null) continue
    const span = arrive_minutes - board_minutes
    // A bus crossing midnight, or a timetable typo. Either way it is not a duration.
    if (span <= 0) continue
    spans.push(span)
  }
  if (!spans.length) return null
  return { min: Math.min(...spans), max: Math.max(...spans) }
}

/**
 * "12 min", "20 to 28 min". Null where no departure publishes both ends.
 *
 * Spelt "to" rather than hyphenated. Inter draws a hyphen with wide sidebearings, so
 * "20-28" reads as "20 - 28" and looks like a subtraction rather than a range.
 */
export function travelLabel(range: TravelRange | null): string | null {
  if (!range) return null
  return range.min === range.max ? `${range.min} min` : `${range.min} to ${range.max} min`
}

/**
 * The plan as one card per operator.
 *
 * The fare is taken from the first block that has one rather than being compared across
 * them: fares are published between places, not routes, so every route between the same
 * two stops carries the same price. Where they ever differ, showing the one a rider will
 * actually be sold when they board is the honest answer, and that is per-block anyway.
 */
export function groupByOperator(options: PlanOption[]): OperatorGroup[] {
  const groups = new Map<string, OperatorGroup>()
  for (const block of flatten(options)) {
    const who = operatorOf(options[block.optionIndex])
    let group = groups.get(who.id)
    if (!group) {
      group = { ...who, blocks: [], fare: null, travel: null }
      groups.set(who.id, group)
    }
    group.blocks.push(block)
    if (!group.fare) group.fare = block.fare
  }
  for (const group of groups.values()) group.travel = travelRange(group.blocks)
  return [...groups.values()]
}

/**
 * The longest a single Golden Arrow ride plausibly takes, in minutes.
 *
 * Used only as a last-resort bound, where a departure publishes neither a real boarding
 * time nor a real arrival - a floor like "from 05:20" and a "via" at the far end. The
 * longest ride actually measurable in this data is under two hours; three is generous.
 * It is a heuristic and the only one here, so it is deliberately loose: it exists to rule
 * out a morning bus still being offered at nine at night, not to trim the edges.
 */
const MAX_RIDE_MINUTES = 180

/**
 * The latest minute a rider could still board this departure.
 *
 * Most Golden Arrow stops are printed as "via" - the bus passes, but no time is given -
 * so a great many departures have no published boarding time at all. Treating those as
 * "time unknown, therefore still catchable" is what put a bus that finished at 07:45 in
 * front of somebody searching at 21:09.
 *
 * There is always a bound, though, and it comes from the ride itself:
 *
 *   - a published boarding time IS the answer
 *   - otherwise the bus must be boarded before it arrives at the far end, so a published
 *     arrival is a hard ceiling
 *   - otherwise the floor on the boarding time plus the longest a ride plausibly runs
 *
 * Only the third is a guess, and it is the loosest of the three.
 */
export function latestBoard(d: PlanDeparture): number | null {
  if (!d.board_approx && d.board_minutes != null) return d.board_minutes
  // An approximate arrival is itself only a floor ("after 06:30"), so it bounds nothing.
  if (!d.arrive_approx && d.arrive_minutes != null) return d.arrive_minutes
  if (d.board_minutes != null) return d.board_minutes + MAX_RIDE_MINUTES
  return null
}

/**
 * The departures still to come at a given time.
 *
 * A bus that has gone is not a choice, so this filters rather than reorders. An earlier
 * version pushed past departures behind the future ones instead, on the reasoning that
 * an empty card is ambiguous - but it put 05:25 in front of somebody searching at five
 * in the afternoon, which is worse than ambiguous. The ambiguity is answered in words
 * instead: the caller checks the count and says "no more buses today".
 *
 * A departure survives only if it could still be boarded - see latestBoard. Where even
 * that cannot be established the departure is kept, because then nothing whatever is
 * known about when the bus runs, and dropping it would hide a real service.
 */
export function fromTime(blocks: DepartureBlock[], minutes: number | null): DepartureBlock[] {
  if (minutes == null) return blocks
  return blocks.filter((b) => {
    const last = latestBoard(b.departure)
    return last == null || last >= minutes
  })
}

/** The day types a timetable is published for, in a rider's words. */
export const DAY_LABEL: Record<string, string> = {
  WEEKDAY: 'Weekdays', SATURDAY: 'Saturday', SUNDAY: 'Sunday',
  // Metrorail publishes one sheet for the weekend without saying whether Sunday differs,
  // so it is shown as it is printed rather than resolved to a day it may not mean.
  WEEKEND: 'Weekends',
  PUBLIC_HOLIDAY: 'Public Holiday', OTHER: 'Other',
}

/** Time of day, the way a rider thinks about a timetable rather than a clock. */
export const TIME_GROUPS = [
  { key: 'morning', label: 'Morning, before 12pm', test: (m: number) => m < 720 },
  { key: 'afternoon', label: 'Afternoon, 12 to 5pm', test: (m: number) => m >= 720 && m < 1020 },
  { key: 'evening', label: 'Evening, after 5pm', test: (m: number) => m >= 1020 },
] as const

/**
 * The day split into parts, for the full-day sheet.
 *
 * A hundred departures in one grid is the wall this screen exists to avoid; the sheet
 * would simply have moved it behind a button. Splitting it is what the original view did
 * and it was right to.
 */
export function bucketByTimeOfDay(blocks: DepartureBlock[]): { key: string; label: string; blocks: DepartureBlock[] }[] {
  const groups: Record<string, DepartureBlock[]> =
    { morning: [], afternoon: [], evening: [], other: [] }
  for (const b of blocks) {
    const m = b.boardMinutes ?? b.departure.arrive_minutes
    const key = m == null ? 'other' : (TIME_GROUPS.find((g) => g.test(m))?.key ?? 'other')
    groups[key].push(b)
  }
  return [...TIME_GROUPS, { key: 'other', label: 'Other times' }]
    .map((g) => ({ key: g.key, label: g.label, blocks: groups[g.key] }))
    .filter((g) => g.blocks.length > 0)
}

/**
 * What a departure's own end times say, or plain words where they say nothing useful.
 *
 * Shared with the original view rather than written twice: getting off at a "via" stop
 * yields a floor that is often the boarding time itself, and "05:20 to 05:20" hints the
 * ride is instant.
 */
export function alightOrNone(d: PlanDeparture | undefined, end: 'board' | 'alight'): string | undefined {
  if (!d) return undefined
  const raw = end === 'board' ? d.board_raw : d.arrive_raw
  const approx = end === 'board' ? d.board_approx : d.arrive_approx
  const mins = end === 'board' ? d.board_minutes : d.arrive_minutes
  return boundIsUseful(mins, approx, d.board_minutes) ? raw : NO_TIME
}

/** How long this one bus takes, where both its ends are published. */
export function blockDuration(b: DepartureBlock): number | null {
  const { board_minutes, arrive_minutes, board_approx, arrive_approx } = b.departure
  if (board_approx || arrive_approx) return null
  if (board_minutes == null || arrive_minutes == null) return null
  const span = arrive_minutes - board_minutes
  return span > 0 ? span : null
}

/** How long a ride takes, and whether the timetable is certain about it. */
export interface Span { minutes: number; approx: boolean }

/**
 * How long the journey takes, said as plainly as the timetable allows.
 *
 * blockDuration above refuses to answer unless both ends are published, which is right
 * for the operator-wide range - an uncertain number would widen it silently. On a single
 * departure the calculation is worth making anyway: a rider comparing tiles wants to know
 * that one bus takes an hour and another takes two and a quarter, and a blank helps
 * nobody.
 *
 * Where either end is a "via" floor the answer is marked approximate and carries the
 * tilde the times themselves already use, so it is never mistaken for a published figure.
 */
export function journeySpan(b: DepartureBlock): Span | null {
  const { board_minutes, arrive_minutes, board_approx, arrive_approx } = b.departure
  if (board_minutes == null || arrive_minutes == null) return null
  const minutes = arrive_minutes - board_minutes
  if (minutes <= 0) return null
  return { minutes, approx: board_approx || arrive_approx }
}

/**
 * "45 min", "1h", "2h 15m".
 *
 * Hours once past sixty minutes: "135 min" is arithmetic a rider should not have to do
 * while deciding which bus to run for.
 */
export function spanLabel(span: Span | null): string | null {
  if (!span) return null
  const { minutes, approx } = span
  const tilde = approx ? '~' : ''
  if (minutes < 60) return `${tilde}${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${tilde}${h}h` : `${tilde}${h}h ${m}m`
}

/** How many of these leave at or after the chosen time, for "nothing left today". */
export function countFrom(blocks: DepartureBlock[], minutes: number | null): number {
  if (minutes == null) return blocks.length
  return blocks.filter((b) => b.boardMinutes != null && (b.boardMinutes as number) >= minutes).length
}
