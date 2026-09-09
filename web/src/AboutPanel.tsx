/**
 * Where the timetables come from, and how old they are.
 *
 * A journey planner is only as true as the paper behind it, and that paper has a date on
 * it. Commuttr republishes Golden Arrow and PRASA schedules; a rider deciding whether to
 * trust a departure deserves to know whose timetable it is and when it was last read.
 *
 * Every number here is asked of the API rather than written into the page, so it cannot
 * quietly become a lie as the data ages.
 */
import { useEffect, useState } from 'react'
import { getAbout, type AboutResponse } from './api'

function when(date: string | null): string {
  if (!date) return 'unknown'
  const d = new Date(date)
  return Number.isNaN(d.getTime())
    ? date
    : d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}

export default function AboutPanel() {
  const [about, setAbout] = useState<AboutResponse | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getAbout().then(setAbout).catch(() => setFailed(true))
  }, [])

  return (
    <div className="space-y-4 text-[13px] text-ink">
      <section>
        <h3 className="mb-1 text-[13px] font-bold">Where this comes from</h3>
        <p className="text-sub">
          Commuttr reads the timetables each operator publishes and does not change them.
          Services, times and fares belong to the operator, and any of them can change
          without this app knowing.
        </p>
      </section>

      {failed && (
        <p className="text-sub">Could not reach the server to check how current the data is.</p>
      )}

      {about && (
        <>
          <section>
            <h3 className="mb-1 text-[13px] font-bold">What is loaded</h3>
            <ul className="space-y-1 text-sub">
              {about.operators.map((o) => (
                <li key={o.code}>
                  <span className="font-semibold text-ink">{o.name}</span>
                  {' '}&mdash; {o.routes} routes, {o.timetables} timetables
                </li>
              ))}
              <li>{about.stops} stops and stations</li>
            </ul>
          </section>

          <section>
            <h3 className="mb-1 text-[13px] font-bold">How current it is</h3>
            <ul className="space-y-1 text-sub">
              <li>Timetables last read: <b className="text-ink">{when(about.last_scraped)}</b></li>
              <li>
                Loaded timetables took effect between {when(about.oldest_timetable)} and{' '}
                {when(about.newest_timetable)}
              </li>
            </ul>
            {/* Said plainly rather than buried. Some of what is loaded took effect years
                ago, and a rider standing at a stop deserves to know that is possible. */}
            <p className="mt-2 text-sub">
              Some of these are old. Where a service has changed since its timetable was
              published, Commuttr will show the old times. Check with the operator before
              relying on a journey that matters.
            </p>
          </section>
        </>
      )}

      <section>
        <h3 className="mb-1 text-[13px] font-bold">Maps</h3>
        <p className="text-sub">
          Map tiles and place names come from{' '}
          <a className="text-accent-deep underline" href="https://www.openstreetmap.org/copyright"
             target="_blank" rel="noreferrer">OpenStreetMap</a> contributors.
        </p>
      </section>

      <section>
        <h3 className="mb-1 text-[13px] font-bold">This is not an official app</h3>
        <p className="text-sub">
          Commuttr is not affiliated with Golden Arrow Bus Services, PRASA or Metrorail.
          It is a planning aid, not a ticket and not a guarantee that a service will run.
        </p>
      </section>
    </div>
  )
}
