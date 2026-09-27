// @vitest-environment jsdom
// Final list step 4: Ultron's hands inside a web page (extension/chrome/background.js).
// The page code runs here the way Chrome runs it: from the function's own source
// text inside the page, so it must be self-contained.
import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const source = fs.readFileSync(path.resolve(__dirname, '../../extension/chrome/background.js'), 'utf8');

// jsdom has no layout: give it innerText / isContentEditable like Chrome.
Object.defineProperty(window.HTMLElement.prototype, 'innerText', {
  configurable: true,
  get() { return this.textContent; },
  set(v) { this.textContent = v; },
});
Object.defineProperty(window.HTMLElement.prototype, 'isContentEditable', {
  configurable: true,
  get() { return this.getAttribute('contenteditable') === 'true' || this.getAttribute('contenteditable') === ''; },
});

const PAGE = `
  <form id="search" action="/s" role="search"><input name="q" placeholder="Search Amazon"><button type="submit">Go</button></form>
  <a href="/cable">USB C cable, 2 m</a>
  <button id="cart">Add to cart</button>
  <button id="buy">Buy now</button>
  <button style="display:none">Hidden thing</button>
  <label for="pw">Password</label><input id="pw" type="password">
  <textarea aria-label="Message"></textarea>
  <div contenteditable="true" aria-label="Chat box"></div>`;

function world() {
  const clicks = [];
  let submits = 0;
  document.body.innerHTML = PAGE;
  document.getElementById('search').addEventListener('submit', (e) => { e.preventDefault(); submits += 1; });
  document.querySelectorAll('button, a').forEach((el) => el.addEventListener('click', (e) => { e.preventDefault(); clicks.push(el.textContent); }));
  window.scrollTo = () => {};
  window.scrollBy = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
  const tab = { id: 7, windowId: 1, title: 'Amazon.in', url: 'https://www.amazon.in/', active: true };
  const noop = { addListener() {} };
  const chrome = {
    runtime: { getManifest: () => ({ version: '1.2.0' }), onStartup: noop, onInstalled: noop },
    alarms: { create() {}, onAlarm: noop },
    tabs: { query: async () => [tab], get: async () => tab },
    scripting: {
      // Chrome serializes func and runs it in the page: do exactly that.
      executeScript: async ({ func, args }) => [{ result: window.eval(`(${func.toString()})`)(...args) }],
    },
  };
  class FakeSocket { constructor() { this.readyState = 1; FakeSocket.last = this; } send(t) { sent.push(JSON.parse(t)); } }
  FakeSocket.OPEN = 1; FakeSocket.CONNECTING = 0;
  const sent = [];
  const fastTimeout = (fn) => setTimeout(fn, 0);
  const context = { chrome, WebSocket: FakeSocket, setTimeout: fastTimeout, clearInterval, setInterval: () => 0, console, JSON, String, Number, Array, Set, Map, Error, Date, Promise, Object };
  vm.createContext(context);
  vm.runInContext(source, context);
  let id = 1;
  async function ask(action, args) {
    const n = id++;
    await FakeSocket.last.onmessage({ data: JSON.stringify({ id: n, action, args }) });
    return sent.filter((m) => m.id === n).pop();
  }
  return { ask, clicks, submits: () => submits, tab };
}

describe('browser page hands', () => {
  let w;
  beforeEach(() => { w = world(); });

  it('look lists visible items with numbers and marks the search box', async () => {
    const r = await w.ask('look', { which: 'current' });
    expect(r.ok).toBe(true);
    const texts = r.data.items.map((i) => i.text);
    expect(texts).toContain('Buy now');
    expect(texts).not.toContain('Hidden thing');
    const box = r.data.items.find((i) => i.text === 'Search Amazon');
    expect(box.kind).toBe('field');
    expect(box.search).toBe(true);
    expect(r.data.items.find((i) => i.text === 'Password').kind).toBe('password');
    expect(r.data.items.map((i) => i.n)).toEqual(r.data.items.map((_, k) => k + 1));
  });

  it('clicks a normal button by number and reports the page after', async () => {
    const look = await w.ask('look', {});
    const cart = look.data.items.find((i) => i.text === 'Add to cart');
    const r = await w.ask('click', { target: String(cart.n) });
    expect(r.ok).toBe(true);
    expect(r.data.clicked).toBe('Add to cart');
    expect(w.clicks).toEqual(['Add to cart']);
    expect(r.data.page_now.url).toBe('https://www.amazon.in/');
  });

  it('never presses Buy without the yes, then presses it with confirmed', async () => {
    let r = await w.ask('click', { target: 'buy now' });
    expect(r.ok).toBe(true);
    expect(r.data.needs_yes).toBe(true);
    expect(r.data.label).toBe('Buy now');
    expect(w.clicks).toEqual([]);
    r = await w.ask('click', { target: 'buy now', confirmed: true });
    expect(r.data.clicked).toBe('Buy now');
    expect(w.clicks).toEqual(['Buy now']);
  });

  it('types into the search box and submits without asking', async () => {
    const r = await w.ask('type', { target: 'search', text: 'usb c cable', submit: true });
    expect(r.ok).toBe(true);
    expect(r.data.typed).toBe(true);
    expect(r.data.submitted).toBe(true);
    expect(document.querySelector('[name=q]').value).toBe('usb c cable');
    expect(w.submits()).toBe(1);
  });

  it('typing a message and sending it needs the yes; typing alone does not', async () => {
    let r = await w.ask('type', { target: 'message', text: 'Hi Riya', submit: true });
    expect(r.data.needs_yes).toBe(true);
    expect(document.querySelector('textarea').value).toBe('');
    r = await w.ask('type', { target: 'message', text: 'Hi Riya' });
    expect(r.data.typed).toBe(true);
    expect(r.data.submitted).toBe(false);
    expect(document.querySelector('textarea').value).toBe('Hi Riya');
  });

  it('types into a rich chat box (contenteditable)', async () => {
    const r = await w.ask('type', { target: 'chat box', text: 'on my way' });
    expect(r.ok).toBe(true);
    expect(document.querySelector('[contenteditable]').textContent).toBe('on my way');
  });

  it('refuses passwords and unknown targets honestly', async () => {
    let r = await w.ask('type', { target: 'password', text: 'secret' });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/do not type passwords/);
    expect(document.getElementById('pw').value).toBe('');
    r = await w.ask('click', { target: 'checkout with paypal' });
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/No button or link matches/);
  });

  it('scrolls and refuses chrome:// pages', async () => {
    let r = await w.ask('scroll', { target: 'down' });
    expect(r.data.scrolled).toBe('down');
    w.tab.url = 'chrome://settings/';
    r = await w.ask('look', {});
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/does not let helpers act/);
  });
});
