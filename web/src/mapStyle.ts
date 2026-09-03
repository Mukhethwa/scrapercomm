import type { StyleSpecification } from 'maplibre-gl'

/**
 * OpenStreetMap raster tiles, as a MapLibre style.
 *
 * The same tiles Leaflet drew, and keyless - no account, no quota, no key in the client.
 * Raster rather than vector on purpose: vector basemaps that need a token would put a
 * credential in a public bundle, and the free vector demo tiles are rate limited.
 */
export const OSM_RASTER: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [
    { id: 'osm', type: 'raster', source: 'osm' },
  ],
}
