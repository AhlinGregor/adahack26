import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import HomeView from './HomeView';
import RouteView from './RouteView';

function MainApp() {
  const [activeTab, setActiveTab] = useState('home'); // 'home' | 'route'

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: '#0f172a',
        color: '#f8fafc',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        boxSizing: 'border-box',
      }}
    >
      {/* Fixed Top Navigation Bar */}
      <header
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 1100, // Stays above Leaflet map controls (z-index 1000)
          backgroundColor: 'rgba(15, 23, 42, 0.9)',
          backdropFilter: 'blur(8px)',
          padding: '16px 20px',
        }}
      >
        <div
          style={{
            maxWidth: '800px',
            margin: '0 auto',
            display: 'flex',
            backgroundColor: '#1e293b',
            padding: '6px',
            borderRadius: '12px',
            border: '1px solid #334155',
            gap: '6px',
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.35)',
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
      </header>

      {/* Main Content Area (padded top so fixed navbar doesn't cover content) */}
      <main style={{ maxWidth: '800px', margin: '0 auto', padding: '96px 20px 48px' }}>
        {activeTab === 'home' ? <HomeView /> : <RouteView />}
      </main>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<MainApp />);