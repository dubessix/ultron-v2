import React, { useState } from 'react';

/**
 * GithubSearchWidget — real GitHub code/repo search via github_search tool.
 */
export default function GithubSearchWidget() {
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [msg, setMsg] = useState("");

  const search = async (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/tools/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id: "github_search", arguments: { query: q.trim() } })
      });
      const data = await res.json();
      if (data.success) {
        setResult(data.data);
        setMsg("");
      } else { setResult(null); setMsg(data.error || "failed"); }
    } catch (err) { setMsg("offline"); }
  };

  return (
    <div className="space-y-3 font-mono text-[9px]">
      <form onSubmit={search} className="flex gap-2">
        <input value={q} onChange={e=>setQ(e.target.value)} placeholder="search github (e.g. fastapi)"
          className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1 text-[9px] placeholder-white/20 focus:outline-none" />
        <button type="submit" className="text-[8px] px-2 py-1 border border-emerald-500/20 text-emerald-400 rounded-sm uppercase">Search</button>
      </form>
      {msg && <p className="text-rose-400">{msg}</p>}
      {result && (
        <div className="space-y-1.5 max-h-44 overflow-y-auto">
          <p className="text-[#7DD3FC]">{result.title || "Result"}</p>
          {result.url && (
            <a href={result.url} target="_blank" rel="noreferrer"
              className="block text-[9px] text-white/60 hover:underline break-all">{result.url}</a>
          )}
          {result.snippet && <p className="text-white/40">{result.snippet}</p>}
          {result.items && result.items.map((it,i)=>(
            <div key={i} className="p-1.5 border border-white/5 rounded-sm">
              <a href={it.url} target="_blank" rel="noreferrer" className="text-[#7DD3FC] hover:underline">{it.name}</a>
              <p className="text-white/30 text-[8px]">{it.path}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
