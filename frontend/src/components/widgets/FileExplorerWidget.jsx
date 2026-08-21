import React, { useState, useEffect } from 'react';
import { FileText, Folder } from 'lucide-react';

/**
 * FileExplorerWidget — real folder navigation (no fake D:\ drives).
 * Navigate by clicking folders, typing a path (e.g. ~/Desktop/jerry), or going up.
 * Lists the actual directory via the backend list_contents tool.
 */
export default function FileExplorerWidget() {
  const [path, setPath] = useState(".");
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async (folder) => {
    setLoading(true); setError("");
    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/tools/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id: "list_contents", arguments: { folderpath: folder } })
      });
      const data = await res.json();
      if (data.success && data.data?.contents) {
        setEntries(data.data.contents);
        setPath(folder);
        setInput(folder);
      } else {
        setError(data.error || "cannot list folder");
      }
    } catch (err) { setError("offline"); } finally { setLoading(false); }
  };

  useEffect(() => { load("."); }, []);

  const goUp = () => {
    if (path === "." || path === "/" || path === "~") return load(".");
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    load(parts.length ? "/" + parts.join("/") : ".");
  };

  const go = (e) => { e.preventDefault(); if (input.trim()) load(input.trim()); };

  return (
    <div className="space-y-2 font-mono text-[9px]">
      <form onSubmit={go} className="flex gap-2">
        <input value={input} onChange={e=>setInput(e.target.value)} placeholder="path, e.g. Desktop/jerry"
          className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1 text-[9px] placeholder-white/20 focus:outline-none" />
        <button type="submit" className="text-[8px] px-2 py-1 border border-emerald-500/20 text-emerald-400 rounded-sm uppercase">Go</button>
        <button type="button" onClick={goUp} className="text-[8px] px-2 py-1 border border-white/10 text-white/70 rounded-sm uppercase">Up</button>
      </form>
      <div className="flex items-center gap-2 text-[8px] text-white/40 truncate">
        <span className="text-[#7DD3FC]">/</span>
        <span className="truncate text-white/60">{path}</span>
      </div>
      {error && <p className="text-rose-400">{error}</p>}
      {loading ? <p className="text-white/25">Loading…</p> : (
        <div className="space-y-1 max-h-40 overflow-y-auto">
          {!error && entries.length === 0 && <p className="text-white/25">(empty folder)</p>}
          {entries.map((e, i) => (
            <button key={i} onClick={() => e.type === "folder" && load(`${path === "." ? path + "/" : path}/${e.name}`.replace(/\/+/g,"/"))}
              className="flex w-full items-center justify-between text-left text-[#F5F5F7] hover:bg-white/5 rounded-sm px-1">
              <span className={`flex min-w-0 items-center gap-1.5 ${e.type === "folder" ? "text-[#7DD3FC]" : ""}`}>
                {e.type === "folder"
                  ? <Folder size={12} strokeWidth={1.8} aria-hidden="true" className="shrink-0" />
                  : <FileText size={12} strokeWidth={1.8} aria-hidden="true" className="shrink-0" />}
                <span className="truncate">{e.name}</span>
              </span>
              <span className="text-white/30 text-[8px]">{e.type === "file" && e.size ? e.size : ""}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
