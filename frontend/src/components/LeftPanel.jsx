import React from 'react';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Cpu,
  MemoryStick,
  MonitorCog,
  Network,
  Thermometer,
} from 'lucide-react';
import useMetricHistory from '../hooks/useMetricHistory';
import { formatBytesPerSecond, sparklinePoints } from '../utils/metricHistory';

/** Reference-style dashboard using only values reported by /api/health. */
export default function LeftPanel({ systemMetrics, backendStatus }) {
  const metrics = systemMetrics || {};
  const { history, networkRates } = useMetricHistory(systemMetrics);
  const cpu = numberOrNull(metrics.cpu_percent);
  const ram = numberOrNull(metrics.ram_percent ?? metrics.total_system_ram_usage_percent);
  const temperature = numberOrNull(metrics.temperature_c);
  const disk = numberOrNull(metrics.disk_percent);
  const uptime = numberOrNull(metrics.uptime_seconds);
  const healthLatency = numberOrNull(metrics.health_latency_ms);
  const network = metrics.network || {};
  const hasTelemetry = cpu !== null && ram !== null;
  const hasTrendHistory = history.cpu.length >= 2 && history.ram.length >= 2;
  const backendConnected = backendStatus === 'CONNECTED';
  const txRate = networkRates.available ? networkRates.txBytesPerSecond : null;
  const rxRate = networkRates.available ? networkRates.rxBytesPerSecond : null;
  const peakRate = Math.max(txRate || 0, rxRate || 0);
  const txActivity = peakRate > 0 && txRate !== null ? (txRate / peakRate) * 100 : 0;
  const rxActivity = peakRate > 0 && rxRate !== null ? (rxRate / peakRate) * 100 : 0;

  const trendStatus = !hasTelemetry
    ? 'Waiting'
    : hasTrendHistory
      ? 'Live'
      : 'Collecting';

  return (
    <aside className="ultron-left-panel col-span-12 h-full min-w-0 space-y-3 overflow-x-hidden overflow-y-auto pr-1 font-mono no-visible-scrollbar md:col-span-3 lg:col-span-3 [@media(max-height:800px)]:space-y-2 2xl:space-y-4">
      <section className="ultron-overview-panel rounded-xl border border-emerald-500/15 bg-[#0B1112]/88 p-3.5 shadow-[0_0_24px_rgba(16,185,129,0.035)] backdrop-blur-xl [@media(max-height:800px)]:p-3 2xl:p-4">
        <div className="ultron-section-heading mb-3 flex items-center justify-between [@media(max-height:800px)]:mb-2 2xl:mb-4">
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-[#F5F5F7] 2xl:text-[11px]">
            <Activity size={14} strokeWidth={1.8} className="text-emerald-400" aria-hidden="true" />
            <span>System overview</span>
          </div>
          <span className={`text-[8px] font-semibold uppercase tracking-widest 2xl:text-[9px] ${hasTelemetry ? 'text-emerald-400' : 'text-amber-300'}`}>
            {trendStatus}
          </span>
        </div>

        <div className="ultron-trend-grid grid grid-cols-2 gap-2.5 [@media(max-height:800px)]:gap-2 2xl:gap-3">
          <TrendMetricCard
            label="CPU"
            value={percent(cpu)}
            history={history.cpu}
            color="#34D399"
          />
          <TrendMetricCard
            label="RAM"
            value={percent(ram)}
            history={history.ram}
            color="#FB923C"
          />
          <TrendMetricCard
            label="Temp"
            value={temperature === null ? 'Unavailable' : `${temperature.toFixed(1)}°C`}
            history={history.temperature}
            available={temperature !== null}
            color="#38BDF8"
          />
          <TrendMetricCard
            label="Disk"
            value={percent(disk)}
            history={history.disk}
            color="#A78BFA"
          />
        </div>
      </section>

      <section
        className="ultron-network-panel rounded-xl border border-emerald-500/15 bg-[#0B1112]/88 p-3.5 shadow-[0_0_24px_rgba(16,185,129,0.035)] backdrop-blur-xl [@media(max-height:800px)]:p-3 2xl:p-4"
        aria-label="Network counters"
      >
        <div className="ultron-section-heading mb-3 flex items-center justify-between [@media(max-height:800px)]:mb-2 2xl:mb-4">
          <div className="flex items-center gap-2.5">
            <span className="ultron-network-icon flex h-8 w-8 items-center justify-center rounded-full border border-cyan-400/15 bg-cyan-400/5 text-cyan-300 2xl:h-9 2xl:w-9">
              <Network size={16} strokeWidth={1.7} aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-[10px] font-bold uppercase tracking-widest text-emerald-300 2xl:text-[11px]">Network</h2>
              <p className="mt-0.5 text-[8px] text-white/42 2xl:text-[9px]">Telemetry link</p>
            </div>
          </div>
          <span className={`rounded-full border px-2 py-1 text-[7px] font-bold uppercase tracking-widest 2xl:px-2.5 2xl:text-[8px] ${
            backendConnected
              ? 'border-emerald-400/20 bg-emerald-400/5 text-emerald-300'
              : 'border-amber-400/20 bg-amber-400/5 text-amber-300'
          }`}>
            {backendConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        <div className="ultron-network-values mb-3 grid grid-cols-2 gap-2.5 [@media(max-height:800px)]:mb-2 [@media(max-height:800px)]:gap-2 2xl:mb-4 2xl:gap-3">
          <NetworkValue
            label="Local round trip"
            value={healthLatency === null ? 'Unavailable' : `${healthLatency.toFixed(1)} ms`}
            color="text-emerald-300"
          />
          <NetworkValue
            label="Uptime"
            value={formatUptime(uptime)}
            color="text-cyan-300"
          />
        </div>

        {network.available ? (
          <div className="ultron-rate-group space-y-3 [@media(max-height:800px)]:space-y-2 2xl:space-y-4">
            <RateRow
              icon={ArrowUp}
              label="TX rate"
              value={networkRates.available ? formatBytesPerSecond(txRate) : rateStatus(networkRates.status)}
              activity={txActivity}
              color="#F472B6"
            />
            <RateRow
              icon={ArrowDown}
              label="RX rate"
              value={networkRates.available ? formatBytesPerSecond(rxRate) : rateStatus(networkRates.status)}
              activity={rxActivity}
              color="#60A5FA"
            />
            <p className="text-right text-[7px] text-white/28">
              {network.interfaces_up ?? 'Unavailable'} interfaces reported up
            </p>
          </div>
        ) : (
          <p className="rounded-lg border border-white/5 bg-black/20 px-3 py-4 text-center text-[8px] text-white/35">
            Network counters unavailable on this device.
          </p>
        )}
      </section>

      <section className="ultron-detail-grid grid grid-cols-2 gap-2.5 [@media(max-height:800px)]:gap-2 2xl:gap-3">
        <DetailMetricCard
          icon={Cpu}
          label="CPU load"
          value={percent(cpu)}
          progress={cpu}
          color="#34D399"
        />
        <DetailMetricCard
          icon={MemoryStick}
          label="RAM usage"
          value={percent(ram)}
          progress={ram}
          color="#FB6A4A"
        />
        <DetailMetricCard
          icon={Thermometer}
          label="Temperature"
          value={temperature === null ? 'Unavailable' : `${temperature.toFixed(1)}°C`}
          color="#38BDF8"
        />
        <DetailMetricCard
          icon={MonitorCog}
          label="System status"
          value={formatPlatform(metrics.platform)}
          status={backendConnected ? 'Active' : 'Offline'}
          color="#C084FC"
        />
      </section>
    </aside>
  );
}

function TrendMetricCard({ label, value, history, color, available = true }) {
  const isUnavailable = value === 'Unavailable';
  return (
    <div className="ultron-trend-card min-w-0 overflow-hidden rounded-lg border border-white/[0.06] bg-black/25 px-2.5 py-2.5 2xl:px-3.5 2xl:py-3.5">
      <span className="block text-[7px] font-semibold uppercase tracking-widest text-white/42 2xl:text-[8px]">{label}</span>
      <div className="ultron-trend-card-row mt-1.5 flex min-h-9 items-end justify-between gap-1.5 2xl:mt-2 2xl:min-h-11">
        <span className={`shrink-0 whitespace-nowrap font-bold text-[#F5F5F7] ${isUnavailable ? 'text-[10px] 2xl:text-[11px]' : 'text-[16px] 2xl:text-[18px]'}`}>
          {value}
        </span>
        <MiniSparkline values={history} color={color} available={available} />
      </div>
    </div>
  );
}

function MiniSparkline({ values, color, available = true }) {
  if (!available) {
    return <span className="ultron-sparkline w-[58px] shrink-0 pb-1 text-right text-[6px] uppercase tracking-wider text-white/25 2xl:w-[76px] 2xl:text-[7px]">No sensor</span>;
  }
  const points = sparklinePoints(values, 58, 24);
  if (!points) {
    return <span className="ultron-sparkline w-[58px] shrink-0 pb-1 text-right text-[6px] uppercase tracking-wider text-white/25 2xl:w-[76px] 2xl:text-[7px]">Collecting</span>;
  }
  return (
    <svg width="58" height="24" viewBox="0 0 58 24" role="img" aria-label="Recent reported trend" className="ultron-sparkline shrink-0 2xl:h-[31px] 2xl:w-[76px]">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function NetworkValue({ label, value, color }) {
  return (
    <div className="ultron-network-value min-w-0 overflow-hidden rounded-lg border border-white/[0.05] bg-black/20 px-3 py-2.5 2xl:px-3.5 2xl:py-3.5">
      <span className="block text-[7px] uppercase tracking-widest text-white/35 2xl:text-[8px]">{label}</span>
      <span className={`mt-1.5 block break-words text-[14px] font-bold 2xl:mt-2 2xl:text-[16px] ${color}`}>{value}</span>
    </div>
  );
}

function RateRow({ icon: Icon, label, value, activity, color }) {
  const width = Number.isFinite(activity) ? Math.max(0, Math.min(100, activity)) : 0;
  return (
    <div className="grid grid-cols-[18px_1fr_auto] items-center gap-2 2xl:grid-cols-[20px_1fr_auto] 2xl:gap-3">
      <Icon size={14} strokeWidth={1.8} style={{ color }} aria-hidden="true" className="2xl:h-4 2xl:w-4" />
      <div>
        <div className="mb-1.5 flex items-center justify-between text-[7px] uppercase tracking-wider text-white/35 2xl:text-[8px]">
          <span>{label}</span>
        </div>
        <div className="h-1 rounded-full bg-white/[0.06] 2xl:h-1.5">
          <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${width}%`, backgroundColor: color }} />
        </div>
      </div>
      <span className="max-w-20 text-right text-[7px] font-semibold text-white/60 2xl:max-w-24 2xl:text-[8px]">{value}</span>
    </div>
  );
}

function DetailMetricCard({ icon: Icon, label, value, progress, color, status }) {
  const width = numberOrNull(progress);
  const isUnavailable = value === 'Unavailable';
  return (
    <div className="ultron-detail-card min-h-24 min-w-0 overflow-hidden rounded-xl border bg-[#0B1112]/88 p-3.5 backdrop-blur-xl [@media(max-height:800px)]:min-h-20 [@media(max-height:800px)]:p-3 2xl:min-h-28 2xl:p-4" style={{ borderColor: `${color}2E` }}>
      <div className="flex items-center gap-2 text-white/45 2xl:gap-2.5">
        <Icon size={14} strokeWidth={1.7} style={{ color }} aria-hidden="true" className="2xl:h-4 2xl:w-4" />
        <span className="text-[7px] font-semibold uppercase tracking-widest 2xl:text-[8px]">{label}</span>
      </div>
      <span className={`ultron-detail-value mt-3 block max-w-full truncate whitespace-nowrap font-bold [@media(max-height:800px)]:mt-2 2xl:mt-4 ${isUnavailable ? 'text-[16px] 2xl:text-[18px]' : 'text-[18px] 2xl:text-[21px]'}`} style={{ color }} title={value}>{value}</span>
      {width !== null && (
        <div className="ultron-detail-progress mt-3 h-1 rounded-full bg-white/[0.06] [@media(max-height:800px)]:mt-2 2xl:mt-4 2xl:h-1.5">
          <div
            className="h-full rounded-full"
            style={{ width: `${Math.max(0, Math.min(100, width))}%`, backgroundColor: color }}
          />
        </div>
      )}
      {status && (
        <span className="ultron-detail-status mt-2 inline-flex rounded-full border border-white/[0.07] bg-white/[0.03] px-2 py-0.5 text-[7px] uppercase tracking-widest text-white/55 [@media(max-height:800px)]:mt-1.5 2xl:mt-3 2xl:px-2.5 2xl:text-[8px]">
          {status}
        </span>
      )}
    </div>
  );
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function percent(value) {
  return value === null ? 'Unavailable' : `${value.toFixed(1)}%`;
}

function formatUptime(value) {
  if (value === null) return 'Unavailable';
  return `${(value / 3600).toFixed(1)} h`;
}

function formatPlatform(value) {
  if (typeof value !== 'string' || !value.trim()) return 'Unavailable';
  const lower = value.toLowerCase();
  if (lower.includes('windows')) return 'WINDOWS';
  if (lower.includes('linux')) return 'LINUX';
  if (lower.includes('darwin') || lower.includes('macos')) return 'MACOS';
  return value.split('-')[0].slice(0, 18).toUpperCase();
}

function rateStatus(status) {
  if (status === 'collecting') return 'Collecting…';
  if (status === 'counter_reset') return 'Counter reset';
  return 'Unavailable';
}
