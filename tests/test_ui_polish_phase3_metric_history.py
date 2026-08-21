"""Phase 3 regressions for real bounded metric trends and network rates."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
UTIL = ROOT / "frontend" / "src" / "utils" / "metricHistory.js"
HOOK = ROOT / "frontend" / "src" / "hooks" / "useMetricHistory.js"


class TestRealMetricHistoryContract(unittest.TestCase):
    def _run_node(self, body: str) -> dict:
        script = f"""
import {{ appendMetricSample, nextMetricHistory, calculateNetworkRates }} from {json.dumps(UTIL.as_uri())};
{body}
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stdout)

    def test_metric_history_is_real_numeric_and_strictly_bounded(self):
        payload = self._run_node(
            """
let values = [];
for (let index = 0; index < 30; index += 1) values = appendMetricSample(values, index, 24);
values = appendMetricSample(values, 'fake', 24);
const history = nextMetricHistory(
  { cpu: [], ram: [], temperature: [], disk: [] },
  { cpu_percent: 0, ram_percent: 41.5, temperature_c: null, disk_percent: 62.25 },
  24
);
console.log(JSON.stringify({ values, history }));
"""
        )
        self.assertEqual(payload["values"], list(range(6, 30)))
        self.assertEqual(payload["history"]["cpu"], [0])
        self.assertEqual(payload["history"]["ram"], [41.5])
        self.assertEqual(payload["history"]["temperature"], [])
        self.assertEqual(payload["history"]["disk"], [62.25])

    def test_network_rates_come_from_counter_and_timestamp_deltas(self):
        payload = self._run_node(
            """
const good = calculateNetworkRates(
  { timestampMs: 1000, bytesSent: 1000, bytesReceived: 2000 },
  { timestampMs: 3000, bytesSent: 5000, bytesReceived: 10000 }
);
const reset = calculateNetworkRates(
  { timestampMs: 3000, bytesSent: 5000, bytesReceived: 10000 },
  { timestampMs: 4000, bytesSent: 10, bytesReceived: 20 }
);
console.log(JSON.stringify({ good, reset }));
"""
        )
        self.assertTrue(payload["good"]["available"])
        self.assertEqual(payload["good"]["txBytesPerSecond"], 2000)
        self.assertEqual(payload["good"]["rxBytesPerSecond"], 4000)
        self.assertFalse(payload["reset"]["available"])
        self.assertEqual(payload["reset"]["status"], "counter_reset")

    def test_frontend_records_honest_health_round_trip_and_sample_time(self):
        app = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        hook = HOOK.read_text(encoding="utf-8")
        self.assertIn("performance.now()", app)
        self.assertIn("health_latency_ms", app)
        self.assertIn("sampled_at_ms", app)
        self.assertIn("nextMetricHistory", hook)
        self.assertIn("calculateNetworkRates", hook)
        self.assertIn("useRef", hook)
        self.assertNotIn("31", hook)
        self.assertNotIn("43%", hook)
        self.assertNotIn("62%", hook)


if __name__ == "__main__":
    unittest.main()
