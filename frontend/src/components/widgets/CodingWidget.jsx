import React, { useState } from 'react';
import { Code2 } from 'lucide-react';

/**
 * CodingWidget
 * Shows the active coding-agent activity: a log of recent coding responses so
 * the user can see what Ultron created/updated (diff summary) without hunting for
 * the right panel. Auto-shown by App.jsx when a turn is a coding turn.
 */
export default function CodingWidget({ log = [] }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="space-y-3 font-mono text-[10px]">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[8px] uppercase tracking-widest font-bold text-sky-300">
          <Code2 size={12} strokeWidth={1.8} aria-hidden="true" />
          Coding Agent
        </span>
        <button
          onClick={() => setOpen(!open)}
          className="text-[8px] text-white/30 hover:text-white/70 uppercase tracking-widest"
        >
          {open ? "hide" : "show"}
        </button>
      </div>

      {open && (
        <div className="space-y-2">
          {log.length === 0 ? (
            <p className="text-white/30 text-[9px]">No coding activity yet. Ask Ultron to build something, e.g. "make an auth API".</p>
          ) : (
            log.map((item, i) => (
              <div key={i} className="border border-white/5 bg-white/[0.02] rounded-sm p-2">
                <p className="text-[9px] text-[#7DD3FC] whitespace-pre-wrap">{item}</p>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
