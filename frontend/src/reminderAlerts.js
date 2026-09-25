// Reminder alerts over /ws/events (V2 Step 2).
//
// The backend pushes:
//   { type: "reminder_triggered", reminder: {...}, speech }   -> live reminder
//   { type: "missed_reminders", items: [...], speech }        -> fired while away
// Rule: if the owner is looking at the screen, speak now. If the tab is hidden
// (he is away / on another window), keep it and say "while you were away"
// the moment he comes back. The queue survives a page reload (localStorage).

const QUEUE_KEY = 'ultron_reminder_queue_v1';
const MAX_QUEUE = 20;

export function readQueue(storage = globalThis.localStorage) {
  try {
    const parsed = JSON.parse(storage?.getItem(QUEUE_KEY) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeQueue(items, storage = globalThis.localStorage) {
  try {
    storage?.setItem(QUEUE_KEY, JSON.stringify(items.slice(-MAX_QUEUE)));
  } catch {
    /* storage full or blocked: alerts still show live */
  }
}

// Normalize both event shapes into simple items: { key, title, whenLocal, late, kind }.
export function itemsFromEvent(event) {
  if (!event || typeof event !== 'object') return [];
  if (event.type === 'reminder_triggered' && event.reminder) {
    const r = event.reminder;
    return [{
      key: r.inbox_id || `${r.id}-${r.target_time || ''}`,
      title: String(r.title || 'reminder'),
      whenLocal: r.when_local || '',
      late: Boolean(r.late),
      kind: r.type === 'alarm' ? 'alarm' : 'reminder',
    }];
  }
  if (event.type === 'missed_reminders' && Array.isArray(event.items)) {
    return event.items.map((r) => ({
      key: r.inbox_id || `${r.id}-${r.when_local || ''}`,
      title: String(r.title || 'reminder'),
      whenLocal: r.when_local || '',
      late: Boolean(r.late),
      kind: r.type === 'alarm' ? 'alarm' : 'reminder',
    }));
  }
  return [];
}

export function enqueue(items, storage = globalThis.localStorage) {
  const queue = readQueue(storage);
  const known = new Set(queue.map((item) => item.key));
  const merged = [...queue, ...items.filter((item) => !known.has(item.key))];
  writeQueue(merged, storage);
  return merged;
}

export function drainQueue(storage = globalThis.localStorage) {
  const queue = readQueue(storage);
  writeQueue([], storage);
  return queue;
}

function cleanTitle(title) {
  return String(title || 'reminder').replace(/[_#*`~<>{}[\]|\\/]+/g, ' ').replace(/\s+/g, ' ').trim();
}

// Plain words only: the voice must never read symbols aloud.
export function awaySpeech(items, owner = 'Sir') {
  if (!items.length) return '';
  const lines = items.slice(0, 5).map((item) => (
    item.late && item.whenLocal ? `${cleanTitle(item.title)}, set for ${item.whenLocal}` : cleanTitle(item.title)
  ));
  let body;
  if (lines.length === 1) body = `one reminder: ${lines[0]}`;
  else body = `${items.length} reminders: ${lines.slice(0, -1).join('; ')}; and ${lines[lines.length - 1]}`;
  if (items.length > lines.length) body += `. Plus ${items.length - lines.length} more on your screen`;
  return `Welcome back, ${owner}. While you were away, ${body}.`;
}

export function liveSpeech(item, owner = 'Sir') {
  return `${owner}, ${item.kind === 'alarm' ? 'alarm' : 'reminder'}: ${cleanTitle(item.title)}.`;
}

// Decide what to do with one event. Pure: returns an action for App.jsx.
//   { action: 'speak', text, items }  owner is here
//   { action: 'queue', items }        owner is away (tab hidden)
//   { action: 'ignore' }
export function planForEvent(event, { hidden, storage = globalThis.localStorage } = {}) {
  const items = itemsFromEvent(event);
  if (!items.length) return { action: 'ignore' };
  if (hidden) {
    enqueue(items, storage);
    return { action: 'queue', items };
  }
  const text = event.speech && typeof event.speech === 'string'
    ? event.speech
    : (event.type === 'missed_reminders' ? awaySpeech(items) : liveSpeech(items[0]));
  return { action: 'speak', text, items };
}

// When the owner comes back to the tab: everything queued, in one sentence.
export function planForReturn(storage = globalThis.localStorage) {
  const items = drainQueue(storage);
  if (!items.length) return { action: 'ignore' };
  return { action: 'speak', text: awaySpeech(items), items };
}

// Self-healing /ws/events connection with capped backoff (2s -> 30s).
export function connectEvents(url, onEvent, {
  WebSocketImpl = globalThis.WebSocket,
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = (id) => clearTimeout(id),
} = {}) {
  let socket = null;
  let timer = null;
  let delay = 2000;
  let stopped = false;

  const open = () => {
    if (stopped || typeof WebSocketImpl !== 'function') return;
    try {
      socket = new WebSocketImpl(url);
    } catch {
      schedule();
      return;
    }
    socket.onopen = () => { delay = 2000; };
    socket.onmessage = (message) => {
      let data;
      try { data = JSON.parse(message.data); } catch { return; }
      onEvent(data);
    };
    socket.onclose = () => { socket = null; schedule(); };
    socket.onerror = () => { try { socket?.close(); } catch { /* already closed */ } };
  };

  const schedule = () => {
    if (stopped || timer) return;
    timer = setTimer(() => { timer = null; open(); }, delay);
    delay = Math.min(delay * 2, 30000);
  };

  open();
  return () => {
    stopped = true;
    if (timer) clearTimer(timer);
    timer = null;
    if (socket) {
      socket.onclose = null;
      try { socket.close(); } catch { /* ignore */ }
    }
    socket = null;
  };
}
