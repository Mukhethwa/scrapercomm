import { useState } from 'react'
import { Info, TicketCheck, Tickets } from 'lucide-react'
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
  { fare, tickets, kind, mode = 'bus' }:
  {
    fare: Fare | ConnectionFare | null
    /** How many tickets the price covers. Absent on a direct journey, which is one. */
    tickets?: number
    /** "through" or "per_leg" on a change-of-bus journey. */
    kind?: string
    /**
     * Bus or train. Everything below the price is a fact about Golden Arrow - the Gold
     * Card, the peak-hour cash difference, asking the driver - and none of it is true of
     * a train. Naming the wrong operator on a Metrorail journey does not just read badly,
     * it tells a rider to pay somebody who will not take their money.
     */
    mode?: 'bus' | 'train'
  },
) {
  const [open, setOpen] = useState(false)

  if (!fare || fare.per_ride_cents == null) {
    return (
      <div className="farebox none">
        <Info size={13} aria-hidden="true" />
        {mode === 'train' ? (
          /* Not "ask the driver": on Metrorail you buy before you board, and there is no
             driver to ask. Said as a fact about the timetables rather than about the
             fare, because what we know is that PRASA does not print prices on them. */
          <span>Metrorail does not publish fares in its timetables. Buy at the station.</span>
        ) : (
          <span>
            Golden Arrow publishes no fare for{' '}
            {kind ? 'part of this journey' : 'this journey'}. Ask the driver.
          </span>
        )}
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
        {/* Whether a change of bus is paid for twice is the thing a rider most wants to
            know here, and it is not our judgement: Golden Arrow publishes a fare for
            this journey with a transfer allowance, or it does not. */}
        {through && (
          <span className="faretag once">
            <TicketCheck size={13} aria-hidden="true" /> Pay once
          </span>
        )}
        {perLeg && tickets && (
          <span className="faretag many">
            <Tickets size={13} aria-hidden="true" />
            {tickets === 2 ? 'Pay twice' : `Pay ${tickets} times`}
          </span>
        )}
        {/* The Gold Card, and the cash-versus-card difference, are Golden Arrow's own
            products. They are not facts about a fare; they are facts about that operator,
            and there is no reason to expect the next one to price the same way. Guarded
            rather than left to be noticed, because a train has no fare today and this
            would have started lying the day one was loaded. */}
        <span className="farelbl">
          {perLeg && tickets
            ? <>for all {tickets} {mode === 'train' ? 'trains' : 'buses'}. </>
            : null}
          {mode === 'bus' && (
            <><b>Golden Arrow Gold Card</b> price. Cash is <b>higher at peak times</b>,
            lower off-peak.</>
          )}
        </span>
        {(fare as Fare).zone_approx && (
          <span className="faretag area" title="Published for the surrounding area, not this exact stop">
            area fare
          </span>
        )}
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
              Golden Arrow publishes no through fare for this journey, so you buy a ticket
              on each of the {tickets} buses. Every price below is the total for all {tickets}.
            </p>
          ) : null}
          {through ? (
            <p className="farefoot lead">
              Golden Arrow sells this journey as one ticket
              {fare.transfers ? `, allowing ${fare.transfers.toLowerCase()} transfer` : ''}
              , so the change of bus costs nothing extra.
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
          {/* The price is the operator's; matching it to this exact stop is ours. Say
              which, rather than presenting an area fare as if it were printed for the
              stop the rider chose. */}
          {(fare as Fare).zone_approx && (
            <p className="farefoot">
              Your stop is not named on the fare page, so this is the published fare for
              the area it is in{(fare as Fare).basis_to ? ` (${(fare as Fare).basis_to})` : ''}.
              The fare you are charged may differ.
            </p>
          )}
          {mode === 'bus' && (
            <p className="farefoot">
              {isFlat(fare.basis)
                ? 'These are GO Easy prices on a Golden Arrow Gold Card'
                : 'These are Golden Arrow Gold Card prices'}
              {' '}and do not change with the time of day. A cash fare does: it is higher
              at peak times and lower off-peak. Golden Arrow does not publish cash fares
              per journey, so this app cannot show you one. Ask the driver.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
