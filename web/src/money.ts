/**
 * Fares, in the words a rider uses.
 *
 * Everything arrives in cents. The operator sells three products and none of them is
 * named for what it is - "Weekly" is 10 rides valid 30 days, "Monthly" is 48 rides valid
 * 90 days - so the per-ride price is what the app leads with and the products are shown
 * underneath for anyone who wants the cheaper ones.
 */
import type { Fare } from './api'

/** Rides each product carries. Straight off the operator's product page. */
export const RIDES = { five: 5, weekly: 10, monthly: 48 }

export function rands(cents: number | null | undefined): string | null {
  if (cents == null) return null
  return `R${(cents / 100).toFixed(2)}`
}

/** Per-ride cost of each product, cheapest last, for the breakdown. */
export function perRide(fare: Fare) {
  return [
    { label: '5 Ride', rides: RIDES.five, total: fare.five_ride_cents,
      each: fare.five_ride_cents == null ? null : Math.round(fare.five_ride_cents / RIDES.five) },
    { label: 'Weekly', rides: RIDES.weekly, total: fare.weekly_cents,
      each: fare.weekly_cents == null ? null : Math.round(fare.weekly_cents / RIDES.weekly) },
    { label: 'Monthly', rides: RIDES.monthly, total: fare.monthly_cents,
      each: fare.monthly_cents == null ? null : Math.round(fare.monthly_cents / RIDES.monthly) },
  ]
}

/**
 * How exactly this price applies to the journey the rider actually asked for.
 *
 * Fares are published between broad places, not between every timing point, so most
 * rides are priced by something wider than themselves. Saying which keeps the number
 * honest instead of implying a fare was printed for their two stops.
 */
export function basisNote(fare: Fare): string | null {
  const between = fare.basis_from && fare.basis_to
    ? `${fare.basis_from} to ${fare.basis_to}`
    : null
  if (fare.basis === 'exact') return between ? `Fare published for ${between}.` : null
  if (fare.basis === 'section')
    return between
      ? `No fare is published for your two stops, so this is the ${between} fare, the nearest published one that covers your whole ride.`
      : null
  return between
    ? `No fare is published for your two stops, so this is the fare for the bus itself, ${between}.`
    : null
}
