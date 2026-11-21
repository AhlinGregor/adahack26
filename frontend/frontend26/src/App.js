import { useState, useEffect } from 'react';
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

export default function LocationMap() {
  const [activeTab, setActiveTab] = useState('home'); // 'home' | 'route'
  const [selectedLayer, setSelectedLayer] = useState(null); // null or one of LAYER_OPTIONS ids

  const [location, setLocation] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // Sample read-only values
  const [airQuality] = useState('42');
  const [windSpeed] = useState('18');

  const defaultPosition = [51.505, -0.09];

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

  // Exclusive toggle handler: turns selected option on and turns all others off
  const handleToggleLayer = (id) => {
    setSelectedLayer((prev) => (prev === id ? null : id));
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: '#0f172a',
        color: '#f8fafc',
        padding: '24px 20px 48px',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        boxSizing: 'border-box',
      }}
    >
      {/* Centered 800px column matching map width */}
      <div style={{ maxWidth: '800px', margin: '0 auto' }}>
        
        {/* Top Navigation Tab Bar */}
        <div
          style={{
            display: 'flex',
            backgroundColor: '#1e293b',
            padding: '6px',
            borderRadius: '12px',
            border: '1px solid #334155',
            marginBottom: '28px',
            gap: '6px',
          }}
        >
          <button
            onClick={() => setActiveTab('home')}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              border: 'none',
              fontSize: '15px',
              fontWeight: '600',
              cursor: 'pointer',
              backgroundColor: activeTab === 'home' ? '#3b82f6' : 'transparent',
              color: activeTab === 'home' ? '#ffffff' : '#94a3b8',
              boxShadow: activeTab === 'home' ? '0 2px 8px rgba(59, 130, 246, 0.35)' : 'none',
              transition: 'all 0.2s ease',
            }}
          >
            Home
          </button>

          <button
            onClick={() => setActiveTab('route')}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              border: 'none',
              fontSize: '15px',
              fontWeight: '600',
              cursor: 'pointer',
              backgroundColor: activeTab === 'route' ? '#3b82f6' : 'transparent',
              color: activeTab === 'route' ? '#ffffff' : '#94a3b8',
              boxShadow: activeTab === 'route' ? '0 2px 8px rgba(59, 130, 246, 0.35)' : 'none',
              transition: 'all 0.2s ease',
            }}
          >
            Route
          </button>
        </div>

        {/* HOME VIEW */}
        {activeTab === 'home' ? (
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
            <div style={{ display: 'flex', gap: '16px', marginBottom: '20px' }}>
              <div
                style={{
                  flex: 1,
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
            <div
              style={{
                height: '450px',
                width: '100%',
                borderRadius: '12px',
                overflow: 'hidden',
                border: '1px solid #334155',
                boxShadow: '0 10px 25px rgba(0, 0, 0, 0.4)',
                marginBottom: '20px',
              }}
            >
              <MapContainer
                center={defaultPosition}
                zoom={13}
                style={{ height: '100%', width: '100%', backgroundColor: '#1e293b' }}
              >
                {/* Esri Dark Gray Base Map */}
                <TileLayer
                  attribution='Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ'
                  url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
                />

                {/* Esri Dark Gray Reference Layer (street & city labels) */}
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
                    {/* Left-aligned label */}
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

                    {/* Right-aligned toggle switch */}
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
        ) : (
          /* ROUTE VIEW (Empty Placeholder) */
          <div
            style={{
              height: '450px',
              backgroundColor: '#1e293b',
              borderRadius: '12px',
              border: '1px solid #334155',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#94a3b8',
            }}
          >
            <p style={{ fontSize: '18px', fontWeight: '600', color: '#e2e8f0', margin: '0 0 6px' }}>
              Route View
            </p>
            <p style={{ fontSize: '14px', margin: 0 }}>
              This view is currently empty.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}