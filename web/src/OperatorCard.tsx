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
import { ArrowUpRight, Bus, TrainFront, X } from 'lucide-react'
import type { DepartureBlock, OperatorGroup } from './results'
import { bucketByTimeOfDay, blockDuration, travelLabel } from './results'
import { shortTime, boundIsUseful } from './times'
import { stopLabel } from './stops'
import { rands } from './money'

const ICON = { bus: Bus, train: TrainFront }

/**
 * What a rider looks for on the front of the bus.
 *
 * The design asked for a route number. There is none: the operator names routes
 * ("KHAYELITSHA - HARARE - BELLVILLE") and numbers only timetables ("006201"), which is
 * an internal reference no commuter has ever seen on a vehicle. The destination is both
 * true and the thing actually painted on the bus.
 */
function busTo(routeLabel: string): string {
  const parts = routeLabel.split(' - ').map((s) => s.trim()).filter(Boolean)
  const terminus = parts[parts.length - 1] ?? routeLabel
  // Title case: the data shouts, and a small grey line under a time should not.
  return `to ${terminus.charAt(0)}${terminus.slice(1).toLowerCase()}`
}

function Block({ block, planned, onAdd, onOpen, open }: {
  block: DepartureBlock
  planned: boolean
  onAdd: () => void
  onOpen: () => void
  open: boolean
}) {
  const d = block.departure
  const board = shortTime(d.board_raw, d.board_approx)
  const arrive = shortTime(
    d.arrive_raw,
    d.arrive_approx,
  )
  const arriveUseful = boundIsUseful(d.arrive_minutes, d.arrive_approx, d.board_minutes)
  const fare = rands(block.fare?.per_ride_cents)
  const stops = stopLabel(d.stop_count)
  /**
   * How long this one bus takes. Shown per departure rather than per operator: routes to
   * the same place take very different roads - some to Bellville go round by Durbanville
   * - so an operator-wide "15-115 min" is true and useless, while a duration against one
   * departure is what lets a rider pick the fast one.
   */
  const mins = blockDuration(block)

  return (
    <div className={`flex w-[136px] shrink-0 flex-col gap-1 rounded-xl p-3 ${
      open ? 'bg-accent-soft ring-1 ring-accent ring-inset' : 'bg-bg'}`}>
      <button className="cursor-pointer text-left" onClick={onOpen}
        title="See the whole trip, and where you get on and off">
        <div className={`text-[22px] leading-tight font-bold tracking-tight ${
          board.approx ? 'text-sub' : 'text-ink'}`}>
          {board.text}
        </div>
        <div className="text-[11px] text-sub">
          {arriveUseful ? `arrives ${arrive.text}` : 'no set arrival'}
        </div>
      </button>
      {fare && <div className="text-[13px] font-bold text-accent">{fare}</div>}
      <div className="truncate text-[11px] text-sub" title={block.routeLabel}>
        {busTo(block.routeLabel)}
      </div>
      {/* The two things that separate one bus from another at the same minute. */}
      <div className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-sub">
        {stops && <span className={d.stop_count === 0 ? 'font-semibold text-ink' : ''}>{stops}</span>}
        {stops && mins != null && <span aria-hidden="true">·</span>}
        {mins != null && <span>{mins} min</span>}
      </div>
      <button
        className={`mt-1 cursor-pointer rounded-lg border px-2 py-1.5 text-[11px] font-semibold ${
          planned
            ? 'border-accent bg-accent-soft text-accent'
            : 'border-line bg-panel text-ink hover:border-accent'
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
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-panel p-4 sm:mb-8 sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-[15px] font-bold text-ink">{group.name}</div>
            <div className="text-[12px] text-sub">{shown.length} departures</div>
          </div>
          <button className="cursor-pointer rounded-lg p-2 text-ink hover:bg-black/5"
            onClick={onClose} aria-label="Close">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {buckets.map((bucket) => (
          <div key={bucket.key} className="mb-4">
            <div className="mb-2 text-[11px] font-bold tracking-[.05em] text-sub uppercase">
              {bucket.label}
            </div>
            <div className="flex flex-wrap gap-2">
              {bucket.blocks.map((b) => (
                <Block
                  key={`${b.optionIndex}-${b.departureIndex}`}
                  block={b}
                  planned={isPlanned(b)}
                  open={openKey === `${b.optionIndex}-${b.departureIndex}`}
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

export default function OperatorCard({ group, shown, all, isPlanned, onAdd, onOpen, openKey }: {
  group: OperatorGroup
  /** The departures in the carousel: still to come, capped. */
  shown: DepartureBlock[]
  /** Everything still to come, for the full-day sheet. */
  all: DepartureBlock[]
  isPlanned: (b: DepartureBlock) => boolean
  onAdd: (b: DepartureBlock) => void
  onOpen: (b: DepartureBlock) => void
  openKey: string | null
}) {
  const [fullDay, setFullDay] = useState(false)
  const Icon = ICON[group.kind]
  /**
   * The spread across every route this operator runs between these two stops. Kept as a
   * range and never averaged: the wide ones are wide because the routes genuinely differ,
   * and a mean would hide exactly the choice a rider is making.
   */
  const travel = travelLabel(group.travel)

  return (
    <div className="rounded-2xl bg-panel p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
          <Icon size={17} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-bold text-ink">{group.name}</div>
          {travel && <div className="text-[12px] text-sub">{travel} depending on route</div>}
        </div>
      </div>

      {/* The row scrolls inside the card's padding rather than bleeding past it. A
          negative margin put the peek right on the rounded corner, and on a phone the
          corner sliced through the block - it read as broken rather than as "more this
          way". Clipping at the padding edge keeps the half-visible block and keeps it
          square. */}
      <div className="flex snap-x snap-mandatory gap-2 overflow-x-auto py-1">
        {shown.map((b) => (
          <div className="snap-start" key={`${b.optionIndex}-${b.departureIndex}`}>
            <Block
              block={b}
              planned={isPlanned(b)}
              open={openKey === `${b.optionIndex}-${b.departureIndex}`}
              onAdd={() => onAdd(b)}
              onOpen={() => onOpen(b)}
            />
          </div>
        ))}
        {shown.length === 0 && (
          <div className="py-4 text-[13px] text-sub">No more buses today at that time.</div>
        )}
      </div>

      <div className="mt-2 text-right">
        <button
          className="inline-flex cursor-pointer items-center gap-1 text-[13px] font-semibold text-accent hover:underline"
          onClick={() => setFullDay(true)}
        >
          View Full Day
          <ArrowUpRight size={14} aria-hidden="true" />
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
