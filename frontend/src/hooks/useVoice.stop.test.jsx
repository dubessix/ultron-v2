// @vitest-environment jsdom
// V2 Step D: "stop" / "ruko" while Ultron is working.

import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useVoice from './useVoice';
import { isStopCommand, normalizeStop, requestStop } from '../stopCommand';

function speechResult(transcript, isFinal) {
  const alternatives = [{ transcript, confidence: isFinal ? 0.9 : 0.5 }];
  alternatives.isFinal = isFinal;
  return alternatives;
}

class FakeSpeechRecognition {
  static instances = [];
  constructor() { this.results = []; this.running = false; FakeSpeechRecognition.instances.push(this); }
  start() { if (this.running) throw new DOMException('x', 'InvalidStateError'); this.running = true; this.onstart?.(); }
  stop() { this.abort(); }
  abort() { const was = this.running; this.running = false; if (was) this.onend?.(); }
  changeResult(index, transcript, isFinal) {
    this.results[index] = speechResult(transcript, isFinal);
    this.onresult?.({ resultIndex: index, results: this.results });
  }
}

const rec = () => FakeSpeechRecognition.instances.at(-1);
const emit = (index, text, isFinal = true) => act(() => rec().changeResult(index, text, isFinal));
const advance = (ms) => act(() => vi.advanceTimersByTime(ms));

function renderVoice(props) {
  return renderHook(
    (p) => useVoice({ enabled: true, alwaysListen: true, ...p }),
    { initialProps: props },
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSpeechRecognition.instances = [];
  Object.defineProperty(window, 'SpeechRecognition', { configurable: true, writable: true, value: FakeSpeechRecognition });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  delete window.SpeechRecognition;
});

describe('stop words', () => {
  it('knows stop / ruko / bas / cancel, with or without his name', () => {
    for (const said of ['stop', 'Stop!', 'Ultron, stop', 'hey ultron stop it', 'ruko', 'Ruk jao.', 'bas karo',
      'cancel', 'stop please', 'Zora stop', 'रुको', 'থামো']) {
      expect(isStopCommand(said), said).toBe(true);
    }
    expect(normalizeStop('Ultron, STOP now!')).toBe('stop');
  });

  it('longer orders are NOT stop words (they go to the brain)', () => {
    for (const said of ['stop the music', 'bus stop near me', 'cancel my 5 pm meeting', 'open downloads', '', 'ultron']) {
      expect(isStopCommand(said), said).toBe(false);
    }
  });

  it('requestStop posts to /api/stop and never throws', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);
    expect(await requestStop('http://127.0.0.1:8000')).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/stop', { method: 'POST' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect(await requestStop('')).toBe(false);
    vi.unstubAllGlobals();
  });
});

describe('mic while Ultron works', () => {
  it('working (not speaking): the mic stays on and "ruko" calls onStop once, nothing is sent', () => {
    const onCommand = vi.fn();
    const onStop = vi.fn();
    const hook = renderVoice({ onCommand, onStop, paused: false, listenForStop: false });
    emit(0, 'clean my downloads');
    advance(2500);
    expect(onCommand).toHaveBeenCalledTimes(1);
    hook.rerender({ onCommand, onStop, paused: true, listenForStop: true });
    expect(rec().running).toBe(true);
    emit(1, 'what is the weather');   // ignored while working
    advance(3000);
    emit(2, 'ruko');
    emit(2, 'ruko', true);            // same word again: still one stop
    emit(3, 'stop');
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onCommand).toHaveBeenCalledTimes(1);
  });

  it('a stop word inside a longer sentence does nothing while working', () => {
    const onStop = vi.fn();
    renderVoice({ onCommand: vi.fn(), onStop, paused: true, listenForStop: true });
    emit(0, 'stop the music and open youtube');
    expect(onStop).not.toHaveBeenCalled();
  });

  it('speaking: the mic is fully off (his own voice can never stop him)', () => {
    const onStop = vi.fn();
    const hook = renderVoice({ onCommand: vi.fn(), onStop, paused: false, listenForStop: false });
    hook.rerender({ onCommand: vi.fn(), onStop, paused: true, listenForStop: false });
    expect(rec().running).toBe(false);
    advance(5000);
    expect(rec().running).toBe(false);
  });

  it('the next job can be stopped again, and after the job normal commands work', () => {
    const onCommand = vi.fn();
    const onStop = vi.fn();
    const hook = renderVoice({ onCommand, onStop, paused: true, listenForStop: true });
    emit(0, 'stop');
    hook.rerender({ onCommand, onStop, paused: false, listenForStop: false });
    emit(1, 'open spotify');
    advance(2500);
    expect(onCommand).toHaveBeenCalledWith('open spotify');
    hook.rerender({ onCommand, onStop, paused: true, listenForStop: true });
    emit(2, 'bas');
    expect(onStop).toHaveBeenCalledTimes(2);
  });
});
