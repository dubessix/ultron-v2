import React, { useEffect, useState } from 'react';
import { executeTool } from '../../api';

/** Shows persisted reminder/alarm records; no sample notifications are inserted. */
export default function NotificationWidget() {
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');

  const load = async () => {
    setStatus('loading');
    setError('');
    try {
      const result = await executeTool('manage_reminder', { action: 'list' });
      if (!result.success) throw new Error(result.error || 'Reminder notifications unavailable.');
      setAlerts(result.data.reminders || []);
      setStatus('ready');
    } catch (err) {
      setAlerts([]);
      setStatus('unavailable');
      setError(err.message || 'Reminder notifications unavailable.');
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-3 font-mono text-[10px]">
      <div className="flex justify-between text-[7px] uppercase tracking-widest text-white/40">
        <span>Persisted reminders and alarms</span>
        <button onClick={load} className="text-[#7DD3FC]">Refresh</button>
      </div>
      {status === 'loading' && <p className="text-white/30 animate-pulse">Loading local records...</p>}
      {status === 'unavailable' && <p className="text-rose-300">Unavailable: {error}</p>}
      {status === 'ready' && alerts.length === 0 && (
        <p className="text-white/30">No reminder or alarm records are currently stored.</p>
      )}
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {alerts.map((alert) => (
          <div key={alert.id} className="p-2 border border-white/5 bg-white/[0.01] rounded-sm flex flex-col gap-1">
            <div className="flex justify-between items-center">
              <span className="font-bold text-[#F5F5F7] text-[9px] uppercase tracking-wider truncate max-w-[70%]">{alert.title}</span>
              <span className="text-[6px] text-white/30 uppercase">{alert.type}</span>
            </div>
            {alert.description && <p className="text-[9px] text-[#8B8B96] leading-relaxed">{alert.description}</p>}
            <span className="text-[7px] text-white/40">Target: {formatTime(alert.target_time)}</span>
            <span className={`text-[6px] uppercase tracking-widest font-bold mt-1 inline-block px-1 rounded-sm w-fit ${
              alert.status === 'triggered' ? 'bg-rose-500/10 text-rose-400' : 'bg-sky-500/10 text-sky-300'
            }`}>{alert.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatTime(value) {
  if (!value) return 'Not reported';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
