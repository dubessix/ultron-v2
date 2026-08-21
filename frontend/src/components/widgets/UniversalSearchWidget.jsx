import React, { useState } from 'react';
import { executeTool } from '../../api';

/** Searches real approved filenames and local assistant records. */
export default function UniversalSearchWidget() {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');

  const search = async (event) => {
    event.preventDefault();
    const cleaned = query.trim();
    if (cleaned.length < 2) return;
    setStatus('loading');
    setError('');
    try {
      const response = await executeTool('universal_search', {
        query: cleaned,
        project_id: 'personal',
        limit: 20,
      });
      if (!response.success) throw new Error(response.error || 'Local search unavailable.');
      setResult(response.data);
      setStatus('ready');
    } catch (err) {
      setResult(null);
      setStatus('unavailable');
      setError(err.message || 'Local search unavailable.');
    }
  };

  const records = result?.results || [];
  return (
    <div className="space-y-3 font-mono text-[10px]">
      <form onSubmit={search} className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search approved files, tasks, reminders, memories..."
          className="flex-1 bg-white/[0.02] border border-white/5 rounded-sm px-3 py-2 text-[10px] text-[#F5F5F7] placeholder-white/20 focus:outline-none focus:border-[#7DD3FC]/30"
        />
        <button disabled={status === 'loading' || query.trim().length < 2} className="px-2 border border-[#7DD3FC]/20 text-[#7DD3FC] disabled:opacity-30">
          {status === 'loading' ? 'Searching…' : 'Search'}
        </button>
      </form>

      {status === 'idle' && <p className="text-[8px] text-white/30">Enter at least two characters. Nothing is pre-populated.</p>}
      {status === 'unavailable' && <p className="text-[8px] text-rose-300">Unavailable: {error}</p>}
      {status === 'ready' && records.length === 0 && (
        <p className="text-[8px] text-white/30">No matching records were found in the searched local sources.</p>
      )}
      {result && (
        <p className="text-[7px] text-white/25 uppercase">
          {result.count} result(s) · {result.files_scanned} filenames checked{result.truncated ? ' · bounded scan stopped early' : ''}
        </p>
      )}
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {records.map((item) => (
          <div key={`${item.category}:${item.id}`} className="p-2 border border-white/5 bg-white/[0.01] rounded-sm flex flex-col gap-1">
            <div className="flex justify-between items-center">
              <span className="font-bold text-[#F5F5F7] break-all">{item.name}</span>
              <span className="text-[7px] bg-[#7DD3FC]/10 text-[#7DD3FC] px-1.5 py-0.5 rounded-sm font-bold uppercase tracking-wider">{item.category}</span>
            </div>
            <span className="text-[8px] text-white/30 break-all">{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
