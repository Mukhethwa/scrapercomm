import { useEffect } from 'react'
import { LngLatBounds } from 'maplibre-gl'
import {
  Map, MapControls, MapMarker, MapRoute, MarkerContent, MarkerTooltip, useMap,
} from '@/components/ui/map'
import type { Stop } from './api'

/** MapLibre takes [longitude, latitude]; everything here is lat/lon. See PlanMap. */
const lngLat = (lat: number, lon: number): [number, number] => [lon, lat]

const CAPE_TOWN: [number, number] = lngLat(-33.925, 18.424)

/** See PlanMap: a map created in a hidden panel keeps a zero-sized buffer until told. */
function KeepSized() {
  const { map } = useMap()
  useEffect(() => {
    if (!map) return
    const ro = new ResizeObserver(() => map.resize())
    ro.observe(map.getContainer())
    map.resize()
    return () => ro.disconnect()
  }, [map])
  return null
}

function FitBounds({ pts }: { pts: [number, number][] }) {
  const { map, isLoaded } = useMap()
  const key = JSON.stringify(pts)
  useEffect(() => {
    if (!map || !isLoaded || pts.length === 0) return
    if (pts.length === 1) {
      map.easeTo({ center: pts[0], zoom: 14 })
      return
    }
    const bounds = pts.reduce((b, p) => b.extend(p), new LngLatBounds(pts[0], pts[0]))
    map.fitBounds(bounds, { padding: 30, duration: 400 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map, isLoaded])
  return null
}

export default function MapView({ stops }: { stops: Stop[] }) {
  const geo = stops.filter((s) => s.lat != null && s.lon != null)
  const pts = geo.map((s) => lngLat(s.lat as number, s.lon as number))
  const missing = stops.length - geo.length

  return (
    <div className="map-wrap">
      <Map
        className="map"
        center={pts[0] ?? CAPE_TOWN}
        zoom={12}
        attributionControl={{ compact: true }}
      >
        <MapControls position="top-left" />
        <KeepSized />
        <FitBounds pts={pts} />
        {pts.length > 1 && (
          <MapRoute id="route" coordinates={pts} color="#ff4500" width={3} opacity={0.85} />
        )}
        {geo.map((s, i) => {
          const first = i === 0
          const last = i === geo.length - 1
          // Black start, orange destination, neutral stops in between.
          const dot = first
            ? { size: 15, fill: '#111111', stroke: '#000000' }
            : last
              ? { size: 15, fill: '#ff4500', stroke: '#cc3700' }
              : { size: 11, fill: '#c9ced4', stroke: '#a8afb7' }
          return (
            <MapMarker
              key={`${s.stop_sequence}-${i}`}
              longitude={s.lon as number}
              latitude={s.lat as number}
            >
              <MarkerContent>
                <span
                  style={{
                    display: 'block', width: dot.size, height: dot.size, borderRadius: '50%',
                    background: dot.fill, border: `2px solid ${dot.stroke}`,
                    boxSizing: 'border-box',
                  }}
                  aria-label={s.name}
                />
              </MarkerContent>
              <MarkerTooltip>{`${s.stop_sequence + 1}. ${s.name}`}</MarkerTooltip>
            </MapMarker>
          )
        })}
      </Map>
      {missing > 0 && (
        <p className="map-note">
          {missing} of {stops.length} stops could not be geocoded and are not shown on the map.
        </p>
      )}
      {geo.length === 0 && (
        <p className="map-note">No geocoded coordinates for this direction's stops yet.</p>
      )}
    </div>
  )
}
