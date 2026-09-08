/**
 * An operator's own logo, where we have one.
 *
 * A generic bus glyph says "some bus company". A rider standing at a stop is looking for
 * a particular livery, and the operator's own mark is what they are actually matching
 * against - so it earns its place over an icon.
 *
 * The file is looked up by operator id, so adding MyCiTi or Metrorail later is a matter
 * of dropping a file in, not of touching this. Where no file exists - or where it fails
 * to load - the mode icon takes over, because a broken image is worse than a plain one.
 */
import { useState } from 'react'
import { Bus, Train } from '@phosphor-icons/react'

const FALLBACK = { bus: Bus, train: Train }

/**
 * Which file each operator's mark lives in.
 *
 * Explicit rather than guessed at, because the extension differs by whatever the operator
 * publishes and a 404 per card is not worth the convenience of a convention.
 */
const LOGOS: Record<string, string> = {
  gabs: '/operators/gabs.png',
  metrorail: '/operators/metrorail.png',
}

export default function OperatorLogo({ id, name, kind, size = 36 }: {
  id: string
  name: string
  kind: 'bus' | 'train'
  /** The height to draw at. Width follows the artwork, which is rarely square. */
  size?: number
}) {
  const [failed, setFailed] = useState(false)
  const src = LOGOS[id]
  const Icon = FALLBACK[kind]

  if (!src || failed) {
    return (
      <span
        className="flex shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
        style={{ width: size, height: size }}
      >
        <Icon size={Math.round(size * 0.5)} weight="fill" aria-hidden="true" />
      </span>
    )
  }

  return (
    /*
     * A rectangle sized by height, not a circle sized by diameter.
     *
     * The Golden Arrow mark is 182x122 and carries a tagline under the letters. Fitted
     * into a round 36px badge the words become a smudge - so the holder takes the shape
     * of the artwork instead, and the row it sits in simply gets a little wider.
     *
     * The white ground stays white in both themes: an operator's mark is drawn for its
     * own background, and recolouring somebody else's logo is not ours to do.
     */
    <span
      className="flex shrink-0 items-center justify-center bg-white px-1.5 py-1"
      style={{ height: size }}
    >
      <img
        src={src}
        alt={`${name} logo`}
        className="h-full w-auto object-contain"
        onError={() => setFailed(true)}
      />
    </span>
  )
}
