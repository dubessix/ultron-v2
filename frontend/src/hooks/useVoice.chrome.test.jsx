// @vitest-environment jsdom
// Owner: "since the infinity button, it forgets to hear". The old fakes start and
// stop INSTANTLY, so timing bugs could never show. This fake behaves like real
// Chrome: start() and abort() finish LATER, start() while starting/stopping
// throws InvalidStateError, every session has a fresh result list, silence ends
// a session with no-speech. We replay a real day through the real hook.

import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useVoice, { NO_SOUND_HINT_MS } from './useVoice';

const START_MS = 250;
const STOP_MS = 200;
const SILENCE_END_MS = 8000;

class ChromeLikeRecognition {
  static instances = [];

  constructor() {
    this.state = 'idle';
    this.results = [];
    this.silence = null;
    ChromeLikeRecognition.instances.push(this);
  }

  start() {
    if (this.state !== 'idle') throw new DOMException('recognition has already started', 'InvalidStateError');
    this.state = 'starting';
    setTimeout(() => {
      if (this.state !== 'starting') return;
      this.state = 'running';
      this.results = [];
      this.onstart?.();
      this.armSilence();
    }, START_MS);
  }

  armSilence() {
    clearTimeout(this.silence);
    this.silence = setTimeout(() => {
      if (this.state !== 'running') return;
      this.onerror?.({ error: 'no-speech' });
      this.finish();
    }, SILENCE_END_MS);
  }

  finish() {
    clearTimeout(this.silence);
    this.state = 'stopping';
    setTimeout(() => { this.state = 'idle'; this.onend?.(); }, STOP_MS);
  }

  abort() {
    if (this.state === 'idle' || this.state === 'stopping') return;
    const wasStarting = this.state === 'starting';
    clearTimeout(this.silence);
    this.state = 'stopping';
    setTimeout(() => {
      this.state = 'idle';
      if (!wasStarting) this.onerror?.({ error: 'aborted' });
      this.onend?.();
    }, STOP_MS);
  }

  stop() { this.abort(); }

  // He speaks: interim words, then the final result.
  say(text) {
    if (this.state !== 'running') return false;
    const index = this.results.length;
    const words = text.split(' ');
    for (let n = 1; n <= words.length; n += 1) {
      const alt = [{ transcript: words.slice(0, n).join(' '), confidence: 0.8 }];
      alt.isFinal = n === words.length;
      this.results[index] = alt;
      this.onresult?.({ resultIndex: index, results: this.results });
    }
    this.armSilence();
    return true;
  }
}

const mic = () => ChromeLikeRecognition.instances.at(-1);
const wait = (ms) => act(() => { vi.advanceTimersByTime(ms); });

beforeEach(() => {
  vi.useFakeTimers();
  ChromeLikeRecognition.instances = [];
  Object.defineProperty(window, 'SpeechRecognition', { configurable: true, writable: true, value: ChromeLikeRecognition });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  delete window.SpeechRecognition;
});

function day({ alwaysListen }) {
  const heard = [];
  const hook = renderHook((p) => useVoice({ enabled: true, alwaysListen, onCommand: (c) => heard.push(c), ...p }), {
    initialProps: { paused: false, listenForStop: false },
  });
  // Like App.jsx: a command -> working (mic listens for stop) -> speaking (mic off) -> idle.
  const reply = async ({ workMs = 1500, speakMs = 2500 } = {}) => {
    hook.rerender({ paused: true, listenForStop: true });
    await wait(workMs);
    hook.rerender({ paused: true, listenForStop: false });
    await wait(speakMs);
    hook.rerender({ paused: false, listenForStop: false });
  };
  // He talks only when Chrome is really listening (like a person would retry).
  const speak = async (text) => {
    for (let tries = 0; tries < 40 && !mic().say(text); tries += 1) await wait(250);
    await wait(3000);
  };
  return { heard, hook, reply, speak };
}

describe('real Chrome timing, a whole day', () => {
  for (const alwaysListen of [true, false]) {
    const name = alwaysListen ? 'infinity ON' : 'infinity OFF (wake word)';
    const cmd = (text) => (alwaysListen ? text : `Ultron ${text}`);

    it(`${name}: ten commands in a row, each one heard`, async () => {
      const { heard, reply, speak, hook } = day({ alwaysListen });
      await wait(START_MS + 10);
      for (let n = 1; n <= 10; n += 1) {
        await speak(cmd(`open item number ${n}`));
        expect(heard.length, `command ${n} was not heard`).toBe(n);
        await reply({ workMs: 300 + n * 137, speakMs: n % 3 === 0 ? 50 : 1800 });
        await wait(n % 2 ? 100 : 12000); // sometimes he answers fast, sometimes stays quiet
      }
      expect(hook.result.current.voiceError).toBe('');
      expect(heard.at(-1)).toBe('open item number 10');
    });

    it(`${name}: very short replies (speaking ends before Chrome finished stopping)`, async () => {
      const { heard, reply, speak } = day({ alwaysListen });
      await wait(START_MS + 10);
      for (let n = 1; n <= 6; n += 1) {
        await speak(cmd(`say number ${n}`));
        await reply({ workMs: 20, speakMs: 30 });
      }
      expect(heard).toHaveLength(6);
    });

    it(`${name}: a spoken reminder while idle does not kill the mic`, async () => {
      const { heard, hook, speak } = day({ alwaysListen });
      await wait(START_MS + 10);
      for (let n = 0; n < 5; n += 1) {
        hook.rerender({ paused: true, listenForStop: false }); // heads up is spoken
        await wait(40 + n * 90);
        hook.rerender({ paused: false, listenForStop: false });
        await wait(30);
      }
      await speak(cmd('what time is it'));
      expect(heard).toEqual(['what time is it']);
    });

    it(`${name}: long silence (many Chrome no-speech restarts) then a command`, async () => {
      const { heard, speak, hook } = day({ alwaysListen });
      await wait(10 * 60 * 1000);
      await speak(cmd('open downloads'));
      expect(heard).toEqual(['open downloads']);
      expect(hook.result.current.voiceError).toBe('');
    });
  }

  it('reload with infinity remembered ON: the hook alone does not start the mic (AppShell decides)', async () => {
    const { heard } = day({ alwaysListen: true });
    await wait(START_MS + 10);
    expect(heard).toEqual([]);
  });

  it('mic hears nothing for 20 s: a clear hint, gone at the first sound', async () => {
    const { hook, speak, heard } = day({ alwaysListen: true });
    await wait(NO_SOUND_HINT_MS - 1000);
    expect(hook.result.current.noSound).toBe(false);
    await wait(2000);
    expect(hook.result.current.noSound).toBe(true);
    await speak('open downloads');
    expect(hook.result.current.noSound).toBe(false);
    expect(heard).toEqual(['open downloads']);
  });

  it('a sound (not words yet) also proves the mic works', async () => {
    const { hook } = day({ alwaysListen: true });
    await wait(START_MS + 10);
    act(() => { mic().onsoundstart?.(); });
    await wait(NO_SOUND_HINT_MS * 3);
    expect(hook.result.current.noSound).toBe(false);
  });

  it('no hint while Ultron is talking', async () => {
    const { hook } = day({ alwaysListen: true });
    hook.rerender({ paused: true, listenForStop: false });
    await wait(NO_SOUND_HINT_MS * 2);
    expect(hook.result.current.noSound).toBe(false);
  });

  it('after a mic error, retry listens again with one click', async () => {
    const { hook, speak, heard } = day({ alwaysListen: true });
    await wait(START_MS + 10);
    act(() => { mic().onerror?.({ error: 'not-allowed' }); });
    await wait(1000);
    expect(hook.result.current.voiceError).toMatch(/Microphone is blocked/);
    act(() => { hook.result.current.retry(); });
    await wait(START_MS + 10);
    expect(hook.result.current.voiceError).toBe('');
    await speak('what time is it');
    expect(heard).toEqual(['what time is it']);
  });
});
