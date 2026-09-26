// Ultron Browser Hands: real tab control for YOUR Ultron on this PC only.
// Connects to ws://127.0.0.1:8000/ws/browser (the server only accepts this
// extension's own id). Does exactly what Ultron asks with chrome.tabs, replies
// with the checked result, and never touches Ultron's own tab.

const SERVER = 'ws://127.0.0.1:8000/ws/browser';
const VERSION = chrome.runtime.getManifest().version;
let socket = null;
let pingTimer = null;
let ultronOrigins = ['http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8000', 'http://localhost:8000'];

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  try {
    socket = new WebSocket(SERVER);
  } catch (e) {
    socket = null;
    return;
  }
  socket.onopen = () => {
    socket.send(JSON.stringify({ type: 'hello', version: VERSION }));
    clearInterval(pingTimer);
    // Traffic every 20 s keeps the service worker alive (Chrome 116+).
    pingTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }));
    }, 20000);
  };
  socket.onmessage = (event) => onMessage(event.data);
  socket.onclose = () => {
    clearInterval(pingTimer);
    socket = null;
    setTimeout(connect, 5000); // Ultron restarted or not running yet
  };
  socket.onerror = () => {};
}

async function onMessage(raw) {
  let msg;
  try { msg = JSON.parse(raw); } catch (e) { return; }
  if (msg.type === 'config') {
    if (Array.isArray(msg.ultron_origins) && msg.ultron_origins.length) ultronOrigins = msg.ultron_origins;
    return;
  }
  if (typeof msg.id !== 'number' || typeof msg.action !== 'string') return;
  let reply;
  try {
    reply = { type: 'reply', id: msg.id, ok: true, data: await run(msg.action, msg.args || {}) };
  } catch (e) {
    reply = { type: 'reply', id: msg.id, ok: false, error: String((e && e.message) || e).slice(0, 300) };
  }
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(reply));
}

// ---------------------------------------------------------------- helpers

function isUltron(tab) {
  const url = tab.url || tab.pendingUrl || '';
  return ultronOrigins.some((origin) => url === origin || url.startsWith(origin + '/'));
}

function brief(tab) {
  return {
    id: tab.id, title: (tab.title || '').slice(0, 80), url: (tab.url || '').slice(0, 200),
    active: !!tab.active, audible: !!tab.audible, muted: !!(tab.mutedInfo && tab.mutedInfo.muted),
    ultron: isUltron(tab),
  };
}

async function allTabs() {
  return chrome.tabs.query({});
}

// "Current tab" = the tab the owner is looking at, but never Ultron's own:
// if Ultron's tab is in front, it is the last used other tab.
async function currentTab() {
  const [front] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (front && !isUltron(front)) return front;
  const others = (await allTabs()).filter((t) => !isUltron(t));
  if (!others.length) throw new Error('No browser tab is open except Ultron.');
  others.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
  return others[0];
}

function words(text) {
  return String(text || '').toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 1);
}

// Find tabs by what the owner said: "youtube", "the github one", a tab id.
async function findTabs(which) {
  const want = String(which || '').trim().toLowerCase();
  if (!want || ['current', 'this', 'this tab', 'active', 'that', 'it'].includes(want)) return [await currentTab()];
  if (/^\d+$/.test(want)) {
    const tab = await chrome.tabs.get(Number(want));
    if (isUltron(tab)) throw new Error("That is Ultron's own tab.");
    return [tab];
  }
  const keys = words(want).filter((w) => !['tab', 'tabs', 'the', 'one', 'all', 'my', 'page'].includes(w));
  if (!keys.length) return [await currentTab()];
  const hits = (await allTabs()).filter((t) => {
    if (isUltron(t)) return false;
    const hay = ((t.title || '') + ' ' + (t.url || '')).toLowerCase();
    return keys.every((k) => hay.includes(k));
  });
  if (!hits.length) throw new Error(`No open tab matches "${which}".`);
  return hits;
}

async function stillOpen(ids) {
  const open = new Set((await allTabs()).map((t) => t.id));
  return ids.filter((id) => open.has(id));
}

// ---------------------------------------------------------------- actions

async function run(action, args) {
  switch (action) {
    case 'list': {
      const tabs = await allTabs();
      return { count: tabs.filter((t) => !isUltron(t)).length, tabs: tabs.slice(0, 50).map(brief) };
    }
    case 'close': {
      const tabs = await findTabs(args.which);
      const many = tabs.length > 1 && !/\ball\b/.test(String(args.which || '').toLowerCase());
      if (many) {
        return { closed: 0, need_choice: true, matches: tabs.slice(0, 8).map(brief),
          note: `${tabs.length} tabs match. Say which one, or say "all".` };
      }
      const ids = tabs.map((t) => t.id);
      await chrome.tabs.remove(ids);
      const left = await stillOpen(ids);
      if (left.length) throw new Error('The tab did not close (it may be asking to leave the page).');
      return { closed: ids.length, titles: tabs.map((t) => (t.title || '').slice(0, 60)), verified_gone: true };
    }
    case 'close_all': {
      const tabs = (await allTabs()).filter((t) => !isUltron(t));
      const ids = tabs.map((t) => t.id);
      if (ids.length) await chrome.tabs.remove(ids);
      const left = await stillOpen(ids);
      return { closed: ids.length - left.length, left: left.length, kept_ultron: true };
    }
    case 'switch': {
      const [tab] = await findTabs(args.which);
      await chrome.tabs.update(tab.id, { active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      return { switched_to: brief(tab) };
    }
    case 'new': {
      const tab = await chrome.tabs.create({ url: args.url || 'chrome://newtab/' });
      return { opened: brief(tab) };
    }
    case 'reload':
    case 'back':
    case 'forward': {
      const [tab] = await findTabs(args.which);
      if (action === 'reload') await chrome.tabs.reload(tab.id);
      else if (action === 'back') await chrome.tabs.goBack(tab.id);
      else await chrome.tabs.goForward(tab.id);
      return { done: action, tab: brief(tab) };
    }
    case 'mute':
    case 'unmute': {
      const tabs = await findTabs(args.which);
      for (const tab of tabs) await chrome.tabs.update(tab.id, { muted: action === 'mute' });
      return { done: action, tabs: tabs.map(brief) };
    }
    case 'read': {
      const [tab] = await findTabs(args.which);
      const [result] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => ({ title: document.title, text: (document.body ? document.body.innerText : '').slice(0, 20000) }),
      });
      const page = (result && result.result) || {};
      return { title: page.title || tab.title, url: tab.url, text: String(page.text || '').replace(/\s+/g, ' ').trim() };
    }
    default:
      throw new Error(`Unknown browser action "${action}".`);
  }
}

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.alarms.create('ultron-reconnect', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === 'ultron-reconnect') connect(); });
connect();
