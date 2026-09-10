import React, { useState, useEffect } from 'react';
import { ShieldAlert, Plus, Zap, AlertTriangle, CheckCircle, RefreshCw } from 'lucide-react';

export default function WatchlistManager({ onTriggerSimulate }) {
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newPlate, setNewPlate] = useState('');
  const [newCategory, setNewCategory] = useState('STOLEN');
  const [newSeverity, setNewSeverity] = useState('CRITICAL');
  const [newNotes, setNewNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  const fetchWatchlist = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/watchlist');
      const data = await res.json();
      setWatchlist(data.watchlist || []);
    } catch (e) {
      console.error('Failed to load watchlist', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWatchlist();
  }, []);

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!newPlate.trim()) return;

    setSubmitting(true);
    try {
      const res = await fetch('/api/v1/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          license_plate: newPlate.trim().toUpperCase(),
          category: newCategory,
          severity: newSeverity,
          notes: newNotes,
        }),
      });
      if (res.ok) {
        setStatusMsg(`Vehicle ${newPlate} added to eGujCop Watchlist`);
        setNewPlate('');
        setNewNotes('');
        fetchWatchlist();
        setTimeout(() => setStatusMsg(''), 3000);
      }
    } catch (e) {
      console.error('Failed to add plate', e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ padding: '24px', overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert color="#ef4444" size={22} />
            eGujCop Watchlist & Automated Threat Radar
          </h2>
          <p style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Statewide Hotlist synced with Gujarat Police Database & Redis In-Memory Pipeline
          </p>
        </div>

        <button
          onClick={fetchWatchlist}
          style={{
            background: 'rgba(255, 255, 255, 0.05)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            color: '#cbd5e1',
            borderRadius: '6px',
            padding: '6px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '12px',
            cursor: 'pointer',
          }}
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {statusMsg && (
        <div style={{ background: 'rgba(16, 185, 129, 0.2)', border: '1px solid #10b981', color: '#6ee7b7', padding: '10px 14px', borderRadius: '6px', marginBottom: '16px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CheckCircle size={16} /> {statusMsg}
        </div>
      )}

      {/* Add Entry Card */}
      <div className="glass-panel" style={{ padding: '16px', borderRadius: '8px', marginBottom: '24px' }}>
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#06b6d4', marginBottom: '12px' }}>
          + REGISTER TARGET VEHICLE TO HOTLIST
        </div>
        <form onSubmit={handleAdd} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 3fr auto', gap: '10px', alignItems: 'center' }}>
          <input
            type="text"
            placeholder="License Plate (e.g. GJ01AB9999)"
            value={newPlate}
            onChange={(e) => setNewPlate(e.target.value.toUpperCase())}
            style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 12px', borderRadius: '6px', color: '#fff', fontFamily: 'monospace', fontSize: '13px' }}
          />
          <select
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 12px', borderRadius: '6px', color: '#fff', fontSize: '12px' }}
          >
            <option value="STOLEN">STOLEN</option>
            <option value="WANTED">WANTED</option>
            <option value="SUSPECT">SUSPECT</option>
          </select>
          <select
            value={newSeverity}
            onChange={(e) => setNewSeverity(e.target.value)}
            style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 12px', borderRadius: '6px', color: '#fff', fontSize: '12px' }}
          >
            <option value="CRITICAL">CRITICAL</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
          </select>
          <input
            type="text"
            placeholder="Case notes / FIR details"
            value={newNotes}
            onChange={(e) => setNewNotes(e.target.value)}
            style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 12px', borderRadius: '6px', color: '#fff', fontSize: '12px' }}
          />
          <button
            type="submit"
            disabled={submitting}
            style={{ background: '#06b6d4', color: '#000', border: 'none', padding: '8px 16px', borderRadius: '6px', fontWeight: 700, fontSize: '12px', cursor: 'pointer' }}
          >
            <Plus size={14} /> Add
          </button>
        </form>
      </div>

      {/* Watchlist Table */}
      <div className="glass-panel" style={{ borderRadius: '8px', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
          <thead>
            <tr style={{ background: 'rgba(0,0,0,0.5)', borderBottom: '1px solid var(--border-color)', color: '#94a3b8' }}>
              <th style={{ padding: '12px 16px' }}>LICENSE PLATE</th>
              <th style={{ padding: '12px 16px' }}>VEHICLE / SUSPECT</th>
              <th style={{ padding: '12px 16px' }}>CATEGORY</th>
              <th style={{ padding: '12px 16px' }}>SEVERITY</th>
              <th style={{ padding: '12px 16px' }}>OFFENSE NOTES</th>
              <th style={{ padding: '12px 16px', textAlign: 'right' }}>LIVE TEST ACTION</th>
            </tr>
          </thead>
          <tbody>
            {watchlist.map((item) => (
              <tr key={item.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <td style={{ padding: '12px 16px', fontFamily: 'monospace', fontWeight: 700, fontSize: '14px', color: '#f87171' }}>
                  {item.license_plate}
                </td>
                <td style={{ padding: '12px 16px' }}>
                  <div style={{ color: '#f8fafc', fontWeight: 600 }}>{item.vehicle_make} {item.vehicle_model}</div>
                  <div style={{ color: '#94a3b8', fontSize: '11px' }}>{item.owner_name}</div>
                </td>
                <td style={{ padding: '12px 16px' }}>
                  <span style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', padding: '2px 8px', borderRadius: '4px', fontWeight: 700, fontSize: '11px' }}>
                    {item.category}
                  </span>
                </td>
                <td style={{ padding: '12px 16px' }}>
                  <span style={{ color: item.severity === 'CRITICAL' ? '#ef4444' : '#f59e0b', fontWeight: 700 }}>
                    {item.severity}
                  </span>
                </td>
                <td style={{ padding: '12px 16px', color: '#cbd5e1', maxWidth: '300px' }}>
                  {item.notes}
                </td>
                <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                  <button
                    onClick={() => onTriggerSimulate(item.license_plate)}
                    style={{
                      background: 'rgba(239, 68, 68, 0.2)',
                      border: '1px solid #ef4444',
                      color: '#f87171',
                      borderRadius: '6px',
                      padding: '6px 12px',
                      fontSize: '11px',
                      fontWeight: 700,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <Zap size={12} /> SIMULATE LIVE HIT
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
