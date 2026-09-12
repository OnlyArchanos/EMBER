/**
 * FireMap — interactive map of classified fire detections with zone overlay.
 *
 * Uses MapLibre GL JS with CARTO's dark-matter vector basemap.
 * Fire markers are rendered as a GeoJSON source + circle layers (not DOM markers).
 * Receives flags data as a prop from Dashboard to highlight flagged persistent sources.
 */

import { useEffect, useRef, useState } from 'react';
import { Map as MapLibreMap, Popup, setWorkerUrl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { getFires, getZones } from '../api/client.js';
import { colors, fireTypeColor } from '../theme.js';

setWorkerUrl(workerUrl);


// --- CARTO basemap style URL ---
const CARTO_API_KEY = import.meta.env.VITE_CARTO_API_KEY;
const STYLE_URL = CARTO_API_KEY
  ? `https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json?key=${CARTO_API_KEY}`
  : 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

// --- GeoJSON feature builder ---
function buildFireFeatures(fires, flags = []) {
  const flaggedClusterIds = new Set(
    flags
      .filter(f => f.persistent_source && f.persistent_source.cluster_id != null)
      .map(f => f.persistent_source.cluster_id)
  );

  return fires.map(f => ({
    type: 'Feature',
    properties: {
      id: f.id,
      fire_type: f.fire_type,
      cluster_id: f.cluster_id,
      is_flagged: flaggedClusterIds.has(f.cluster_id) ? 1 : 0,
      state: f.state,
      district: f.district,
      acq_date: f.acq_date,
      acq_time: f.acq_time,
      brightness: f.brightness,
      frp: f.frp,
      confidence: f.confidence,
      satellite: f.satellite,
      is_persistent: f.is_persistent,
    },
    geometry: {
      type: 'Point',
      coordinates: [f.longitude, f.latitude],
    },
  }));
}

// --- WKT parsing ---

/**
 * Parse a WKT POLYGON or MULTIPOLYGON string into a GeoJSON geometry object.
 * Handles the two geometry types present in our zone data.
 */
function parseWktToGeoJson(wkt) {
  if (!wkt || typeof wkt !== 'string') return null;

  const trimmed = wkt.trim();

  if (trimmed.startsWith('MULTIPOLYGON')) {
    // MULTIPOLYGON (((lon lat, ...), (hole)), ((lon lat, ...)))
    const inner = trimmed.replace(/^MULTIPOLYGON\s*\(\s*/, '').replace(/\s*\)$/, '');
    const polygons = [];
    // Split on ")),((" to separate polygons
    const polyStrings = inner.split(/\)\s*,\s*\(/);
    for (const ps of polyStrings) {
      const cleaned = ps.replace(/^\(+/, '').replace(/\)+$/, '');
      const rings = cleaned.split(/\)\s*,\s*\(/);
      const parsedRings = rings.map(parseRing);
      if (parsedRings.every(r => r !== null)) {
        polygons.push(parsedRings);
      }
    }
    if (polygons.length === 0) return null;
    return { type: 'MultiPolygon', coordinates: polygons };
  }

  if (trimmed.startsWith('POLYGON')) {
    // POLYGON ((lon lat, lon lat, ...), (hole lon lat, ...))
    const inner = trimmed.replace(/^POLYGON\s*\(\s*/, '').replace(/\s*\)$/, '');
    const ringStrings = inner.split(/\)\s*,\s*\(/);
    const rings = ringStrings.map(r => parseRing(r.replace(/^\(+/, '').replace(/\)+$/, '')));
    if (rings.some(r => r === null)) return null;
    return { type: 'Polygon', coordinates: rings };
  }

  return null;
}

/** Parse a single ring string "lon lat, lon lat, ..." into [[lon, lat], ...] */
function parseRing(ringStr) {
  if (!ringStr) return null;
  const coords = ringStr.split(',').map(pair => {
    const parts = pair.trim().split(/\s+/);
    if (parts.length < 2) return null;
    const lon = parseFloat(parts[0]);
    const lat = parseFloat(parts[1]);
    if (isNaN(lon) || isNaN(lat)) return null;
    return [lon, lat];
  });
  if (coords.some(c => c === null)) return null;
  return coords;
}

// --- Zone colors (semi-transparent, per zone_type) ---
// Reuses fire type palette tokens: wildfire for forest, agricultural for farmland
const ZONE_COLORS = {
  industrial: colors.fireIndustrial,
  forest:     colors.fireWildfire,
  farmland:   colors.fireAgricultural,
};

/** Safely display a value, replacing null/undefined with "Unknown" */
function displayValue(val) {
  if (val === null || val === undefined || val === '') return 'Unknown';
  return String(val);
}

/** Capitalize first letter */
function capitalize(str) {
  if (!str) return 'Unknown';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// --- Component ---

function FireMap({
  flags = [],
  filters = null,
  selectedLocation = null,
  initialFires = null,
  initialZones = null,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const flagsRef = useRef(flags);
  flagsRef.current = flags;
  const rawFiresRef = useRef([]);
  const [error, setError] = useState(null);
  const [zonesVisible, setZonesVisible] = useState(true);
  const [loading, setLoading] = useState(true);

  // Update flagged ring when flags change without recreating the map
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded() || !map.getSource('fires')) return;
    const updatedFeatures = buildFireFeatures(rawFiresRef.current, flags);
    map.getSource('fires').setData({
      type: 'FeatureCollection',
      features: updatedFeatures,
    });
  }, [flags]);

  // Re-fetch fires when filter criteria change
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded() || !map.getSource('fires') || filters === null) return;

    let cancelled = false;
    async function updateFilteredFires() {
      try {
        const queryParams = { limit: 2000 };
        if (filters.fire_type) queryParams.fire_type = filters.fire_type;
        if (filters.state) queryParams.state = filters.state;
        if (filters.date_from) queryParams.date_from = filters.date_from;
        if (filters.date_to) queryParams.date_to = filters.date_to;

        const newFires = await getFires(queryParams);
        if (cancelled) return;

        const validFires = (Array.isArray(newFires) ? newFires : []).filter(
          f => f.latitude != null && f.longitude != null && isFinite(f.latitude) && isFinite(f.longitude)
        );
        rawFiresRef.current = validFires;
        const features = buildFireFeatures(validFires, flagsRef.current);
        map.getSource('fires').setData({
          type: 'FeatureCollection',
          features,
        });
      } catch (err) {
        console.error('Failed to update fires for filter:', err);
      }
    }

    updateFilteredFires();
    return () => {
      cancelled = true;
    };
  }, [filters]);

  // Pan map when a flagged cluster or location is selected
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedLocation || selectedLocation.latitude == null || selectedLocation.longitude == null) return;
    map.flyTo({
      center: [selectedLocation.longitude, selectedLocation.latitude],
      zoom: selectedLocation.zoom || 11,
      essential: true,
    });
  }, [selectedLocation]);


  useEffect(() => {
    let map;
    let cancelled = false;
    let loadTimeout;

    async function init() {
      // Check for missing CARTO basemap API key
      if (!CARTO_API_KEY || !CARTO_API_KEY.trim()) {
        if (!cancelled) {
          setError('Map style failed to load. Check your CARTO API key configuration.');
          setLoading(false);
        }
        return;
      }

      // Use pre-fetched data if provided by Dashboard, otherwise fetch
      let fires = initialFires || [];
      let zones = initialZones || [];

      if (!initialFires) {
        try {
          const [firesResult, zonesResult] = await Promise.allSettled([
            getFires({ limit: 2000 }),
            getZones(),
          ]);

          if (firesResult.status === 'fulfilled') {
            fires = firesResult.value;
          } else {
            console.error('Failed to load fires:', firesResult.reason);
            if (!cancelled) setError('Failed to load fire data. Is the backend running?');
            return;
          }

          if (zonesResult.status === 'fulfilled') {
            zones = zonesResult.value;
          } else {
            console.error('Failed to load zones (non-fatal, rendering fires only):', zonesResult.reason);
          }
        } catch (err) {
          console.error('Data fetch error:', err);
          if (!cancelled) setError(err.message);
          return;
        }
      }

      if (cancelled) return;

      // Filter out fires with missing/malformed coordinates
      const validFires = fires.filter(f =>
        f.latitude != null && f.longitude != null &&
        isFinite(f.latitude) && isFinite(f.longitude)
      );
      rawFiresRef.current = validFires;

      // Compute bounds from fire data for auto-fit
      let bounds = null;
      if (validFires.length > 0) {
        let minLon = Infinity, maxLon = -Infinity;
        let minLat = Infinity, maxLat = -Infinity;
        for (const f of validFires) {
          if (f.longitude < minLon) minLon = f.longitude;
          if (f.longitude > maxLon) maxLon = f.longitude;
          if (f.latitude < minLat) minLat = f.latitude;
          if (f.latitude > maxLat) maxLat = f.latitude;
        }
        bounds = [[minLon, minLat], [maxLon, maxLat]];
      }

      // Initialize map
      try {
        console.log('[FireMap] Creating MapLibre instance on container:', containerRef.current, {
          clientWidth: containerRef.current?.clientWidth,
          clientHeight: containerRef.current?.clientHeight,
          STYLE_URL,
        });

        map = new MapLibreMap({
          container: containerRef.current,
          style: STYLE_URL,
          center: [72.0, 22.5], // fallback center (Gujarat) — overridden by fitBounds
          zoom: 6,
          attributionControl: true,
        });
        mapRef.current = map;
        window.__map = map;
      } catch (err) {
        console.error('[FireMap] Map initialization failed:', err);
        if (!cancelled) setError(`Map failed to initialize: ${err.message}`);
        return;
      }

      // Safety timeout for map loading
      loadTimeout = setTimeout(() => {
        if (!cancelled && map && !map.loaded()) {
          console.warn('[FireMap] Map style load timed out after 15s');
          setError('Map style failed to load. Check your CARTO API key configuration.');
          setLoading(false);
        }
      }, 15000);

      // Handle map-level errors (bad style URL, tile load failures, invalid/revoked keys)
      map.on('error', (e) => {
        console.error('[FireMap] map.on("error"):', e.error || e);
        const errMsg = e?.error?.message || (typeof e?.error === 'string' ? e.error : '') || '';
        const status = e?.error?.status;
        if (
          status === 401 ||
          status === 403 ||
          status === 404 ||
          errMsg.toLowerCase().includes('style') ||
          errMsg.toLowerCase().includes('401') ||
          errMsg.toLowerCase().includes('403') ||
          errMsg.toLowerCase().includes('unauthorized') ||
          errMsg.toLowerCase().includes('forbidden') ||
          (!map.isStyleLoaded() && !map.loaded())
        ) {
          clearTimeout(loadTimeout);
          setError('Map style failed to load. Check your CARTO API key configuration.');
          setLoading(false);
        }
      });

      map.on('load', () => {
        console.log('[FireMap] map.on("load") event fired!');
        clearTimeout(loadTimeout);
        if (cancelled) return;
        setLoading(false);

        try {
          // --- Zone overlay ---
          console.log('[FireMap] Adding zones:', zones.length);
          if (zones.length > 0) {
            const zoneFeatures = zones
              .map(zone => {
                const geometry = parseWktToGeoJson(zone.geometry);
                if (!geometry) return null;
                return {
                  type: 'Feature',
                  properties: { zone_type: zone.zone_type, name: zone.name || '' },
                  geometry,
                };
              })
              .filter(Boolean);

            console.log('[FireMap] Parsed zone features:', zoneFeatures.length);
            if (zoneFeatures.length > 0) {
              map.addSource('zones', {
                type: 'geojson',
                data: { type: 'FeatureCollection', features: zoneFeatures },
              });


            map.addLayer({
              id: 'zones-fill',
              type: 'fill',
              source: 'zones',
              paint: {
                'fill-color': [
                  'match', ['get', 'zone_type'],
                  'industrial', ZONE_COLORS.industrial,
                  'forest',     ZONE_COLORS.forest,
                  'farmland',   ZONE_COLORS.farmland,
                  colors.textMuted,
                ],
                'fill-opacity': 0.2,
              },
            });

            map.addLayer({
              id: 'zones-outline',
              type: 'line',
              source: 'zones',
              paint: {
                'line-color': [
                  'match', ['get', 'zone_type'],
                  'industrial', ZONE_COLORS.industrial,
                  'forest',     ZONE_COLORS.forest,
                  'farmland',   ZONE_COLORS.farmland,
                  colors.textMuted,
                ],
                'line-width': 1,
                'line-opacity': 0.5,
              },
            });
          }
        }

        // --- Fire markers ---
        const fireFeatures = buildFireFeatures(validFires, flagsRef.current);

        map.addSource('fires', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: fireFeatures },
        });

        // Flagged ring layer (behind the dot) — accent-colored halo
        map.addLayer({
          id: 'fires-flagged-ring',
          type: 'circle',
          source: 'fires',
          filter: ['==', ['get', 'is_flagged'], 1],
          paint: {
            'circle-radius': 10,
            'circle-color': 'transparent',
            'circle-stroke-color': colors.accent,
            'circle-stroke-width': 2.5,
            'circle-stroke-opacity': 0.9,
          },
        });

        // Main fire dots
        map.addLayer({
          id: 'fires-layer',
          type: 'circle',
          source: 'fires',
          paint: {
            'circle-radius': 5,
            'circle-color': [
              'match', ['get', 'fire_type'],
              'industrial',   fireTypeColor.industrial,
              'wildfire',     fireTypeColor.wildfire,
              'agricultural', fireTypeColor.agricultural,
              'unclassified', fireTypeColor.unclassified,
              colors.textMuted,
            ],
            'circle-stroke-color': colors.background,
            'circle-stroke-width': 1,
            'circle-opacity': 0.9,
          },
        });

        // --- Popup on click ---
        map.on('click', 'fires-layer', (e) => {
          if (!e.features || e.features.length === 0) return;
          const props = e.features[0].properties;
          const coords = e.features[0].geometry.coordinates.slice();

          // Build popup HTML
          const flaggedBadge = props.is_flagged
            ? `<span style="color:${colors.accent};font-weight:600;">⚠ Flagged</span><br/>`
            : '';

          const confidenceMap = { l: 'Low', n: 'Nominal', h: 'High' };
          const confDisplay = confidenceMap[props.confidence] || displayValue(props.confidence);

          const html = `
            <div style="font-family:Inter,system-ui,sans-serif;font-size:13px;color:${colors.textPrimary};line-height:1.5;">
              ${flaggedBadge}
              <strong style="color:${fireTypeColor[props.fire_type] || colors.textPrimary};">
                ${capitalize(props.fire_type)}
              </strong><br/>
              <span style="color:${colors.textMuted};">Location:</span>
              ${displayValue(props.state)}${props.district && props.district !== 'null' ? ', ' + displayValue(props.district) : ''}<br/>
              <span style="color:${colors.textMuted};">Date:</span> ${displayValue(props.acq_date)}
              <span style="color:${colors.textMuted};">Time:</span> ${displayValue(props.acq_time)}<br/>
              <span style="color:${colors.textMuted};">Brightness:</span> ${displayValue(props.brightness)} K
              <span style="color:${colors.textMuted};">FRP:</span> ${displayValue(props.frp)} MW<br/>
              <span style="color:${colors.textMuted};">Confidence:</span> ${confDisplay}
              <span style="color:${colors.textMuted};">Satellite:</span> ${displayValue(props.satellite)}<br/>
              <span style="color:${colors.textMuted};">Persistent:</span> ${props.is_persistent ? 'Yes' : 'No'}
            </div>
          `;

          // Remove previous popup
          if (popupRef.current) popupRef.current.remove();

          popupRef.current = new Popup({
            closeButton: true,
            closeOnClick: true,
            maxWidth: '320px',
          })
            .setLngLat(coords)
            .setHTML(html)
            .addTo(map);
        });

        // Cursor change on hover
        map.on('mouseenter', 'fires-layer', () => {
          map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', 'fires-layer', () => {
          map.getCanvas().style.cursor = '';
        });

        // Auto-fit bounds to fire data
        if (bounds) {
          console.log('[FireMap] Fitting bounds:', bounds);
          map.fitBounds(bounds, { padding: 60, maxZoom: 12 });
        }

        // Force resize to ensure canvas matches container dimensions
        map.resize();
        console.log('[FireMap] Finished map setup successfully!');
      } catch (err) {
        console.error('[FireMap] Exception inside map.on("load") handler:', err);
      }
    });
  }

    init();

    return () => {
      cancelled = true;
      if (loadTimeout) clearTimeout(loadTimeout);
      if (popupRef.current) popupRef.current.remove();
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, []);

  // Toggle zone visibility
  function handleToggleZones() {
    const map = mapRef.current;
    if (!map) return;
    const next = !zonesVisible;
    setZonesVisible(next);
    const vis = next ? 'visible' : 'none';
    if (map.getLayer('zones-fill')) map.setLayoutProperty('zones-fill', 'visibility', vis);
    if (map.getLayer('zones-outline')) map.setLayoutProperty('zones-outline', 'visibility', vis);
  }

  // --- Error state ---
  if (error) {
    return (
      <div
        className="flex items-center justify-center h-full bg-panel border border-border rounded-lg"
        style={{ minHeight: '400px' }}
      >
        <div className="text-center p-8 max-w-md">
          <div className="text-4xl mb-4">🗺️</div>
          <h2 className="text-lg font-semibold text-text-primary mb-2">Map Unavailable</h2>
          <p className="text-text-muted text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full" style={{ width: '100%', height: '100%', minHeight: '400px' }}>
      {/* Map container */}
      <div ref={containerRef} className="absolute inset-0 rounded-lg overflow-hidden" style={{ width: '100%', height: '100%' }} />

      {/* Loading overlay */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-panel/80 rounded-lg z-10">
          <p className="text-text-muted text-sm">Loading map…</p>
        </div>
      )}



      {/* Zone toggle */}
      {!loading && (
        <button
          onClick={handleToggleZones}
          className="absolute top-3 right-3 z-20 px-3 py-1.5 text-xs font-medium rounded border transition-colors"
          style={{
            backgroundColor: zonesVisible ? colors.panel : 'transparent',
            borderColor: colors.border,
            color: zonesVisible ? colors.textPrimary : colors.textMuted,
          }}
        >
          {zonesVisible ? '🟢 Zones' : '⚪ Zones'}
        </button>
      )}

      {/* Legend */}
      {!loading && (
        <div
          className="absolute bottom-6 left-3 z-20 rounded-lg p-3 text-xs"
          style={{
            backgroundColor: `${colors.panel}ee`,
            borderColor: colors.border,
            border: `1px solid ${colors.border}`,
          }}
        >
          <div className="font-semibold text-text-primary mb-2">Fire Types</div>
          {Object.entries(fireTypeColor).map(([type, color]) => (
            <div key={type} className="flex items-center gap-2 mb-1">
              <span
                className="inline-block w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: color }}
              />
              <span style={{ color: colors.textMuted }}>{capitalize(type)}</span>
            </div>
          ))}
          <div className="flex items-center gap-2 mt-2 pt-2" style={{ borderTop: `1px solid ${colors.border}` }}>
            <span
              className="inline-block w-3 h-3 rounded-full"
              style={{
                backgroundColor: 'transparent',
                border: `2px solid ${colors.accent}`,
              }}
            />
            <span style={{ color: colors.accent }}>Flagged Source</span>
          </div>
          <div className="mt-2 pt-1" style={{ borderTop: `1px solid ${colors.border}`, color: colors.textMuted, fontSize: '10px' }}>
            © OpenStreetMap contributors · © CARTO
          </div>
        </div>
      )}
    </div>
  );
}

export default FireMap;
