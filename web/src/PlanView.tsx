import { useEffect, useMemo, useState } from 'react'
import {
  getStops, getGeocode, getAreas, reachableFor, connectingFor, getPlan, getTripStops, getNearbyOrigins,
  getConnections,
  type StopHit, type GeoHit, type ReachableStop, type ConnectingStop, type Endpoint, type PlanOption,
  type PlanDeparture, type TripStop, type TripNote, type NearbyOrigin, type Connection,
} from './api'
import PlanMap from './PlanMap'
import TripStrip from './TripStrip'
import FarePanel from './FarePanel'
import ModePicker from './ModePicker'
import { useModes } from './modes'
import { buildJourney, usePlanner } from './planner'
import { shortTime, boundIsUseful, NO_TIME } from './times'
import { stopLabel } from './stops'
import { rands, plural } from './money'
import { ArrowRightLeft, CircleCheck, CircleX, Info, Lightbulb, TriangleAlert, X } from 'lucide-react'
import ConnectionsPanel from './ConnectionsPanel'
import { PinIcon } from './icons'
import { usePlanSearch } from './usePlanSearch'
import { alightOrNone } from './results'
import { pinEnd } from './pins'

const DAY_LABEL: Record<string, string> = {
  WEEKDAY: 'Mon-Fri', SATURDAY: 'Saturday', SUNDAY: 'Sunday',
  PUBLIC_HOLIDAY: 'Public Holiday', OTHER: 'Other',
}

const TIME_GROUPS = [
  { key: 'morning', label: 'Morning, before 12pm', test: (m: number) => m < 720 },
  { key: 'afternoon', label: 'Afternoon, 12 to 5pm', test: (m: number) => m >= 720 && m < 1020 },
  { key: 'evening', label: 'Evening, after 5pm', test: (m: number) => m >= 1020 },
] as const

/** The bus's front sign: the terminus and vias, read from the route name ORIGIN - VIA - TERMINUS. */
function busSign(routeLabel: string) {
  const parts = routeLabel.split(' - ').map((s) => s.trim()).filter(Boolean)
  return {
    origin: parts[0] ?? routeLabel,
    terminus: parts[parts.length - 1] ?? routeLabel,
    via: parts.slice(1, -1).join(', '),
  }
}

function bucketDeps(deps: PlanDeparture[]) {
  const groups: Record<string, { d: PlanDeparture; j: number }[]> =
    { morning: [], afternoon: [], evening: [], other: [] }
  deps.forEach((d, j) => {
    const m = d.board_minutes ?? d.arrive_minutes
    const key = m == null ? 'other' : (TIME_GROUPS.find((g) => g.test(m))?.key ?? 'other')
    groups[key].push({ d, j })
  })
  return groups
}




/**
 * The suggestion menu floats over the content below it (position: absolute, up to 280px
 * tall), so leaving it open once the field loses focus hides real information.
 *
 * Visibility is tied to whether the field has focus rather than to clearing the results
 * array: a search started on focus can resolve after the user has already left the
 * field, and clearing the array would simply be undone when that promise lands. Menu
 * items use onMouseDown, which fires before blur, so clicking a suggestion still
 * registers. Escape blurs, which closes the menu by the same rule.
 */
/**
 * Does any departure here carry a time the timetable never printed?
 *
 * The option's own board_approx/alight_approx describe whichever candidate happened to
 * build the group, so a group can show "~05:30" while reporting false. Gating the legend
 * on that flag hid the explanation from the exact rows that needed it.
 */
function hasApprox(o: PlanOption): boolean {
  return o.departures.some((d) => d.board_approx || d.arrive_approx)
}

/**
 * What one end of the ride should say, decided once so the departure button and the trip
 * breakdown can never disagree about the same stop.
 */
/** One end of a departure button: a published time, or a visibly-approximate one. */
function DepTime({ raw, approx, useful = true }:
  { raw: string; approx: boolean; useful?: boolean }) {
  const t = shortTime(useful ? raw : NO_TIME, approx)
  return <span className={t.approx ? 'aprx' : ''}>{t.text}</span>
}

export default function PlanView() {
  const {
    from, setFrom, to, setTo, fromText, setFromText, toText, setToText,
    fromHits, toHits, fromOpen, setFromOpen, toOpen, setToOpen,
    plan, setPlan, loading, sel, setSel,
    reachable, setReachable, connecting, setConnecting,
    conns, connLegs, connLoading, connFrom, dayAlts, setDayAlts, altDays,
    openDep, setOpenDep, tripStops, tripNotes, loadingTrip,
    mapOpen, setMapOpen, armed, setArmed, onMapClick, segment, roadPath, ride,
    pickError, setPickError, stage,
    filteredReach, filteredConnecting, nearbyAlternatives, betterNearby, bestLegs,
    choose, pickFrom, pickTo, clearFrom, clearTo, swapEnds,
    useAlt, selectDep, togglePlanned,
    modes, planner,
  } = usePlanSearch()

  // Bus or train, taken from where the rider is standing - see PlanScreen for why.
  const vehicle = from?.mode === 'train' ? 'train' : 'bus'
  const vehicles = plural(vehicle)
  /**
   * What a journey with a change actually runs on.
   *
   * `vehicle` reads the ORIGIN, and a place carries no mode at all, so it falls back to
   * bus - which described two Metrorail trains as "2 buses". No stop here is served by
   * both networks, so a journey with a change never mixes them and the stop the API
   * resolved the origin to settles it for the whole journey.
   */
  const connVehicles = plural(connFrom?.operator_kind ?? vehicle)

  return (
    <div className="planwrap">
      <div className="planbar">
        <div className="field">
          <label>Starting point</label>
          <div className="ac">
            <input value={fromText} placeholder="Bus stop, place, or address"
              onChange={(e) => { setFromText(e.target.value); if (from) { setFrom(null); setReachable(null); setConnecting([]); setPlan(null); setTo(null); setDayAlts({}) } }}
              onFocus={() => setFromOpen(true)}
              onBlur={() => setFromOpen(false)}
              onKeyDown={(e) => { if (e.key === 'Escape') e.currentTarget.blur() }} />
            {/* One row, so a longer label can never push one button under the
                other - which a fixed right offset did. */}
            <div className="fieldbtns">
              {fromText && (
                <button
                  className="clearbtn"
                  onClick={clearFrom}
                  title="Clear"
                  aria-label="Clear starting point"
                >
                  <X size={13} aria-hidden="true" />
                </button>
              )}
              <button className={`pinbtn ${armed === 'from' ? 'armed' : ''}`} onClick={() => setArmed(armed === 'from' ? null : 'from')}><PinIcon /> Map</button>
            </div>
            {fromOpen && fromHits.length > 0 && (
              <div className="acmenu">
                {fromHits.map((h, i) => (
                  <button key={i} className="acitem" onMouseDown={() => choose(h, pickFrom)}>
                    <span className="hittag">{h.kind === 'stop' ? 'Stop' : h.kind === 'area' ? 'Area' : 'Place'}</span>
                    {h.name}{h.sub ? <span className="acsub"> {h.sub}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* The arrow between the two fields is where a rider already looks to see which
            way round the journey is, so that is where turning it around belongs. */}
        <button
          type="button"
          className="swapbtn mb-2 inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center
                     self-end rounded-full border border-line bg-panel text-accent
                     hover:border-accent hover:bg-accent-fill hover:text-white
                     disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-panel
                     disabled:hover:text-accent"
          onClick={swapEnds}
          disabled={!from || !to}
          title="Swap starting point and destination"
          aria-label="Swap starting point and destination"
        >
          <ArrowRightLeft size={15} aria-hidden="true" />
        </button>

        <div className="field">
          <label>Destination</label>
          <div className="ac">
            <input value={toText} disabled={!from}
              placeholder={!from ? 'Choose a starting point first' : 'Where do you want to go?'}
              onChange={(e) => { setToText(e.target.value); if (to) { setTo(null); setPlan(null); setDayAlts({}) } }}
              onFocus={() => setToOpen(true)}
              onBlur={() => setToOpen(false)}
              onKeyDown={(e) => { if (e.key === 'Escape') e.currentTarget.blur() }} />
            {/* One row, so a longer label can never push one button under the
                other - which a fixed right offset did. */}
            <div className="fieldbtns">
              {toText && (
                <button
                  className="clearbtn"
                  onClick={clearTo}
                  title="Clear"
                  aria-label="Clear destination"
                >
                  <X size={13} aria-hidden="true" />
                </button>
              )}
              <button className={`pinbtn ${armed === 'to' ? 'armed' : ''}`} disabled={!from} onClick={() => setArmed(armed === 'to' ? null : 'to')}><PinIcon /> Map</button>
            </div>
            {toOpen && toHits.length > 0 && (
              <div className="acmenu">
                {toHits.map((h, i) => (
                  <button key={i} className="acitem" onMouseDown={() => choose(h, pickTo)}>
                    <span className="hittag">{h.kind === 'stop' ? 'Stop' : h.kind === 'area' ? 'Area' : 'Place'}</span>
                    {h.name}{h.sub ? <span className="acsub"> {h.sub}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* A toast, not a banner in the flow. Inserted above the picker it pushed the
          whole page - map included - down by its own height, which is a lot of movement
          for a message about one failed click. */}
      {pickError && (
        <div
          role="status"
          className="fixed top-4 left-1/2 z-50 flex -translate-x-1/2 items-start gap-2 rounded-lg border border-bad bg-bad px-3 py-2 text-[13px] text-white shadow-lg"
        >
          <CircleX size={16} aria-hidden="true" className="mt-px shrink-0" />
          <span>{pickError}</span>
          <button
            className="ml-2 cursor-pointer font-bold text-white/80 hover:text-white"
            onClick={() => setPickError(null)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <ModePicker />

      {/* Only rendered on narrow screens; CSS hides it where both panes fit. */}
      <div className="mapswitch">
        <button
          className={`mapswitchbtn ${mapOpen ? 'on' : ''}`}
          onClick={() => setMapOpen(!mapOpen)}
          aria-pressed={mapOpen}
        >
          <PinIcon />
          {mapOpen ? 'Back to times' : 'View map'}
        </button>
      </div>

      <div className={`plancontent ${mapOpen ? 'mapopen' : ''}`}>
        <section className="planleft">
          {/* Every timetable, stop and fare here came from Golden Arrow, so turning it
              off leaves nothing to search. Saying so beats an empty result that looks
              like the journey does not exist. */}
          {modes.none && (
            <div className="placeholder">
              No transport selected. Everything this app knows about comes from
              <b> Golden Arrow</b>, so turn it back on above to plan a journey. Metro Rail
              and MyCiTi are not available yet.
            </div>
          )}
          {!modes.none && stage === 'from' && (
            <div className="placeholder">
              Search a stop or place above, or tap <b>Map</b> to drop a pin.
            </div>
          )}

          {!modes.none && stage === 'reachable' && (
            <>
              <div className="reachhead">
                {reachable == null ? 'Finding destinations…'
                  : <>You can reach {filteredReach.length} stop{filteredReach.length === 1 ? '' : 's'} from <b>{from!.name}</b> on one {from!.mode === 'train' ? 'train' : 'bus'}{from!.kind === 'pin' ? <span className="approxtag"> (near your point)</span> : null}</>}
              </div>
              <div className="browsehint">Popular places you can reach from here. You can also type any stop or place above.</div>
              <div className="reachlist">
                {filteredReach.map((r) => (
                  <button key={r.id} className="reachitem" onClick={() =>
                    pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                    <span className="rname">{r.name}</span>
                    <span className="rtrips">{r.trip_count} trips</span>
                  </button>
                ))}
                {reachable != null && filteredReach.length === 0 && (
                  <div className="empty">No direct {vehicle} goes to "{toText}" from here.</div>
                )}
              </div>

              {filteredConnecting.length > 0 && (
                <>
                  <div className="reachhead sub">
                    …and {filteredConnecting.length} more with one change of bus
                  </div>
                  <div className="browsehint">
                    No single bus runs the whole way, so these need you to change once. Pick
                    one and I will work out where to change and what time to be there.
                  </div>
                  <div className="reachlist">
                    {filteredConnecting.map((r) => (
                      <button key={r.id} className="reachitem connecting" onClick={() =>
                        pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                        <span className="rname">{r.name}</span>
                        <span className="rtrips">1 change</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </>
          )}

          {!modes.none && stage === 'journeys' && (
            <>
              <div className="reachhead">
                <b>{from!.name}</b> <span className="arrowin">to</span> <b>{to!.name}</b>
                <button className="link" onClick={() => { setTo(null); setToText(''); setPlan(null); setDayAlts({}) }}>Change destination</button>
              </div>
              {loading && <div className="placeholder">Finding buses…</div>}

              {/* Above the results, not below them. A shorter journey is only useful
                  before the rider has read and chosen from the long one. */}
              {!loading && !connLoading && betterNearby.length > 0 && bestLegs < Infinity && (
                <div className="altbox better">
                  <div className="altlbl">
                    <Lightbulb size={15} aria-hidden="true" className="alticon" />
                    <span>
                      <b>Suggestion.</b> {to!.name} needs {bestLegs} bus{bestLegs === 1 ? '' : 'es'},
                      but these stops nearby are quicker to reach.
                    </span>
                  </div>
                  <div className="altlist">
                    {betterNearby.map((r) => (
                      <button key={r.id} className="altitem" onClick={() =>
                        pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                        <span className="altname">{r.name}</span>
                        <span className="altmeta">
                          {r.km < 1 ? `${Math.round(r.km * 1000)} m` : `${r.km.toFixed(1)} km`} from{' '}
                          {to!.name} · {r.change ? '2 buses' : 'direct'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {plan && !loading && plan.length > 0 && (
                <div className="banner good">
                  <CircleCheck size={16} aria-hidden="true" />
                  <span><b>Direct bus.</b> You can travel from {from!.name} to {to!.name} without changing.</span>
                </div>
              )}

              {plan && !loading && connLoading && (
                <div className="banner info">
                  <Info size={16} aria-hidden="true" />
                  <span>
                    {plan.length === 0 ? `No direct ${vehicle}. Looking` : 'Also looking'}
                    {' '}for a journey with a change…
                  </span>
                </div>
              )}

              {/* Shown whether or not something runs straight through: one direct bus
                  used to hide every journey with a change, so a rider after the train
                  from Kraaifontein to Rosebank was told there wasn't one. */}
              {plan && !loading && !connLoading && conns && conns.length > 0 && (
                <>
                  <div className={plan.length === 0 ? 'banner warn' : 'banner info'}>
                    {plan.length === 0
                      ? <TriangleAlert size={16} aria-hidden="true" />
                      : <Info size={16} aria-hidden="true" />}
                    <span>
                      {plan.length === 0
                        ? <><b>No direct {vehicle}</b> from {from!.name} to {to!.name}. You can still get there by taking </>
                        : <>You can also get from {from!.name} to {to!.name} by taking </>}
                      <b>{connLegs} {connVehicles}</b>, changing at <b>{conns[0].change_at.join(' then ')}</b>.
                    </span>
                  </div>
                  <ConnectionsPanel connections={conns} legsRequired={connLegs}
                    mode={connFrom?.operator_kind ?? vehicle} />
                </>
              )}

              {plan && !loading && plan.length === 0 && !connLoading && conns && conns.length === 0 && (
                <div className="banner bad">
                  <CircleX size={16} aria-hidden="true" />
                  <span>
                    <b>No way to get there by {vehicle}.</b> There is no direct service from {from!.name} to{' '}
                    {to!.name}, and no combination of up to three {vehicles} connects them either.
                  </span>
                </div>
              )}

              {plan && !loading && plan.length === 0 && !connLoading && conns && conns.length === 0
                && nearbyAlternatives.length > 0 && (
                <div className="altbox">
                  <div className="altlbl">
                    You can reach these stops near {to!.name}
                  </div>
                  <div className="altlist">
                    {nearbyAlternatives.map((r) => (
                      <button key={r.id} className="altitem" onClick={() =>
                        pickTo({ kind: 'stop', id: r.id, name: r.name, lat: r.lat!, lon: r.lon! })}>
                        <span className="altname">{r.name}</span>
                        <span className="altmeta">
                          {r.km < 1 ? `${Math.round(r.km * 1000)} m` : `${r.km.toFixed(1)} km`} away
                          {r.change ? ' · 1 change' : ' · direct'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {plan && !loading && plan.length === 0 && !connLoading && conns === null && (
                <div className="banner bad">
                  <CircleX size={16} aria-hidden="true" />
                  <span>
                    <b>No direct {vehicle}.</b> Journeys with a change can only be worked out between
                    named stops, not dropped pins.
                  </span>
                </div>
              )}

              {plan && !loading && plan.map((o, i) => {
                const sign = busSign(o.route_label)
                const groups = bucketDeps(o.departures)
                return (
                  <div key={i} className={`optcard ${i === sel ? 'active' : ''}`}>
                    <div className="opthead" onClick={() => setSel(i)}>
                      {/* Two rows, not three columns. The sign used to sit between the
                          number and the pills, which left it floating in the middle of
                          the card with no edge to line up against and squeezed the route
                          line into a narrow column. The number and the pills own the top
                          row; the sign gets the full width underneath. */}
                      <div className="optheadtop">
                        <span className="optrank" aria-label={`Route choice ${i + 1} of ${plan.length}`}>
                          {i + 1}
                        </span>
                        <span className="optmeta">
                          {hasApprox(o) && <span className="approxpill">Approx times</span>}
                          <span className="daypill">{DAY_LABEL[o.day_type] ?? o.day_type}</span>
                        </span>
                      </div>
                      <div className="signblock">
                        <div className="signlbl">Look for the bus to</div>
                        <div className="signdest">{sign.terminus}</div>
                        <div className="signroute">Route: {o.route_label}, timetable #{o.timetable_number}</div>
                      </div>
                    </div>
                    <FarePanel fare={o.fare}
                      mode={o.operator_kind === 'train' ? 'train' : 'bus'} />
                    <div className="depshint">Tap a departure to see where you get on and off.</div>
                    {[...TIME_GROUPS, { key: 'other', label: 'Other times' }].map((g) =>
                      groups[g.key].length > 0 ? (
                        <div key={g.key} className="depgroup">
                          <div className="depgrouplbl">{g.label}</div>
                          <div className="depsgrid">
                            {groups[g.key].map(({ d, j }) => {
                              const planned = planner.has({
                                scheduleId: d.schedule_id, tripIndex: d.trip_index,
                                fromSeq: d.from_seq, toSeq: d.to_seq,
                              })
                              return (
                                <div key={j} className={`depwrap ${planned ? 'planned' : ''}`}>
                                  <button className={`dep ${openDep?.oi === i && openDep?.di === j ? 'on' : ''}`}
                                    onClick={() => selectDep(i, j, d)}>
                                    <span className="deptimes">
                                      <DepTime raw={d.board_raw} approx={d.board_approx} />
                                      <span className="da">to</span>
                                      <DepTime raw={d.arrive_raw} approx={d.arrive_approx}
                                        useful={boundIsUseful(d.arrive_minutes, d.arrive_approx, d.board_minutes)} />
                                    </span>
                                    {/* Cash only, as everywhere else. A card price is
                                        not what a cash payer is charged and a card holder
                                        has already bought their rides. */}
                                    {o.fare?.cash_cents != null && (
                                      <span className="depfare">{rands(o.fare.cash_cents)}</span>
                                    )}
                                  </button>
                                  {/* The stop count shares the row with Add, so a rider
                                      can tell a fast bus from a slow one without opening
                                      each departure in turn. */}
                                  <div className="depfoot">
                                    <button
                                      className={`addbtn ${planned ? 'on' : ''}`}
                                      onClick={() => togglePlanned(o, d)}
                                      title={planned ? 'Remove from your planner' : 'Add to your planner'}
                                      aria-pressed={planned}
                                    >
                                      {planned ? '✓ Added' : '+ Add'}
                                    </button>
                                    {stopLabel(d.stop_count) && (
                                      <span className={`depstops ${d.stop_count === 0 ? 'direct' : ''}`}>
                                        {stopLabel(d.stop_count)}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ) : null,
                    )}
                    {/* Never on a train: a place is where the walk starts, not where
                        anybody boards. See PlanScreen. */}
                    {openDep?.oi === i && (
                      <TripStrip
                        stops={tripStops} loading={loadingTrip} notes={tripNotes}
                        riderFromSeq={o.departures[openDep.di]?.from_seq ?? 0}
                        riderToSeq={o.departures[openDep.di]?.to_seq ?? 9999}
                        boardPin={pinEnd({ end: from, label: o.board_label,
                          operatorKind: o.operator_kind,
                          time: o.departures[openDep.di]?.board_raw,
                          approx: o.departures[openDep.di]?.board_approx })}
                        alightPin={pinEnd({ end: to, label: o.alight_label,
                          operatorKind: o.operator_kind,
                          time: o.departures[openDep.di]?.arrive_raw,
                          approx: o.departures[openDep.di]?.arrive_approx })}
                        boardTime={alightOrNone(o.departures[openDep.di], 'board')}
                        alightTime={alightOrNone(o.departures[openDep.di], 'alight')}
                        kind={o.operator_kind === 'train' ? 'train' : 'bus'}
                        onClose={() => setOpenDep(null)}
                      />
                    )}
                  </div>
                )
              })}

              {plan && !loading && altDays.length > 0 && (
                <div className="nearbybox">
                  <div className="nearbyhead">
                    {plan.length ? `On other days, the nearest stop with a direct ${vehicle}:` : `Nearest stops with a direct ${vehicle} there:`}
                  </div>
                  {altDays.map((d) => (
                    <div key={d} className="dayalt">
                      <div className="dayaltlbl">{DAY_LABEL[d]}</div>
                      {dayAlts[d].map((o) => (
                        <button key={o.id} className="nearbyitem" onClick={() => useAlt(o)}>
                          <span className="rname">{o.name}</span>
                          <span className="rtrips">
                            {(o.distance_m / 1000).toFixed(1)} km away{o.earliest ? `, first ${vehicle} ${o.earliest}` : ''}, {o.trip_count} trips
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}

              {plan && !loading && plan.length === 0 && altDays.length === 0 && (
                <div className="empty">No stop within 8 km has a direct {vehicle} there either.</div>
              )}
            </>
          )}
        </section>

        <section className="planright">
          <PlanMap
            from={from} to={to} segment={segment} roadPath={roadPath} ride={ride}
            reachable={stage === 'reachable' && from ? [from, ...(reachable ?? [])] : undefined}
            onMapClick={onMapClick}
            armLabel={armed === 'from' ? 'your starting point' : armed === 'to' ? 'your destination' : null}
          />
        </section>
      </div>
    </div>
  )
}
