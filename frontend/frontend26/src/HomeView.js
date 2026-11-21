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

function RecenterMap({ coords }) {
  const map = useMap();
  useEffect(() => {
    if (coords) {
      map.flyTo([coords.latitude, coords.longitude], 16, { duration: 1.5 });
    }
  }, [coords, map]);
  return null;
}

// Forces Leaflet to recalculate tile bounds when entering/exiting fullscreen
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

    // In fullscreen mode, allow normal scrolling/dragging since page scroll isn't needed
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

function getAqiGradient(value) {
  const num = parseFloat(value);
  if (isNaN(num) || value === '') return 'linear-gradient(135deg, #1e293b, #334155)';
  if (num <= 50) return 'linear-gradient(135deg, #065f46, #10b981)';
  if (num <= 100) return 'linear-gradient(135deg, #92400e, #f59e0b)';
  if (num <= 150) return 'linear-gradient(135deg, #9a3412, #f97316)';
  return 'linear-gradient(135deg, #991b1b, #ef4444)';
}

function getWindGradient(value) {
  const num = parseFloat(value);
  if (isNaN(num) || value === '') return 'linear-gradient(135deg, #1e293b, #334155)';
  if (num <= 15) return 'linear-gradient(135deg, #075985, #0ea5e9)';
  if (num <= 35) return 'linear-gradient(135deg, #115e59, #14b8a6)';
  if (num <= 60) return 'linear-gradient(135deg, #854d0e, #eab308)';
  return 'linear-gradient(135deg, #581c87, #a855f7)';
}

const LAYER_OPTIONS = [
  { id: 'wind', label: 'Wind' },
  { id: 'airQuality', label: 'Air Quality' },
  { id: 'uvIndex', label: 'UV Index' },
  { id: 'rainfall', label: 'Rainfall' },
];

export default function HomeView() {
  const [selectedLayer, setSelectedLayer] = useState(null);
  const [location, setLocation] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Track whether viewport is desktop (>= 768px)
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  );

  // Gesture hint state
  const [gestureHint, setGestureHint] = useState(null);
  const hintTimeoutRef = useRef(null);

  // Sample read-only values
  const [airQuality] = useState('42');
  const [windSpeed] = useState('18');

  const defaultPosition = [51.505, -0.09];

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

  // Allow pressing Escape key on desktop to exit fullscreen
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  // Lock background page scroll while map is fullscreen
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

  const handleToggleLayer = (id) => {
    setSelectedLayer((prev) => (prev === id ? null : id));
  };

  const showDesktopFullscreenBar = isFullscreen && isDesktop;

  const mapWrapperStyle = isFullscreen
    ? {
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100dvh',
        zIndex: 2000, // Above fixed navbar (zIndex 1100)
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

      {/* Read-Only Air Quality & Wind Speed Gradient Cards */}
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
            Air Quality (AQI)
          </label>
          <input
            type="text"
            readOnly
            value={airQuality || '—'}
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
            background: getWindGradient(windSpeed),
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
            Wind Speed (km/h)
          </label>
          <input
            type="text"
            readOnly
            value={windSpeed ? `${windSpeed} km/h` : '—'}
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
        {/* Translucent Gesture Hint Overlay */}
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

        {/* Fullscreen Toggle Button (Lower Right Corner) */}
        <button
          type="button"
          onClick={() => setIsFullscreen((prev) => !prev)}
          title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen Map'}
          aria-label={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen Map'}
          style={{
            position: 'absolute',
            bottom: showDesktopFullscreenBar
              ? '84px' // Clear of the fixed bottom layer bar on desktop fullscreen
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
        {showDesktopFullscreenBar && (
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
              {LAYER_OPTIONS.map((option) => {
                const isOn = selectedLayer === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="switch"
                    aria-checked={isOn}
                    onClick={() => handleToggleLayer(option.id)}
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
                    <span>{option.label}</span>

                    {/* Mini Toggle Pill */}
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
          scrollWheelZoom={false}
          style={{ height: '100%', width: '100%', backgroundColor: '#1e293b' }}
        >
          <MapResizeHandler isFullscreen={isFullscreen} />
          <CooperativeGestures onShowHint={triggerGestureHint} isFullscreen={isFullscreen} />

          <TileLayer
            attribution='Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ'
            url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          />
          <TileLayer
            url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
          />

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

      {/* Bottom Exclusive Layer Options */}
      <div
        style={{
          backgroundColor: '#1e293b',
          borderRadius: '12px',
          border: '1px solid #334155',
          overflow: 'hidden',
        }}
      >
        {LAYER_OPTIONS.map((option, index) => {
          const isOn = selectedLayer === option.id;
          return (
            <div
              key={option.id}
              onClick={() => handleToggleLayer(option.id)}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '16px 20px',
                cursor: 'pointer',
                borderBottom: index < LAYER_OPTIONS.length - 1 ? '1px solid #334155' : 'none',
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
                {option.label}
              </span>

              <button
                type="button"
                role="switch"
                aria-checked={isOn}
                onClick={(e) => {
                  e.stopPropagation();
                  handleToggleLayer(option.id);
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
        })}
      </div>
    </>
  );
}