import 'leaflet/dist/leaflet.css'

import L from 'leaflet'
import { useEffect, useRef } from 'react'

import { strings } from '../../strings/en'
import type { Pin } from './draft'

const d = strings.pharmacy.details

// The pin is drawn here: Leaflet's own marker is a picture file, and the website loads
// no pictures (docs/11 §10).
const PIN_ICON = L.divIcon({
  className: 'map-pin',
  html:
    '<svg viewBox="0 0 32 40" width="32" height="40" aria-hidden="true">' +
    '<path d="M16 0C7.2 0 0 7 0 15.6 0 27 16 40 16 40s16-13 16-24.4C32 7 24.8 0 16 0z" fill="#2f4bdb"/>' +
    '<circle cx="16" cy="15" r="6" fill="#ffffff"/></svg>',
  iconSize: [32, 40],
  iconAnchor: [16, 40],
})

/**
 * A map on which a pharmacy puts its pin (PS-1; docs/11 §11). A tap puts it, a drag
 * moves it. With a keyboard: move the map with the arrow keys, then press the button
 * under it, which puts the pin at the map's centre.
 *
 * The map's pictures come from OpenStreetMap's servers, straight to this browser: they
 * see which part of the map is looked at, never where the pin is put (docs/10 §4.3).
 */
export default function PinMap({
  value,
  center,
  onChange,
  label = d.map,
}: {
  value: Pin | null
  center: Pin
  onChange: (pin: Pin) => void
  /** What the map is for, said to a screen reader. A pharmacy's pin unless told. */
  label?: string
}) {
  const holder = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const marker = useRef<L.Marker | null>(null)
  const tell = useRef(onChange)
  useEffect(() => {
    tell.current = onChange
  }, [onChange])
  const start = useRef({ value, center })

  useEffect(() => {
    if (!holder.current) return
    const { value: pin, center: around } = start.current
    const made = L.map(holder.current, {
      center: pin ? [pin.lat, pin.lon] : [around.lat, around.lon],
      zoom: pin ? 16 : 12,
      // The wheel scrolls the page, not the map: a form with a map in the middle must
      // not swallow the scroll (seen while trying the admin's page). + and − zoom.
      scrollWheelZoom: false,
    })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: d.mapCredit,
    }).addTo(made)
    // Only the map's own credit: no link that leaves the form.
    made.attributionControl.setPrefix(false)
    made.on('click', (event: L.LeafletMouseEvent) =>
      tell.current({ lat: event.latlng.lat, lon: event.latlng.lng }),
    )
    map.current = made
    return () => {
      made.remove()
      map.current = null
      marker.current = null
    }
  }, [])

  // The pin follows the value: put by a tap here, or read from what was saved.
  useEffect(() => {
    if (!map.current) return
    if (!value) {
      marker.current?.remove()
      marker.current = null
      return
    }
    if (marker.current) {
      marker.current.setLatLng([value.lat, value.lon])
      return
    }
    const placed = L.marker([value.lat, value.lon], {
      icon: PIN_ICON,
      draggable: true,
      keyboard: false,
    }).addTo(map.current)
    placed.on('dragend', () => {
      const at = placed.getLatLng()
      tell.current({ lat: at.lat, lon: at.lng })
    })
    marker.current = placed
  }, [value])

  // Choosing a district moves the map there, until a pin says where the pharmacy is.
  const hasPin = value !== null
  useEffect(() => {
    if (map.current && !hasPin) map.current.setView([center.lat, center.lon], 13)
  }, [center.lat, center.lon, hasPin])

  return (
    <div className="map-field">
      <div ref={holder} className="map" role="application" aria-label={label} />
      <button
        type="button"
        className="text-button"
        onClick={() => {
          const at = map.current?.getCenter()
          if (at) onChange({ lat: at.lat, lon: at.lng })
        }}
      >
        {d.pinHere}
      </button>
    </div>
  )
}
