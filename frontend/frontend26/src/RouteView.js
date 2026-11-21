export default function RouteView() {
  return (
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
  );
}