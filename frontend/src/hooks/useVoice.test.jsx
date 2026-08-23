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
    this.lang = '';
    this.results = [];
    this.startCount = 0;
    this.startAttempts = 0;
    this.failNextStarts = 0;
    this.stopCount = 0;
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

  stop() {
    this.stopCount += 1;
    const wasRunning = this.running;
    this.running = false;
    if (wasRunning) this.onend?.();
  }

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

  endUnexpectedly() {
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

function renderVoice(onCommand = vi.fn(), extra = {}) {
  return renderHook(
    ({ callback, enabled, paused }) => useVoice({
      onCommand: callback,
      enabled,
      paused,
    }),
    {
      initialProps: {
        callback: onCommand,
        enabled: true,
        paused: false,
        ...extra,
      },
    },
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSpeechRecognition.instances = [];
  Object.defineProperty(window, 'SpeechRecognition', {
    configurable: true,
    writable: true,
    value: FakeSpeechRecognition,
  });
  Object.defineProperty(window, 'webkitSpeechRecognition', {
    configurable: true,
    writable: true,
    value: undefined,
  });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete window.SpeechRecognition;
  delete window.webkitSpeechRecognition;
});

describe('Voice C1 — one-wake conversational contract', () => {
  it('keeps the voice conversation active for direct follow-up turns until Stop Mic', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');
    expect(hook.result.current.conversationActive).toBe(true);
    emit(recognition, 1, 'open VS Code');
    emit(recognition, 2, 'show git status');
    emit(recognition, 3, 'what did we decide yesterday');
    emit(recognition, 4, 'and what is the next step');
    emit(recognition, 5, 'list my important memories');

    expect(onCommand.mock.calls.map(([command]) => command)).toEqual([
      'open VS Code',
      'show git status',
      'what did we decide yesterday',
      'and what is the next step',
      'list my important memories',
    ]);
    expect(hook.result.current.conversationActive).toBe(true);
  });

  it('accepts punctuation after the one approved wake phrase', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);

    emit(latestRecognizer(), 0, 'Hey Ultron, open VS Code');

    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('open VS Code');
  });

  it('does not unlock for broad legacy trigger words', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);

    emit(latestRecognizer(), 0, 'activate open settings');

    expect(onCommand).not.toHaveBeenCalled();
  });
});

describe('Voice C1 — transcript and callback correctness', () => {
  it('replaces interim hypotheses instead of duplicating them', () => {
    const onCommand = vi.fn();
    renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');
    emit(recognition, 1, 'open', false);
    emit(recognition, 1, 'open VS', false);
    emit(recognition, 1, 'open VS Code', true);

    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('open VS Code');
  });

  it('dispatches through the latest callback after the owner session changes', () => {
    const oldCallback = vi.fn();
    const newCallback = vi.fn();
    const hook = renderVoice(oldCallback);
    const recognition = latestRecognizer();

    hook.rerender({ callback: newCallback, enabled: true, paused: false });
    emit(recognition, 0, 'Ultron');
    emit(recognition, 1, 'remember this in the current session');

    expect(oldCallback).not.toHaveBeenCalled();
    expect(newCallback).toHaveBeenCalledOnce();
    expect(newCallback).toHaveBeenCalledWith('remember this in the current session');
  });

  it('pauses for processing/TTS without losing the conversation, then resumes', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');
    expect(hook.result.current.conversationActive).toBe(true);
    const startsBeforePause = recognition.startCount;

    hook.rerender({ callback: onCommand, enabled: true, paused: true });
    expect(recognition.abortCount).toBeGreaterThan(0);
    expect(hook.result.current.isListening).toBe(false);
    expect(hook.result.current.conversationActive).toBe(true);

    emit(recognition, 1, 'This is Ultron speaking through the laptop');
    expect(onCommand).not.toHaveBeenCalled();

    hook.rerender({ callback: onCommand, enabled: true, paused: false });
    expect(recognition.startCount).toBe(startsBeforePause + 1);
    expect(hook.result.current.isListening).toBe(true);
    expect(hook.result.current.conversationActive).toBe(true);

    emit(recognition, 2, 'continue with my next question');
    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('continue with my next question');
  });
});

describe('Voice C1 — lifecycle safety already expected from the final design', () => {
  it('cancels pending silence dispatch and restart when Stop Mic is pressed', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron');
    emit(recognition, 1, 'unfinished command', false);
    const startsBeforeStop = recognition.startCount;

    hook.rerender({ callback: onCommand, enabled: false, paused: false });
    act(() => vi.advanceTimersByTime(5000));

    expect(onCommand).not.toHaveBeenCalled();
    expect(recognition.startCount).toBe(startsBeforeStop);
    expect(hook.result.current.isListening).toBe(false);
    expect(hook.result.current.conversationActive).toBe(false);
  });

  it('stops cleanly on microphone permission denial without a restart loop', () => {
    const hook = renderVoice();
    const recognition = latestRecognizer();

    act(() => recognition.emitError('not-allowed'));
    act(() => vi.advanceTimersByTime(5000));

    expect(recognition.startCount).toBe(1);
    expect(hook.result.current.isListening).toBe(false);
    expect(hook.result.current.conversationActive).toBe(false);
    expect(hook.result.current.voiceError).toBe('Microphone permission was denied.');
  });

  it('uses a bounded delayed restart after an unexpected browser end', () => {
    renderVoice();
    const recognition = latestRecognizer();

    act(() => recognition.endUnexpectedly());
    expect(recognition.startCount).toBe(1);

    act(() => vi.advanceTimersByTime(499));
    expect(recognition.startCount).toBe(1);

    act(() => vi.advanceTimersByTime(1));
    expect(recognition.startCount).toBe(2);
  });

  it('deduplicates repeated end events into one pending restart', () => {
    renderVoice();
    const recognition = latestRecognizer();

    act(() => {
      recognition.endUnexpectedly();
      recognition.endUnexpectedly();
      recognition.endUnexpectedly();
    });
    expect(recognition.startCount).toBe(1);

    act(() => vi.advanceTimersByTime(500));
    expect(recognition.startCount).toBe(2);
  });

  it('cancels a scheduled restart while processing or TTS is paused', () => {
    const hook = renderVoice();
    const recognition = latestRecognizer();

    act(() => recognition.endUnexpectedly());
    hook.rerender({ callback: vi.fn(), enabled: true, paused: true });
    act(() => vi.advanceTimersByTime(5000));
    expect(recognition.startCount).toBe(1);

    hook.rerender({ callback: vi.fn(), enabled: true, paused: false });
    expect(recognition.startCount).toBe(2);
  });

  it('cancels a scheduled restart when the owner presses Stop Mic', () => {
    const hook = renderVoice();
    const recognition = latestRecognizer();

    act(() => recognition.endUnexpectedly());
    hook.rerender({ callback: vi.fn(), enabled: false, paused: false });
    act(() => vi.advanceTimersByTime(5000));

    expect(recognition.startCount).toBe(1);
    expect(hook.result.current.isListening).toBe(false);
  });

  it('recovers from no-speech only after the initial restart delay', () => {
    renderVoice();
    const recognition = latestRecognizer();

    act(() => recognition.emitError('no-speech'));
    expect(recognition.startCount).toBe(1);
    act(() => vi.advanceTimersByTime(499));
    expect(recognition.startCount).toBe(1);
    act(() => vi.advanceTimersByTime(1));
    expect(recognition.startCount).toBe(2);
  });

  it('treats an unsupported recognition language as fatal', () => {
    const hook = renderVoice();
    const recognition = latestRecognizer();

    act(() => recognition.emitError('language-not-supported'));
    act(() => vi.advanceTimersByTime(5000));

    expect(recognition.startCount).toBe(1);
    expect(hook.result.current.voiceError).toBe('The selected voice recognition language is unsupported.');
  });

  it('stops retrying after bounded synchronous start failures', () => {
    const hook = renderVoice();
    const recognition = latestRecognizer();
    recognition.failNextStarts = 10;

    act(() => recognition.endUnexpectedly());
    for (const delay of [500, 1000, 2000, 4000, 4000]) {
      act(() => vi.advanceTimersByTime(delay));
    }

    expect(recognition.startCount).toBe(1);
    expect(recognition.startAttempts).toBe(6);
    expect(hook.result.current.voiceError).toBe('Voice recognition could not restart. Use Stop and Start Voice to retry.');

    act(() => vi.advanceTimersByTime(10000));
    expect(recognition.startAttempts).toBe(6);
  });
});
