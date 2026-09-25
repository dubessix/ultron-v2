import React, { useState, useEffect } from 'react';
import { FileText, Folder, Home, ArrowUp } from 'lucide-react';
import { apiBase } from '../../api';

/**
 * FileExplorerWidget: whole-disk folder navigation via the list_contents tool.
 * Opens where Ultron last worked (else home), so it follows Ultron. When a
 * folder tool runs, the widget reloads and jumps there. Shows the full path.
 * Up goes all the way to / (or C:\ on Windows). Folders you open here become
 * "that folder" for Ultron too.
 */
const QUICK = [
  { label: "Home", path: "~" },
  { label: "Desktop", path: "~/Desktop" },
  { label: "Documents", path: "~/Documents" },
  { label: "Downloads", path: "~/Downloads" },
];

function joinPath(base, name) {
  const sep = base.includes("\\") && !base.includes("/") ? "\\" : "/";
  return base.endsWith(sep) ? base + name : base + sep + name;
}

function rootOf(path) {
  const drive = /^[A-Za-z]:[\\/]/.exec(path || "");
  return drive ? drive[0] : "/";
}

export default function FileExplorerWidget() {
  const [path, setPath] = useState("");
  const [parent, setParent] = useState(null);
  const [input, setInput] = useState("");
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async (folder) => {
    setLoading(true); setError("");
    try {
      const res = await fetch(`${apiBase}/api/tools/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id: "list_contents", arguments: { folderpath: folder } })
      });
      const data = await res.json();
      if (data.success && data.data?.contents) {
        const sorted = [...data.data.contents].sort((a, b) =>
          (a.type === b.type ? 0 : a.type === "folder" ? -1 : 1) || a.name.localeCompare(b.name));
        const showHidden = folder.split(/[\\/]/).pop()?.startsWith(".");
        setEntries(showHidden ? sorted : sorted.filter(e => !e.name.startsWith(".")));
        const full = data.data.path || folder;
        setPath(full);
        setParent(data.data.parent ?? null);
        setInput(full);
      } else {
        setError(data.error || "cannot list folder");
      }
    } catch (err) { setError("offline"); } finally { setLoading(false); }
  };

  // "" = where Ultron last worked (else home). Remounts on Ultron folder tools.
  useEffect(() => { load(""); }, []);

  const goUp = () => { if (parent) load(parent); };
  const go = (e) => { e.preventDefault(); if (input.trim()) load(input.trim()); };
  const btn = "text-[8px] px-2 py-1 border border-white/10 text-white/70 rounded-sm uppercase hover:bg-white/5";

  return (
    <div className="space-y-2 font-mono text-[9px]">
      <form onSubmit={go} className="flex gap-2">
        <input value={input} onChange={e=>setInput(e.target.value)} placeholder="any path, e.g. /etc or ~/Desktop/jerry"
          className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1 text-[9px] placeholder-white/20 focus:outline-none" />
        <button type="submit" className="text-[8px] px-2 py-1 border border-emerald-500/20 text-emerald-400 rounded-sm uppercase">Go</button>
        <button type="button" onClick={goUp} disabled={!parent} title="Up one folder"
          className={`${btn} flex items-center gap-1 disabled:opacity-30`}><ArrowUp size={10} />Up</button>
      </form>
      <div className="flex flex-wrap gap-1">
        {QUICK.map(q => (
          <button key={q.label} type="button" onClick={() => load(q.path)} className={btn}>
            {q.label === "Home" ? <span className="flex items-center gap-1"><Home size={10} />Home</span> : q.label}
          </button>
        ))}
        <button type="button" onClick={() => load(rootOf(path))} className={btn} title="Top of the disk">{rootOf(path)}</button>
      </div>
      <div className="text-[8px] text-white/60 break-all" title={path}>
        <span className="text-[#7DD3FC]">at </span>{path || "…"}
      </div>
      {error && <p className="text-rose-400">{error}</p>}
      {loading ? <p className="text-white/25">Loading…</p> : (
        <div className="space-y-1 max-h-40 overflow-y-auto">
          {!error && entries.length === 0 && <p className="text-white/25">(empty folder)</p>}
          {entries.map((e, i) => (
            <button key={i} onClick={() => e.type === "folder" && load(joinPath(path, e.name))}
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
