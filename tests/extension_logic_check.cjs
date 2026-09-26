// Runs extension/chrome/background.js with a fake chrome API and checks the
// tab rules (used by tests/test_v2_step_c_extension.py). Prints "ALL OK".
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(path.join(__dirname, '..', 'extension', 'chrome', 'background.js'), 'utf8');

function makeWorld() {
  let tabs = [
    { id: 1, windowId: 1, title: 'Ultron', url: 'http://127.0.0.1:5173/', active: true, lastAccessed: 50 },
    { id: 2, windowId: 1, title: 'lofi beats - YouTube', url: 'https://www.youtube.com/watch?v=a', active: false, lastAccessed: 40, audible: true },
    { id: 3, windowId: 1, title: 'news today - YouTube', url: 'https://www.youtube.com/watch?v=b', active: false, lastAccessed: 30 },
    { id: 4, windowId: 1, title: 'dubessix/ultron-v2 - GitHub', url: 'https://github.com/dubessix/ultron-v2', active: false, lastAccessed: 45 },
  ];
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
    scripting: { executeScript: async ({ target }) => [{ result: { title: 'page ' + target.tabId, text: 'hello   world' } }] },
    tabs: {
      query: async (q) => (q.active ? tabs.filter((t) => t.active) : tabs.slice()),
      get: async (id) => { const t = tabs.find((x) => x.id === id); if (!t) throw new Error('No tab'); return t; },
      remove: async (ids) => { const drop = new Set([].concat(ids)); tabs = tabs.filter((t) => !drop.has(t.id)); },
      update: async (id, props) => { const t = tabs.find((x) => x.id === id); Object.assign(t, props, props.muted !== undefined ? { mutedInfo: { muted: props.muted } } : {}); if (props.active) tabs.forEach((x) => { if (x.id !== id) x.active = false; }); return t; },
      create: async ({ url }) => { const t = { id: 99, windowId: 1, title: '', url }; tabs.push(t); return t; },
      reload: async () => {}, goBack: async () => {}, goForward: async () => {},
    },
  };
  const context = { chrome, WebSocket: FakeSocket, setTimeout, clearInterval, setInterval: () => 0, console, JSON, String, Number, Array, Set, Error };
  vm.createContext(context);
  vm.runInContext(source, context);
  let nextId = 1;
  async function ask(action, args) {
    const id = nextId++;
    await FakeSocket.last.onmessage({ data: JSON.stringify({ id, action, args }) });
    return sent.filter((m) => m.id === id).pop();
  }
  return { ask, tabs: () => tabs, sent };
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

  console.log('ALL OK');
})().catch((e) => { console.error(e); process.exit(1); });
