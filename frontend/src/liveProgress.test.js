import { describe, expect, it } from 'vitest';
import { progressAction } from './liveProgress';

describe('live progress', () => {
  const event = { type: 'ultron_progress', text: 'Running npm install', speak: true, session_id: 's1' };

  it('shows and speaks only while waiting for an answer', () => {
    expect(progressAction(event, { processing: true, sessionId: 's1' })).toEqual({ text: 'Running npm install', speak: true });
    expect(progressAction(event, { processing: false, sessionId: 's1' })).toBeNull();
  });

  it('ignores other sessions, other events and empty text', () => {
    expect(progressAction(event, { processing: true, sessionId: 's2' })).toBeNull();
    expect(progressAction({ type: 'reminder_triggered' }, { processing: true })).toBeNull();
    expect(progressAction({ ...event, text: '  ' }, { processing: true })).toBeNull();
  });

  it('never gives the voice symbols', () => {
    const out = progressAction({ ...event, text: 'Reading src/App.jsx {x}' }, { processing: true });
    expect(out.text).toBe('Reading src App.jsx x');
  });

  it('a new session (no id yet) still hears it', () => {
    expect(progressAction(event, { processing: true, sessionId: null }).speak).toBe(true);
  });
});
