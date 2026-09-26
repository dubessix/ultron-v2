// Runs extension/chrome/background.js with a fake chrome API and checks the
// tab rules (used by tests/test_v2_step_c_extension.py). Prints "ALL OK".
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(path.join(__dirname, '..', 'extension', 'chrome', 'background.js'), 'utf8');

function makeWorld(extra) {
  let closed = [];
  let tabs = [
    { id: 1, windowId: 1, title: 'Ultron', url: 'http://127.0.0.1:5173/', active: true, lastAccessed: 50 },
    { id: 2, windowId: 1, title: 'lofi beats - YouTube', url: 'https://www.youtube.com/watch?v=a', active: false, lastAccessed: 40, audible: true },
    { id: 3, windowId: 1, title: 'news today - YouTube', url: 'https://www.youtube.com/watch?v=b', active: false, lastAccessed: 30 },
    { id: 4, windowId: 1, title: 'dubessix/ultron-v2 - GitHub', url: 'https://github.com/dubessix/ultron-v2', active: false, lastAccessed: 45 },
  ].concat(extra || []);
  const history = [
    { url: 'https://react.dev/reference/react/hooks', title: 'Built-in React Hooks', lastVisitTime: 1700000000000 },
    { url: 'https://react.dev/reference/react/hooks#top', title: 'Built-in React Hooks', lastVisitTime: 1690000000000 },
    { url: 'http://127.0.0.1:5173/?q=react hooks', title: 'Ultron react hooks', lastVisitTime: 1700000000000 },
    { url: 'https://example.com/cats', title: 'Cats', lastVisitTime: 1700000000000 },
  ];
  const historyCalls = [];
  const sent = [];
  class FakeSocket {
    constructor() { this.readyState = 1; FakeSocket.last = this; setTimeout(() => this.onopen && this.onopen(), 0); }
    send(text) { sent.push(JSON.parse(text)); }
  }
  FakeSocket.OPEN = 1; FakeSocket.CONNECTING = 0;
  const noop = { addListener() {} };
  const chrome = {
    runtime: { getManifest: () => ({ version: '1.0.0' }), onStartup: noop, onInstalled: noop },
    alarms: { create() {}, onAlarm: noop },
    windows: { update: async () => ({}) },
    sessions: {
      getRecentlyClosed: async () => closed.slice(),
      restore: async (sessionId) => { const i = closed.findIndex((c) => c.tab && c.tab.sessionId === sessionId); const [c] = closed.splice(i, 1); const t = Object.assign({}, c.tab, { id: 200 + i }); delete t.sessionId; tabs.push(t); return { tab: t }; },
    },
    history: { search: async (q) => { historyCalls.push(q); return history.filter((h) => q.text.split(' ').every((k) => (h.title + ' ' + h.url).toLowerCase().includes(k))); } },
    scripting: { executeScript: async ({ target }) => [{ result: { title: 'page ' + target.tabId, text: 'hello   world' } }] },
    tabs: {
      query: async (q) => (q.active ? tabs.filter((t) => t.active) : tabs.slice()),
      get: async (id) => { const t = tabs.find((x) => x.id === id); if (!t) throw new Error('No tab'); return t; },
      remove: async (ids) => { const drop = new Set([].concat(ids)); closed = tabs.filter((t) => drop.has(t.id)).map((t) => ({ lastModified: 1, tab: Object.assign({ sessionId: 's' + t.id }, t) })).reverse().concat(closed); tabs = tabs.filter((t) => !drop.has(t.id)); },
      discard: async (id) => { const t = tabs.find((x) => x.id === id); if (!t || t.active || t.discarded) return undefined; if (t.url.startsWith('chrome://')) throw new Error('Cannot discard'); t.discarded = true; return t; },
      update: async (id, props) => { const t = tabs.find((x) => x.id === id); Object.assign(t, props, props.muted !== undefined ? { mutedInfo: { muted: props.muted } } : {}); if (props.active) tabs.forEach((x) => { if (x.id !== id) x.active = false; }); return t; },
      create: async ({ url }) => { const t = { id: 99, windowId: 1, title: '', url }; tabs.push(t); return t; },
      reload: async () => {}, goBack: async () => {}, goForward: async () => {},
    },
  };
  const context = { chrome, WebSocket: FakeSocket, setTimeout, clearInterval, setInterval: () => 0, console, JSON, String, Number, Array, Set, Map, Error, Date };
  vm.createContext(context);
  vm.runInContext(source, context);
  let nextId = 1;
  async function ask(action, args) {
    const id = nextId++;
    await FakeSocket.last.onmessage({ data: JSON.stringify({ id, action, args }) });
    return sent.filter((m) => m.id === id).pop();
  }
  return { ask, tabs: () => tabs, sent, historyCalls };
}

(async () => {
  let w = makeWorld();
  await new Promise((r) => setTimeout(r, 5));
  assert.strictEqual(w.sent[0].type, 'hello');

  // "close this tab" while Ultron is in front -> the last used OTHER tab (GitHub), never Ultron.
  let r = await w.ask('close', { which: 'current' });
  assert.ok(r.ok, JSON.stringify(r));
  assert.deepStrictEqual(w.tabs().map((t) => t.id), [1, 2, 3]);
  assert.ok(r.data.verified_gone);

  // Two YouTube tabs -> a question, nothing closed.
  r = await w.ask('close', { which: 'youtube' });
  assert.ok(r.data.need_choice);
  assert.strictEqual(w.tabs().length, 3);

  // Specific words pick one.
  r = await w.ask('close', { which: 'lofi youtube' });
  assert.strictEqual(r.data.closed, 1);
  assert.deepStrictEqual(w.tabs().map((t) => t.id), [1, 3]);

  // Ultron's own tab can't be closed by name or id.
  r = await w.ask('close', { which: 'ultron' });
  assert.ok(!r.ok);
  r = await w.ask('close', { which: '1' });
  assert.ok(!r.ok && /Ultron/.test(r.error));

  // "all youtube" closes every match; close_all keeps Ultron.
  w = makeWorld();
  await new Promise((r2) => setTimeout(r2, 5));
  r = await w.ask('close', { which: 'all youtube' });
  assert.strictEqual(r.data.closed, 2);
  r = await w.ask('list', {});
  assert.strictEqual(r.data.count, 1);
  assert.ok(r.data.tabs.find((t) => t.ultron));
  r = await w.ask('close_all', {});
  assert.deepStrictEqual(w.tabs().map((t) => t.id), [1]);
  assert.ok(r.data.kept_ultron);

  // switch, mute, read, unknown.
  w = makeWorld();
  await new Promise((r2) => setTimeout(r2, 5));
  r = await w.ask('switch', { which: 'github' });
  assert.strictEqual(r.data.switched_to.id, 4);
  r = await w.ask('mute', { which: 'lofi' });
  assert.ok(r.data.tabs[0].muted);
  r = await w.ask('read', { which: 'github' });
  assert.strictEqual(r.data.text, 'hello world');
  r = await w.ask('explode', {});
  assert.ok(!r.ok);
  r = await w.ask('close', { which: 'nothing like this' });
  assert.ok(!r.ok && /No open tab/.test(r.error));

  // sleep: only background, silent, awake, unpinned tabs; never Ultron / front / playing.
  w = makeWorld([
    { id: 5, windowId: 1, title: 'Gmail', url: 'https://mail.google.com/', pinned: true, lastAccessed: 10 },
    { id: 6, windowId: 1, title: 'Settings', url: 'chrome://settings/', lastAccessed: 5 },
  ]);
  await new Promise((r2) => setTimeout(r2, 5));
  r = await w.ask('sleep', { which: 'current' });
  assert.ok(r.ok, JSON.stringify(r));
  assert.strictEqual(r.data.slept, 2, JSON.stringify(r.data)); // news (3) + GitHub (4)
  const asleep = w.tabs().filter((t) => t.discarded).map((t) => t.id).sort();
  assert.deepStrictEqual(asleep, [3, 4]);   // not Ultron 1, not playing 2, not pinned 5, chrome:// 6 skipped safely
  r = await w.ask('sleep', {});
  assert.strictEqual(r.data.slept, 0);
  assert.ok(/No tab could sleep/.test(r.data.note));
  r = await w.ask('sleep', { which: 'gmail' });   // named -> pinned allowed
  assert.strictEqual(r.data.slept, 1);

  // reopen: the last closed tab comes back; by words picks the older one; never Ultron.
  w = makeWorld();
  await new Promise((r2) => setTimeout(r2, 5));
  r = await w.ask('reopen', {});
  assert.ok(!r.ok && /No recently closed/.test(r.error));
  await w.ask('close', { which: 'github' });
  await w.ask('close', { which: 'news' });
  r = await w.ask('reopen', { which: 'github tab' });
  assert.ok(r.ok, JSON.stringify(r));
  assert.ok(/GitHub/.test(r.data.reopened.title));
  r = await w.ask('reopen', { which: 'the last closed tab' });
  assert.ok(/news/.test(r.data.reopened.title));
  r = await w.ask('reopen', { which: 'ultron' });
  assert.ok(!r.ok);

  // dedupe: keeps the one in front / playing / last used; Ultron never counted.
  w = makeWorld([
    { id: 7, windowId: 1, title: 'lofi beats - YouTube', url: 'https://www.youtube.com/watch?v=a#t=5', lastAccessed: 99 },
    { id: 8, windowId: 1, title: 'dubessix/ultron-v2 - GitHub', url: 'https://github.com/dubessix/ultron-v2/', lastAccessed: 1 },
    { id: 9, windowId: 1, title: 'Ultron', url: 'http://127.0.0.1:5173/', lastAccessed: 1 },
  ]);
  await new Promise((r2) => setTimeout(r2, 5));
  r = await w.ask('dedupe', {});
  assert.strictEqual(r.data.closed, 2, JSON.stringify(r.data));
  assert.deepStrictEqual(w.tabs().map((t) => t.id).sort((a, b) => a - b), [1, 2, 3, 4, 9]); // playing 2 kept over newer 7
  r = await w.ask('dedupe', {});
  assert.strictEqual(r.data.closed, 0);

  // history: searches 90 days, one result per page, never Ultron's own pages, needs words.
  r = await w.ask('history', { which: 'the site about react hooks I saw' });
  assert.ok(r.ok, JSON.stringify(r));
  assert.strictEqual(r.data.count, 1);
  assert.strictEqual(r.data.matches[0].url, 'https://react.dev/reference/react/hooks');
  const q = w.historyCalls.pop();
  assert.strictEqual(q.text, 'react hooks');
  assert.ok(Date.now() - q.startTime > 89 * 86400000);
  r = await w.ask('history', { which: 'current' });
  assert.ok(!r.ok && /Say what the page/.test(r.error));
  r = await w.ask('history', { which: 'dinosaurs' });
  assert.strictEqual(r.data.count, 0);

  console.log('ALL OK');
})().catch((e) => { console.error(e); process.exit(1); });
