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
    advance(1800);
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
    advance(1399);
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
    advance(1399);
    expect(onCommand).not.toHaveBeenCalled();
    advance(1);

    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('create a task for tomorrow morning');
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
    advance(1400);
    expect(onCommand).toHaveBeenCalledOnce();
    expect(onCommand).toHaveBeenCalledWith('open VS Code');
  });

  it('returns to wake-only mode after one command; a follow-up without Ultron is ignored', () => {
    const onCommand = vi.fn();
    const hook = renderVoice(onCommand);
    const recognition = latestRecognizer();

    emit(recognition, 0, 'Ultron open calendar');
    advance(1800);
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
    advance(1400);
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
    advance(1800);
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
    expect(hook.result.current.voiceError).toBe('Microphone permission was denied.');
    expect(hook.result.current.isListening).toBe(false);
  });
});
