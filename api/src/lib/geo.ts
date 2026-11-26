/**
 * The one place where stored GeoJSON becomes API coordinates (plan §9.1 "Location
 * format"). Clients only ever see `{lat, lng}`; GeoJSON's `[lng, lat]` order never leaks.
 */

export interface GeoPoint {
  type: "Point";
  coordinates: [number, number]; // [lng, lat]
}

export interface LatLng {
  lat: number;
  lng: number;
}

export function toLatLng(point: GeoPoint): LatLng {
  const [lng, lat] = point.coordinates;
  return { lat, lng };
}
