import { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Circle, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

// Fix for default Leaflet marker icons
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

// ============================================================================
// ENDPOINT BUILDER (Literal URLs so exact query params are sent as-is)
// ============================================================================
const POLLUTANTS_URL =
  process.env.REACT_APP_POLLUTANTS_API_URL || 'https://adahack.duckdns.org/api/v1/';

const STATIONS_URL =
  process.env.REACT_APP_STATIONS_API_URL || 'https://adahack.duckdns.org/api/v1/stations';

const READINGS_ORIGIN =
  process.env.REACT_APP_READINGS_BASE_URL || 'https://adahack.duckdns.org/api/v1/readings';

function getPollutantsEndpoint() {
  return `${POLLUTANTS_URL}`;
}

function getStationsEndpoint() {
  return `${STATIONS_URL}`;
}

function getReadingsEndpoint(pollutant) {
  const safePollutant = pollutant || 'NO2';
  const start = '2026-11-01T01';
  const end = '2026-11-22T01';
  const compact = 'false';
  return `${READINGS_ORIGIN}?pollutant=${safePollutant}&start=${start}&end=${end}&compact=${compact}`;
}
// ============================================================================

function RecenterMap({ coords }) {
  const map = useMap();
  useEffect(() => {
    if (coords) {
      const targetZoom = Math.min(16, map.getMaxZoom());
      map.flyTo([coords.latitude, coords.longitude], targetZoom, { duration: 1.5 });
    }
  }, [coords, map]);
  return null;
}

function MapResizeHandler({ isFullscreen }) {
  const map = useMap();
  useEffect(() => {
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 50);
    return () => clearTimeout(timer);
  }, [isFullscreen, map]);
  return null;
}

// Requires Ctrl/Cmd + Scroll on desktop, and 2 fingers on mobile
function CooperativeGestures({ onShowHint, isFullscreen }) {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();

    if (isFullscreen) {
      map.scrollWheelZoom.enable();
      map.dragging.enable();
      return;
    }

    map.scrollWheelZoom.disable();

    const handleWheel = (e) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        e.stopPropagation();

        const delta = e.deltaY < 0 ? 1 : -1;
        const nextZoom = map.getZoom() + delta;
        const point = map.mouseEventToContainerPoint(e);
        const latLng = map.containerPointToLatLng(point);
        map.setZoomAround(latLng, nextZoom);
      } else {
        onShowHint('Use Ctrl + scroll to zoom the map');
      }
    };

    const handleTouchStart = (e) => {
      if (e.touches.length === 1) {
        map.dragging.disable();
      } else if (e.touches.length >= 2) {
        map.dragging.enable();
      }
    };

    const handleTouchMove = (e) => {
      if (e.touches.length === 1) {
        onShowHint('Use two fingers to move the map');
      }
    };

    const handleTouchEnd = () => {
      map.dragging.enable();
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    container.addEventListener('touchstart', handleTouchStart, { passive: true });
    container.addEventListener('touchmove', handleTouchMove, { passive: true });
    container.addEventListener('touchend', handleTouchEnd, { passive: true });

    return () => {
      container.removeEventListener('wheel', handleWheel);
      container.removeEventListener('touchstart', handleTouchStart);
      container.removeEventListener('touchmove', handleTouchMove);
      container.removeEventListener('touchend', handleTouchEnd);
    };
  }, [map, onShowHint, isFullscreen]);

  return null;
}

function valueToRgb(value) {
  const stops = [
    { v: 0, rgb: [16, 185, 129] },
    { v: 50, rgb: [250, 204, 21] },
    { v: 100, rgb: [249, 115, 22] },
    { v: 150, rgb: [239, 68, 68] },
  ];

  if (value <= stops[0].v) return stops[0].rgb;
  if (value >= stops[stops.length - 1].v) return stops[stops.length - 1].rgb;

  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i];
    const b = stops[i + 1];
    if (value >= a.v && value <= b.v) {
      const t = (value - a.v) / (b.v - a.v);
      return [
        Math.round(a.rgb[0] + (b.rgb[0] - a.rgb[0]) * t),
        Math.round(a.rgb[1] + (b.rgb[1] - a.rgb[1]) * t),
        Math.round(a.rgb[2] + (b.rgb[2] - a.rgb[2]) * t),
      ];
    }
  }
  return stops[0].rgb;
}

function distanceKm(lat1, lon1, lat2, lon2) {
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const avgLat = (((lat1 + lat2) / 2) * Math.PI) / 180;
  const x = dLon * Math.cos(avgLat);
  return 6371 * Math.sqrt(dLat * dLat + x * x);
}

function extractStationValue(station) {
  const rawList = Array.isArray(station?.readings)
    ? station.readings
    : Array.isArray(station?.reading)
    ? station.reading
    : [];

  const validValues = rawList
    .map((entry) => {
      if (entry && typeof entry === 'object' && entry.value !== undefined) {
        return parseFloat(entry.value);
      }
      return parseFloat(entry);
    })
    .filter((num) => !Number.isNaN(num));

  if (validValues.length === 0) return null;
  return validValues[validValues.length - 1];
}

function StationPollutionLayer({ points, maxRadiusKm = 35, power = 2 }) {
  const map = useMap();

  useEffect(() => {
    if (!points || points.length === 0) return;

    const CustomGridLayer = L.GridLayer.extend({
      createTile: function (coords) {
        const tile = document.createElement('canvas');
        const tileSize = this.getTileSize();
        const step = 4;
        tile.width = tileSize.x;
        tile.height = tileSize.y;

        const ctx = tile.getContext('2d');
        const nwPoint = coords.scaleBy(tileSize);

        for (let py = 0; py < tileSize.y; py += step) {
          for (let px = 0; px < tileSize.x; px += step) {
            const worldPoint = L.point(nwPoint.x + px + step / 2, nwPoint.y + py + step / 2);
            const latLng = map.unproject(worldPoint, coords.z);

            let weightSum = 0;
            let rSum = 0;
            let gSum = 0;
            let bSum = 0;
            let minDist = Infinity;
            let exactMatch = null;

            for (let i = 0; i < points.length; i++) {
              const pt = points[i];
              const d = distanceKm(latLng.lat, latLng.lng, pt.lat, pt.lon);
              if (d < minDist) minDist = d;

              if (d < 0.05) {
                exactMatch = pt;
                break;
              }

              if (d <= maxRadiusKm) {
                const w = 1 / Math.pow(d, power);
                const [r, g, b] = valueToRgb(pt.value);
                weightSum += w;
                rSum += w * r;
                gSum += w * g;
                bSum += w * b;
              }
            }

            let fillStyle = null;
            if (exactMatch) {
              const [r, g, b] = valueToRgb(exactMatch.value);
              fillStyle = `rgba(${r}, ${g}, ${b}, 0.55)`;
            } else if (weightSum > 0) {
              const r = Math.round(rSum / weightSum);
              const g = Math.round(gSum / weightSum);
              const b = Math.round(bSum / weightSum);
              const falloff = Math.max(0, 1 - minDist / maxRadiusKm);
              const alpha = (0.55 * Math.pow(falloff, 0.7)).toFixed(3);
              fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
            }

            if (fillStyle) {
              ctx.fillStyle = fillStyle;
              ctx.fillRect(px, py, step, step);
            }
          }
        }

        return tile;
      },
    });

    const layer = new CustomGridLayer({ opacity: 1, zIndex: 400 });
    layer.addTo(map);

    return () => {
      map.removeLayer(layer);
    };
  }, [map, points, maxRadiusKm, power]);

  return null;
}

function getAqiGradient(value) {
  const num = parseFloat(value);
  if (isNaN(num) || value === '' || value === null) {
    return 'linear-gradient(135deg, #1e293b, #334155)';
  }
  if (num <= 50) return 'linear-gradient(135deg, #065f46, #10b981)';
  if (num <= 100) return 'linear-gradient(135deg, #92400e, #f59e0b)';
  if (num <= 150) return 'linear-gradient(135deg, #9a3412, #f97316)';
  return 'linear-gradient(135deg, #991b1b, #ef4444)';
}

function getNo2Gradient(value) {
  const num = parseFloat(value);
  if (isNaN(num) || value === '' || value === null) {
    return 'linear-gradient(135deg, #1e293b, #334155)';
  }
  if (num <= 25) return 'linear-gradient(135deg, #075985, #0ea5e9)';
  if (num <= 40) return 'linear-gradient(135deg, #115e59, #14b8a6)';
  if (num <= 100) return 'linear-gradient(135deg, #854d0e, #eab308)';
  return 'linear-gradient(135deg, #581c87, #a855f7)';
}

async function fetchJsonWithDetails(url, signal) {
  console.log('[API Request]:', url);
  const res = await fetch(url, { signal });
  if (!res.ok) {
    let detail = '';
    try {
      const errBody = await res.json();
      detail = typeof errBody === 'string' ? errBody : JSON.stringify(errBody);
    } catch {
      detail = await res.text().catch(() => '');
    }
    throw new Error(`HTTP ${res.status} on ${url}${detail ? ` — ${detail}` : ''}`);
  }
  return res.json();
}

export default function HomeView() {
  const [pollutants, setPollutants] = useState([]);
  const [pollutantsLoading, setPollutantsLoading] = useState(true);
  const [pollutantsError, setPollutantsError] = useState(null);

  const [selectedPollutant, setSelectedPollutant] = useState('NO2');

  const [stations, setStations] = useState([]);
  const [stationsError, setStationsError] = useState(null);

  const [paintedPoints, setPaintedPoints] = useState([]);
  const [readingsLoading, setReadingsLoading] = useState(false);
  const [readingsError, setReadingsError] = useState(null);

  const [location, setLocation] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Left card: average of whichever pollutant is toggled on
  const [airQuality, setAirQuality] = useState('—');

  // Right card: always fetches and displays real NO2 data from the backend
  const [no2Value, setNo2Value] = useState(null);
  const [no2Loading, setNo2Loading] = useState(true);

  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  );

  const [gestureHint, setGestureHint] = useState(null);
  const hintTimeoutRef = useRef(null);

  const defaultPosition = [46.0569, 14.5058];

  // 1. Fetch pollutants list from https://adahack.duckdns.org/api/v1/ (body.pollutants)
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);

    async function loadPollutants() {
      setPollutantsLoading(true);
      setPollutantsError(null);

      try {
        const url = getPollutantsEndpoint();
        const data = await fetchJsonWithDetails(url, controller.signal);
        const list = Array.isArray(data?.pollutants) ? data.pollutants : [];

        if (!cancelled) {
          setPollutants(list);
          if (list.length > 0) {
            setSelectedPollutant((prev) => (list.includes(prev) ? prev : list[0]));
          }
        }
      } catch (err) {
        if (!cancelled) {
          setPollutantsError(
            err.name === 'AbortError' ? 'Pollutants request timed out after 8s' : err.message
          );
        }
      } finally {
        clearTimeout(timeoutId);
        if (!cancelled) {
          setPollutantsLoading(false);
        }
      }
    }

    loadPollutants();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
      controller.abort();
    };
  }, []);

  // 2. Fetch weather station coordinates (stations[i].details.lat & lon)
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function loadStations() {
      setStationsError(null);
      try {
        const url = getStationsEndpoint();
        const data = await fetchJsonWithDetails(url, controller.signal);
        const rawStations = Array.isArray(data?.stations) ? data.stations : [];

        const parsed = rawStations
          .map((st, idx) => ({
            id: st?.id ?? st?.station_id ?? st?.details?.station_id ?? `station_${idx}`,
            index: idx,
            lat: parseFloat(st?.details?.lat ?? st?.lat),
            lon: parseFloat(st?.details?.lon ?? st?.lon),
          }))
          .filter((st) => !Number.isNaN(st.lat) && !Number.isNaN(st.lon));

        if (!cancelled) {
          setStations(parsed);
        }
      } catch (err) {
        if (!cancelled && err.name !== 'AbortError') {
          setStationsError(err.message);
        }
      }
    }

    loadStations();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  // 3. Dedicated fetch for the hardcoded NO2 card from the backend
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function loadNo2CardData() {
      setNo2Loading(true);
      try {
        const url = getReadingsEndpoint('NO2');
        const data = await fetchJsonWithDetails(url, controller.signal);
        const readingStations = Array.isArray(data?.stations) ? data.stations : [];

        const values = readingStations
          .map((st) => extractStationValue(st))
          .filter((val) => val !== null && !Number.isNaN(val));

        if (!cancelled) {
          if (values.length > 0) {
            const avg = values.reduce((acc, v) => acc + v, 0) / values.length;
            setNo2Value(avg.toFixed(1));
          } else {
            setNo2Value(null);
          }
        }
      } catch (err) {
        if (!cancelled && err.name !== 'AbortError') {
          console.error('Failed to load NO2 card data:', err);
          setNo2Value(null);
        }
      } finally {
        if (!cancelled) {
          setNo2Loading(false);
        }
      }
    }

    loadNo2CardData();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  // 4. Fetch readings for active map pollutant and map station readings[].value to coordinates
  useEffect(() => {
    if (!selectedPollutant) return;

    let cancelled = false;
    const controller = new AbortController();

    async function loadReadingsForPollutant() {
      setReadingsLoading(true);
      setReadingsError(null);

      try {
        const url = getReadingsEndpoint(selectedPollutant);
        const data = await fetchJsonWithDetails(url, controller.signal);
        const readingStations = Array.isArray(data?.stations) ? data.stations : [];

        const combined = readingStations
          .map((st, idx) => {
            const val = extractStationValue(st);
            if (val === null || Number.isNaN(val)) return null;

            const stationId = st?.id ?? st?.station_id ?? st?.details?.station_id ?? null;
            const matchedById = stationId
              ? stations.find((s) => s.id && String(s.id) === String(stationId))
              : null;
            const matchedByIndex = stations[idx];

            const lat = parseFloat(
              st?.details?.lat ?? st?.lat ?? matchedById?.lat ?? matchedByIndex?.lat
            );
            const lon = parseFloat(
              st?.details?.lon ?? st?.lon ?? matchedById?.lon ?? matchedByIndex?.lon
            );

            if (Number.isNaN(lat) || Number.isNaN(lon)) {
              return null;
            }

            return {
              id: stationId || matchedByIndex?.id || `station_${idx}`,
              lat,
              lon,
              value: val,
            };
          })
          .filter(Boolean);

        if (!cancelled) {
          setPaintedPoints(combined);

          if (combined.length > 0) {
            const avg =
              combined.reduce((acc, item) => acc + item.value, 0) / combined.length;
            setAirQuality(avg.toFixed(1));
          } else {
            setAirQuality('—');
          }
        }
      } catch (err) {
        if (!cancelled && err.name !== 'AbortError') {
          setReadingsError(err.message);
          setPaintedPoints([]);
        }
      } finally {
        if (!cancelled) {
          setReadingsLoading(false);
        }
      }
    }

    loadReadingsForPollutant();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [selectedPollutant, stations]);

  useEffect(() => {
    const handleResize = () => {
      setIsDesktop(window.innerWidth >= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const triggerGestureHint = (message) => {
    setGestureHint(message);
    if (hintTimeoutRef.current) clearTimeout(hintTimeoutRef.current);
    hintTimeoutRef.current = setTimeout(() => {
      setGestureHint(null);
    }, 1500);
  };

  useEffect(() => {
    return () => {
      if (hintTimeoutRef.current) clearTimeout(hintTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  useEffect(() => {
    document.body.style.overflow = isFullscreen ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [isFullscreen]);

  const handleFindMe = () => {
    if (!('geolocation' in navigator)) {
      setError('Geolocation is not supported by your browser.');
      return;
    }

    setLoading(true);
    setError(null);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
        });
        setLoading(false);
      },
      (err) => {
        setError(err.message);
        setLoading(false);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  };

  const handleSelectPollutant = (pollutant) => {
    setSelectedPollutant(pollutant);
  };

  const showDesktopFullscreenBar = isFullscreen && isDesktop;

  const mapWrapperStyle = isFullscreen
    ? {
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100dvh',
        zIndex: 2000,
        borderRadius: 0,
        border: 'none',
        margin: 0,
      }
    : {
        position: 'relative',
        height: '450px',
        width: '100%',
        borderRadius: '12px',
        overflow: 'hidden',
        border: '1px solid #334155',
        boxShadow: '0 10px 25px rgba(0, 0, 0, 0.4)',
        marginBottom: '20px',
      };

  return (
    <>
      {/* Header & Location Button */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          marginBottom: '24px',
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: '24px', fontWeight: '700', letterSpacing: '-0.02em' }}>
            Environment & GPS Tracker
          </h1>
          {location ? (
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#94a3b8' }}>
              {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)} (±{Math.round(location.accuracy)}m)
            </p>
          ) : (
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#94a3b8' }}>
              Click below to center the map on your current location
            </p>
          )}
        </div>

        <button
          onClick={handleFindMe}
          disabled={loading}
          style={{
            padding: '10px 20px',
            cursor: loading ? 'not-allowed' : 'pointer',
            fontSize: '14px',
            fontWeight: '600',
            borderRadius: '8px',
            border: 'none',
            backgroundColor: '#3b82f6',
            color: '#ffffff',
            boxShadow: '0 4px 14px rgba(59, 130, 246, 0.4)',
            transition: 'background-color 0.2s ease',
          }}
        >
          {loading ? 'Locating...' : 'Show My Location'}
        </button>
      </div>

      {error && (
        <div
          style={{
            padding: '12px 16px',
            marginBottom: '16px',
            borderRadius: '8px',
            backgroundColor: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            color: '#fca5a5',
            fontSize: '14px',
          }}
        >
          Error: {error}
        </div>
      )}

      {(stationsError || readingsError) && (
        <div
          style={{
            padding: '12px 16px',
            marginBottom: '16px',
            borderRadius: '8px',
            backgroundColor: 'rgba(245, 158, 11, 0.15)',
            border: '1px solid rgba(245, 158, 11, 0.4)',
            color: '#fcd34d',
            fontSize: '14px',
            wordBreak: 'break-word',
          }}
        >
          {stationsError || readingsError}
        </div>
      )}

      {/* Read-Only Selected Pollutant & Live Backend NO2 Gradient Cards */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', marginBottom: '20px' }}>
        <div
          style={{
            flex: 1,
            minWidth: '160px',
            padding: '18px 20px',
            borderRadius: '12px',
            background: getAqiGradient(airQuality),
            border: '1px solid rgba(255, 255, 255, 0.12)',
            boxShadow: '0 8px 20px rgba(0, 0, 0, 0.25)',
            transition: 'background 0.4s ease',
          }}
        >
          <label
            style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '700',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: 'rgba(255, 255, 255, 0.85)',
              marginBottom: '8px',
            }}
          >
            {selectedPollutant} Index
          </label>
          <input
            type="text"
            readOnly
            value={readingsLoading ? 'Loading...' : airQuality || '—'}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '8px',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              backgroundColor: 'rgba(15, 23, 42, 0.45)',
              color: '#ffffff',
              fontSize: '20px',
              fontWeight: '700',
              boxSizing: 'border-box',
              outline: 'none',
              cursor: 'default',
            }}
          />
        </div>

        <div
          style={{
            flex: 1,
            minWidth: '160px',
            padding: '18px 20px',
            borderRadius: '12px',
            background: getNo2Gradient(no2Value),
            border: '1px solid rgba(255, 255, 255, 0.12)',
            boxShadow: '0 8px 20px rgba(0, 0, 0, 0.25)',
            transition: 'background 0.4s ease',
          }}
        >
          <label
            style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '700',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: 'rgba(255, 255, 255, 0.85)',
              marginBottom: '8px',
            }}
          >
            NO2
          </label>
          <input
            type="text"
            readOnly
            value={no2Loading ? 'Loading...' : no2Value !== null ? `${no2Value} µg/m³` : '—'}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '8px',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              backgroundColor: 'rgba(15, 23, 42, 0.45)',
              color: '#ffffff',
              fontSize: '20px',
              fontWeight: '700',
              boxSizing: 'border-box',
              outline: 'none',
              cursor: 'default',
            }}
          />
        </div>
      </div>

      {/* Esri Dark Gray Canvas Map Container */}
      <div style={mapWrapperStyle}>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 1000,
            backgroundColor: 'rgba(15, 23, 42, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
            opacity: gestureHint && !isFullscreen ? 1 : 0,
            transition: 'opacity 0.25s ease',
          }}
        >
          <span
            style={{
              backgroundColor: 'rgba(30, 41, 59, 0.95)',
              color: '#f8fafc',
              padding: '10px 18px',
              borderRadius: '8px',
              border: '1px solid #475569',
              fontSize: '15px',
              fontWeight: '600',
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
            }}
          >
            {gestureHint}
          </span>
        </div>

        <button
          type="button"
          onClick={() => setIsFullscreen((prev) => !prev)}
          title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen Map'}
          aria-label={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen Map'}
          style={{
            position: 'absolute',
            bottom: showDesktopFullscreenBar
              ? '84px'
              : isFullscreen
              ? 'calc(24px + env(safe-area-inset-bottom))'
              : '22px',
            right: '12px',
            zIndex: 1002,
            width: '38px',
            height: '38px',
            borderRadius: '8px',
            backgroundColor: '#1e293b',
            color: '#f8fafc',
            border: '1px solid #475569',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.45)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'background-color 0.2s ease, bottom 0.2s ease',
          }}
        >
          {isFullscreen ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 3v3a2 2 0 0 1-2 2H3" />
              <path d="M21 8h-3a2 2 0 0 1-2-2V3" />
              <path d="M3 16h3a2 2 0 0 1 2 2v3" />
              <path d="M16 21v-3a2 2 0 0 1 2-2h3" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 3h6v6" />
              <path d="M9 21H3v-6" />
              <path d="M21 3l-7 7" />
              <path d="M3 21l7-7" />
            </svg>
          )}
        </button>

        {/* Desktop-Only Fixed Bottom Bar in Fullscreen Mode */}
        {showDesktopFullscreenBar && pollutants.length > 0 && (
          <div
            style={{
              position: 'fixed',
              bottom: 0,
              left: 0,
              right: 0,
              zIndex: 1001,
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              backdropFilter: 'blur(10px)',
              borderTop: '1px solid #334155',
              padding: '12px 24px',
              display: 'flex',
              justifyContent: 'center',
              boxShadow: '0 -6px 24px rgba(0, 0, 0, 0.45)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                flexWrap: 'wrap',
              }}
            >
              {pollutants.map((pollutant) => {
                const isOn = selectedPollutant === pollutant;
                return (
                  <button
                    key={pollutant}
                    type="button"
                    role="switch"
                    aria-checked={isOn}
                    onClick={() => handleSelectPollutant(pollutant)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '8px 14px',
                      borderRadius: '10px',
                      border: isOn ? '1px solid #3b82f6' : '1px solid #334155',
                      backgroundColor: isOn ? 'rgba(59, 130, 246, 0.16)' : '#1e293b',
                      color: isOn ? '#ffffff' : '#cbd5e1',
                      fontSize: '14px',
                      fontWeight: '500',
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    <span>{pollutant}</span>

                    <span
                      style={{
                        width: '38px',
                        height: '22px',
                        borderRadius: '999px',
                        padding: '2px',
                        backgroundColor: isOn ? '#3b82f6' : '#475569',
                        display: 'inline-flex',
                        alignItems: 'center',
                        boxSizing: 'border-box',
                        transition: 'background-color 0.2s ease',
                      }}
                    >
                      <span
                        style={{
                          width: '18px',
                          height: '18px',
                          borderRadius: '50%',
                          backgroundColor: '#ffffff',
                          transform: isOn ? 'translateX(16px)' : 'translateX(0px)',
                          transition: 'transform 0.2s ease',
                        }}
                      />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <MapContainer
          center={defaultPosition}
          zoom={13}
          maxZoom={19}
          scrollWheelZoom={false}
          style={{ height: '100%', width: '100%', backgroundColor: '#1e293b' }}
        >
          <MapResizeHandler isFullscreen={isFullscreen} />
          <CooperativeGestures onShowHint={triggerGestureHint} isFullscreen={isFullscreen} />

          <TileLayer
            attribution='Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ'
            url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
            maxNativeZoom={16}
            maxZoom={19}
          />
          <TileLayer
            url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
            maxNativeZoom={16}
            maxZoom={19}
          />

          {paintedPoints.length > 0 && (
            <StationPollutionLayer points={paintedPoints} maxRadiusKm={1.5} power={2} />
          )}

          {location && (
            <>
              <RecenterMap coords={location} />
              <Marker position={[location.latitude, location.longitude]}>
                <Popup>
                  You are here! <br /> Accuracy: ±{Math.round(location.accuracy)} meters
                </Popup>
              </Marker>
              <Circle
                center={[location.latitude, location.longitude]}
                radius={location.accuracy}
                pathOptions={{ color: '#60a5fa', fillColor: '#3b82f6', fillOpacity: 0.2 }}
              />
            </>
          )}
        </MapContainer>
      </div>

      {/* Bottom Exclusive Pollutant Toggles */}
      <div
        style={{
          backgroundColor: '#1e293b',
          borderRadius: '12px',
          border: '1px solid #334155',
          overflow: 'hidden',
        }}
      >
        {pollutantsLoading ? (
          <div style={{ padding: '16px 20px', color: '#94a3b8', fontSize: '14px', textAlign: 'left' }}>
            Loading pollutants...
          </div>
        ) : pollutantsError ? (
          <div
            style={{
              padding: '16px 20px',
              color: '#fca5a5',
              fontSize: '14px',
              textAlign: 'left',
              wordBreak: 'break-word',
            }}
          >
            Failed to load pollutants: {pollutantsError}
          </div>
        ) : pollutants.length === 0 ? (
          <div style={{ padding: '16px 20px', color: '#94a3b8', fontSize: '14px', textAlign: 'left' }}>
            No pollutants returned.
          </div>
        ) : (
          pollutants.map((pollutant, index) => {
            const isOn = selectedPollutant === pollutant;
            return (
              <div
                key={pollutant}
                onClick={() => handleSelectPollutant(pollutant)}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '16px 20px',
                  cursor: 'pointer',
                  borderBottom: index < pollutants.length - 1 ? '1px solid #334155' : 'none',
                  backgroundColor: isOn ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                  transition: 'background-color 0.2s ease',
                }}
              >
                <span
                  style={{
                    textAlign: 'left',
                    fontSize: '15px',
                    fontWeight: '500',
                    color: isOn ? '#ffffff' : '#cbd5e1',
                  }}
                >
                  {pollutant}
                </span>

                <button
                  type="button"
                  role="switch"
                  aria-checked={isOn}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSelectPollutant(pollutant);
                  }}
                  style={{
                    width: '46px',
                    height: '26px',
                    borderRadius: '999px',
                    border: 'none',
                    padding: '3px',
                    backgroundColor: isOn ? '#3b82f6' : '#475569',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    transition: 'background-color 0.2s ease',
                    flexShrink: 0,
                  }}
                >
                  <span
                    style={{
                      width: '20px',
                      height: '20px',
                      borderRadius: '50%',
                      backgroundColor: '#ffffff',
                      boxShadow: '0 1px 3px rgba(0, 0, 0, 0.3)',
                      transform: isOn ? 'translateX(20px)' : 'translateX(0px)',
                      transition: 'transform 0.2s ease',
                    }}
                  />
                </button>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}