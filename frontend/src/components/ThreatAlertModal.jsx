import React, { useEffect } from 'react';
import { AlertTriangle, ShieldAlert, Radio, XCircle, Send } from 'lucide-react';

export default function ThreatAlertModal({ alert, onDismiss, onDispatch }) {
  if (!alert) return null;

  // Synthesize police alarm sound using Web Audio API (zero external asset dependency)
  useEffect(() => {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(880, ctx.currentTime); // A5
        osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.3); // A4
        osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.6);

        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.8);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start();
        osc.stop(ctx.currentTime + 0.8);
      }
    } catch (e) {
      // Audio autoplay may require user interaction
    }
  }, [alert]);

  return (
    <>
      {/* 1. Top Flashing Alert Strobe */}
      <div
        className="animate-threat-strobe"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 9999,
          padding: '12px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '2px solid #ef4444',
          color: '#ffffff',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <ShieldAlert size={26} color="#ef4444" className="animate-badge-pulse" />
          <div>
            <div style={{ fontSize: '15px', fontWeight: 800, letterSpacing: '0.08em', color: '#fca5a5' }}>
              🚨 CRITICAL THREAT DETECTED — eGujCop WATCHLIST HIT
            </div>
            <div style={{ fontSize: '12px', color: '#e2e8f0' }}>
              Target Vehicle: <b style={{ fontFamily: 'monospace', color: '#ffffff', fontSize: '13px' }}>{alert.license_plate}</b> sighted at <b>{alert.camera_name || alert.camera_id}</b> ({alert.city})
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={() => onDispatch(alert)}
            style={{
              background: '#ef4444',
              color: '#ffffff',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontWeight: 700,
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              boxShadow: '0 0 15px rgba(239, 68, 68, 0.7)',
            }}
          >
            <Send size={14} /> DISPATCH 112 INTERCEPTOR
          </button>
          <button
            onClick={onDismiss}
            style={{
              background: 'rgba(255, 255, 255, 0.1)',
              color: '#ffffff',
              border: '1px solid rgba(255, 255, 255, 0.2)',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            ACKNOWLEDGE
          </button>
        </div>
      </div>

      {/* 2. Floating Dossier Card on Bottom-Right */}
      <div
        className="glass-panel"
        style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          zIndex: 9999,
          width: '380px',
          borderRadius: '12px',
          border: '2px solid #ef4444',
          boxShadow: '0 10px 40px rgba(239, 68, 68, 0.3)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            background: 'linear-gradient(90deg, #991b1b 0%, #dc2626 100%)',
            padding: '12px 16px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={18} color="#ffffff" />
            <span style={{ fontWeight: 800, fontSize: '13px', letterSpacing: '0.05em' }}>
              WANTED SUSPECT PROFILE
            </span>
          </div>
          <button
            onClick={onDismiss}
            style={{ background: 'transparent', border: 'none', color: '#ffffff', cursor: 'pointer' }}
          >
            <XCircle size={18} />
          </button>
        </div>

        <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: '#94a3b8' }}>Registration Number</span>
            <span
              style={{
                fontFamily: 'monospace',
                fontSize: '16px',
                fontWeight: 800,
                color: '#ef4444',
                background: 'rgba(239, 68, 68, 0.1)',
                padding: '2px 8px',
                borderRadius: '4px',
                border: '1px solid rgba(239, 68, 68, 0.4)',
              }}
            >
              {alert.license_plate}
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>Offense / Category</span>
            <span style={{ color: '#f87171', fontWeight: 700 }}>{alert.category} ({alert.severity})</span>
          </div>

          {alert.vehicle_info && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#94a3b8' }}>Vehicle Info</span>
              <span style={{ color: '#f8fafc', fontWeight: 600 }}>{alert.vehicle_info}</span>
            </div>
          )}

          {alert.owner_name && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#94a3b8' }}>Suspect / Owner</span>
              <span style={{ color: '#f8fafc' }}>{alert.owner_name}</span>
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>Location Sighted</span>
            <span style={{ color: '#38bdf8' }}>{alert.city} — {alert.camera_id}</span>
          </div>

          {alert.notes && (
            <div
              style={{
                background: 'rgba(15, 23, 42, 0.6)',
                padding: '8px',
                borderRadius: '6px',
                color: '#cbd5e1',
                fontSize: '11px',
                lineHeight: 1.4,
                borderLeft: '3px solid #ef4444',
              }}
            >
              {alert.notes}
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
            <button
              onClick={() => onDispatch(alert)}
              style={{
                flex: 1,
                background: '#ef4444',
                color: '#ffffff',
                border: 'none',
                padding: '8px',
                borderRadius: '6px',
                fontWeight: 700,
                fontSize: '12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
              }}
            >
              <Radio size={14} /> ALERT PATROL TEAM
            </button>
            <button
              onClick={onDismiss}
              style={{
                background: 'rgba(148, 163, 184, 0.15)',
                color: '#cbd5e1',
                border: 'none',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              DISMISS
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
