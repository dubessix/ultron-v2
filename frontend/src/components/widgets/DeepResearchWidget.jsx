import React, { useState } from 'react';
import { executeTool } from '../../api';

/** Runs real Tavily/keyless research and saves only returned findings. */
export default function DeepResearchWidget() {
  const [query, setQuery] = useState('');
  const [findings, setFindings] = useState(null);
  const [status, setStatus] = useState('idle');
  const [message, setMessage] = useState('');

  const research = async (event) => {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setStatus('loading');
    setMessage('');
    try {
      const result = await executeTool('tavily_research', { query: query.trim() });
      if (!result.success) throw new Error(result.error || 'Research unavailable.');
      setFindings(result.data);
      setStatus('ready');
    } catch (err) {
      setFindings(null);
      setStatus('unavailable');
      setMessage(err.message || 'Research unavailable.');
    }
  };

  const save = async () => {
    if (!findings) return;
    setMessage('Saving returned findings...');
    const sourceLines = (findings.sources || []).map((source) => `${source.name}: ${source.url}`);
    try {
      const result = await executeTool('manage_memory', {
        action: 'remember',
        project_id: 'personal',
        content: `Research: ${findings.topic}\n${findings.summary}\nSources:\n${sourceLines.join('\n')}`,
        category: 'research',
        importance: 'normal',
      });
      if (!result.success) throw new Error(result.error || 'Memory save failed.');
      setMessage('Returned findings saved to personal memory.');
    } catch (err) {
      setMessage(`Save unavailable: ${err.message || 'unknown error'}`);
    }
  };

  return (
    <div className="space-y-4 font-mono text-[10px]">
      <form onSubmit={research} className="flex gap-2">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Research a topic using live sources..."
          className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1.5 placeholder-white/20 focus:outline-none" />
        <button disabled={status === 'loading' || query.trim().length < 2} className="px-2 border border-[#7DD3FC]/20 text-[#7DD3FC] disabled:opacity-30">
          {status === 'loading' ? 'Researching…' : 'Run'}
        </button>
      </form>

      {status === 'idle' && <p className="text-[8px] text-white/30">No findings loaded. Enter a topic to make a live request.</p>}
      {status === 'unavailable' && <p className="text-[8px] text-rose-300">Unavailable: {message}</p>}
      {findings && (
        <>
          <div className="bg-[#7DD3FC]/5 border border-[#7DD3FC]/10 p-2.5 rounded-sm">
            <span className="block text-[7px] text-[#7DD3FC] uppercase tracking-widest font-bold">Returned topic</span>
            <p className="text-xs font-bold text-[#F5F5F7] mt-1">{findings.topic}</p>
          </div>
          <div className="space-y-2">
            <span className="text-[7px] text-[#8B8B96] uppercase tracking-widest font-bold">Returned summary</span>
            <p className="text-[9px] text-[#F5F5F7] leading-relaxed bg-white/[0.01] border border-white/5 p-3 rounded-sm">{findings.summary}</p>
          </div>
          <div className="space-y-1.5">
            <span className="text-[7px] text-[#8B8B96] uppercase tracking-widest font-bold">Verified source URLs</span>
            {(findings.sources || []).map((source) => (
              <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer"
                className="block text-[8px] text-[#7DD3FC] underline break-all">{source.name}</a>
            ))}
          </div>
          <button onClick={save} className="w-full py-1.5 border border-white/10 bg-white/5 text-[9px] uppercase tracking-widest font-bold hover:bg-white/10">
            Save returned findings to memory
          </button>
          {message && status === 'ready' && <p className="text-[8px] text-white/40">{message}</p>}
        </>
      )}
    </div>
  );
}
