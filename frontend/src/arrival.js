// V2 Step 8 - notice when the owner comes back (activity after 2+ hours idle).
// Pure and tiny: no timers, no polling. App.jsx feeds it real activity events.
export const AWAY_MS = 2 * 60 * 60 * 1000;

export function createPresenceTracker({ idleMs = AWAY_MS, now = () => Date.now(), startAt } = {}) {
  let last = typeof startAt === 'number' ? startAt : now();
  return {
    // Returns true when this activity ends an idle gap of idleMs or more.
    activity() {
      const t = now();
      const cameBack = t - last >= idleMs;
      last = t;
      return cameBack;
    },
    lastActivity: () => last,
  };
}
