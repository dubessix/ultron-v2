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
    active: !!tab.active, audible: !!tab.audible, muted: !!(tab.mutedInfo && tab.mutedInfo.muted), asleep: !!tab.discarded,
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
  if (hits.length) return hits;
  const near = fuzzyTabs(await allTabs(), keys);
  if (near.length) return near;
  throw new Error(`No open tab matches "${which}".`);
}

// True when a and b differ by one letter (added, dropped or changed): "youtub" ~ "youtube".
function oneEditApart(a, b) {
  if (a === b) return true;
  const la = a.length, lb = b.length;
  if (la - lb > 1 || lb - la > 1) return false;
  let i = 0;
  while (i < la && i < lb && a[i] === b[i]) i += 1;
  if (la === lb) return a.slice(i + 1) === b.slice(i + 1);
  return la > lb ? a.slice(i + 1) === b.slice(i) : a.slice(i) === b.slice(i + 1);
}

function hostOf(url) {
  const m = /^[a-z]+:\/\/([^/?#]+)/i.exec(String(url || ''));
  return m ? m[1].toLowerCase() : String(url || '');
}

// A spoken name one letter off ("youtub", "githib"). Used only when nothing matched
// exactly, only for words of 4+ letters, and only when every hit is the same site,
// so a typo can never pick an unrelated tab.
function fuzzyTabs(tabs, keys) {
  if (!keys.every((k) => k.length >= 4)) return [];
  const hits = tabs.filter((t) => {
    if (isUltron(t)) return false;
    const hay = words((t.title || '') + ' ' + (t.url || ''));
    return keys.every((k) => hay.some((w) => w.length >= 4 && oneEditApart(k, w)));
  });
  const sites = new Set(hits.map((t) => hostOf(t.url)));
  return sites.size === 1 ? hits : [];
}

async function stillOpen(ids) {
  const open = new Set((await allTabs()).map((t) => t.id));
  return ids.filter((id) => open.has(id));
}

// "all", "current", "" -> every tab; otherwise the words pick tabs.
function meansAll(which) {
  const want = String(which || '').trim().toLowerCase();
  return !want || ['current', 'this', 'this tab', 'active', 'all', 'all tabs', 'tabs', 'background', 'other', 'others'].includes(want);
}

// Same page = same address without the #part and the last slash.
function samePage(url) {
  return String(url || '').split('#')[0].replace(/\/+$/, '').toLowerCase();
}

const HISTORY_DAYS = 90;

// ---------------------------------------------------------------- hands inside a page
// These run INSIDE the web page (chrome.scripting.executeScript), so each one is
// self-contained. Real DOM actions only: no OS mouse or keyboard.
// Sending, posting, buying, paying or deleting is never done without the owner's
// yes: the element's own words are checked right before the click.

const PAGE_RISKY = '\\b(send|post|publish|tweet|reply|submit|buy|purchase|pay|payment|place (your )?order|order now|checkout|check out|confirm|subscribe|donate|delete|transfer|book now|reserve)\\b';
const PAGE_MAX_ITEMS = 40;

function pageHands(action, target, text, submit, confirmed, riskySource, maxItems) {
  const SEL = 'a[href],button,input:not([type=hidden]),textarea,select,summary,[role=button],[role=link],[role=tab],' +
    '[role=menuitem],[role=checkbox],[role=switch],[role=textbox],[role=searchbox],[role=combobox],[contenteditable=""],[contenteditable=true]';
  const risky = new RegExp(riskySource, 'i');
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (el.hidden || el.disabled || el.closest('[aria-hidden="true"],[inert]')) return false;
    if (typeof el.checkVisibility === 'function') return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    const style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textTypes = ['', 'text', 'search', 'email', 'url', 'tel', 'number', 'password'];
  const kindOf = (el) => {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && type === 'password') return 'password';
    if (tag === 'textarea' || el.isContentEditable || ['textbox', 'searchbox', 'combobox'].includes(role) ||
        (tag === 'input' && textTypes.includes(type))) return 'field';
    if (tag === 'select') return 'choice';
    if ((tag === 'input' && (type === 'checkbox' || type === 'radio')) || role === 'checkbox' || role === 'switch') return 'checkbox';
    if (tag === 'a' || role === 'link') return 'link';
    return 'button';
  };
  const labelOf = (el) => {
    const kind = kindOf(el);
    const byId = el.getAttribute('aria-labelledby');
    const labelled = byId ? byId.split(/\s+/).map((id) => (document.getElementById(id) || {}).innerText || '').join(' ') : '';
    const img = el.querySelector && el.querySelector('img[alt]');
    return clean(el.getAttribute('aria-label') || labelled || (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.getAttribute('placeholder') || (kind === 'field' || kind === 'password' ? '' : (el.innerText || el.value)) ||
      el.getAttribute('title') || el.getAttribute('name') || (img && img.alt) || '').slice(0, 60);
  };
  const isSearch = (el) => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const hint = [el.getAttribute('name'), el.id, el.getAttribute('aria-label'), el.getAttribute('placeholder'),
      el.form && el.form.getAttribute('role'), el.form && el.form.getAttribute('action')].join(' ').toLowerCase();
    return type === 'search' || role === 'searchbox' || el.getAttribute('name') === 'q' || /search|find|query/.test(hint);
  };
  const all = () => Array.from(document.querySelectorAll(SEL)).filter(visible);
  const find = (want, fieldsOnly) => {
    const t = clean(want);
    if (/^\d+$/.test(t)) return document.querySelector('[data-ultron-n="' + t + '"]');
    let pool = all();
    if (fieldsOnly) pool = pool.filter((el) => ['field', 'password'].includes(kindOf(el)));
    if (!t) {
      const active = document.activeElement;
      if (fieldsOnly && active && pool.includes(active)) return active;
      return pool.find(isSearch) || pool[0] || null;
    }
    const low = t.toLowerCase();
    const named = pool.map((el) => [el, labelOf(el).toLowerCase()]);
    for (const test of [(l) => l === low, (l) => l.startsWith(low), (l) => l.includes(low)]) {
      const hit = named.find(([, l]) => l && test(l));
      if (hit) return hit[0];
    }
    return null;
  };

  if (action === 'look') {
    document.querySelectorAll('[data-ultron-n]').forEach((el) => el.removeAttribute('data-ultron-n'));
    const height = window.innerHeight || 800;
    const rows = [];
    for (const el of all()) {
      const kind = kindOf(el);
      const label = labelOf(el);
      if (!label && kind !== 'field') continue;
      const box = el.getBoundingClientRect();
      rows.push({ el, kind, label, onScreen: box.bottom > 0 && box.top < height, top: box.top });
    }
    rows.sort((a, b) => (b.onScreen - a.onScreen) || (a.top - b.top));
    const items = rows.slice(0, maxItems).map((row, i) => {
      row.el.setAttribute('data-ultron-n', String(i + 1));
      const item = { n: i + 1, kind: row.kind, text: row.label || '(no label)' };
      if (row.kind === 'field') {
        if (isSearch(row.el)) item.search = true;
        const now = clean(row.el.isContentEditable ? row.el.innerText : row.el.value);
        if (now) item.value = now.slice(0, 40);
      }
      if (row.kind === 'checkbox') item.checked = !!(row.el.checked || row.el.getAttribute('aria-checked') === 'true');
      return item;
    });
    return { title: document.title, url: location.href, items, more: Math.max(0, rows.length - items.length) };
  }

  if (action === 'scroll') {
    const up = /up|top/i.test(String(target || ''));
    if (/top|bottom/i.test(String(target || ''))) window.scrollTo(0, up ? 0 : document.body.scrollHeight);
    else window.scrollBy(0, (up ? -0.8 : 0.8) * (window.innerHeight || 800));
    const bottom = window.scrollY + (window.innerHeight || 800) >= document.body.scrollHeight - 4;
    return { scrolled: up ? 'up' : 'down', at_top: window.scrollY <= 0, at_bottom: bottom };
  }

  if (action === 'click') {
    const el = find(target, false);
    if (!el) return { error: 'No button or link matches "' + clean(target) + '" on this page. Look at the page first.' };
    const label = labelOf(el);
    const formWords = el.form && (el.type === 'submit' || kindOf(el) === 'button') ? clean(el.form.getAttribute('aria-label')) : '';
    if (!confirmed && risky.test(label + ' ' + formWords)) return { needs_yes: true, label };
    el.scrollIntoView({ block: 'center' });
    if (typeof el.focus === 'function') el.focus();
    el.click();
    return { clicked: label || '(no label)', kind: kindOf(el) };
  }

  if (action === 'type') {
    const el = find(target, true);
    if (!el) return { error: 'No text box matches "' + clean(target) + '" on this page. Look at the page first.' };
    if (kindOf(el) === 'password') return { error: 'I do not type passwords. Please type it yourself, Sir.' };
    const label = labelOf(el);
    if (submit && !confirmed && !isSearch(el)) return { needs_yes: true, label: 'send "' + clean(text).slice(0, 60) + '" in ' + (label || 'this box') };
    el.scrollIntoView({ block: 'center' });
    el.focus();
    const value = String(text || '');
    if (el.isContentEditable) {
      // execCommand is old but still the way editors (WhatsApp Web, Gmail) accept text.
      const canExec = typeof document.execCommand === 'function';
      if (canExec) document.execCommand('selectAll', false);
      if (!canExec || !document.execCommand('insertText', false, value)) el.innerText = value;
    } else {
      const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    const now = clean(el.isContentEditable ? el.innerText : el.value);
    if (now !== clean(value)) return { error: 'The page did not accept the text (it shows "' + now.slice(0, 40) + '").' };
    let sent = false;
    if (submit) {
      if (el.form && typeof el.form.requestSubmit === 'function') { el.form.requestSubmit(); sent = true; } else {
        for (const type of ['keydown', 'keypress', 'keyup']) {
          el.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
        }
        sent = true;
      }
    }
    return { typed: true, box: label || '(no label)', submitted: sent };
  }
  return { error: 'Unknown page action.' };
}

async function pageAction(action, args) {
  const [tab] = await findTabs(args.which);
  const url = String(tab.url || '');
  if (!/^(https?|file):/i.test(url)) throw new Error('Chrome does not let helpers act on this kind of page (' + url.split(':')[0] + ').');
  const [injected] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: pageHands,
    args: [action, String(args.target || ''), String(args.text || ''), !!args.submit, !!args.confirmed, PAGE_RISKY, PAGE_MAX_ITEMS],
  });
  const result = (injected && injected.result) || {};
  if (result.error) throw new Error(result.error);
  if (result.needs_yes) {
    return { done: false, needs_yes: true, label: result.label,
      note: 'This sends, posts, buys or deletes. Ask the owner; after his yes call again with confirmed=true.' };
  }
  if (action === 'click' || (action === 'type' && result.submitted)) {
    // Check what really happened: did the page change?
    await new Promise((resolve) => setTimeout(resolve, 1200));
    const after = await chrome.tabs.get(tab.id).catch(() => null);
    result.page_now = after ? { title: (after.title || '').slice(0, 80), url: (after.url || '').slice(0, 200) } : { closed: true };
    result.page_changed = !after || after.url !== tab.url || after.title !== tab.title;
  }
  return { tab: (tab.title || '').slice(0, 80), ...result };
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
    case 'sleep': {
      // Frees RAM: background tabs stay in the tab bar and reload when clicked.
      // Never the tab in front, a tab playing sound, Ultron, or (unless named) a pinned tab.
      const named = !meansAll(args.which);
      const pool = named ? await findTabs(args.which) : await allTabs();
      const picks = pool.filter((t) => !isUltron(t) && !t.active && !t.audible && !t.discarded && (named || !t.pinned));
      const slept = [];
      for (const tab of picks) {
        try {
          const done = await chrome.tabs.discard(tab.id);
          if (done && done.discarded !== false) slept.push((tab.title || '').slice(0, 60));
        } catch (e) { /* a tab Chrome won't sleep (e.g. its own pages); skip it */ }
      }
      const awake = (await allTabs()).filter((t) => !isUltron(t) && !t.discarded).length;
      return { slept: slept.length, titles: slept.slice(0, 10), still_awake: awake,
        note: slept.length ? '' : 'No tab could sleep: the rest are in front, playing sound or already asleep.' };
    }
    case 'reopen': {
      // The last closed tab (or the one whose title matches), from Chrome's own list.
      const keys = words(args.which).filter((w) => !['tab', 'tabs', 'the', 'closed', 'last', 'current', 'this', 'that', 'it', 'just', 'one', 'my'].includes(w));
      const recent = await chrome.sessions.getRecentlyClosed({ maxResults: 25 });
      const entry = recent.find((s) => {
        const tab = s.tab;
        if (!tab || isUltron(tab)) return false;
        const hay = ((tab.title || '') + ' ' + (tab.url || '')).toLowerCase();
        return keys.every((k) => hay.includes(k));
      });
      if (!entry) throw new Error(keys.length ? `No recently closed tab matches "${args.which}".` : 'No recently closed tab to reopen.');
      const back = await chrome.sessions.restore(entry.tab.sessionId);
      const tab = (back && back.tab) || entry.tab;
      return { reopened: { title: (tab.title || '').slice(0, 80), url: (tab.url || '').slice(0, 200) } };
    }
    case 'dedupe': {
      // Same page open more than once -> keep one (the one in front, playing, or last used).
      const groups = new Map();
      for (const tab of await allTabs()) {
        if (isUltron(tab) || !tab.url) continue;
        const key = samePage(tab.url);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(tab);
      }
      const drop = [];
      for (const list of groups.values()) {
        if (list.length < 2) continue;
        list.sort((a, b) => (!!b.active - !!a.active) || (!!b.audible - !!a.audible) || ((b.lastAccessed || 0) - (a.lastAccessed || 0)));
        drop.push(...list.slice(1));
      }
      const ids = drop.map((t) => t.id);
      if (ids.length) await chrome.tabs.remove(ids);
      const left = await stillOpen(ids);
      return { closed: ids.length - left.length, titles: drop.slice(0, 10).map((t) => (t.title || '').slice(0, 60)), left: left.length };
    }
    case 'history': {
      // Search Chrome history on this PC for the words said; only matches are returned.
      const keys = words(args.which).filter((w) => !['tab', 'tabs', 'the', 'site', 'page', 'website', 'current', 'this', 'that', 'about', 'saw', 'seen', 'visited', 'opened',
        'was', 'yesterday', 'today', 'earlier', 'last', 'week', 'one', 'my', 'history', 'find', 'open'].includes(w));
      if (!keys.length) throw new Error('Say what the page was about, like "react hooks".');
      const items = await chrome.history.search({ text: keys.join(' '), startTime: Date.now() - HISTORY_DAYS * 86400000, maxResults: 60 });
      const seen = new Set();
      const matches = [];
      for (const item of items) {
        const key = samePage(item.url);
        if (!item.url || seen.has(key) || isUltron({ url: item.url })) continue;
        seen.add(key);
        matches.push({ title: (item.title || '').slice(0, 80), url: item.url.slice(0, 200), last_visit: new Date(item.lastVisitTime || 0).toISOString().slice(0, 16) });
        if (matches.length >= 8) break;
      }
      return { count: matches.length, matches, note: matches.length ? 'Open one with open_new_tab.' : `Nothing in the last ${HISTORY_DAYS} days matches.` };
    }
    case 'look':
    case 'click':
    case 'type':
    case 'scroll':
      return pageAction(action, args);
    default:
      throw new Error(`Unknown browser action "${action}".`);
  }
}

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.alarms.create('ultron-reconnect', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === 'ultron-reconnect') connect(); });
connect();
