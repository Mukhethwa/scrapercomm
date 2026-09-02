import { useState } from 'react'
import { Info } from 'lucide-react'
import type { Fare, ConnectionFare } from './api'
import { rands, perRide, basisNote, isFlat } from './money'

/**
 * What a journey costs.
 *
 * The per-ride price leads, because that is what somebody about to get on a bus wants to
 * know; the products sit behind "Other tickets" for anyone buying ahead. Shared by a
 * direct journey and a change-of-bus one, which used to get a single line of text and
 * none of the ticket detail - the same rider, deciding the same thing, and on the more
 * expensive journey of the two.
 */
export default function FarePanel(
  { fare, tickets, kind }:
  {
    fare: Fare | ConnectionFare | null
    /** How many tickets the price covers. Absent on a direct journey, which is one. */
    tickets?: number
    /** "through" or "per_leg" on a change-of-bus journey. */
    kind?: string
  },
) {
  const [open, setOpen] = useState(false)

  if (!fare || fare.per_ride_cents == null) {
    return (
      <div className="farebox none">
        <Info size={13} aria-hidden="true" />
        <span>
          Golden Arrow publishes no fare for {kind ? 'part of this journey' : 'this journey'}.
          Ask the driver.
        </span>
      </div>
    )
  }

  const note = basisNote(fare as Fare)
  const perLeg = kind === 'per_leg'
  const through = kind === 'through'

  return (
    <div className="farebox">
      <div className="fareline">
        <span className="fareamt">{rands(fare.per_ride_cents)}</span>
        <span className="farelbl">
          {perLeg && tickets ? <>for all {tickets} buses. </> : null}
          Price on a <b>Golden Arrow Gold Card</b>. <b>Paying cash costs more.</b>
        </span>
        {fare.code && <span className="farecode">{fare.code}</span>}
        <button className="infobtn" onClick={() => setOpen(!open)} aria-expanded={open}>
          <Info size={13} aria-hidden="true" />
          <span>{open ? 'Hide' : 'Other tickets'}</span>
        </button>
      </div>

      {open && (
        <div className="faredetail">
          {/* On a journey paid for per bus every figure here is the sum across the buses,
              so the table has to say so or it reads as the price of one ticket. */}
          {perLeg && tickets ? (
            <p className="farefoot lead">
              A separate ticket for each of the {tickets} buses. Every price below is the
              total for all {tickets}.
            </p>
          ) : null}
          {through ? (
            <p className="farefoot lead">
              One ticket covers the whole journey, including the change of bus.
            </p>
          ) : null}
          <table className="faretable">
            <thead>
              <tr><th>Ticket</th><th>Price</th><th>Rides</th><th>Each</th></tr>
            </thead>
            <tbody>
              {perRide(fare as Fare).map((p) => (
                <tr key={p.label}>
                  <td>{p.label}</td>
                  <td>{rands(p.total) ?? '-'}</td>
                  <td>{p.rides}</td>
                  <td><b>{rands(p.each) ?? '-'}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="farefoot">
            A "Weekly" is 10 rides valid 30 days and a "Monthly" is 48 rides valid 90
            days, so the longer tickets are cheaper per ride, not just longer.
          </p>
          {fare.transfers && fare.transfers !== 'Zero' && (
            <p className="farefoot">Includes {fare.transfers.toLowerCase()} transfer.</p>
          )}
          {note && <p className="farefoot">{note}</p>}
          <p className="farefoot">
            {isFlat(fare.basis)
              ? 'These are GO Easy prices on a Golden Arrow Gold Card'
              : 'These are Golden Arrow Gold Card prices'}
            {' '}and do not change with the time of day. <b>Paying cash costs more</b>, and
            the cash fare itself differs between peak (16:00-08:00) and off-peak; Golden
            Arrow does not publish cash fares per journey.
          </p>
        </div>
      )}
    </div>
  )
}
