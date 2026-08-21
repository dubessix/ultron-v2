import React, { useState } from 'react';
import { executeToolWithConfirmation } from '../../api';

/**
 * GitCloneWidget — Jarvis-style clone automation.
 * Paste a repo URL -> Ultron says "Okay Sir, I'm ready" -> clones (downloads code)
 * -> shows result + offers to open in VS Code.
 */
export default function GitCloneWidget() {
  const [url, setUrl] = useState("");
  const [dir, setDir] = useState("repos");
  const [stage, setStage] = useState("idle"); // idle | ready | cloning | done | error
  const [msg, setMsg] = useState("");

  const run = async (action, args) => {
    try {
      return await executeToolWithConfirmation(action, args, "git_clone_widget");
    } catch (err) { return { success: false, error: "offline" }; }
  };

  const clone = async () => {
    if (!url.trim()) return;
    setStage("cloning"); setMsg("Cloning...");
    const r = await run("git_clone", { url: url.trim(), directory: dir.trim() || "repos" });
    if (r.success) { setStage("done"); setMsg(r.data?.message || "Cloned."); }
    else { setStage("error"); setMsg(r.error || "failed"); }
  };

  const openVscode = async () => {
    const requestedPath = dir.trim() || "repos";
    const r = await run("open_vscode", { path: requestedPath });
    setMsg(r.success
      ? `${r.data?.message || 'VS Code launch dispatched.'} Path: ${r.data?.requested_path || requestedPath}`
      : (r.error || "could not dispatch VS Code"));
  };

  return (
    <div className="space-y-3 font-mono text-[9px]">
      <div className="flex items-center gap-2">
        <span className="text-[8px] uppercase tracking-widest text-white/40 font-bold">Git Clone</span>
        <span className={`text-[7px] px-1.5 py-0.5 rounded-full ${stage==="ready"||stage==="done"?"bg-emerald-500/10 text-emerald-400":"bg-white/5 text-white/40"}`}>
          {stage === "cloning" ? "working..." : stage === "done" ? "ready" : stage === "error" ? "error" : "idle"}
        </span>
      </div>

      <input
        value={url}
        onChange={e => { setUrl(e.target.value); setStage("idle"); }}
        placeholder="paste repo link, e.g. https://github.com/user/repo.git"
        className="w-full bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1.5 text-[9px] placeholder-white/20 focus:outline-none focus:border-[#7DD3FC]/30"
      />
      <input
        value={dir}
        onChange={e => setDir(e.target.value)}
        placeholder="target folder (e.g. repos)"
        className="w-full bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1.5 text-[9px] placeholder-white/20 focus:outline-none"
      />

      <button
        onClick={() => setStage("ready")}
        disabled={!url.trim()}
        className="w-full text-[8px] px-2 py-1.5 border border-emerald-500/20 bg-emerald-500/5 text-emerald-400 rounded-sm uppercase disabled:opacity-30"
      >
        Ready
      </button>

      {stage === "ready" && (
        <p className="text-[#7DD3FC]">Okay Sir, I'm ready. Shall I clone this repository?</p>
      )}

      {stage !== "idle" && (
        <div className="flex gap-1.5">
          {stage === "ready" && (
            <button onClick={clone} className="flex-1 text-[8px] px-2 py-1 border border-sky-400/30 text-[#7DD3FC] rounded-sm uppercase">Clone</button>
          )}
          {stage === "done" && (
            <button onClick={openVscode} className="flex-1 text-[8px] px-2 py-1 border border-emerald-400/30 text-emerald-400 rounded-sm uppercase">Open VS Code</button>
          )}
        </div>
      )}

      {msg && <p className={stage === "error" ? "text-rose-400" : "text-white/60"}>{msg}</p>}
    </div>
  );
}
