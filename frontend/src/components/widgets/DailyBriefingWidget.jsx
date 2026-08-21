import React, { useEffect, useState } from 'react';
import { executeTool } from '../../api';

/** Builds a briefing from local records and explicitly sourced live data. */
export default function DailyBriefingWidget() {
  const [status, setStatus] = useState('loading');
  const [briefing, setBriefing] = useState(null);
  const [error, setError] = useState('');

  const fetchBriefing = async () => {
    setStatus('loading');
    setError('');
    try {
      const result = await executeTool('daily_briefing', {
        include_weather: true,
        include_tasks: true,
        include_schedule: true,
        include_news: true,
      });
      if (!result.success) throw new Error(result.error || 'Briefing unavailable.');
      setBriefing(result.data);
      setStatus('ready');
    } catch (err) {
      setBriefing(null);
      setStatus('unavailable');
      setError(err.message || 'Briefing unavailable.');
    }
  };

  useEffect(() => { fetchBriefing(); }, []);

  return (
    <div className="flex flex-col h-full w-full font-mono text-[10px] text-white/90 p-4 space-y-4 overflow-y-auto custom-scrollbar">
      <div className="flex justify-between items-center border-b border-white/5 pb-2">
        <span className="text-[11px] font-bold tracking-widest text-[#7DD3FC] uppercase">Daily Jarvis Briefing</span>
        <button onClick={fetchBriefing} disabled={status === 'loading'}
          className="bg-[#7DD3FC]/10 border border-[#7DD3FC]/30 text-[#7DD3FC] text-[8px] px-2 py-0.5 rounded-sm uppercase tracking-wider disabled:opacity-30">
          {status === 'loading' ? 'Compiling...' : 'Refresh'}
        </button>
      </div>

      {status === 'loading' && <p className="text-white/30 uppercase">Collecting local and live sources...</p>}
      {status === 'unavailable' && (
        <div className="space-y-2">
          <p className="text-rose-300">Unavailable: {error}</p>
          <p className="text-white/30">No briefing values were substituted.</p>
        </div>
      )}
      {briefing && (
        <div className="space-y-3 flex-1 overflow-y-auto max-h-[240px] custom-scrollbar text-[9px]">
          <div className="bg-white/5 p-2 rounded-sm flex justify-between items-center border border-white/5">
            <div>
              <span className="text-white/40 block text-[7px]">DATE</span>
              <span className="font-bold text-[#7DD3FC]">{briefing.date}</span>
            </div>
            <div className="text-right max-w-[55%]">
              <span className="text-white/40 block text-[7px]">LIVE WEATHER</span>
              <span className="font-bold text-[#7DD3FC]">
                {briefing.weather?.available
                  ? `${briefing.weather.temperature} (${briefing.weather.windspeed || 'wind not reported'})`
                  : 'Unavailable — no estimate'}
              </span>
            </div>
          </div>
          <div className="bg-white/[0.01] border border-white/5 p-3 rounded-sm leading-relaxed whitespace-pre-wrap text-white/80">
            {briefing.briefing_text}
          </div>
          <p className="text-[7px] text-white/30 uppercase">
            News status: {briefing.news?.available ? `${briefing.news.items.length} sourced result(s)` : 'unavailable'}
          </p>
        </div>
      )}
    </div>
  );
}
