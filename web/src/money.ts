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

/**
 * "bus" pluralises to "buses", not "buss".
 *
 * Three components each built the plural by appending an s, which is right for "trains"
 * and wrong for the word it is used for most. One function so the next one to need it
 * cannot get it wrong again.
 */
export const plural = (vehicle: string) => (vehicle === 'bus' ? 'buses' : `${vehicle}s`)

/** GO Easy is the flat fare: one price for any journey, wherever it goes. */
export const isFlat = (basis: string) => basis === 'go_easy'

export function rands(cents: number | null | undefined): string | null {
  if (cents == null) return null
  return `R${(cents / 100).toFixed(2)}`
}

/**
 * The price to show a rider: the cash fare, or nothing.
 *
 * Gold Card prices are not shown anywhere any more. They were what the app led with -
 * the five-ride price divided by five - and they are the wrong number for almost
 * everybody: a card holder has already paid for five rides and does not care what one
 * costs, while a cash payer hands over something else entirely. Mukhethwa: "only cash
 * price should be displayed because thats what users would actually care for who want
 * to compare with train prices".
 *
 * Golden Arrow publishes a cash fare for 21 routes, so this is null far more often than
 * not, and null means the screen says nothing rather than something misleading. Showing
 * no price is a smaller failure than showing a price nobody will be charged.
 */
export function cashFare(fare: { cash_cents?: number | null } | null | undefined) {
  return rands(fare?.cash_cents ?? null)
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
  if (isFlat(fare.basis))
    return 'GO Easy is one price for any journey, however far it goes. It is not valid to or from Atlantis, Darling, Dassenberg, Mamre/Pella, Malmesbury, Koeberg Power Station, Melkbosstrand, Fisantekraal, Wellington, Paarl or Stellenbosch, which are priced by distance instead.'
  if (fare.basis === 'exact') return between ? `Fare published for ${between}.` : null
  if (fare.basis === 'section')
    return between
      ? `No fare is published for your two stops, so this is the ${between} fare, the nearest published one that covers your whole ride.`
      : null
  return between
    ? `No fare is published for your two stops, so this is the fare for the bus itself, ${between}.`
    : null
}
