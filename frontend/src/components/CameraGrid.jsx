import React, { useState, useEffect } from 'react';
import { Video, Cpu, Activity, Shield, Filter, Radio } from 'lucide-react';

export default function CameraGrid({ cameras = [], onSelectCamera = () => {} }) {
  const [filterCity, setFilterCity] = useState('ALL');
  const [feedCount, setFeedCount] = useState(50);
  const [ticker, setTicker] = useState(0);

  // Live frame ticker simulation
  useEffect(() => {
    const timer = setInterval(() => setTicker((t) => (t + 1) % 10000), 200);
    return () => clearInterval(timer);
  }, []);

  // Generate 50 heterogeneous camera feeds based on Gujarat network
  const generatedFeeds = Array.from({ length: feedCount }, (_, i) => {
    const baseCam = cameras[i % Math.max(1, cameras.length)] || { properties: { city: 'Ahmedabad', camera_id: `CAM_${i + 1}` } };
    const cities = ['Ahmedabad', 'Surat', 'Vadodara', 'Rajkot', 'Gandhinagar', 'Jamnagar', 'Bhavnagar', 'Mehsana', 'Palanpur', 'Bhuj'];
    const city = baseCam.properties?.city || cities[i % cities.length];
    const offloadTargets = ['EDGE', 'LOCAL', 'CLOUD'];
    const offload = offloadTargets[i % 3];

    return {
      id: `FEED_${String(i + 1).padStart(3, '0')}`,
      cam_id: `CAM_${city.substring(0, 3).toUpperCase()}_${String((i % 5) + 1).padStart(2, '0')}`,
      city: city,
      location: `${city} Sector ${(i % 12) + 1} Highway Junction`,
      fps: 25 + (i % 6),
      resolution: i % 2 === 0 ? '1080p' : '720p',
      offload: offload,
      latency: 35 + (i % 25),
      activeObjects: (i % 7) + 2,
    };
  });

  const filtered = filterCity === 'ALL' ? generatedFeeds : generatedFeeds.filter((f) => f.city === filterCity);

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%' }}>
      {/* Top Banner & Stats */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Video color="#06b6d4" size={22} />
            50-Camera Ingestion Matrix — Live Heterogeneous Streams
          </h2>
          <p style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Concurrent High-Throughput RTSP Ingestion Pipeline with Dynamic Edge/Local/Cloud Offloading (Click to Inspect)
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div className="glass-panel" style={{ padding: '6px 14px', borderRadius: '6px', fontSize: '12px', display: 'flex', gap: '12px' }}>
            <span>Active Streams: <b style={{ color: '#10b981' }}>{feedCount}</b></span>
            <span>Avg FPS: <b style={{ color: '#38bdf8' }}>28.4</b></span>
            <span>Total Bandwidth: <b style={{ color: '#f59e0b' }}>84.2 Mbps</b></span>
          </div>

          <select
            value={filterCity}
            onChange={(e) => setFilterCity(e.target.value)}
            style={{
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid rgba(6, 182, 212, 0.4)',
              color: '#ffffff',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '12px',
            }}
          >
            <option value="ALL">All Gujarat Districts</option>
            <option value="Ahmedabad">Ahmedabad</option>
            <option value="Surat">Surat</option>
            <option value="Vadodara">Vadodara</option>
            <option value="Rajkot">Rajkot</option>
            <option value="Gandhinagar">Gandhinagar</option>
          </select>
        </div>
      </div>

      {/* Grid of 50 Streams */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: '14px',
        }}
      >
        {filtered.map((feed, idx) => {
          const offloadColor = feed.offload === 'EDGE' ? '#10b981' : feed.offload === 'LOCAL' ? '#06b6d4' : '#818cf8';

          return (
            <div
              key={feed.id}
              className="glass-panel"
              onClick={() =>
                onSelectCamera({
                  properties: {
                    camera_id: feed.cam_id,
                    name: feed.location,
                    city: feed.city,
                    status: 'online',
                  },
                })
              }
              style={{
                borderRadius: '8px',
                overflow: 'hidden',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                transition: 'all 0.2s',
                cursor: 'pointer',
              }}
            >

              {/* Simulated Camera Video Box */}
              <div
                style={{
                  height: '130px',
                  background: 'linear-gradient(180deg, #090e17 0%, #151d2c 100%)',
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  overflow: 'hidden',
                }}
              >
                {/* Simulated Grid Scanlines */}
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundImage: 'radial-gradient(rgba(6, 182, 212, 0.1) 1px, transparent 1px)',
                    backgroundSize: '16px 16px',
                    opacity: 0.6,
                  }}
                />

                {/* Simulated Object Bounding Box */}
                <div
                  style={{
                    position: 'absolute',
                    top: `${30 + ((idx * 7 + ticker) % 35)}%`,
                    left: `${20 + ((idx * 11 + ticker * 2) % 45)}%`,
                    width: '55px',
                    height: '38px',
                    border: '1.5px solid #06b6d4',
                    background: 'rgba(6, 182, 212, 0.1)',
                    borderRadius: '2px',
                    boxShadow: '0 0 8px rgba(6, 182, 212, 0.4)',
                  }}
                >
                  <div
                    style={{
                      position: 'absolute',
                      top: '-12px',
                      left: 0,
                      background: '#06b6d4',
                      color: '#000',
                      fontSize: '8px',
                      fontWeight: 800,
                      padding: '1px 3px',
                      borderRadius: '1px',
                    }}
                  >
                    VEHICLE 96%
                  </div>
                </div>

                {/* Overlay Header on Video */}
                <div
                  style={{
                    position: 'absolute',
                    top: '6px',
                    left: '8px',
                    right: '8px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontSize: '10px',
                    fontFamily: 'monospace',
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#ef4444' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#ef4444', animation: 'pulse-ring 1.5s infinite' }}></span>
                    REC
                  </span>
                  <span style={{ color: '#94a3b8' }}>{feed.resolution} @ {feed.fps}fps</span>
                </div>

                {/* Cam ID overlay */}
                <div
                  style={{
                    position: 'absolute',
                    bottom: '6px',
                    left: '8px',
                    fontSize: '11px',
                    fontWeight: 700,
                    fontFamily: 'monospace',
                    color: '#f8fafc',
                  }}
                >
                  {feed.cam_id}
                </div>

                {/* Offload badge */}
                <div
                  style={{
                    position: 'absolute',
                    bottom: '6px',
                    right: '8px',
                    fontSize: '9px',
                    fontWeight: 800,
                    padding: '2px 5px',
                    borderRadius: '3px',
                    background: 'rgba(0,0,0,0.7)',
                    border: `1px solid ${offloadColor}`,
                    color: offloadColor,
                  }}
                >
                  ⚡ {feed.offload}
                </div>
              </div>

              {/* Feed Card Footer */}
              <div style={{ padding: '8px 12px', background: 'rgba(15, 23, 42, 0.6)', fontSize: '11px' }}>
                <div style={{ fontWeight: 600, color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {feed.location}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', fontSize: '10px', marginTop: '3px' }}>
                  <span>Latency: <b style={{ color: '#cbd5e1' }}>{feed.latency}ms</b></span>
                  <span>Active Tracks: <b style={{ color: '#38bdf8' }}>{feed.activeObjects}</b></span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
