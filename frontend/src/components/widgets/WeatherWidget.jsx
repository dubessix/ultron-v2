import React, { useEffect, useState } from 'react';
import { executeTool } from '../../api';

/** Displays only live Open-Meteo values returned by the backend. */
export default function WeatherWidget() {
  const [weather, setWeather] = useState(null);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');

  const load = async () => {
    setStatus('loading');
    setError('');
    try {
      const result = await executeTool('weather_tool', { latitude: 22.57, longitude: 88.36 });
      if (!result.success) throw new Error(result.error || 'Live weather unavailable.');
      setWeather(result.data);
      setStatus('ready');
    } catch (err) {
      setWeather(null);
      setStatus('unavailable');
      setError(err.message || 'Live weather unavailable.');
    }
  };

  useEffect(() => { load(); }, []);

  if (status === 'loading') {
    return <div className="text-[9px] text-[#8B8B96] uppercase animate-pulse">Requesting live weather...</div>;
  }
  if (!weather) {
    return (
      <div className="space-y-2 font-mono text-[9px]">
        <p className="text-rose-300">Unavailable: {error}</p>
        <p className="text-white/30">No estimate or cached forecast was substituted.</p>
        <button onClick={load} className="text-[#7DD3FC] uppercase">Retry</button>
      </div>
    );
  }

  const hourly = weather.hourly || [];
  const weekly = weather.weekly || [];
  return (
    <div className="space-y-4 font-mono text-[10px]">
      <div className="flex justify-between items-center bg-white/5 p-3 rounded-sm">
        <div>
          <span className="text-[7px] text-[#8B8B96] uppercase tracking-widest font-bold">{weather.location}</span>
          <p className="text-lg font-bold text-amber-300 mt-1">{weather.temp}</p>
          <span className="text-[8px] text-white/40 uppercase mt-0.5 block">{weather.condition}</span>
          <span className="text-[7px] text-white/30 block mt-1">Wind: {weather.windspeed}</span>
        </div>
        <div className="text-right text-[7px] text-emerald-300 uppercase">
          {weather.source}<br />{weather.observed_at || 'time not reported'}
        </div>
      </div>

      <ForecastSection title="Upcoming hourly values" empty="Provider returned no upcoming hourly values." count={hourly.length}>
        <div className="grid grid-cols-3 gap-2 text-center">
          {hourly.map((item) => (
            <div key={item.time} className="bg-white/[0.01] border border-white/5 p-1.5 rounded-sm">
              <span className="text-[7px] text-white/30 block">{item.time}</span>
              <span className="text-[10px] font-bold text-[#F5F5F7] mt-1 block">{item.temp}</span>
              <span className="text-[7px] text-white/30 block">{item.condition}</span>
            </div>
          ))}
        </div>
      </ForecastSection>

      <ForecastSection title="Daily maximum forecast" empty="Provider returned no daily values." count={weekly.length}>
        <div className="space-y-1">
          {weekly.map((item) => (
            <div key={item.date || item.day} className="flex justify-between items-center bg-white/[0.01] border border-white/5 px-2 py-1.5 rounded-sm">
              <span className="font-bold text-[#F5F5F7] text-[9px]">{item.day}</span>
              <span className="text-white/40 text-[9px]">{item.cond}</span>
              <span className="font-bold text-[#7DD3FC] text-[9px]">{item.temp}</span>
            </div>
          ))}
        </div>
      </ForecastSection>
    </div>
  );
}

function ForecastSection({ title, empty, count, children }) {
  return (
    <div className="space-y-2">
      <span className="text-[7px] text-[#8B8B96] uppercase tracking-widest font-bold">{title}</span>
      {count ? children : <p className="text-[8px] text-white/30">{empty}</p>}
    </div>
  );
}
