import React, { useState, useEffect } from 'react';
import { Video, RefreshCw, Radio, Shield, Filter, Eye, AlertCircle } from 'lucide-react';
import GridPlayer from './GridPlayer.jsx';
import FocusPlayer from './FocusPlayer.jsx';

/**
 * CCTVGrid: Main Dashboard View for Government Sentinel Sandbox Video Ingestion
 * 
 * Directives:
 * 1. Fetches camera array from FastAPI proxy (/api/v1/cameras/ingest).
 * 2. Renders 3x3 grid (first 9 active cameras) using GridPlayer (HLS).
 * 3. On click, launches FocusPlayer modal with ultra-low latency WebRTC (WHEP).
 * 4. Zero hardcoding: dynamically constructs stream URLs using VITE_SANDBOX_HOST.
 */
export default function CCTVGrid() {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [focusedCamera, setFocusedCamera] = useState(null);
  const [selectedDistrict, setSelectedDistrict] = useState('ALL');

  // Resolve Sandbox Host from environment variable
  const sandboxHost = import.meta.env.VITE_SANDBOX_HOST || '127.0.0.1:8001';
  const cleanHost = sandboxHost.replace(/^https?:\/\//, '').replace(/\/+$/, '');

  // 1. Fetch camera topology dynamically from FastAPI proxy
  const fetchCameras = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/v1/cameras/ingest');
      if (!response.ok) {
        throw new Error(`Proxy returned HTTP ${response.status}`);
      }
      const data = await response.json();
      const cameraList = data.cameras || [];
      setCameras(cameraList);
    } catch (err) {
      console.error('[CCTVGrid] Failed to fetch cameras from proxy:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCameras();
  }, []);

  // Filter cameras by district if selected
  const filteredCameras = selectedDistrict === 'ALL'
    ? cameras
    : cameras.filter((c) => c.location?.city === selectedDistrict || c.city === selectedDistrict);

  // Directive: Display the first 9 active cameras in the primary HLS grid
  const activeCameras = filteredCameras.slice(0, 9);

  // Extract unique districts for filtering
  const districtList = ['ALL', ...new Set(cameras.map((c) => c.location?.city || c.city || 'Gujarat').filter(Boolean))];

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        width: '100%',
        backgroundColor: '#060911',
        overflow: 'hidden',
        color: '#f8fafc',
      }}
    >
      {/* Top Controls Header */}
      <div
        className="glass-panel"
        style={{
          padding: '12px 24px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '6px',
              background: 'rgba(6, 182, 212, 0.15)',
              border: '1px solid #06b6d4',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Video size={18} color="#06b6d4" />
          </div>

          <div>
            <h2 style={{ fontSize: '15px', fontWeight: 800, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              STATEWIDE 9-FEED HLS SURVEILLANCE MATRIX
              <span
                style={{
                  fontSize: '10px',
                  background: 'rgba(16, 185, 129, 0.2)',
                  color: '#10b981',
                  border: '1px solid rgba(16, 185, 129, 0.4)',
                  padding: '1px 6px',
                  borderRadius: '4px',
                }}
              >
                HLS ACTIVE
              </span>
            </h2>
            <p style={{ fontSize: '11px', color: '#94a3b8', margin: '2px 0 0 0' }}>
              Sentinel Sandbox Dynamic Ingest • Host: <span style={{ fontFamily: 'monospace', color: '#38bdf8' }}>{cleanHost}</span>
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* District Filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Filter size={14} color="#94a3b8" />
            <select
              value={selectedDistrict}
              onChange={(e) => setSelectedDistrict(e.target.value)}
              style={{
                background: 'rgba(15, 23, 42, 0.8)',
                border: '1px solid rgba(6, 182, 212, 0.3)',
                color: '#f8fafc',
                padding: '6px 12px',
                borderRadius: '6px',
                fontSize: '12px',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              {districtList.map((d) => (
                <option key={d} value={d}>
                  {d === 'ALL' ? 'All Gujarat Districts' : `${d} District`}
                </option>
              ))}
            </select>
          </div>

          {/* Stream Telemetry Counter */}
          <div
            className="glass-panel"
            style={{
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '11px',
              display: 'flex',
              gap: '12px',
            }}
          >
            <span>Feeds Ingested: <b style={{ color: '#10b981' }}>{activeCameras.length} / {cameras.length}</b></span>
            <span>WAN Bandwidth: <b style={{ color: '#f59e0b' }}>{(activeCameras.length * 2.8).toFixed(1)} Mbps</b></span>
          </div>

          {/* Refresh Button */}
          <button
            onClick={fetchCameras}
            disabled={loading}
            style={{
              background: 'rgba(6, 182, 212, 0.15)',
              border: '1px solid #06b6d4',
              color: '#06b6d4',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '11px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            SYNC TOPOLOGY
          </button>
        </div>
      </div>

      {/* Main 3x3 Video Grid */}
      <div
        style={{
          flex: 1,
          padding: '16px',
          overflowY: 'auto',
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gridTemplateRows: 'repeat(3, 1fr)',
          gap: '12px',
          minHeight: 0,
        }}
      >
        {activeCameras.map((cam) => {
          const camId = cam.id || cam.camera_id;
          const camName = cam.name || `Camera ${camId}`;
          const city = cam.location?.city || cam.city || 'Gujarat';
          const codec = (cam.codec || 'H.264').toUpperCase();

          // Construct Dynamic HLS Endpoint as specified in Context Directive 2:
          // http://<SANDBOX_HOST>/live/stream/<id>/index.m3u8
          const hlsUrl = cam.endpoints?.hls || `http://${cleanHost}/live/stream/${camId}/index.m3u8`;

          return (
            <div
              key={camId}
              style={{
                position: 'relative',
                borderRadius: '8px',
                overflow: 'hidden',
                boxShadow: '0 4px 16px rgba(0, 0, 0, 0.5)',
                transition: 'transform 0.15s, box-shadow 0.15s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = '0 0 20px rgba(6, 182, 212, 0.4)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = '0 4px 16px rgba(0, 0, 0, 0.5)';
              }}
            >
              <GridPlayer
                streamUrl={hlsUrl}
                cameraId={camId}
                cameraName={camName}
                city={city}
                codec={codec}
                onClick={() => setFocusedCamera(cam)}
              />

              {/* Click-to-Inspect Hint Badge */}
              <div
                onClick={() => setFocusedCamera(cam)}
                style={{
                  position: 'absolute',
                  top: '8px',
                  right: '8px',
                  background: 'rgba(0, 0, 0, 0.6)',
                  borderRadius: '4px',
                  padding: '3px 6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontSize: '9px',
                  fontWeight: 700,
                  color: '#38bdf8',
                  cursor: 'pointer',
                  border: '1px solid rgba(6, 182, 212, 0.3)',
                  zIndex: 2,
                }}
              >
                <Eye size={10} />
                INSPECT (WHEP)
              </div>
            </div>
          );
        })}

        {/* Empty State / Loading State */}
        {activeCameras.length === 0 && !loading && (
          <div
            style={{
              gridColumn: '1 / -1',
              gridRow: '1 / -1',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'rgba(15, 23, 42, 0.4)',
              borderRadius: '8px',
              border: '1px dashed rgba(255, 255, 255, 0.15)',
              padding: '32px',
            }}
          >
            <AlertCircle size={32} color="#f59e0b" />
            <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '12px' }}>
              No Active Camera Feeds Discovered
            </div>
            <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
              Verify connectivity to Sentinel Sandbox at {sandboxHost}
            </div>
            <button
              onClick={fetchCameras}
              style={{
                marginTop: '16px',
                background: '#06b6d4',
                border: 'none',
                color: '#090d16',
                padding: '8px 16px',
                borderRadius: '6px',
                fontWeight: 700,
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              Retry Discovery
            </button>
          </div>
        )}
      </div>

      {/* Focus Inspection Modal: Low-Latency WebRTC (WHEP) Feed */}
      {focusedCamera && (
        <FocusPlayer
          camera={focusedCamera}
          onClose={() => setFocusedCamera(null)}
        />
      )}
    </div>
  );
}
