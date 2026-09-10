import React, { useEffect, useRef } from 'react';
import L from 'leaflet';

// Gujarat geographical center
const GUJARAT_CENTER = [22.8, 71.8];
const DEFAULT_ZOOM = 7.5;

export default function GisMap({
  cameras = [],
  routeData = null,
  activePlaybackStep = null,
  activeThreat = null,
  onSelectCamera = () => {},
}) {
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersLayerRef = useRef(null);
  const routeLayerRef = useRef(null);
  const playbackMarkerRef = useRef(null);

  // 1. Initialize Map
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: GUJARAT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: false,
      attributionControl: false,
    });

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Dark high-tech basemap
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png', {
      maxZoom: 19,
      subdomains: 'abcd',
    }).addTo(map);

    // Marker & Route layers
    markersLayerRef.current = L.layerGroup().addTo(map);
    routeLayerRef.current = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // 2. Render Surveillance Cameras
  useEffect(() => {
    const map = mapInstanceRef.current;
    const markersLayer = markersLayerRef.current;
    if (!map || !markersLayer) return;

    markersLayer.clearLayers();

    cameras.forEach((cam) => {
      const isThreatCam = activeThreat && activeThreat.camera_id === cam.properties.camera_id;
      const isOnline = cam.properties.status === 'online';

      const customIcon = L.divIcon({
        className: 'custom-camera-icon',
        html: `
          <div class="camera-pulse-marker">
            <div class="camera-pulse-ring ${isThreatCam ? 'threat' : ''}"></div>
            <div class="camera-dot ${isThreatCam ? 'threat' : ''}"></div>
          </div>
        `,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });

      const marker = L.marker([cam.geometry.coordinates[1], cam.geometry.coordinates[0]], {
        icon: customIcon,
      });

      marker.bindPopup(`
        <div style="font-size: 13px; line-height: 1.5;">
          <div style="font-weight: 700; color: ${isThreatCam ? '#ef4444' : '#06b6d4'}; font-size: 14px; margin-bottom: 4px;">
            ${isThreatCam ? '🚨 THREAT SIGHTING CAMERA' : 'SURVEILLANCE CAMERA'}
          </div>
          <div style="font-weight: 600; color: #f8fafc;">${cam.properties.name}</div>
          <div style="color: #94a3b8; font-size: 11px; margin-top: 2px;">
            ID: <span style="font-family: monospace; color: #38bdf8;">${cam.properties.camera_id}</span> | City: <b>${cam.properties.city}</b>
          </div>
          <div style="margin-top: 6px; padding: 4px 8px; background: rgba(0,0,0,0.4); border-radius: 4px; font-size: 11px; display: flex; justify-content: space-between;">
            <span>Status: <b style="color: ${isOnline ? '#10b981' : '#ef4444'}">${cam.properties.status.toUpperCase()}</b></span>
            <span>Total Events: <b>${cam.properties.events_count}</b></span>
          </div>
        </div>
      `);

      marker.on('click', () => onSelectCamera(cam));
      markersLayer.addLayer(marker);
    });
  }, [cameras, activeThreat, onSelectCamera]);

  // 3. Render Route Trajectory (Polyline & Checkpoint Markers)
  useEffect(() => {
    const map = mapInstanceRef.current;
    const routeLayer = routeLayerRef.current;
    if (!map || !routeLayer) return;

    routeLayer.clearLayers();

    if (!routeData || !routeData.features || routeData.features.length === 0) return;

    const lineFeature = routeData.features.find((f) => f.geometry.type === 'LineString');
    const pointFeatures = routeData.features.filter((f) => f.geometry.type === 'Point');

    const isThreatVehicle = routeData.properties.is_watchlist_match;
    const routeColor = isThreatVehicle ? '#ef4444' : '#06b6d4';

    // A. Draw Traversed Route Polyline
    if (lineFeature && lineFeature.geometry.coordinates.length > 1) {
      const latLngs = lineFeature.geometry.coordinates.map(([lon, lat]) => [lat, lon]);

      // Glow backdrop polyline
      L.polyline(latLngs, {
        color: routeColor,
        weight: 8,
        opacity: 0.35,
        lineCap: 'round',
        lineJoin: 'round',
      }).addTo(routeLayer);

      // Core neon polyline
      const mainLine = L.polyline(latLngs, {
        color: isThreatVehicle ? '#f87171' : '#38bdf8',
        weight: 3.5,
        opacity: 0.95,
        dashArray: '8, 6',
      }).addTo(routeLayer);

      // Fit map bounds to show complete trajectory across Gujarat
      map.fitBounds(mainLine.getBounds(), { padding: [60, 60] });
    }

    // B. Draw Sequenced Checkpoint Markers
    pointFeatures.forEach((pt, index) => {
      const [lon, lat] = pt.geometry.coordinates;
      const order = pt.properties.checkpoint_order || index + 1;
      const isLatest = order === pointFeatures.length;

      const checkpointIcon = L.divIcon({
        className: 'checkpoint-icon',
        html: `
          <div style="
            position: relative;
            width: 28px;
            height: 28px;
            background: ${isLatest ? '#ef4444' : '#1e293b'};
            border: 2px solid ${isLatest ? '#ffffff' : routeColor};
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 800;
            color: #ffffff;
            box-shadow: 0 0 12px ${isLatest ? 'rgba(239, 68, 68, 0.8)' : 'rgba(6, 182, 212, 0.6)'};
          ">
            #${order}
          </div>
        `,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      });

      const marker = L.marker([lat, lon], { icon: checkpointIcon });

      const dateStr = pt.properties.first_seen
        ? new Date(pt.properties.first_seen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        : 'N/A';

      marker.bindPopup(`
        <div style="font-size: 13px; line-height: 1.5; min-width: 200px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <span style="font-weight: 800; color: ${routeColor}; font-size: 13px;">CHECKPOINT #${order}</span>
            <span style="background: rgba(6, 182, 212, 0.15); color: #38bdf8; font-size: 11px; padding: 2px 6px; border-radius: 4px; font-family: monospace;">
              ${dateStr}
            </span>
          </div>
          <div style="font-weight: 700; color: #f8fafc;">${pt.properties.camera_name}</div>
          <div style="color: #94a3b8; font-size: 11px; margin-top: 2px;">
            City: <b>${pt.properties.city}</b> | Camera: <span style="font-family: monospace;">${pt.properties.camera_id}</span>
          </div>
          <div style="margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 6px; display: flex; justify-content: space-between; font-size: 11px;">
            <span>Confidence: <b style="color: #10b981">${Math.round(pt.properties.best_confidence * 100)}%</b></span>
            <span>Sightings: <b>${pt.properties.detections_count}</b></span>
          </div>
        </div>
      `);

      routeLayer.addLayer(marker);
    });
  }, [routeData]);

  // 4. Vehicle Playback Marker
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (playbackMarkerRef.current) {
      playbackMarkerRef.current.remove();
      playbackMarkerRef.current = null;
    }

    if (activePlaybackStep && activePlaybackStep.lat && activePlaybackStep.lon) {
      const carIcon = L.divIcon({
        className: 'vehicle-playback-icon',
        html: `
          <div style="
            width: 38px;
            height: 38px;
            background: #ef4444;
            border: 3px solid #ffffff;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 25px #ef4444;
            animation: pulse-ring 1s infinite;
          ">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
              <rect x="2" y="5" width="20" height="14" rx="2"></rect>
              <circle cx="7" cy="15" r="2"></circle>
              <circle cx="17" cy="15" r="2"></circle>
            </svg>
          </div>
        `,
        iconSize: [38, 38],
        iconAnchor: [19, 19],
      });

      const marker = L.marker([activePlaybackStep.lat, activePlaybackStep.lon], { icon: carIcon }).addTo(map);
      marker.bindTooltip(`📍 Traversing: ${activePlaybackStep.city || 'Checkpoint'}`, {
        permanent: true,
        direction: 'top',
        className: 'playback-tooltip',
      });
      playbackMarkerRef.current = marker;
      map.panTo([activePlaybackStep.lat, activePlaybackStep.lon], { animate: true, duration: 0.5 });
    }
  }, [activePlaybackStep]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />

      {/* Map Overlay Badge */}
      <div
        className="glass-panel"
        style={{
          position: 'absolute',
          top: '16px',
          left: '16px',
          zIndex: 999,
          padding: '8px 14px',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}
      >
        <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#10b981', display: 'inline-block', boxShadow: '0 0 8px #10b981' }}></span>
        <span style={{ fontSize: '12px', fontWeight: 600, letterSpacing: '0.05em', color: '#e2e8f0' }}>
          GUJARAT STATEWIDE GIS GRID (1,000 KM)
        </span>
        <span style={{ fontSize: '11px', color: '#06b6d4', background: 'rgba(6, 182, 212, 0.1)', padding: '2px 6px', borderRadius: '4px' }}>
          {cameras.length} NODES ONLINE
        </span>
      </div>
    </div>
  );
}
