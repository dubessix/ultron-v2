// @vitest-environment jsdom
// Infinity button: continuous listening with no wake word. Off = old behaviour.

import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useVoice, { isFillerOnly } from './useVoice';

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

function renderVoice(onCommand, alwaysListen) {
  return renderHook(
    ({ always }) => useVoice({ onCommand, enabled: true, paused: false, alwaysListen: always }),
    { initialProps: { always: alwaysListen } },
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

describe('Infinity mode — keep listening without "Ultron"', () => {
  it('sends a command with no wake word when infinity is on', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, true);
    emit(0, 'open spotify');
    advance(2500);
    expect(onCommand).toHaveBeenCalledWith('open spotify');
  });

  it('keeps listening: every next sentence is a new command', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, true);
    emit(0, 'open spotify');
    advance(2500);
    emit(1, 'play lofi music');
    advance(2500);
    emit(2, 'volume down');
    advance(2500);
    expect(onCommand.mock.calls.map((c) => c[0])).toEqual(['open spotify', 'play lofi music', 'volume down']);
  });

  it('still strips the name when he says it anyway', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, true);
    emit(0, 'Ultron open calendar');
    advance(2500);
    expect(onCommand).toHaveBeenCalledWith('open calendar');
  });

  it('still switches to Zora when he calls her', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, true);
    emit(0, 'hey Zora I am tired');
    advance(2500);
    expect(onCommand).toHaveBeenCalledWith('Zora, I am tired');
  });

  it('ignores lone filler sounds (no wasted AI call)', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, true);
    emit(0, 'hmm');
    advance(3000);
    emit(1, 'uh');
    advance(3000);
    expect(onCommand).not.toHaveBeenCalled();
    expect(isFillerOnly('Hmm...')).toBe(true);
    expect(isFillerOnly('hmm open music')).toBe(false);
  });

  it('infinity off = exactly as before: speech without the wake word is ignored', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, false);
    emit(0, 'open spotify');
    advance(5000);
    expect(onCommand).not.toHaveBeenCalled();
    emit(1, 'Ultron open spotify');
    advance(2500);
    expect(onCommand).toHaveBeenCalledWith('open spotify');
  });

  it('turning infinity off mid-session goes back to wake-word mode', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand, true);
    emit(0, 'open spotify');
    advance(2500);
    hook.rerender({ always: false });
    emit(1, 'next song');
    advance(5000);
    expect(onCommand).toHaveBeenCalledTimes(1);
  });
});
