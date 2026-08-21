import React, { useState } from 'react';
import { executeToolWithConfirmation } from '../../api';

/**
 * MusicWidget — real music controls via backend music_tools.
 * Play/pause/next/prev/volume + current track.
 */
export default function MusicWidget() {
  const [path, setPath] = useState("");
  const [track, setTrack] = useState("");
  const [msg, setMsg] = useState("");

  const run = async (action, args = {}) => {
    try {
      const data = await executeToolWithConfirmation(action, args, "music_widget");
      if (data.success) {
        const d = data.data || {};
        setTrack(d.current_track || "");
        setMsg(d.message || "");
      } else {
        setMsg(data.error || "failed");
      }
    } catch (err) { setMsg("offline"); }
  };

  return (
    <div className="space-y-3 font-mono text-[9px]">
      <form onSubmit={(e)=>{e.preventDefault(); path && run('play_music',{filepath:path});}} className="flex gap-2">
        <input value={path} onChange={e=>setPath(e.target.value)} placeholder="path to audio file"
          className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1 text-[9px] placeholder-white/20 focus:outline-none" />
        <button type="submit" className="text-[8px] px-2 py-1 border border-emerald-500/20 text-emerald-400 rounded-sm uppercase">Play</button>
      </form>

      <div className="flex gap-1.5 flex-wrap">
        {[['pause_music','Pause'],['resume_music','Resume'],['stop_music','Stop'],['next_track','Next'],['previous_track','Prev']].map(([a,l])=>(
          <button key={a} onClick={()=>run(a)} className="text-[8px] px-2 py-1 border border-white/10 text-white/70 rounded-sm uppercase hover:text-white">{l}</button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <span className="text-white/40 text-[8px]">Vol</span>
        <input type="range" min="0" max="100" defaultValue="70"
          onChange={e=>run('set_volume',{level:Number(e.target.value)})}
          className="flex-1 accent-emerald-400" />
      </div>

      {track && <p className="text-[#7DD3FC]">▶ {track}</p>}
      {msg && <p className="text-white/50">{msg}</p>}
    </div>
  );
}
