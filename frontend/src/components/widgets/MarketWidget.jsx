import React, { useEffect, useState } from 'react';
import { executeTool } from '../../api';

/** Live crypto quotes routed through the standardized backend world-monitor tool. */
export default function MarketWidget() {
  const [coins, setCoins] = useState([]);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');
  const [source, setSource] = useState('');

  const load = async () => {
    setStatus('loading');
    setError('');
    try {
      const result = await executeTool('world_monitor', {
        endpoint: 'list_market_quotes',
        parameters: {},
      });
      if (!result.success) throw new Error(result.error || 'Live market quotes unavailable.');
      setCoins(result.data.quotes || []);
      setSource(result.data.source || 'Source not reported');
      setStatus('ready');
    } catch (err) {
      setCoins([]);
      setSource('');
      setStatus('unavailable');
      setError(err.message || 'Live market quotes unavailable.');
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-2 font-mono text-[10px]">
      <div className="flex justify-between text-[7px] uppercase tracking-widest text-white/40 font-bold">
        <span>Market quotes {source && `· ${source}`}</span>
        <button onClick={load} className={status === 'unavailable' ? 'text-rose-400' : 'text-emerald-400'}>
          {status === 'loading' ? 'loading…' : status === 'unavailable' ? 'retry' : 'LIVE'}
        </button>
      </div>
      {status === 'unavailable' && <p className="text-[9px] text-rose-300">Unavailable: {error}</p>}
      {status === 'ready' && coins.length === 0 && <p className="text-[9px] text-white/30">Provider returned no valid quotes.</p>}
      <div className="space-y-1.5">
        {coins.map((coin) => {
          const change = coin.change_24h;
          return (
            <div key={coin.asset} className="flex items-center justify-between border border-white/5 bg-white/[0.01] p-2 rounded-sm">
              <span className="text-[#F5F5F7]">{coin.symbol}/USD</span>
              <span className="flex items-center gap-2">
                <span className="text-white/70">${Number(coin.price_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                <span className={change == null ? 'text-white/40' : change >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {change == null ? 'Unavailable' : `${change > 0 ? '+' : ''}${Number(change).toFixed(2)}%`}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
