import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Keeps a broken map from taking the journey with it.
 *
 * The map is the least important thing on the page - the times, the stops and the fares
 * all read perfectly well without it - but it is by far the most likely to fail, because
 * it is the only part that depends on the device's graphics stack. Without a boundary,
 * an exception while the map renders unmounts the whole app and a rider loses the
 * timetable they came for.
 *
 * A class component on purpose: catching render errors is the one thing hooks cannot do.
 */
export default class MapBoundary extends Component<
  { children: ReactNode; fallback?: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Left on the console rather than swallowed: this is the failure most likely to be
    // reported as "the app is broken on my phone", and it should be diagnosable.
    console.error('Map failed to render; the rest of the page continues.', error, info)
  }

  render() {
    if (this.state.failed) {
      return (
        this.props.fallback ?? (
          <div className="map-wrap">
            <p className="map-note">
              The map could not be drawn on this device. Everything else on this page -
              the times, the stops and the fares - still works.
            </p>
          </div>
        )
      )
    }
    return this.props.children
  }
}
