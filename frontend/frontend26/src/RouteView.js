import { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet';
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

const START_POINT = {
  label: 'Tehnološki park, Ljubljana',
  coords: [46.0506, 14.4605],
};

const END_POINT = {
  label: 'Park pri gradu Kodeljevo, Ljubljana',
  coords: [46.0468, 14.5342],
};

// Dummy route 1: Quickest route via main high-traffic roads (Tržaška -> Center -> Litijska)
const QUICKEST_ROUTE = {
  id: 'quickest',
  name: 'Quickest Route',
  duration: '16 min',
  distance: '6.4 km',
  avgNo2: '44.8 µg/m³',
  pollutionLevel: 'Moderate-High Traffic',
  color: '#f59e0b',
  path: [
    [46.0506, 14.4605], // Tehnološki park
    [46.0474, 14.4652], // Brdo / Pot Rdečega križa
    [46.0419, 14.4748], // Tržaška cesta (Vič)
    [46.0446, 14.4885], // Tržaška cesta (Mirje)
    [46.0467, 14.4998], // Aškerčeva cesta
    [46.0464, 14.5065], // Zoisova / Karlovški most
    [46.0454, 14.5142], // Roška / Poljanski nasip
    [46.0488, 14.5245], // Litijska cesta
    [46.0475, 14.5315], // Povšetova / Kodeljevo approach
    [46.0468, 14.5342], // Park pri gradu Kodeljevo
  ],
};

// Dummy route 2: Less air pollution route via green corridors & Ljubljanica riverbanks
const CLEAN_AIR_ROUTE = {
  id: 'clean',
  name: 'Less Air Pollution Route',
  duration: '21 min',
  distance: '7.2 km',
  avgNo2: '25.9 µg/m³',
  pollutionLevel: '42% Lower NO₂ • Green Corridor',
  color: '#10b981',
  path: [
    [46.0506, 14.4605], // Tehnološki park
    [46.0542, 14.4668], // PST / Večna pot edge
    [46.0568, 14.4775], // Rožnik / Tivoli forest edge
    [46.0545, 14.4892], // Tivoli Park paths
    [46.0518, 14.4995], // Cankarjeva / pedestrian zone
    [46.0504, 14.5078], // Petkovškovo nabrežje (car-free riverside)
    [46.0512, 14.5175], // Poljanski nasip riverside path
    [46.0501, 14.5268], // Ob Ljubljanici greenway
    [46.0481, 14.5322], // Kodeljevo park path
    [46.0468, 14.5342], // Park pri gradu Kodeljevo
  ],
};

function FitRoutesBounds({ showRoutes }) {
  const map = useMap();

  useEffect(() => {
    if (!showRoutes) return;
    const allCoords = [...QUICKEST_ROUTE.path, ...CLEAN_AIR_ROUTE.path];
    const bounds = L.latLngBounds(allCoords);
    map.fitBounds(bounds, { padding: [45, 45], maxZoom: 15 });
  }, [showRoutes, map]);

  return null;
}

export default function RouteView() {
  const [showRoutes, setShowRoutes] = useState(false);
  const [highlightedRoute, setHighlightedRoute] = useState(null); // null = both emphasized, or 'quickest' / 'clean'

  const defaultCenter = [46.0495, 14.498];

  const handleShowRoute = () => {
    setShowRoutes(true);
    setHighlightedRoute(null);
  };

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ margin: 0, fontSize: '24px', fontWeight: '700', letterSpacing: '-0.02em' }}>
          Clean Air Route Planner
        </h1>
        <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#94a3b8' }}>
          Compare the fastest path against the lowest air-pollution corridor across Ljubljana
        </p>
      </div>

      {/* Locked From / To Inputs & Show Route Button */}
      <div
        style={{
          backgroundColor: '#1e293b',
          borderRadius: '12px',
          border: '1px solid #334155',
          padding: '18px 20px',
          marginBottom: '20px',
          boxShadow: '0 8px 20px rgba(0, 0, 0, 0.25)',
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', marginBottom: '16px' }}>
          {/* From Box (Locked) */}
          <div style={{ flex: 1, minWidth: '220px' }}>
            <label
              htmlFor="route-from-input"
              style={{
                display: 'block',
                fontSize: '12px',
                fontWeight: '700',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                color: '#94a3b8',
                marginBottom: '6px',
              }}
            >
              From
            </label>
            <input
              id="route-from-input"
              type="text"
              value={START_POINT.label}
              readOnly
              disabled
              aria-readonly="true"
              style={{
                width: '100%',
                padding: '11px 14px',
                borderRadius: '8px',
                border: '1px solid #334155',
                backgroundColor: '#0f172a',
                color: '#e2e8f0',
                fontSize: '14px',
                fontWeight: '500',
                boxSizing: 'border-box',
                cursor: 'not-allowed',
                opacity: 0.9,
              }}
            />
          </div>

          {/* To Box (Locked) */}
          <div style={{ flex: 1, minWidth: '220px' }}>
            <label
              htmlFor="route-to-input"
              style={{
                display: 'block',
                fontSize: '12px',
                fontWeight: '700',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                color: '#94a3b8',
                marginBottom: '6px',
              }}
            >
              To
            </label>
            <input
              id="route-to-input"
              type="text"
              value={END_POINT.label}
              readOnly
              disabled
              aria-readonly="true"
              style={{
                width: '100%',
                padding: '11px 14px',
                borderRadius: '8px',
                border: '1px solid #334155',
                backgroundColor: '#0f172a',
                color: '#e2e8f0',
                fontSize: '14px',
                fontWeight: '500',
                boxSizing: 'border-box',
                cursor: 'not-allowed',
                opacity: 0.9,
              }}
            />
          </div>
        </div>

        <button
          type="button"
          onClick={handleShowRoute}
          style={{
            width: '100%',
            padding: '12px 20px',
            cursor: 'pointer',
            fontSize: '15px',
            fontWeight: '600',
            borderRadius: '8px',
            border: 'none',
            backgroundColor: '#3b82f6',
            color: '#ffffff',
            boxShadow: '0 4px 14px rgba(59, 130, 246, 0.4)',
            transition: 'background-color 0.2s ease',
          }}
        >
          Show Route
        </button>
      </div>

      {/* Map Container */}
      <div
        style={{
          position: 'relative',
          height: '450px',
          width: '100%',
          borderRadius: '12px',
          overflow: 'hidden',
          border: '1px solid #334155',
          boxShadow: '0 10px 25px rgba(0, 0, 0, 0.4)',
          marginBottom: '20px',
        }}
      >
        {/* Floating Legend Overlay once routes are shown */}
        {showRoutes && (
          <div
            style={{
              position: 'absolute',
              top: '12px',
              right: '12px',
              zIndex: 1000,
              backgroundColor: 'rgba(15, 23, 42, 0.92)',
              backdropFilter: 'blur(8px)',
              border: '1px solid #334155',
              borderRadius: '10px',
              padding: '10px 14px',
              boxShadow: '0 4px 14px rgba(0, 0, 0, 0.45)',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#f8fafc' }}>
              <span
                style={{
                  width: '18px',
                  height: '4px',
                  borderRadius: '999px',
                  backgroundColor: CLEAN_AIR_ROUTE.color,
                  display: 'inline-block',
                }}
              />
              <span>Less Air Pollution ({CLEAN_AIR_ROUTE.duration})</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#f8fafc' }}>
              <span
                style={{
                  width: '18px',
                  height: '4px',
                  borderRadius: '999px',
                  backgroundColor: QUICKEST_ROUTE.color,
                  display: 'inline-block',
                }}
              />
              <span>Quickest Route ({QUICKEST_ROUTE.duration})</span>
            </div>
          </div>
        )}

        <MapContainer
          center={defaultCenter}
          zoom={13}
          maxZoom={19}
          style={{ height: '100%', width: '100%', backgroundColor: '#1e293b' }}
        >
          <FitRoutesBounds showRoutes={showRoutes} />

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

          {/* Origin & Destination Markers */}
          <Marker position={START_POINT.coords}>
            <Popup>
              <strong>Start:</strong> {START_POINT.label}
            </Popup>
          </Marker>

          <Marker position={END_POINT.coords}>
            <Popup>
              <strong>Destination:</strong> {END_POINT.label}
            </Popup>
          </Marker>

          {/* Two Routes */}
          {showRoutes && (
            <>
              <Polyline
                positions={QUICKEST_ROUTE.path}
                pathOptions={{
                  color: QUICKEST_ROUTE.color,
                  weight: highlightedRoute === 'quickest' ? 7 : 5,
                  opacity: highlightedRoute === 'clean' ? 0.35 : 0.9,
                  dashArray: '8, 6',
                }}
                eventHandlers={{
                  click: () => setHighlightedRoute('quickest'),
                }}
              >
                <Popup>
                  <strong>{QUICKEST_ROUTE.name}</strong>
                  <br />
                  Time: {QUICKEST_ROUTE.duration} ({QUICKEST_ROUTE.distance})
                  <br />
                  Avg NO₂: {QUICKEST_ROUTE.avgNo2}
                </Popup>
              </Polyline>

              <Polyline
                positions={CLEAN_AIR_ROUTE.path}
                pathOptions={{
                  color: CLEAN_AIR_ROUTE.color,
                  weight: highlightedRoute === 'clean' ? 7 : 6,
                  opacity: highlightedRoute === 'quickest' ? 0.35 : 0.95,
                }}
                eventHandlers={{
                  click: () => setHighlightedRoute('clean'),
                }}
              >
                <Popup>
                  <strong>{CLEAN_AIR_ROUTE.name}</strong>
                  <br />
                  Time: {CLEAN_AIR_ROUTE.duration} ({CLEAN_AIR_ROUTE.distance})
                  <br />
                  Avg NO₂: {CLEAN_AIR_ROUTE.avgNo2} ({CLEAN_AIR_ROUTE.pollutionLevel})
                </Popup>
              </Polyline>
            </>
          )}
        </MapContainer>
      </div>

      {/* Route Comparison Cards (Shown after clicking "Show Route") */}
      {showRoutes && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px' }}>
          {[CLEAN_AIR_ROUTE, QUICKEST_ROUTE].map((route) => {
            const isSelected = highlightedRoute === route.id;
            return (
              <div
                key={route.id}
                onClick={() =>
                  setHighlightedRoute((prev) => (prev === route.id ? null : route.id))
                }
                style={{
                  flex: 1,
                  minWidth: '240px',
                  padding: '16px 20px',
                  borderRadius: '12px',
                  backgroundColor: '#1e293b',
                  border: isSelected
                    ? `2px solid ${route.color}`
                    : '1px solid #334155',
                  boxShadow: '0 8px 20px rgba(0, 0, 0, 0.25)',
                  cursor: 'pointer',
                  transition: 'border-color 0.2s ease, transform 0.15s ease',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '8px',
                  }}
                >
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      fontSize: '15px',
                      fontWeight: '700',
                      color: '#f8fafc',
                    }}
                  >
                    <span
                      style={{
                        width: '10px',
                        height: '10px',
                        borderRadius: '50%',
                        backgroundColor: route.color,
                      }}
                    />
                    {route.name}
                  </span>
                  <span
                    style={{
                      fontSize: '14px',
                      fontWeight: '700',
                      color: route.color,
                    }}
                  >
                    {route.duration}
                  </span>
                </div>

                <div style={{ fontSize: '13px', color: '#94a3b8', lineHeight: 1.5 }}>
                  <div>
                    Distance: <strong style={{ color: '#e2e8f0' }}>{route.distance}</strong> • Avg
                    NO₂: <strong style={{ color: '#e2e8f0' }}>{route.avgNo2}</strong>
                  </div>
                  <div style={{ color: route.color, fontWeight: '500', marginTop: '2px' }}>
                    {route.pollutionLevel}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}