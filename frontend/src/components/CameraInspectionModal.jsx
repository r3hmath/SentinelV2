import React, { useState, useEffect } from 'react';
import { X, Video, Radio, Cpu, Activity, Shield, Maximize2, RefreshCw } from 'lucide-react';

export default function CameraInspectionModal({ camera, onClose }) {
  const [protocol, setProtocol] = useState('WHEP'); // 'WHEP' (WebRTC) | 'HLS' | 'RTSP'
  const [isLiveConnected, setIsLiveConnected] = useState(false);
  const [streamFps, setStreamFps] = useState(25);
  const [streamBitrate, setStreamBitrate] = useState('3.8 Mbps');
  const [latencyMs, setLatencyMs] = useState(42);

  if (!camera) return null;

  const props = camera.properties || {};
  const coords = camera.geometry?.coordinates || [72.57, 23.02];
  const camId = props.camera_id || props.id || 'CAM_UNKNOWN';
  const camName = props.name || props.camera_name || 'Gujarat Highway Surveillance Node';
  const city = props.city || 'Gujarat';
  const codec = (props.codec || (camId.toLowerCase().includes('ptz') ? 'H.265' : 'H.264')).toUpperCase();

  // Low-latency WebRTC WHEP endpoint & HLS fallback
  const whepUrl = `http://127.0.0.1:8889/live/${camId}/whep`;
  const hlsUrl = `http://127.0.0.1:8888/live/${camId}/index.m3u8`;
  const rtspUrl = `rtsp://127.0.0.1:8554/live/${camId}`;

  useEffect(() => {
    // Simulate WebRTC ICE gathering and handshake
    const timer = setTimeout(() => {
      setIsLiveConnected(true);
    }, 400);

    const interval = setInterval(() => {
      setLatencyMs(35 + Math.floor(Math.random() * 15));
      setStreamFps(24 + Math.floor(Math.random() * 3));
    }, 1500);

    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [camId, protocol]);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(5, 8, 16, 0.85)',
        backdropFilter: 'blur(12px)',
        zIndex: 2000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
    >
      <div
        className="glass-panel"
        style={{
          width: '880px',
          maxWidth: '95vw',
          borderRadius: '12px',
          border: '1px solid rgba(6, 182, 212, 0.4)',
          boxShadow: '0 0 40px rgba(6, 182, 212, 0.25)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          background: '#090e17',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'rgba(15, 23, 42, 0.6)',
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
              <div style={{ fontSize: '15px', fontWeight: 800, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
                {camName}
                <span
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: 'rgba(16, 185, 129, 0.2)',
                    color: '#10b981',
                    border: '1px solid rgba(16, 185, 129, 0.4)',
                  }}
                >
                  LIVE FEED
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: 'rgba(56, 189, 248, 0.2)',
                    color: '#38bdf8',
                  }}
                >
                  {codec}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                ID: <span style={{ fontFamily: 'monospace', color: '#06b6d4' }}>{camId}</span> • District: <b>{city}</b> • Coordinates: [{coords[1].toFixed(4)}, {coords[0].toFixed(4)}]
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {/* Protocol Switcher */}
            <div style={{ display: 'flex', gap: '4px', background: 'rgba(0,0,0,0.4)', padding: '3px', borderRadius: '6px' }}>
              <button
                onClick={() => setProtocol('WHEP')}
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  border: 'none',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  background: protocol === 'WHEP' ? '#06b6d4' : 'transparent',
                  color: protocol === 'WHEP' ? '#0a0d14' : '#94a3b8',
                }}
              >
                WebRTC (/whep)
              </button>
              <button
                onClick={() => setProtocol('HLS')}
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  border: 'none',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  background: protocol === 'HLS' ? '#06b6d4' : 'transparent',
                  color: protocol === 'HLS' ? '#0a0d14' : '#94a3b8',
                }}
              >
                HLS
              </button>
            </div>

            <button
              onClick={onClose}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '6px',
                color: '#94a3b8',
                padding: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Video Canvas Container */}
        <div
          style={{
            position: 'relative',
            width: '100%',
            height: '420px',
            background: 'linear-gradient(180deg, #050810 0%, #0d1524 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
          }}
        >
          {/* Target Reticle Grid Scanlines */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundImage: 'radial-gradient(rgba(6, 182, 212, 0.15) 1px, transparent 1px)',
              backgroundSize: '24px 24px',
            }}
          />

          {/* Video Stream Simulated Canvas */}
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              position: 'relative',
            }}
          >
            {/* Center Crosshairs */}
            <div style={{ position: 'absolute', width: '60px', height: '60px', border: '1px solid rgba(6, 182, 212, 0.4)', borderRadius: '50%', pointerEvents: 'none' }} />
            <div style={{ position: 'absolute', width: '10px', height: '10px', background: 'rgba(6, 182, 212, 0.8)', borderRadius: '50%', pointerEvents: 'none' }} />

            {/* Video Stream Feed Metadata Overlay */}
            <div
              style={{
                position: 'absolute',
                top: '16px',
                left: '16px',
                background: 'rgba(0, 0, 0, 0.7)',
                padding: '6px 12px',
                borderRadius: '6px',
                fontFamily: 'monospace',
                fontSize: '11px',
                color: '#38bdf8',
                border: '1px solid rgba(6, 182, 212, 0.3)',
              }}
            >
              <div>PROTOCOL: <b style={{ color: '#ffffff' }}>{protocol} (TCP RTSP INGEST)</b></div>
              <div>ENDPOINT: <b style={{ color: '#10b981' }}>{protocol === 'WHEP' ? whepUrl : hlsUrl}</b></div>
              <div>TRANSPORT: <b style={{ color: '#ffffff' }}>RTSP_TCP / {codec}</b></div>
            </div>

            {/* Top Right Latency Indicator */}
            <div
              style={{
                position: 'absolute',
                top: '16px',
                right: '16px',
                background: 'rgba(0, 0, 0, 0.7)',
                padding: '6px 12px',
                borderRadius: '6px',
                fontFamily: 'monospace',
                fontSize: '11px',
                color: '#10b981',
                border: '1px solid rgba(16, 185, 129, 0.3)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
              <span>GLASS-TO-GLASS: <b>{latencyMs} ms</b></span>
            </div>

            {/* Simulated Live Detection Boxes */}
            <div
              style={{
                position: 'absolute',
                top: '40%',
                left: '35%',
                width: '120px',
                height: '75px',
                border: '2px solid #06b6d4',
                background: 'rgba(6, 182, 212, 0.12)',
                boxShadow: '0 0 15px rgba(6, 182, 212, 0.5)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                padding: '4px',
              }}
            >
              <span style={{ background: '#06b6d4', color: '#000', fontSize: '9px', fontWeight: 800, padding: '1px 4px', width: 'fit-content' }}>
                TRACK #418 [CAR]
              </span>
              <span style={{ background: 'rgba(0,0,0,0.8)', color: '#fff', fontSize: '10px', fontFamily: 'monospace', padding: '1px 4px' }}>
                GJ01AB1234
              </span>
            </div>
          </div>
        </div>

        {/* Bottom Telemetry Footer */}
        <div
          style={{
            padding: '14px 20px',
            background: 'rgba(15, 23, 42, 0.8)',
            borderTop: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '12px',
          }}
        >
          <div style={{ display: 'flex', gap: '20px' }}>
            <span>Framerate: <b style={{ color: '#38bdf8' }}>{streamFps} FPS</b></span>
            <span>Bitrate: <b style={{ color: '#f59e0b' }}>{streamBitrate}</b></span>
            <span>Codec Profile: <b style={{ color: '#10b981' }}>{codec} Main@L4.1</b></span>
            <span>Ingest Transport: <b style={{ color: '#a855f7' }}>TCP / POS_MSEC</b></span>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={() => alert(`PTZ Scan Patrol Initiated on Camera ${camId}`)}
              style={{
                background: 'rgba(6, 182, 212, 0.15)',
                border: '1px solid #06b6d4',
                color: '#06b6d4',
                padding: '6px 14px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              PTZ PATROL SCAN
            </button>
            <button
              onClick={() => alert(`Target Track Locked on ${camId}`)}
              style={{
                background: '#06b6d4',
                border: 'none',
                color: '#0a0d14',
                padding: '6px 14px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 800,
                cursor: 'pointer',
              }}
            >
              LOCK TARGET
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
