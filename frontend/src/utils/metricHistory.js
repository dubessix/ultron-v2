export const METRIC_HISTORY_LIMIT = 24;

export function finiteNumberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function appendMetricSample(history, value, limit = METRIC_HISTORY_LIMIT) {
  const numeric = finiteNumberOrNull(value);
  if (numeric === null) return Array.isArray(history) ? history : [];
  const boundedLimit = Math.max(2, Math.min(120, Math.trunc(limit) || METRIC_HISTORY_LIMIT));
  return [...(Array.isArray(history) ? history : []), numeric].slice(-boundedLimit);
}

export function nextMetricHistory(current, metrics, limit = METRIC_HISTORY_LIMIT) {
  const previous = current || {};
  const reported = metrics || {};
  return {
    cpu: appendMetricSample(previous.cpu, reported.cpu_percent, limit),
    ram: appendMetricSample(
      previous.ram,
      reported.ram_percent ?? reported.total_system_ram_usage_percent,
      limit,
    ),
    temperature: appendMetricSample(previous.temperature, reported.temperature_c, limit),
    disk: appendMetricSample(previous.disk, reported.disk_percent, limit),
  };
}

export function networkSampleFromMetrics(metrics) {
  const reported = metrics || {};
  const network = reported.network || {};
  const timestampMs = finiteNumberOrNull(reported.sampled_at_ms);
  const bytesSent = finiteNumberOrNull(network.bytes_sent);
  const bytesReceived = finiteNumberOrNull(network.bytes_received);
  if (!network.available || timestampMs === null || bytesSent === null || bytesReceived === null) {
    return null;
  }
  return { timestampMs, bytesSent, bytesReceived };
}

export function calculateNetworkRates(previous, current) {
  if (!previous || !current) {
    return {
      available: false,
      status: 'collecting',
      txBytesPerSecond: null,
      rxBytesPerSecond: null,
    };
  }
  const elapsedSeconds = (current.timestampMs - previous.timestampMs) / 1000;
  if (!Number.isFinite(elapsedSeconds) || elapsedSeconds <= 0) {
    return {
      available: false,
      status: 'invalid_time_delta',
      txBytesPerSecond: null,
      rxBytesPerSecond: null,
    };
  }
  const sentDelta = current.bytesSent - previous.bytesSent;
  const receivedDelta = current.bytesReceived - previous.bytesReceived;
  if (sentDelta < 0 || receivedDelta < 0) {
    return {
      available: false,
      status: 'counter_reset',
      txBytesPerSecond: null,
      rxBytesPerSecond: null,
    };
  }
  return {
    available: true,
    status: 'reported',
    txBytesPerSecond: sentDelta / elapsedSeconds,
    rxBytesPerSecond: receivedDelta / elapsedSeconds,
  };
}

export function sparklinePoints(values, width = 100, height = 32) {
  const reported = (Array.isArray(values) ? values : []).filter(
    (value) => finiteNumberOrNull(value) !== null,
  );
  if (reported.length < 2) return '';
  const minimum = Math.min(...reported);
  const maximum = Math.max(...reported);
  const range = maximum - minimum;
  const rounded = (value) => Math.round(value * 100) / 100;
  return reported
    .map((value, index) => {
      const x = (index / (reported.length - 1)) * width;
      const y = range === 0 ? height / 2 : height - ((value - minimum) / range) * height;
      return `${rounded(x)},${rounded(y)}`;
    })
    .join(' ');
}

export function formatBytesPerSecond(value) {
  const numeric = finiteNumberOrNull(value);
  if (numeric === null || numeric < 0) return 'Unavailable';
  if (numeric < 1024) return `${numeric.toFixed(0)} B/s`;
  if (numeric < 1024 ** 2) return `${(numeric / 1024).toFixed(1)} KB/s`;
  return `${(numeric / (1024 ** 2)).toFixed(1)} MB/s`;
}
