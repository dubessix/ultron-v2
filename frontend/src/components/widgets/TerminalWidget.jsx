import React, { useState } from 'react';
import { Lightbulb } from 'lucide-react';
import { executeToolWithConfirmation } from '../../api';

/**
 * TerminalWidget — real command runner (Set B: no fake logs).
 * Runs a command via the backend terminal_run tool and shows real output.
 */
export default function TerminalWidget() {
  const [cmd, setCmd] = useState("");
  const [logs, setLogs] = useState([]);
  const [running, setRunning] = useState(false);

  const run = async (e) => {
    e.preventDefault();
    if (!cmd.trim() || running) return;
    const input = cmd.trim();
    setCmd("");
    setRunning(true);
    setLogs(prev => [...prev, { line: `$ ${input}`, type: "cmd" }]);
    try {
      const data = await executeToolWithConfirmation(
        "terminal_run",
        { command: input },
        "terminal_widget",
      );
      if (data.success) {
        const out = data.data?.stdout;
        if (out) setLogs(prev => [...prev, { line: out, type: "success" }]);
        const err = data.data?.stderr;
        if (err) setLogs(prev => [...prev, { line: err, type: "error" }]);
        const fix = data.data?.self_healing_fix;
        if (fix && fix.fix_hint) setLogs(prev => [...prev, { line: fix.fix_hint, type: "error", hint: true }]);
      } else {
        setLogs(prev => [...prev, { line: data.status === "PENDING_CONFIRMATION" ? "confirmation cancelled" : `error: ${data.error || "command failed"}`, type: "error" }]);
      }
    } catch (err) {
      setLogs(prev => [...prev, { line: "offline", type: "error" }]);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-3 font-mono text-[9px]">
      <form onSubmit={run} className="flex gap-2">
        <input
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          placeholder="type a command, e.g. ls"
          disabled={running}
          className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1 text-[9px] text-[#F5F5F7] placeholder-white/20 focus:outline-none focus:border-[#7DD3FC]/30"
        />
        <button type="submit" disabled={running || !cmd.trim()}
          className="text-[8px] px-2 py-1 border border-emerald-500/20 bg-emerald-500/5 text-emerald-400 rounded-sm uppercase disabled:opacity-30">
          Run
        </button>
      </form>
      <div className="bg-black/40 border border-white/5 rounded-sm p-2 h-36 overflow-y-auto space-y-1">
        {logs.length === 0 && <p className="text-white/25">Run a command to see real output…</p>}
        {logs.map((l, i) => (
          <div key={i} className={`flex items-start gap-1.5 ${l.type === "cmd" ? "text-[#7DD3FC]" : l.type === "error" ? "text-rose-400" : "text-white/70"}`}>
            {l.hint && <Lightbulb size={11} strokeWidth={1.8} aria-hidden="true" className="mt-0.5 shrink-0" />}
            <p>{l.line}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
