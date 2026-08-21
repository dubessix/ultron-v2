import React, { useEffect, useState } from 'react';
import { executeTool } from '../../api';

/** Displays only telemetry reported by the local backend. */
export default function SystemWidget() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');

  const load = async () => {
    setStatus('loading');
    setError('');
    try {
      const result = await executeTool('system_metrics', {});
      if (!result.success) throw new Error(result.error || 'System metrics unavailable.');
      setData(result.data);
      setStatus('ready');
    } catch (err) {
      setData(null);
      setStatus('unavailable');
      setError(err.message || 'System metrics unavailable.');
    }
  };

  useEffect(() => { load(); }, []);

  if (status === 'loading') {
    return <div className="text-[9px] text-[#8B8B96] uppercase animate-pulse">Reading local sensors...</div>;
  }
  if (!data) {
    return (
      <div className="space-y-2 font-mono text-[9px]">
        <p className="text-rose-300">Unavailable: {error}</p>
        <button onClick={load} className="text-[#7DD3FC] uppercase">Retry</button>
      </div>
    );
  }

  const uptime = data.uptime_seconds == null
    ? 'Unavailable'
    : `${(data.uptime_seconds / 3600).toFixed(1)} hours`;

  return (
    <div className="space-y-3 font-mono text-[10px]">
      <div className="flex justify-between text-[7px] uppercase tracking-widest text-white/40">
        <span>Reported local telemetry</span>
        <button onClick={load} className="text-[#7DD3FC]">Refresh</button>
      </div>
      <div className="space-y-2.5">
        <Metric label="CPU Load" value={data.cpu} />
        <Metric label="RAM Utilization" value={data.ram} detail={`Ultron process: ${data.proc_ram_mb} MB`} />
        <Metric label="Disk Space" value={data.disk} />
        <Metric label="Temperature" value={data.temperature_display} />
        <Metric label="Battery" value={data.battery_display} />
        <Metric label="Network counters" value={data.network_display} />
        <Metric label="System uptime" value={uptime} />
      </div>
      {data.unavailable_fields?.length > 0 && (
        <p className="text-[7px] text-amber-300/70 uppercase">
          Not reported by this device: {data.unavailable_fields.join(', ')}
        </p>
      )}
    </div>
  );
}

function Metric({ label, value, detail }) {
  return (
    <div>
      <span className="text-[7px] text-[#8B8B96] uppercase tracking-widest font-bold block">{label}</span>
      <p className="text-xs font-bold text-[#F5F5F7] mt-1 break-words">{value ?? 'Unavailable'}</p>
      {detail && <p className="text-[8px] text-[#8B8B96] mt-0.5">{detail}</p>}
    </div>
  );
}
