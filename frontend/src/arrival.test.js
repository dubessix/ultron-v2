import { describe, it, expect } from 'vitest';
import { createPresenceTracker, AWAY_MS } from './arrival';
import { planForEvent } from './reminderAlerts';

describe('arrival (V2 Step 8)', () => {
  it('fires only after 2+ hours without activity', () => {
    let t = 0;
    const tracker = createPresenceTracker({ now: () => t });
    t = 60_000; expect(tracker.activity()).toBe(false);
    t += AWAY_MS - 1; expect(tracker.activity()).toBe(false);
    t += AWAY_MS; expect(tracker.activity()).toBe(true);
    t += 1000; expect(tracker.activity()).toBe(false);
  });

  it('speaks the welcome-back briefing even if the tab was hidden', () => {
    const plan = planForEvent({ type: 'arrival_briefing', speech: 'Good evening, Sir. Welcome back.' }, { hidden: true });
    expect(plan.action).toBe('speak');
    expect(plan.heading).toBe('Welcome back');
    expect(plan.text).toContain('Welcome back');
  });

  it('heads-up warnings are spoken right away, never queued', () => {
    const event = { type: 'heads_up', kind: 'deadline', title: 'project report', minutes: 60,
      speech: 'Sir, heads up: project report is due in 1 hour.' };
    const plan = planForEvent(event, { hidden: true });
    expect(plan.action).toBe('speak');
    expect(plan.heading).toBe('Heads up');
    expect(plan.text).toBe(event.speech);
  });
});
