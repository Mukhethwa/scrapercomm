/**
 * One operator's departures, as a card the eye can take in at once.
 *
 * The old screen gave every route its own card and every card its whole day, stacked
 * downward. One operator running three routes filled a screen before a rider had
 * compared a single time, and the moment a second operator is loaded that becomes
 * unreadable. So the card's height is fixed and the departures run sideways: a rider
 * looks *down* the page to compare operators, and *across* one to compare times.
 *
 * The whole day is still there, behind "View full day", and split into morning,
 * afternoon and evening exactly as the original was. Moving a hundred departures behind
 * a button without splitting them would only have hidden the wall, not removed it.
 */
import { useState } from 'react'
import { ArrowUpRight, Check, X } from '@phosphor-icons/react'
import OperatorLogo from './OperatorLogo'
import type { DepartureBlock, OperatorGroup } from './results'
import {
  bucketByTimeOfDay, journeySpan, spanLabel, travelLabel, blockKey, ownsOpenDeparture,
  DAY_LABEL,
} from './results'
import { shortTime, boundIsUseful } from './times'
import { cashFare } from './money'

/**
 * What a rider looks for on the front of the bus.
 *
 * The design asked for a route number. There is none: the operator names routes
 * ("KHAYELITSHA - HARARE - BELLVILLE") and numbers only timetables ("006201"), which is
 * an internal reference no commuter has ever seen on a vehicle. The destination is both
 * true and the thing actually painted on the bus.
 */
/**
 * How many stops the rider sits through, excluding their own two ends.
 *
 * "Direct" rather than the shared helper's "non-stop": Inter's hyphen carries enough
 * space that "non-stop" reads as "non - stop" at 11px. The classic view keeps its own
 * wording, which suits the font it was set in.
 */
function stopsLabel(n: number | null | undefined): string | null {
  if (n == null) return null
  if (n === 0) return 'Direct'
  return n === 1 ? '1 stop' : `${n} stops`
}

function busTo(routeLabel: string, kind: 'bus' | 'train' = 'bus'): string {
  /*
   * What a rider is looking for as the vehicle arrives.
   *
   * On a bus that is the destination painted on the front, which is the last place its
   * route names. A train is not signed that way: PRASA labels the service by its line and
   * direction, and that is what the platform indicator shows - so "Southern Line" is the
   * useful thing, and "to Southern line inbound" is nonsense a rider cannot act on.
   */
  if (kind === 'train') {
    const line = routeLabel.replace(/\b(INBOUND|OUTBOUND)\b/i, '').trim()
    return line ? line.replace(/\s+/g, ' ') : routeLabel
  }
  // A label that already names its own destination, which is how MyCiTi writes one.
  //
  // Golden Arrow labels a direction by its two ends - "CAPE GATE - TOWN CENTRE" - so the
  // terminus is the part after the last dash. MyCiTi writes "T01 to Civic Centre", which
  // has no dash in it, so that rule took the whole string and produced "to T01 to civic
  // centre". The route number is what is lit up on the front of a MyCiTi bus, so the
  // label is already the right words and only needs leaving alone.
  const own = routeLabel.match(/^(\S+) to (.+)$/)
  if (own) return `${own[1]} to ${sentence(own[2])}`

  const parts = routeLabel.split(' - ').map((s) => s.trim()).filter(Boolean)
  const terminus = parts[parts.length - 1] ?? routeLabel
  // Title case: the data shouts, and a small grey line under a time should not.
  return `to ${sentence(terminus)}`
}

/** "TOWN CENTRE" -> "Town centre". Left alone if it is not already shouting. */
function sentence(text: string): string {
  if (text !== text.toUpperCase()) return text
  return `${text.charAt(0)}${text.slice(1).toLowerCase()}`
}

function Block({ block, planned, onAdd, onOpen, open, kind }: {
  block: DepartureBlock
  planned: boolean
  onAdd: () => void
  onOpen: () => void
  open: boolean
  kind: 'bus' | 'train'
}) {
  const d = block.departure
  const board = shortTime(d.board_raw, d.board_approx)
  const arrive = shortTime(
    d.arrive_raw,
    d.arrive_approx,
  )
  const arriveUseful = boundIsUseful(d.arrive_minutes, d.arrive_approx, d.board_minutes)
  // The cash fare or none. A Gold Card price on a tile told a cash payer a number they
  // will not be charged, which is the whole reason this changed.
  const fare = cashFare(block.fare)
  const stops = stopsLabel(d.stop_count)
  /**
   * How long this one bus takes, in brackets beside the arrival.
   *
   * Per departure rather than per operator: routes to the same place take very different
   * roads - some to Bellville go round by Durbanville - so an operator-wide "15 to 115
   * min" is true and useless, while a duration against one departure is what lets a rider
   * pick the fast one. Beside the arrival because that is the moment the question occurs:
   * "07:30" means nothing until you know it is two and a quarter hours away.
   */
  const span = spanLabel(journeySpan(block))

  return (
    /*
     * A solid orange block with white on it, square-cornered, the way the brand's own
     * tiles are drawn. Everything inside is therefore white: the price cannot stay orange
     * on orange, and a corner would make it a card rather than a tile.
     *
     * The open one deepens rather than lightens, and takes a white ring: on a row of
     * identical orange blocks a border colour alone does not register.
     */
    <div className={`flex h-full w-[150px] shrink-0 flex-col gap-1 p-3 text-white ${
      open ? 'bg-accent-fill ring-2 ring-white ring-inset' : 'bg-accent'}`}>
      <button className="cursor-pointer text-left" onClick={onOpen}
        title="See the whole trip, and where you get on and off">
        {/* A plan covers every day the route runs, so the row holds Saturday buses beside
            Tuesday ones. Without this they are indistinguishable, and a rider plans around
            a bus that does not run on the day they are travelling. */}
        <div className="text-[10px] font-bold tracking-[.06em] text-white/90 uppercase">
          {DAY_LABEL[block.dayType] ?? block.dayType}
        </div>
        <div className={`text-[22px] leading-tight font-bold tracking-tight ${
          board.approx ? 'text-white/90' : 'text-white'}`}>
          {board.text}
        </div>
        <div className="text-[11px] text-white/90">
          {arriveUseful ? `arrives ${arrive.text}` : 'no set arrival'}
          {arriveUseful && span && <span className="font-semibold"> ({span})</span>}
        </div>
      </button>
      {fare && <div className="text-[13px] font-bold text-white">{fare}</div>}
      <div className="truncate text-[11px] text-white/90" title={block.routeLabel}>
        {busTo(block.routeLabel, kind)}
      </div>
      {/* The two things that separate one bus from another at the same minute. */}
      <div className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-white/90">
        {stops && <span className={d.stop_count === 0 ? 'font-semibold text-white' : ''}>{stops}</span>}
      </div>
      <button
        className={`mt-auto cursor-pointer border px-2 py-1.5 text-[11px] font-semibold ${
          planned
            ? 'border-white bg-white text-accent-fill'
            : 'border-white/60 text-white hover:bg-white/15'
        }`}
        onClick={onAdd}
        aria-pressed={planned}
      >
        {planned ? '✓ Added' : '+ Add to Planner'}
      </button>
    </div>
  )
}

/** The whole day, split the way the original view split it. */
function FullDay({ group, shown, onClose, isPlanned, onAdd, onOpen, openKey }: {
  group: OperatorGroup
  shown: DepartureBlock[]
  onClose: () => void
  isPlanned: (b: DepartureBlock) => boolean
  onAdd: (b: DepartureBlock) => void
  onOpen: (b: DepartureBlock) => void
  openKey: string | null
}) {
  const buckets = bucketByTimeOfDay(shown)
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40"
      onClick={onClose} role="dialog" aria-modal="true" aria-label={`${group.name}, full day`}>
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto bg-panel p-4 sm:mb-8 sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-[15px] font-bold text-ink">{group.name}</div>
            <div className="text-[12px] text-sub">{shown.length} departures</div>
          </div>
          <button className="cursor-pointer p-2 text-ink hover:bg-line/50"
            onClick={onClose} aria-label="Close">
            <X size={18} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {buckets.map((bucket) => (
          <div key={bucket.key} className="mb-4">
            <div className="mb-2 text-[11px] font-bold tracking-[.05em] text-sub uppercase">
              {bucket.label}
            </div>
            <div className="flex flex-wrap items-stretch gap-2">
              {bucket.blocks.map((b) => (
                <Block
                  key={blockKey(b.optionIndex, b.departureIndex)}
                  block={b}
                  planned={isPlanned(b)}
                  kind={group.kind}
                  open={openKey === blockKey(b.optionIndex, b.departureIndex)}
                  onAdd={() => onAdd(b)}
                  onOpen={() => onOpen(b)}
                />
              ))}
            </div>
          </div>
        ))}

        {shown.length === 0 && (
          <div className="py-6 text-center text-[13px] text-sub">
            No more departures at or after the time you chose.
          </div>
        )}
      </div>
    </div>
  )
}

export default function OperatorCard({ group, shown, all, isPlanned, onAdd, onOpen, openKey, detail }: {
  group: OperatorGroup
  /** The departures in the carousel: still to come, capped. */
  shown: DepartureBlock[]
  /** Everything still to come, for the full-day sheet. */
  all: DepartureBlock[]
  isPlanned: (b: DepartureBlock) => boolean
  onAdd: (b: DepartureBlock) => void
  onOpen: (b: DepartureBlock) => void
  openKey: string | null
  /**
   * The opened departure's stop-by-stop breakdown, drawn immediately under the row it
   * came from. It used to render below every card and every suggestion, so tapping a
   * time appeared to do nothing until the rider scrolled - which is indistinguishable
   * from a dead button.
   */
  detail?: React.ReactNode
}) {
  const [fullDay, setFullDay] = useState(false)
  /**
   * Whether the opened departure is one of this operator's.
   *
   * Asked against everything still to come rather than the eight in the carousel,
   * because a departure opened from the full-day sheet is this card's too.
   */
  const mine = ownsOpenDeparture(openKey, all)
  /**
   * The spread across every route this operator runs between these two stops. Kept as a
   * range and never averaged: the wide ones are wide because the routes genuinely differ,
   * and a mean would hide exactly the choice a rider is making.
   */
  const travel = travelLabel(group.travel)

  return (
    <div className="border border-line bg-panel p-4">
      <div className="mb-3 flex items-center gap-2.5">
        <OperatorLogo id={group.id} name={group.name} kind={group.kind} size={36} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-[15px] font-bold text-ink">{group.name}</span>
            {/* The original view said this as a full-width green banner. It is worth
                keeping and not worth a banner: no change of bus is the best answer on
                the board, and it should read like one without taking a row to do it. */}
            <span className="inline-flex shrink-0 items-center gap-1 bg-good-soft px-2 py-0.5 text-[10px] font-bold tracking-[.04em] text-good-strong uppercase">
              <Check size={11} weight="bold" aria-hidden="true" />
              Direct {group.kind === 'train' ? 'train' : 'bus'}
            </span>
          </div>
          {travel && <div className="text-[12px] text-sub">{travel} depending on route</div>}
        </div>
      </div>

      {/* The row scrolls inside the card's padding rather than bleeding past it. A
          negative margin put the peek right on the corner, and on a phone the
          corner sliced through the block - it read as broken rather than as "more this
          way". Clipping at the padding edge keeps the half-visible block and keeps it
          square. */}
      <div className="flex snap-x snap-mandatory gap-2 overflow-x-auto py-1">
        {shown.map((b) => (
          <div className="flex snap-start" key={blockKey(b.optionIndex, b.departureIndex)}>
            <Block
              block={b}
              planned={isPlanned(b)}
              kind={group.kind}
              open={openKey === blockKey(b.optionIndex, b.departureIndex)}
              onAdd={() => onAdd(b)}
              onOpen={() => onOpen(b)}
            />
          </div>
        ))}
        {shown.length === 0 && (
          <div className="py-4 text-[13px] text-sub">
            No more {group.kind === 'train' ? 'trains' : 'buses'} today at that time.
          </div>
        )}
      </div>

      {/* Only the operator whose departure is open. Every card was handed the same node
          and every card drew it, so opening the 04:50 train put an identical train
          breakdown under Golden Arrow Buses, beneath a heading reading DIRECT BUS. */}
      {mine && detail && <div className="mt-3">{detail}</div>}

      <div className="mt-2 text-right">
        <button
          className="inline-flex cursor-pointer items-center gap-1 text-[13px] font-semibold text-accent-deep hover:underline"
          onClick={() => setFullDay(true)}
        >
          View Full Day
          <ArrowUpRight size={14} weight="bold" aria-hidden="true" />
        </button>
      </div>

      {fullDay && (
        <FullDay
          group={group}
          shown={all}
          openKey={openKey}
          onClose={() => setFullDay(false)}
          isPlanned={isPlanned}
          onAdd={onAdd}
          onOpen={(b) => { onOpen(b); setFullDay(false) }}
        />
      )}
    </div>
  )
}
