// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useVoice from './useVoice';

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
    ({ callback, enabled, paused }) => useVoice({ onCommand: callback, enabled, paused }),
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

describe('Voice Option A — wake phrase and one complete command', () => {
  it('treats Ultron alone as wake-only and never sends it to the backend', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');

    expect(onCommand).not.toHaveBeenCalled();
    expect(hook.result.current.wakeDetected).toBe(true);
    expect(hook.result.current.conversationActive).toBe(true);
    advance(5999);
    expect(onCommand).not.toHaveBeenCalled();
  });

  it('treats Ultron wake up and wake up Ultron as wake-only phrases', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron wake up');
    expect(onCommand).not.toHaveBeenCalled();
    expect(hook.result.current.wakeDetected).toBe(true);

    emit(recognition, 1, 'open calendar');
    advance(2000);
    expect(onCommand).toHaveBeenCalledWith('open calendar');

    emit(recognition, 2, 'wake up Ultron');
    expect(onCommand).toHaveBeenCalledTimes(1);
  });

  it('does not treat Electron, activate, or ordinary speech as a wake phrase', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Electron open settings');
    emit(recognition, 1, 'activate open settings');
    emit(recognition, 2, 'open settings');
    advance(5000);

    expect(onCommand).not.toHaveBeenCalled();
  });

  it('waits for silence even when the browser marks a same-utterance command final', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Hey Ultron, open the calendar', true);
    expect(onCommand).not.toHaveBeenCalled();
    advance(1799);
    expect(onCommand).not.toHaveBeenCalled();
    advance(1);

    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('open the calendar');
  });

  it('keeps listening across a mid-sentence pause and sends the complete command once', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron create a task', true);
    advance(1000);
    expect(onCommand).not.toHaveBeenCalled();

    emit(recognition, 1, 'for tomorrow morning', true);
    advance(1799);
    expect(onCommand).not.toHaveBeenCalled();
    advance(1);

    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('create a task for tomorrow morning');
  });

  it('gives a long command the extended completion window before dispatching', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron, create a task named finish my project documentation tomorrow morning', true);
    advance(2399);
    expect(onCommand).not.toHaveBeenCalled();
    advance(1);

    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith(
      'create a task named finish my project documentation tomorrow morning',
    );
  });

  it('replaces overlapping interim hypotheses instead of growing open open open', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');
    emit(recognition, 1, 'open', false);
    emit(recognition, 1, 'open VS', false);
    emit(recognition, 1, 'open VS Code', true);

    expect(hook.result.current.heardText).toBe('open VS Code');
    advance(1800);
    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('open VS Code');
  });

  it('returns to wake-only mode after one command; a follow-up without Ultron is ignored', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron open calendar');
    advance(2000);
    expect(onCommand).toHaveBeenCalledWith('open calendar');
    expect(hook.result.current.conversationActive).toBe(false);

    emit(recognition, 1, 'show git status');
    advance(5000);
    expect(onCommand).toHaveBeenCalledTimes(1);
  });
});

describe('Voice Option A — resilience and honest lifecycle', () => {
  it('preserves a partial command across an unexpected browser end and merges the continuation once', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');
    emit(recognition, 1, 'create a task', false);
    recognition.beginFreshBrowserSession();
    advance(500);
    expect(recognition.startCount).toBe(2);

    emit(recognition, 0, 'for tomorrow', true);
    advance(1800);
    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('create a task for tomorrow');
  });

  it('cancels the unfinished turn when Stop Mic is pressed', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');
    emit(recognition, 1, 'unfinished command', false);
    hook.rerender({ callback: onCommand, enabled: false, paused: false });
    advance(5000);

    expect(onCommand).not.toHaveBeenCalled();
    expect(hook.result.current.conversationActive).toBe(false);
  });

  it('does not send browser audio while processing or TTS is paused, then resumes wake-only listening', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    hook.rerender({ callback: onCommand, enabled: true, paused: true });
    emit(recognition, 0, 'Ultron open settings');
    expect(onCommand).not.toHaveBeenCalled();

    hook.rerender({ callback: onCommand, enabled: true, paused: false });
    emit(recognition, 0, 'Ultron open settings');
    advance(2000);
    expect(onCommand).toHaveBeenCalledWith('open settings');
  });

  it('restarts silently after no-speech and reports true fatal microphone failures', () => {
    const hook = renderVoice();
    const recognition = latestRecognizer();

    act(() => recognition.emitError('no-speech'));
    recognition.beginFreshBrowserSession();
    advance(500);
    expect(recognition.startCount).toBe(2);

    act(() => recognition.emitError('not-allowed'));
    advance(5000);
    expect(hook.result.current.voiceError).toMatch(/^Microphone is blocked/);
    expect(hook.result.current.isListening).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Real-browser behaviour: Chrome/Edge rarely spell "Ultron" right and a
// browser without a speech service fails with endless network errors.
// ---------------------------------------------------------------------------
function emitAlternatives(recognizer, index, transcripts, isFinal = true) {
  const alternatives = transcripts.map((transcript) => ({ transcript, confidence: 0.6 }));
  alternatives.isFinal = isFinal;
  act(() => {
    recognizer.results[index] = alternatives;
    recognizer.onresult?.({ resultIndex: index, results: recognizer.results });
  });
}

describe('Listening fix — misheard wake words (real Chrome output)', () => {
  it.each([
    ['Hey Altron, open the calendar'],
    ['ultran open the calendar'],
    ['Ultra open the calendar'],
    ['alton, open the calendar'],
    ['all tron open the calendar'],
    ['OK Ultron open the calendar'],
  ])('wakes on "%s" and sends only the command', (heard) => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    emit(latestRecognizer(), 0, heard);
    advance(2000);
    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('open the calendar');
  });

  it('checks every browser alternative, not only the first guess', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    emitAlternatives(latestRecognizer(), 0, ['old run open the calendar', 'Ultron open the calendar']);
    advance(2000);
    expect(onCommand).toHaveBeenCalledWith('open the calendar');
  });

  it('never wakes on "ultra" in the middle of normal speech', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    emit(latestRecognizer(), 0, 'I bought an ultra wide monitor');
    advance(5000);
    expect(onCommand).not.toHaveBeenCalled();
    expect(hook.result.current.wakeDetected).toBe(false);
  });
});

describe('Listening fix — no endless "reconnecting" loop', () => {
  it('stops with a clear browser message after repeated network errors', () => {
    const hook = renderVoice();
    const recognition = latestRecognizer();
    for (let attempt = 0; attempt < 3; attempt += 1) {
      act(() => recognition.emitError('network'));
      advance(5000);
    }
    expect(hook.result.current.isListening).toBe(false);
    expect(hook.result.current.voiceError).toMatch(/Chrome or Microsoft Edge/);
    const starts = recognition.startAttempts;
    advance(20000);
    expect(recognition.startAttempts).toBe(starts);
  });

  it('one network blip still recovers, and heard speech resets the counter', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();
    act(() => recognition.emitError('network'));
    advance(5000);
    act(() => recognition.emitError('network'));
    advance(5000);
    emit(recognition, 0, 'Ultron open settings');
    advance(2000);
    expect(onCommand).toHaveBeenCalledWith('open settings');
    act(() => recognition.emitError('network'));
    advance(5000);
    expect(hook.result.current.voiceError).not.toMatch(/Chrome or Microsoft Edge/);
  });

  it('explains https/localhost when opened on a plain-http network address', () => {
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false });
    try {
      const hook = renderVoice();
      expect(hook.result.current.voiceError).toMatch(/https or localhost/);
      expect(FakeSpeechRecognition.instances.length).toBe(0);
    } finally {
      delete window.isSecureContext;
    }
  });
});
