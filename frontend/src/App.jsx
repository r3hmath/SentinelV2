import React, { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Activity,
  MapPin,
  Video,
  AlertTriangle,
  Radio,
  Sliders,
  Bell,
  Cpu,
} from 'lucide-react';
import GisMap from './components/GisMap.jsx';
import RoutePanel from './components/RoutePanel.jsx';
import ThreatAlertModal from './components/ThreatAlertModal.jsx';
import WatchlistManager from './components/WatchlistManager.jsx';
import CameraGrid from './components/CameraGrid.jsx';
import CCTVGrid from './components/CCTVGrid.jsx';
import CameraInspectionModal from './components/CameraInspectionModal.jsx';


export default function App() {
  const [activeTab, setActiveTab] = useState('gis'); // 'gis' | 'grid' | 'watchlist'
  const [cameras, setCameras] = useState([]);
  const [selectedPlate, setSelectedPlate] = useState('GJ01AB1234');
  const [routeData, setRouteData] = useState(null);
  const [loadingRoute, setLoadingRoute] = useState(false);
  const [inspectedCamera, setInspectedCamera] = useState(null);

  // Playback state
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackIndex, setPlaybackIndex] = useState(-1);
  const playbackTimerRef = useRef(null);

  // WebSocket & Alerts state
  const [wsConnected, setWsConnected] = useState(false);
  const [activeThreat, setActiveThreat] = useState(null);
  const wsRef = useRef(null);

  // 1. Fetch Cameras
  useEffect(() => {
    fetch('/api/v1/tracking/cameras')
      .then((res) => res.json())
      .then((data) => setCameras(data.features || []))
      .catch((e) => console.error('Failed to load cameras', e));
  }, []);

  // 2. Fetch Initial Route for GJ01AB1234
  const fetchRoute = async (plate) => {
    setLoadingRoute(true);
    try {
      const res = await fetch(`/api/v1/tracking/route/${plate}`);
      const data = await res.json();
      setRouteData(data);
      setSelectedPlate(plate);
      setIsPlaying(false);
      setPlaybackIndex(-1);

      // If plate is threat, set active threat state
      if (data.properties.is_watchlist_match && data.properties.watchlist_details) {
        const firstPoint = data.features.find((f) => f.geometry.type === 'Point');
        setActiveThreat({
          license_plate: plate,
          category: data.properties.watchlist_details.category,
          severity: data.properties.watchlist_details.severity,
          owner_name: data.properties.watchlist_details.owner_name,
          vehicle_info: `${data.properties.watchlist_details.vehicle_make} ${data.properties.watchlist_details.vehicle_model}`,
          notes: data.properties.watchlist_details.notes,
          camera_id: firstPoint?.properties?.camera_id || 'CAM_AHM_01',
          camera_name: firstPoint?.properties?.camera_name || 'Ahmedabad Ring Road',
          city: firstPoint?.properties?.city || 'Ahmedabad',
        });
      }
    } catch (e) {
      console.error('Failed to load route', e);
    } finally {
      setLoadingRoute(false);
    }
  };

  useEffect(() => {
    fetchRoute('GJ01AB1234');
  }, []);

  // 3. Connect to WebSocket Live Threat Feed
  useEffect(() => {
    let ws;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.port === '5173' ? '127.0.0.1:8001' : window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws/alerts`;

    const connectWs = () => {
      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log('[Sentinel WS] Connected to live threat stream');
          setWsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            console.log('[Sentinel WS] Received alert:', payload);

            if (payload.event_type === 'THREAT_DETECTED') {
              setActiveThreat(payload);
              // Auto-switch to GIS view and select plate if desired
              if (payload.license_plate) {
                fetchRoute(payload.license_plate);
              }
            }
          } catch (err) {
            console.error('[Sentinel WS] Message error:', err);
          }
        };

        ws.onclose = () => {
          console.warn('[Sentinel WS] Connection closed. Reconnecting in 3s...');
          setWsConnected(false);
          setTimeout(connectWs, 3000);
        };

        ws.onerror = (e) => {
          console.error('[Sentinel WS] Error:', e);
          ws.close();
        };

        wsRef.current = ws;
      } catch (e) {
        console.error('[Sentinel WS] Setup error:', e);
      }
    };

    connectWs();

    return () => {
      if (ws) ws.close();
    };
  }, []);

  // 4. Playback Logic
  const pointFeatures = routeData?.features?.filter((f) => f.geometry.type === 'Point') || [];

  const handleStartPlayback = () => {
    if (pointFeatures.length === 0) return;
    setIsPlaying(true);
    setPlaybackIndex(0);
  };

  const handleStopPlayback = () => {
    setIsPlaying(false);
    setPlaybackIndex(-1);
    if (playbackTimerRef.current) clearInterval(playbackTimerRef.current);
  };

  useEffect(() => {
    if (!isPlaying) return;

    playbackTimerRef.current = setInterval(() => {
      setPlaybackIndex((prev) => {
        if (prev + 1 >= pointFeatures.length) {
          setIsPlaying(false);
          return 0;
        }
        return prev + 1;
      });
    }, 1800);

    return () => {
      if (playbackTimerRef.current) clearInterval(playbackTimerRef.current);
    };
  }, [isPlaying, pointFeatures.length]);

  const activePlaybackStep =
    playbackIndex >= 0 && pointFeatures[playbackIndex]
      ? {
          lat: pointFeatures[playbackIndex].geometry.coordinates[1],
          lon: pointFeatures[playbackIndex].geometry.coordinates[0],
          city: pointFeatures[playbackIndex].properties.city,
          camera: pointFeatures[playbackIndex].properties.camera_name,
        }
      : null;

  // 5. Trigger Simulated Detection from Watchlist
  const handleTriggerSimulate = async (plate) => {
    try {
      const res = await fetch('/api/v1/watchlist/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          license_plate: plate,
          camera_id: 'CAM_AHM_01',
          city: 'Ahmedabad',
          confidence: 0.99,
        }),
      });
      const data = await res.json();
      if (data.threat_alert) {
        setActiveThreat(data.threat_alert);
        setActiveTab('gis');
        fetchRoute(plate);
      }
    } catch (e) {
      console.error('Simulate error', e);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* High Visibility Threat Alert Strobe & Modal */}
      <ThreatAlertModal
        alert={activeThreat}
        onDismiss={() => setActiveThreat(null)}
        onDispatch={(threat) => {
          alert(`🚨 112 Interceptor Unit Dispatched to ${threat.camera_name || threat.camera_id} (${threat.city})! Intercepting target vehicle ${threat.license_plate}.`);
          setActiveThreat(null);
        }}
      />

      {/* Navigation Header */}
      <header
        className="glass-panel"
        style={{
          height: '60px',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border-color)',
          zIndex: 1000,
          flexShrink: 0,
        }}
      >
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 15px rgba(6, 182, 212, 0.4)',
            }}
          >
            <Shield size={22} color="#ffffff" />
          </div>

          <div>
            <div style={{ fontSize: '15px', fontWeight: 800, letterSpacing: '0.08em', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
              SENTINEL
              <span style={{ fontSize: '10px', background: 'rgba(6, 182, 212, 0.2)', color: '#06b6d4', padding: '1px 6px', borderRadius: '4px', border: '1px solid rgba(6, 182, 212, 0.3)' }}>
                GUJARAT POLICE VIDEO INTELLIGENCE
              </span>
            </div>
            <div style={{ fontSize: '10px', color: '#94a3b8' }}>
              Hybrid Edge-Cloud Video Intelligence Platform • 1,000 km Geographical Grid
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div style={{ display: 'flex', gap: '6px', background: 'rgba(15, 23, 42, 0.7)', padding: '4px', borderRadius: '8px', border: '1px solid rgba(255, 255, 255, 0.08)' }}>
          <button
            onClick={() => setActiveTab('gis')}
            style={{
              background: activeTab === 'gis' ? '#06b6d4' : 'transparent',
              color: activeTab === 'gis' ? '#0a0d14' : '#cbd5e1',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <MapPin size={14} /> GIS ROUTE RECONSTRUCTION
          </button>

          <button
            onClick={() => setActiveTab('grid')}
            style={{
              background: activeTab === 'grid' ? '#06b6d4' : 'transparent',
              color: activeTab === 'grid' ? '#0a0d14' : '#cbd5e1',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <Video size={14} /> 50-CAMERA MATRIX
          </button>

          <button
            onClick={() => setActiveTab('watchlist')}
            style={{
              background: activeTab === 'watchlist' ? '#ef4444' : 'transparent',
              color: activeTab === 'watchlist' ? '#ffffff' : '#cbd5e1',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <AlertTriangle size={14} /> eGujCop WATCHLIST
          </button>
        </div>

        {/* Live System Telemetry Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#94a3b8' }}>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: wsConnected ? '#10b981' : '#ef4444',
                boxShadow: `0 0 8px ${wsConnected ? '#10b981' : '#ef4444'}`,
              }}
            />
            <span>LIVE RADAR WS: <b style={{ color: wsConnected ? '#10b981' : '#ef4444' }}>{wsConnected ? 'CONNECTED' : 'CONNECTING'}</b></span>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '11px',
              background: 'rgba(6, 182, 212, 0.1)',
              border: '1px solid rgba(6, 182, 212, 0.2)',
              padding: '4px 8px',
              borderRadius: '6px',
              color: '#38bdf8',
            }}
          >
            <Cpu size={12} />
            <span>SCHEDULER: <b>ADAPTIVE</b></span>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {activeTab === 'gis' && (
          <div style={{ display: 'flex', width: '100%', height: '100%' }}>
            <RoutePanel
              routeData={routeData}
              selectedPlate={selectedPlate}
              onSearchPlate={(plate) => fetchRoute(plate)}
              onStartPlayback={handleStartPlayback}
              onStopPlayback={handleStopPlayback}
              isPlaying={isPlaying}
              playbackIndex={playbackIndex}
            />

            <div style={{ flex: 1, position: 'relative', height: '100%' }}>
              <GisMap
                cameras={cameras}
                routeData={routeData}
                activePlaybackStep={activePlaybackStep}
                activeThreat={activeThreat}
                onSelectCamera={(cam) => setInspectedCamera(cam)}
              />
            </div>
          </div>
        )}

        {activeTab === 'grid' && <CCTVGrid />}


        {activeTab === 'watchlist' && (
          <WatchlistManager onTriggerSimulate={handleTriggerSimulate} />
        )}

        {/* WebRTC / WHEP Live Camera Inspection Modal */}
        {inspectedCamera && (
          <CameraInspectionModal
            camera={inspectedCamera}
            onClose={() => setInspectedCamera(null)}
          />
        )}
      </main>
    </div>
  );
}

