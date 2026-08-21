import React, { useEffect, useState } from 'react';
import { executeTool } from '../../api';

/** Displays verified local Git status or an explicit unavailable state. */
export default function GitWidget() {
  const [data, setData] = useState(null);
  const [repositoryPath, setRepositoryPath] = useState('.');
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');

  const load = async () => {
    setStatus('loading');
    setError('');
    try {
      const result = await executeTool('git_status', { directory: repositoryPath.trim() || '.' });
      if (!result.success) throw new Error(result.error || 'Git status unavailable.');
      setData(result.data);
      setStatus('ready');
    } catch (err) {
      setData(null);
      setStatus('unavailable');
      setError(err.message || 'Git status unavailable.');
    }
  };

  useEffect(() => { load(); }, []);

  if (status === 'loading') {
    return <div className="text-[9px] text-[#8B8B96] uppercase animate-pulse">Querying local Git tree...</div>;
  }
  if (!data) {
    return (
      <div className="space-y-2 font-mono text-[9px]">
        <RepositoryInput value={repositoryPath} onChange={setRepositoryPath} onSubmit={load} />
        <p className="text-rose-300">Unavailable: {error}</p>
        <p className="text-white/30">No branch, file, or commit values were substituted.</p>
      </div>
    );
  }

  const files = data.uncommitted_files || [];
  return (
    <div className="space-y-4 font-mono text-[10px]">
      <RepositoryInput value={repositoryPath} onChange={setRepositoryPath} onSubmit={load} />
      <div className="flex justify-between items-start bg-white/[0.01] border border-white/5 p-3 rounded-sm">
        <div>
          <span className="block text-[7px] text-[#8B8B96] uppercase tracking-widest font-bold">Active Branch</span>
          <p className="text-sm font-bold text-[#7DD3FC] mt-1">⎇ {data.branch || 'Not reported'}</p>
        </div>
        <button onClick={load} className="text-[7px] text-[#7DD3FC] uppercase">Refresh</button>
      </div>
      <div className="space-y-2">
        <span className="text-[7px] text-[#8B8B96] uppercase tracking-widest font-bold">Uncommitted Changes</span>
        {files.length === 0 ? (
          <p className="text-[8px] text-white/30">Git reported no uncommitted files.</p>
        ) : (
          <div className="space-y-1">
            {files.map((file) => (
              <div key={file} className="flex items-center justify-between bg-white/[0.01] border border-white/5 px-2 py-1.5 rounded-sm">
                <span className="truncate text-[9px] max-w-[80%] text-amber-300">{file}</span>
                <span className="text-[6px] border border-amber-500/20 bg-amber-500/5 px-1.5 py-0.5 text-amber-400 rounded-sm">CHANGED</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="border-t border-white/5 pt-2 text-[7px] text-white/30 truncate">
        HEAD: {data.last_commit || 'Not reported'}
      </div>
    </div>
  );
}

function RepositoryInput({ value, onChange, onSubmit }) {
  return (
    <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }} className="flex gap-2">
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder="approved repository path"
        className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1 text-[9px] placeholder-white/20 focus:outline-none" />
      <button type="submit" className="text-[8px] px-2 border border-[#7DD3FC]/20 text-[#7DD3FC]">Load</button>
    </form>
  );
}
