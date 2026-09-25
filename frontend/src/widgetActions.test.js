import { describe, it, expect } from 'vitest';
import { applyWidgetAction } from './widgetActions';

const base = () => ({
  calendar: { visible: false, x: 1, y: 2 },
  reminder: { visible: true, refreshKey: 0 },
  todo: { visible: true },
});

describe('applyWidgetAction (V2 Step 4)', () => {
  it('opens the panel the AI chose and keeps its position', () => {
    const next = applyWidgetAction(base(), { action: 'open_widget', widget_id: 'calendar' });
    expect(next.calendar).toMatchObject({ visible: true, x: 1, y: 2 });
  });
  it('reloads an open panel after its data changed', () => {
    const next = applyWidgetAction(base(), { action: 'open_widget', widget_id: 'reminder', refresh: true });
    expect(next.reminder.refreshKey).toBe(1);
  });
  it('closes one panel or all panels', () => {
    expect(applyWidgetAction(base(), { action: 'close_widget', widget_id: 'todo' }).todo.visible).toBe(false);
    const all = applyWidgetAction(base(), { action: 'close_all_widgets' });
    expect(Object.values(all).every(w => !w.visible)).toBe(true);
  });
  it('ignores none and unknown panels', () => {
    const prev = base();
    expect(applyWidgetAction(prev, { action: 'none' })).toBe(prev);
    expect(applyWidgetAction(prev, { action: 'open_widget', widget_id: 'nope' })).toBe(prev);
    expect(applyWidgetAction(prev, null)).toBe(prev);
  });
});
