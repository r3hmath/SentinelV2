import React, { useState, useEffect } from 'react';
import { Search, Play, Pause, RotateCcw, MapPin, Clock, Gauge, Shield, AlertCircle } from 'lucide-react';

export default function RoutePanel({
  routeData,
  selectedPlate,
  onSearchPlate,
  onStartPlayback,
  onStopPlayback,
  isPlaying,
  playbackIndex,
  popularPlates = [],
}) {
  const [searchInput, setSearchInput] = useState(selectedPlate || '');

  useEffect(() => {
    setSearchInput(selectedPlate);
  }, [selectedPlate]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (searchInput.trim()) {
      onSearchPlate(searchInput.trim().toUpperCase());
    }
  };

  const isThreat = routeData?.properties?.is_watchlist_match;
  const checkpoints = routeData?.features?.filter((f) => f.geometry.type === 'Point') || [];
  const totalDistance = routeData?.properties?.total_distance_km || 0;
  const durationMin = routeData?.properties?.transit_duration_minutes || 0;
  const avgSpeed = durationMin > 0 ? Math.round((totalDistance / (durationMin / 60)) * 10) / 10 : 0;

  return (
    <div
      className="glass-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        width: '380px',
        borderRight: '1px solid var(--border-color)',
        zIndex: 100,
      }}
    >
      {/* 1. Header & Search */}
      <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
          <MapPin size={18} color="#06b6d4" />
          <span style={{ fontSize: '13px', fontWeight: 800, letterSpacing: '0.08em', color: '#f8fafc' }}>
            ROUTE RECONSTRUCTION
          </span>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '8px' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
              placeholder="Enter License Plate (e.g. GJ01AB1234)"
              style={{
                width: '100%',
                background: 'rgba(15, 23, 42, 0.8)',
                border: '1px solid rgba(6, 182, 212, 0.4)',
                borderRadius: '6px',
                padding: '8px 12px',
                color: '#ffffff',
                fontFamily: 'monospace',
                fontSize: '13px',
                fontWeight: 600,
                outline: 'none',
              }}
            />
          </div>
          <button
            type="submit"
            style={{
              background: '#06b6d4',
              border: 'none',
              borderRadius: '6px',
              padding: '0 14px',
              color: '#0a0d14',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Search size={16} />
          </button>
        </form>

        {/* Quick select plate chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '10px' }}>
          {['GJ01AB1234', 'GJ05CD5678', 'GJ06EF9012'].map((plate) => (
            <button
              key={plate}
              onClick={() => {
                setSearchInput(plate);
                onSearchPlate(plate);
              }}
              style={{
                background: selectedPlate === plate ? 'rgba(6, 182, 212, 0.25)' : 'rgba(255, 255, 255, 0.05)',
                border: selectedPlate === plate ? '1px solid #06b6d4' : '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                padding: '2px 8px',
                fontSize: '11px',
                fontFamily: 'monospace',
                color: selectedPlate === plate ? '#38bdf8' : '#94a3b8',
                cursor: 'pointer',
              }}
            >
              {plate}
            </button>
          ))}
        </div>
      </div>

      {/* 2. Trajectory Metrics Card */}
      {routeData && (
        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', background: 'rgba(0,0,0,0.2)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div>
              <div style={{ fontSize: '11px', color: '#94a3b8' }}>TARGET VEHICLE</div>
              <div style={{ fontSize: '18px', fontWeight: 800, fontFamily: 'monospace', color: '#f8fafc' }}>
                {routeData.properties.license_plate}
              </div>
            </div>

            <div
              style={{
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 800,
                letterSpacing: '0.05em',
                background: isThreat ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                color: isThreat ? '#ef4444' : '#10b981',
                border: `1px solid ${isThreat ? '#ef4444' : '#10b981'}`,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              {isThreat ? <AlertCircle size={13} /> : <Shield size={13} />}
              {isThreat ? 'WATCHLIST HIT' : 'CLEAN'}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px' }}>
            <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: '10px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <MapPin size={10} /> DISTANCE
              </div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#f8fafc', marginTop: '2px' }}>
                {totalDistance} <span style={{ fontSize: '10px', color: '#94a3b8' }}>km</span>
              </div>
            </div>

            <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: '10px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Clock size={10} /> DURATION
              </div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#f8fafc', marginTop: '2px' }}>
                {durationMin} <span style={{ fontSize: '10px', color: '#94a3b8' }}>min</span>
              </div>
            </div>

            <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: '10px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Gauge size={10} /> SPEED
              </div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#f8fafc', marginTop: '2px' }}>
                {avgSpeed} <span style={{ fontSize: '10px', color: '#94a3b8' }}>km/h</span>
              </div>
            </div>
          </div>

          {/* Playback Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '12px' }}>
            <button
              onClick={isPlaying ? onStopPlayback : onStartPlayback}
              style={{
                flex: 1,
                background: isPlaying ? '#f59e0b' : '#06b6d4',
                color: '#0a0d14',
                border: 'none',
                borderRadius: '6px',
                padding: '6px 12px',
                fontWeight: 700,
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                cursor: 'pointer',
              }}
            >
              {isPlaying ? <Pause size={14} /> : <Play size={14} />}
              {isPlaying ? 'PAUSE ROUTE REPLAY' : 'PLAY TRAJECTORY REPLAY'}
            </button>
            <button
              onClick={onStopPlayback}
              style={{
                background: 'rgba(255, 255, 255, 0.08)',
                border: '1px solid rgba(255, 255, 255, 0.15)',
                color: '#cbd5e1',
                borderRadius: '6px',
                padding: '6px 10px',
                cursor: 'pointer',
              }}
            >
              <RotateCcw size={14} />
            </button>
          </div>
        </div>
      )}

      {/* 3. Checkpoint Timeline */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
        <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', letterSpacing: '0.05em', marginBottom: '12px' }}>
          CHRONOLOGICAL CHECKPOINTS ({checkpoints.length})
        </div>

        {checkpoints.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '30px 10px', color: '#64748b', fontSize: '12px' }}>
            Enter a valid vehicle plate or select a sample plate above to reconstruct route.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {checkpoints.map((pt, idx) => {
              const active = playbackIndex === idx;
              const timeStr = pt.properties.first_seen
                ? new Date(pt.properties.first_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                : 'N/A';

              return (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    gap: '12px',
                    padding: '10px',
                    borderRadius: '8px',
                    background: active ? 'rgba(6, 182, 212, 0.15)' : 'rgba(15, 23, 42, 0.5)',
                    border: active ? '1px solid #06b6d4' : '1px solid rgba(255, 255, 255, 0.05)',
                    transition: 'all 0.2s ease',
                  }}
                >
                  <div
                    style={{
                      width: '24px',
                      height: '24px',
                      borderRadius: '50%',
                      background: active ? '#06b6d4' : 'rgba(6, 182, 212, 0.2)',
                      color: active ? '#000' : '#38bdf8',
                      fontWeight: 800,
                      fontSize: '11px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    {idx + 1}
                  </div>

                  <div style={{ flex: 1, fontSize: '12px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, color: '#f8fafc' }}>{pt.properties.camera_name}</span>
                      <span style={{ color: '#06b6d4', fontFamily: 'monospace', fontSize: '11px' }}>{timeStr}</span>
                    </div>

                    <div style={{ color: '#94a3b8', fontSize: '11px', marginTop: '2px' }}>
                      City: <b>{pt.properties.city}</b> | Cam: <span style={{ fontFamily: 'monospace' }}>{pt.properties.camera_id}</span>
                    </div>

                    <div style={{ display: 'flex', gap: '10px', marginTop: '4px', fontSize: '10px', color: '#64748b' }}>
                      <span>Confidence: <b style={{ color: '#10b981' }}>{Math.round(pt.properties.best_confidence * 100)}%</b></span>
                      <span>Detections: <b>{pt.properties.detections_count}</b></span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
