import React, { useState, useEffect } from 'react';

/**
 * WorldMonitorWidget — real live earthquakes via world_monitor tool.
 */
export default function WorldMonitorWidget() {
  const [quakes, setQuakes] = useState([]);
  const [msg, setMsg] = useState("loading");

  const load = async () => {
    setMsg("loading");
    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/tools/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id: "world_monitor", arguments: { endpoint: "list_earthquakes", parameters: { min_magnitude: 5.0 } } })
      });
      const data = await res.json();
      if (data.success) {
        const items = (data.data?.events) || (data.data?.earthquakes) || [];
        setQuakes(items);
        setMsg(items.length ? "live" : "no significant quakes");
      } else {
        setQuakes([]); setMsg(data.error || "failed");
      }
    } catch (err) { setMsg("offline"); }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-2 font-mono text-[9px]">
      <div className="flex items-center justify-between">
        <span className="text-[8px] uppercase tracking-widest text-white/40 font-bold">World Monitor</span>
        <button onClick={load} className="text-[8px] text-[#7DD3FC] uppercase">refresh</button>
      </div>
      <p className={msg==="offline"?"text-rose-400":"text-white/40"}>{msg}</p>
      <div className="space-y-1.5 max-h-44 overflow-y-auto">
        {quakes.map((q, i) => (
          <div key={i} className="p-2 border border-white/5 bg-white/[0.01] rounded-sm">
            <div className="flex justify-between">
              <span className="text-rose-400 font-bold">M{q.mag ?? q.magnitude ?? "?"}</span>
              <span className="text-white/50">{q.place || q.location || ""}</span>
            </div>
            <p className="text-white/30 text-[8px]">{q.time || q.ts || ""}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
