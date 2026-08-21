import { useEffect, useRef, useState } from 'react';
import {
  METRIC_HISTORY_LIMIT,
  calculateNetworkRates,
  networkSampleFromMetrics,
  nextMetricHistory,
} from '../utils/metricHistory';

const EMPTY_HISTORY = {
  cpu: [],
  ram: [],
  temperature: [],
  disk: [],
};

const EMPTY_NETWORK_RATES = {
  available: false,
  status: 'collecting',
  txBytesPerSecond: null,
  rxBytesPerSecond: null,
};

/** Keep only recent real health samples; never synthesize missing sensors. */
export default function useMetricHistory(metrics, limit = METRIC_HISTORY_LIMIT) {
  const [history, setHistory] = useState(EMPTY_HISTORY);
  const [networkRates, setNetworkRates] = useState(EMPTY_NETWORK_RATES);
  const previousNetworkSample = useRef(null);

  useEffect(() => {
    if (!metrics) return;
    setHistory((current) => nextMetricHistory(current, metrics, limit));

    const sample = networkSampleFromMetrics(metrics);
    if (!sample) {
      previousNetworkSample.current = null;
      setNetworkRates({
        ...EMPTY_NETWORK_RATES,
        status: metrics.network?.available ? 'collecting' : 'unavailable',
      });
      return;
    }

    setNetworkRates(calculateNetworkRates(previousNetworkSample.current, sample));
    previousNetworkSample.current = sample;
  }, [metrics, limit]);

  return { history, networkRates };
}
