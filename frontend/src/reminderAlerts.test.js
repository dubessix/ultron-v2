// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  awaySpeech,
  connectEvents,
  itemsFromEvent,
  planForEvent,
  planForReturn,
  readQueue,
} from './reminderAlerts';

const live = (title, extra = {}) => ({
  type: 'reminder_triggered',
  reminder: { id: `r-${title}`, inbox_id: `i-${title}`, type: 'reminder', title, when_local: '10:00 AM today', late: false, ...extra },
  speech: `Sir, reminder: ${title}.`,
});

describe('reminder alerts', () => {
  beforeEach(() => localStorage.clear());

  it('speaks right away when the owner is at the screen', () => {
    const plan = planForEvent(live('drink water'), { hidden: false });
    expect(plan.action).toBe('speak');
    expect(plan.text).toBe('Sir, reminder: drink water.');
    expect(readQueue()).toEqual([]);
  });

  it('keeps reminders while away and says them on return, once', () => {
    expect(planForEvent(live('call Rahul', { late: true, when_local: '10:00 AM today' }), { hidden: true }).action).toBe('queue');
    expect(planForEvent(live('gym'), { hidden: true }).action).toBe('queue');
    planForEvent(live('gym'), { hidden: true }); // duplicate ignored
    expect(readQueue()).toHaveLength(2);

    const back = planForReturn();
    expect(back.action).toBe('speak');
    expect(back.text).toBe(
      'Welcome back, Sir. While you were away, 2 reminders: call Rahul, set for 10:00 AM today; and gym.',
    );
    expect(planForReturn().action).toBe('ignore');
  });

  it('uses the backend summary for reminders missed while the app was closed', () => {
    const event = {
      type: 'missed_reminders',
      items: [{ id: 'a', inbox_id: 'x', type: 'alarm', title: 'standup', when_local: '9:00 AM today', late: true }],
      speech: 'Welcome back, Sir. While you were away, one reminder: standup, set for 9:00 AM today.',
    };
    expect(itemsFromEvent(event)[0].kind).toBe('alarm');
    expect(planForEvent(event, { hidden: false }).text).toBe(event.speech);
  });

  it('never reads symbols aloud', () => {
    const text = awaySpeech([{ key: 'k', title: 'call_#Rahul*', late: false }]);
    expect(text).toBe('Welcome back, Sir. While you were away, one reminder: call Rahul.');
  });

  it('ignores unrelated events', () => {
    expect(planForEvent({ type: 'emergency_alert' }, { hidden: false }).action).toBe('ignore');
  });

  it('reconnects with backoff and stops cleanly', () => {
    const sockets = [];
    class FakeSocket { constructor(url) { this.url = url; sockets.push(this); } close() {} }
    const timers = [];
    const onEvent = vi.fn();
    const stop = connectEvents('ws://x/ws/events', onEvent, {
      WebSocketImpl: FakeSocket,
      setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
      clearTimer: () => {},
    });
    sockets[0].onmessage({ data: JSON.stringify({ type: 'reminder_triggered' }) });
    expect(onEvent).toHaveBeenCalledTimes(1);
    sockets[0].onclose();
    expect(timers[0].ms).toBe(2000);
    timers[0].fn();
    expect(sockets).toHaveLength(2);
    sockets[1].onclose();
    expect(timers[1].ms).toBe(4000);
    stop();
    timers[1].fn();
    expect(sockets).toHaveLength(2); // no reconnect after stop
  });
});
