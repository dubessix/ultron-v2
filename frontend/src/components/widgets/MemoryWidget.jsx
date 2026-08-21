import React, { useEffect, useState } from 'react';
import { api } from '../../api';

/** Displays real project-scoped memory rows or an explicit unavailable state. */
export default function MemoryWidget() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');

  const load = async () => {
    setStatus('loading');
    setError('');
    try {
      const result = await api('/api/memory/recent?limit=5&project_id=personal');
      setData(result);
      setStatus('ready');
    } catch (err) {
      setData(null);
      setStatus('unavailable');
      setError(err.message || 'Memory query unavailable.');
    }
  };

  useEffect(() => { load(); }, []);

  const memories = data?.memories || [];
  return (
    <div className="space-y-3 font-mono text-[10px]">
      <div className="flex justify-between items-center bg-white/5 p-2 rounded-sm text-[8px] text-[#8B8B96] uppercase tracking-wider font-bold">
        <span>Recent personal memories</span>
        <button onClick={load} className="text-[#7DD3FC]">Refresh</button>
      </div>
      {status === 'loading' && <p className="text-[9px] text-white/30">Loading memories…</p>}
      {status === 'unavailable' && <p className="text-[9px] text-rose-300">Unavailable: {error}</p>}
      {status === 'ready' && memories.length === 0 && <p className="text-[9px] text-white/30">No personal memories are stored.</p>}
      {data && <p className="text-[7px] text-white/25 uppercase">Returned rows: {data.total}</p>}
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {memories.map((memory) => (
          <div key={memory.id} className="p-2 border border-white/5 bg-white/[0.01] rounded-sm flex flex-col gap-1.5">
            <p className="text-[9px] text-[#F5F5F7] leading-relaxed select-text">{memory.content}</p>
            <div className="flex justify-between items-center text-[7px] uppercase tracking-widest font-bold mt-1 text-white/40">
              <span className="text-[#7DD3FC]">{memory.type}</span>
              <span>{memory.created_at || 'time not reported'}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
