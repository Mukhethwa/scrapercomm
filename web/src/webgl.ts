/**
 * Can this device run the MapLibre basemap?
 *
 * MapLibre 6 asks for a WebGL 2 context and has no WebGL 1 path, so a device without it
 * gets no map from mapcn at all - and, without a guard, an exception during render that
 * would take the timetables and fares down with it. Leaflet needs no WebGL, which is why
 * it is still here as the fallback.
 *
 * Checked once and cached: creating a context is not free, and the answer cannot change
 * within a page view.
 */
let cached: boolean | null = null

export function supportsWebGL2(): boolean {
  if (cached !== null) return cached
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl2')
    // Chrome can hand back a context that is immediately lost on a blocklisted driver,
    // which would fail later rather than here. Treat that as unsupported now.
    cached = !!gl && !(gl as WebGL2RenderingContext).isContextLost()
  } catch {
    cached = false
  }
  return cached
}
