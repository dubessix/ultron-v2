// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useVoice, { wakeNameOf } from './useVoice';

function speechResult(transcript, isFinal) {
  const alternatives = [{ transcript, confidence: isFinal ? 0.9 : 0.5 }];
  alternatives.isFinal = isFinal;
  return alternatives;
}

class FakeSpeechRecognition {
  static instances = [];

  constructor() {
    this.continuous = false;
    this.interimResults = false;
    this.maxAlternatives = 1;
    this.lang = '';
    this.results = [];
    this.startCount = 0;
    this.startAttempts = 0;
    this.failNextStarts = 0;
    this.abortCount = 0;
    this.running = false;
    FakeSpeechRecognition.instances.push(this);
  }

  start() {
    this.startAttempts += 1;
    if (this.failNextStarts > 0) {
      this.failNextStarts -= 1;
      throw new DOMException('Recognition start failed', 'InvalidStateError');
    }
    if (this.running) throw new DOMException('Recognition already started', 'InvalidStateError');
    this.running = true;
    this.startCount += 1;
    this.onstart?.();
  }

  stop() { this.abort(); }

  abort() {
    this.abortCount += 1;
    const wasRunning = this.running;
    this.running = false;
    if (wasRunning) this.onend?.();
  }

  changeResult(index, transcript, isFinal) {
    this.results[index] = speechResult(transcript, isFinal);
    this.onresult?.({ resultIndex: index, results: this.results });
  }

  beginFreshBrowserSession() {
    this.results = [];
    this.running = false;
    this.onend?.();
  }

  emitError(error) {
    this.onerror?.({ error });
  }
}

function latestRecognizer() {
  const instance = FakeSpeechRecognition.instances.at(-1);
  if (!instance) throw new Error('SpeechRecognition was not created');
  return instance;
}

function emit(recognizer, index, transcript, isFinal = true) {
  act(() => recognizer.changeResult(index, transcript, isFinal));
}

function advance(milliseconds) {
  act(() => vi.advanceTimersByTime(milliseconds));
}

function renderVoice(onCommand = vi.fn(), extra = {}) {
  return renderHook(
    ({ callback, enabled, paused, activePersonality }) => useVoice({ onCommand: callback, enabled, paused, activePersonality }),
    {
      initialProps: { callback: onCommand, enabled: true, paused: false, ...extra },
    },
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSpeechRecognition.instances = [];
  Object.defineProperty(window, 'SpeechRecognition', { configurable: true, writable: true, value: FakeSpeechRecognition });
  Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, writable: true, value: undefined });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete window.SpeechRecognition;
  delete window.webkitSpeechRecognition;
});

describe('Zora wake word and the personality switch (V2 Step 3)', () => {
  it('Hey Zora while Ultron is active hands the command to Zora', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, { activePersonality: 'ultron' });
    emit(latestRecognizer(), 0, "Hey Zora, I'm really tired today");
    advance(2400);
    expect(onCommand).toHaveBeenCalledWith("Zora, I'm really tired today");
  });

  it('calling the personality who is already active adds nothing', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, { activePersonality: 'zora' });
    emit(latestRecognizer(), 0, 'Hey Zora, play some music');
    advance(2400);
    expect(onCommand).toHaveBeenCalledWith('play some music');
  });

  it('Ultron wake word while Zora is active brings Ultron back', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, { activePersonality: 'zora' });
    emit(latestRecognizer(), 0, 'Ultron open my downloads folder');
    advance(2400);
    expect(onCommand).toHaveBeenCalledWith('Ultron, open my downloads folder');
  });

  it('just "Hey Zora" switches after the wake wait so she can greet him', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, { activePersonality: 'ultron' });
    emit(latestRecognizer(), 0, 'Hey Zora');
    advance(5999);
    expect(onCommand).not.toHaveBeenCalled();
    advance(1);
    expect(onCommand).toHaveBeenCalledWith('Hey Zora');
  });

  it('bare Ultron with Ultron active is still wake-only', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand, { activePersonality: 'ultron' });
    emit(latestRecognizer(), 0, 'Ultron');
    advance(7000);
    expect(onCommand).not.toHaveBeenCalled();
  });

  it('ordinary words that sound similar never wake anyone', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    emit(latestRecognizer(), 0, 'Zara is my friend from college');
    emit(latestRecognizer(), 1, 'I watched a Sora video');
    advance(7000);
    expect(onCommand).not.toHaveBeenCalled();
  });

  it('maps heard phrases to names', () => {
    expect(wakeNameOf('hey zorah')).toBe('zora');
    expect(wakeNameOf('hey sora')).toBe('zora');
    expect(wakeNameOf('altron')).toBe('ultron');
    expect(wakeNameOf('wake up')).toBe(null);
  });
});
