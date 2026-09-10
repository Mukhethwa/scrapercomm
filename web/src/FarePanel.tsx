import { useState } from 'react'
import { Info, TicketCheck, Tickets } from 'lucide-react'
import type { Fare, ConnectionFare } from './api'
import { rands, basisNote, trainTickets } from './money'

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

  // Only a cash fare counts as a price now. A journey with a Gold Card fare and no cash
  // fare shows nothing, because the card number is not what a cash payer is charged and
  // is of no use to a card holder, who has already bought their five rides.
  if (!fare || fare.cash_cents == null) {
    return (
      <div className="farebox none">
        <Info size={13} aria-hidden="true" />
        {mode === 'train' ? (
          /* Not "ask the driver": on Metrorail you buy before you board, and there is no
             driver to ask. Said as a fact about the timetables rather than about the
             fare, because what we know is that PRASA does not print prices on them. */
          <span>
            Metrorail publishes no fare for this journey. Buy at the station.
          </span>
        ) : (
          <span>
            Golden Arrow publishes no cash fare for{' '}
            {kind ? 'part of this journey' : 'this journey'}. Ask the driver, or phone
            the Transport Information Centre on 0800 65 64 63.
          </span>
        )}
      </div>
    )
  }

  const note = basisNote(fare as Fare)
  const perLeg = kind === 'per_leg'
  const through = kind === 'through'

  /*
   * The cash fare, where Golden Arrow publishes one.
   *
   * Only 21 routes have it, so this is null far more often than not - and that is the
   * honest shape of the data rather than a gap worth filling. Dated, because these took
   * effect in August 2025 and the card fares moved again a year later, so a rider should
   * read it as the last published figure and not as today's.
   */
  const cash = (fare as Fare).cash_cents ?? null
  const cashDate = (() => {
    const raw = (fare as Fare).cash_effective_from
    if (!raw) return null
    const d = new Date(raw)
    return Number.isNaN(d.getTime())
      ? raw
      : d.toLocaleDateString(undefined, { year: 'numeric', month: 'long' })
  })()

  return (
    <div className="farebox">
      <div className="fareline">
        <span className="fareamt">{rands(cash)}</span>
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
          {/* What the number is, and what it is not. Cash fares differ between peak and
              off-peak - the operator says so and gives the window - but the notice
              prints one figure per route, so this is the published fare and not a
              promise about a particular bus at a particular hour. */}
          {mode === 'bus' && (
            <><b>cash</b> fare{cashDate ? <>, published {cashDate}</> : null}. Golden
            Arrow charges more at peak times (16:00 to 08:00) and less off-peak, and
            publishes one figure per route.</>
          )}
          {/* A train fare is set by how far apart the stations are, not by the route, so
              saying the distance explains the number rather than decorating it. */}
          {mode === 'train' && (
            <><b>single</b> ticket
            {(fare as Fare).distance_km != null
              ? <>, {Math.round((fare as Fare).distance_km as number)} km apart</>
              : null}. 40% off between 09:00 and 14:00.</>
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
          <span>{open ? 'Hide' : 'About this fare'}</span>
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
          {/* Golden Arrow's Gold Card products used to be listed here and are gone: a
              card holder has already bought their rides and does not price a journey.
              Metrorail is the opposite case. PRASA sells four tickets for one journey
              and the price of each is the reason to pick it, so they belong here. */}
          {mode === 'train' && trainTickets(fare as Fare).length > 0 && (
            <>
              <table className="faretable">
                <thead>
                  <tr><th>Ticket</th><th>Price</th><th></th></tr>
                </thead>
                <tbody>
                  {trainTickets(fare as Fare).map((t) => (
                    <tr key={`${t.label}-${t.note}`}>
                      <td>{t.label}</td>
                      <td><b>{rands(t.cents)}</b></td>
                      <td>{t.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="farefoot">
                Metrorail prices by distance, not by route
                {(fare as Fare).distance_km != null
                  ? `: these two stations are ${Math.round((fare as Fare).distance_km as number)} km apart`
                  : ''}
                {(fare as Fare).code ? `, which is zone ${(fare as Fare).code}` : ''}.
              </p>
              <p className="farefoot">
                Everyone pays <b>40% less</b> on single and return tickets between{' '}
                <b>09:00 and 14:00</b>. Pensioners, military veterans and scholars in full
                uniform pay <b>50% less</b> - pensioners and veterans off-peak, scholars at
                any hour.
              </p>
            </>
          )}
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
              This is Golden Arrow's published cash fare for the route
              {(fare as Fare).cash_effective_from
                ? `, which took effect on ${(fare as Fare).cash_effective_from}`
                : ''}. Cash fares differ with the time of day - Golden Arrow charges the
              peak fare from 16:00 to 08:00 and the off-peak fare from 08:00 to 16:00 -
              but only one figure per route is published, so treat this as the fare for
              the route rather than for your particular bus. Gold Card prices are not
              shown: a card is bought by the ride, not by the journey.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
