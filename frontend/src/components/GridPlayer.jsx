import React, { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { VideoOff, Radio } from 'lucide-react';

/**
 * GridPlayer: Production-grade HLS Stream Player for CCTV Grid
 * 
 * Features:
 * - Uses hls.js for adaptive HTTP Live Streaming.
 * - Strict resource cleanup (hls.destroy()) on unmount to prevent memory leaks across 50 feeds.
 * - Visual suppression of benign decoder warnings and non-fatal stream jitter.
 * - Native HLS fallback for WebKit / Safari browsers.
 */
export default function GridPlayer({
  streamUrl,
  cameraId = 'CAM_FEED',
  cameraName = 'Surveillance Feed',
  city = 'Gujarat',
  codec = 'H.264',
  onClick = () => {},
}) {
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [hasStreamError, setHasStreamError] = useState(false);

  useEffect(() => {
    const videoElement = videoRef.current;
    if (!videoElement || !streamUrl) return;

    setHasStreamError(false);
    setIsPlaying(false);

    // Clean up previous Hls instance if streamUrl changes
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    if (Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        backBufferLength: 0, // Minimize RAM footprint across multi-camera grid
        maxBufferLength: 4,  // Low buffer to prevent frame latency buildup
        maxMaxBufferLength: 8,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 4,
      });

      hlsRef.current = hls;

      hls.attachMedia(videoElement);

      hls.on(Hls.Events.MEDIA_ATTACHED, () => {
        hls.loadSource(streamUrl);
      });

      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        videoElement.play().catch(() => {
          // Autoplay policy: muted playback is always permitted
          videoElement.muted = true;
          videoElement.play().catch(() => {});
        });
      });

      // Error Handling & Visual Warning Suppression
      hls.on(Hls.Events.ERROR, (event, data) => {
        // Suppress non-fatal decode/RPS/POC buffer warnings silently
        if (!data.fatal) {
          return;
        }

        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            // Attempt seamless reconnect for gateway drops
            hls.startLoad();
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            // Recover from decoder macroblock glitches without UI disruption
            hls.recoverMediaError();
            break;
          default:
            // Fatal unrecoverable error
            hls.destroy();
            setHasStreamError(true);
            break;
        }
      });
    } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
      // Native HLS support (Safari / iOS)
      videoElement.src = streamUrl;
      videoElement.addEventListener('loadedmetadata', () => {
        videoElement.play().catch(() => {});
      });
    } else {
      setHasStreamError(true);
    }

    // Strict Memory Cleanup on Unmount
    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      if (videoElement) {
        videoElement.pause();
        videoElement.removeAttribute('src');
        videoElement.load();
      }
    };
  }, [streamUrl]);

  return (
    <div
      onClick={onClick}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '130px',
        backgroundColor: '#070a12',
        borderRadius: '6px',
        overflow: 'hidden',
        cursor: 'pointer',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        transition: 'border-color 0.2s',
      }}
    >
      {/* Video Element */}
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        onPlaying={() => setIsPlaying(true)}
        onError={() => {
          // Gracefully suppress raw decode crashes
          setIsPlaying(false);
        }}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          display: isPlaying && !hasStreamError ? 'block' : 'none',
        }}
      />

      {/* Simulated Video Placeholder & Loading Scanline */}
      {(!isPlaying || hasStreamError) && (
        <div
          style={{
            width: '100%',
            height: '100%',
            minHeight: '130px',
            background: 'linear-gradient(180deg, #090e17 0%, #111827 100%)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            position: 'relative',
          }}
        >
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundImage: 'radial-gradient(rgba(6, 182, 212, 0.12) 1px, transparent 1px)',
              backgroundSize: '14px 14px',
            }}
          />

          <Radio size={20} color="#06b6d4" style={{ animation: 'pulse 1.5s infinite' }} />
          <span style={{ fontSize: '11px', color: '#94a3b8', marginTop: '6px', fontWeight: 600 }}>
            {hasStreamError ? 'SIGNAL LOSS / BUFFERING' : 'CONNECTING HLS...'}
          </span>
          <span style={{ fontSize: '9px', color: '#64748b', fontFamily: 'monospace' }}>
            {cameraId}
          </span>
        </div>
      )}

      {/* CCTV Top Overlay HUD */}
      <div
        style={{
          position: 'absolute',
          top: '6px',
          left: '6px',
          right: '6px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          pointerEvents: 'none',
        }}
      >
        <div
          style={{
            background: 'rgba(0, 0, 0, 0.75)',
            padding: '2px 6px',
            borderRadius: '4px',
            fontFamily: 'monospace',
            fontSize: '10px',
            color: '#f8fafc',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          <span
            style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              backgroundColor: isPlaying ? '#10b981' : '#f59e0b',
              boxShadow: isPlaying ? '0 0 6px #10b981' : 'none',
            }}
          />
          <span>{cameraId}</span>
        </div>

        <div
          style={{
            background: 'rgba(6, 182, 212, 0.2)',
            border: '1px solid rgba(6, 182, 212, 0.4)',
            color: '#38bdf8',
            padding: '1px 5px',
            borderRadius: '4px',
            fontSize: '9px',
            fontWeight: 700,
          }}
        >
          {codec}
        </div>
      </div>

      {/* CCTV Bottom Location Tag */}
      <div
        style={{
          position: 'absolute',
          bottom: '6px',
          left: '6px',
          right: '6px',
          background: 'rgba(0, 0, 0, 0.75)',
          padding: '3px 6px',
          borderRadius: '4px',
          fontSize: '10px',
          color: '#cbd5e1',
          display: 'flex',
          justifyContent: 'space-between',
          pointerEvents: 'none',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '140px' }}>
          {city} • {cameraName}
        </span>
        <span style={{ color: '#06b6d4', fontWeight: 600 }}>HLS LIVE</span>
      </div>
    </div>
  );
}
