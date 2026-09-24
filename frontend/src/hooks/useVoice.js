import { useRef, useState, useCallback, useEffect } from 'react';

/**
 * Browser Web Speech lifecycle for an owner-controlled Option A microphone
 * session. A wake phrase opens one command only; after dispatch Ultron returns
 * to wake-only listening. No local/remote STT model is used here.
 */
const WAKE_WORDS = [
  'ultron wake up',
  'wake up ultron',
  'hey ultron',
  'wake up',
  'ultron',
];

// Real browsers (Chrome/Edge cloud STT) rarely spell "Ultron" correctly —
// they hear "ultra", "altron", "ultran", "alton"... These heard-as forms are
// accepted as the wake word too. They are deliberately narrow: "Electron",
// "activate" and ordinary words never wake Ultron.
const HEARD_AS_WAKE = [
  'hey altron', 'hey ultran', 'hey ultra', 'hey alton', 'hey all tron', 'hey ul tron', 'hey oltron',
  'hi ultron', 'hi ultra', 'ok ultron', 'okay ultron', 'ok ultra', 'okay ultra',
  'altron', 'ultran', 'ultrons', "ultron's", 'all tron', 'ul tron', 'oltron', 'alltron', 'ultraan',
];
// Bare "ultra"/"alton" only wake when they are the FIRST word Chrome heard
// (so "an ultra wide monitor" never triggers).
const LEADING_ONLY_WAKE = ['ultra', 'alton', 'alton,', 'ultra,'];

const RECOG_LANG = import.meta.env.VITE_VOICE_LANG || 'en-IN';
// After this many back-to-back network/service errors with no speech heard,
// the browser has no working speech service (Brave, Opera, Electron, offline).
const NETWORK_ERROR_FATAL_COUNT = 3;
// Tuned for natural speech: long commands need enough room for a human pause
// without being sent mid-sentence. New words always reset these windows.
const SILENCE_BASE_MS = 1800;
const SILENCE_SHORT_COMMAND_MS = 2000;
const SILENCE_LONG_COMMAND_MS = 2400;
const LONG_COMMAND_WORDS = 7;
const INTERIM_SETTLE_GRACE_MS = 600;
const WAKE_WAIT_MS = 6000;
const RESTART_BASE_MS = 500;
const RESTART_MAX_MS = 4000;
const RESTART_MAX_ATTEMPTS = 5;
const RESTART_RECOVERY_GRACE_MS = 2200;

function isWordCharacter(value) {
  return Boolean(value) && /[\p{L}\p{N}_]/u.test(value);
}

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function matchesWakeWord(transcript) {
  const original = String(transcript || '');
  const lower = original.toLowerCase();
  for (const phrase of [...WAKE_WORDS, ...HEARD_AS_WAKE]) {
    let fromIndex = 0;
    while (fromIndex < lower.length) {
      const index = lower.indexOf(phrase, fromIndex);
      if (index < 0) break;
      const end = index + phrase.length;
      if (!isWordCharacter(lower[index - 1]) && !isWordCharacter(lower[end])) {
        return { matched: phrase, index, end };
      }
      fromIndex = index + 1;
    }
  }
  const leading = lower.trimStart();
  const offset = lower.length - leading.length;
  for (const phrase of LEADING_ONLY_WAKE) {
    const word = phrase.replace(/,$/, '');
    if (leading.startsWith(word) && !isWordCharacter(leading[word.length])) {
      return { matched: word, index: offset, end: offset + word.length };
    }
  }
  return { matched: null, index: -1, end: -1 };
}

/** Check every alternative the browser offers, not only its first guess. */
function matchWakeInResult(result) {
  const count = Math.max(1, Number(result?.length) || 0);
  for (let alt = 0; alt < count; alt += 1) {
    const text = cleanText(result?.[alt]?.transcript);
    const wake = matchesWakeWord(text);
    if (wake.matched) return { ...wake, alt };
  }
  return { matched: null, index: -1, end: -1, alt: 0 };
}

function resultText(result, alt = 0) {
  return cleanText(result?.[alt]?.transcript || result?.[0]?.transcript);
}

/**
 * Chromium commonly repeats the final prefix in the next interim hypothesis:
 * "open" then "open the calendar". Join by word overlap, not concatenation.
 */
function mergeTranscript(leftValue, rightValue) {
  const left = cleanText(leftValue);
  const right = cleanText(rightValue);
  if (!left) return right;
  if (!right) return left;
  if (left === right || left.toLowerCase().endsWith(right.toLowerCase())) return left;
  if (right.toLowerCase().startsWith(left.toLowerCase())) return right;

  const leftWords = left.split(' ');
  const rightWords = right.split(' ');
  for (let size = Math.min(leftWords.length, rightWords.length); size > 0; size -= 1) {
    if (leftWords.slice(-size).join(' ').toLowerCase() === rightWords.slice(0, size).join(' ').toLowerCase()) {
      return [...leftWords, ...rightWords.slice(size)].join(' ');
    }
  }
  return `${left} ${right}`;
}

function silenceDelay(command) {
  const words = cleanText(command).split(' ').filter(Boolean).length;
  if (words >= LONG_COMMAND_WORDS) return SILENCE_LONG_COMMAND_MS;
  if (words < 3) return SILENCE_SHORT_COMMAND_MS;
  return SILENCE_BASE_MS;
}

export default function useVoice({ onCommand, enabled, paused = false }) {
  const [isListening, setIsListening] = useState(false);
  const [wakeDetected, setWakeDetected] = useState(false);
  // In Option A this means a wake/command turn is currently open. It is reset
  // immediately after that one command dispatches; it is not multi-turn mode.
  const [conversationActive, setConversationActive] = useState(false);
  const [heardText, setHeardText] = useState('');
  const [voiceError, setVoiceError] = useState('');
  const supported = typeof window !== 'undefined' && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

  const recRef = useRef(null);
  const recognizerRunningRef = useRef(false);
  const enabledRef = useRef(enabled);
  const pausedRef = useRef(paused);
  const onCommandRef = useRef(onCommand);
  const fatalRef = useRef(false);
  const sessionIdRef = useRef(0);

  const capturingRef = useRef(false);
  const captureSessionIdRef = useRef(0);
  const captureStartIndexRef = useRef(0);
  const captureWakePhraseRef = useRef(null);
  const captureAltRef = useRef(0);
  const networkErrorsRef = useRef(0);
  const turnSegmentsRef = useRef(new Map());
  const carriedTextRef = useRef('');
  const commandTextRef = useRef('');
  const lastHeardTextRef = useRef('');
  const latestResultFinalRef = useRef(false);
  const interimGraceUsedRef = useRef(false);
  const dispatchingRef = useRef(false);

  const silenceTimerRef = useRef(null);
  const wakeTimerRef = useRef(null);
  const recoveryTimerRef = useRef(null);
  const restartTimerRef = useRef(null);
  const restartAttemptRef = useRef(0);
  const restartSchedulerRef = useRef(null);
  const dispatchRef = useRef(() => {});

  enabledRef.current = enabled;
  pausedRef.current = paused;
  onCommandRef.current = onCommand;

  const clearTimer = useCallback((ref) => {
    if (ref.current) {
      clearTimeout(ref.current);
      ref.current = null;
    }
  }, []);

  const clearTurnTimers = useCallback(() => {
    clearTimer(silenceTimerRef);
    clearTimer(wakeTimerRef);
    clearTimer(recoveryTimerRef);
  }, [clearTimer]);

  const clearRestartTimer = useCallback(() => clearTimer(restartTimerRef), [clearTimer]);

  const resetTurn = useCallback((clearHeard = false, preserveDispatchLock = false) => {
    capturingRef.current = false;
    captureSessionIdRef.current = sessionIdRef.current;
    captureStartIndexRef.current = 0;
    captureWakePhraseRef.current = null;
    turnSegmentsRef.current.clear();
    carriedTextRef.current = '';
    commandTextRef.current = '';
    lastHeardTextRef.current = '';
    latestResultFinalRef.current = false;
    interimGraceUsedRef.current = false;
    if (!preserveDispatchLock) dispatchingRef.current = false;
    clearTurnTimers();
    setWakeDetected(false);
    setConversationActive(false);
    if (clearHeard) setHeardText('');
  }, [clearTurnTimers]);

  const scheduleRestart = useCallback((recognizer) => {
    if (
      restartTimerRef.current
      || recRef.current !== recognizer
      || !enabledRef.current
      || pausedRef.current
      || fatalRef.current
      || recognizerRunningRef.current
    ) {
      return;
    }

    if (restartAttemptRef.current >= RESTART_MAX_ATTEMPTS) {
      fatalRef.current = true;
      setVoiceError('Voice recognition could not restart. Use Stop and Start Voice to retry.');
      setIsListening(false);
      return;
    }

    const delay = Math.min(RESTART_BASE_MS * (2 ** restartAttemptRef.current), RESTART_MAX_MS);
    restartTimerRef.current = setTimeout(() => {
      restartTimerRef.current = null;
      if (
        recRef.current !== recognizer
        || !enabledRef.current
        || pausedRef.current
        || fatalRef.current
        || recognizerRunningRef.current
      ) {
        return;
      }
      restartAttemptRef.current += 1;
      try {
        recognizer.start();
      } catch (_error) {
        recognizerRunningRef.current = false;
        restartSchedulerRef.current?.(recognizer);
      }
    }, delay);
  }, []);
  restartSchedulerRef.current = scheduleRestart;

  const buildTurnText = useCallback(() => {
    let text = '';
    const entries = [...turnSegmentsRef.current.entries()].sort(([left], [right]) => left - right);
    for (const [index, segment] of entries) {
      let segmentText = segment.text;
      if (index === captureStartIndexRef.current && captureWakePhraseRef.current) {
        const wake = matchesWakeWord(segmentText);
        if (wake.matched) {
          segmentText = segmentText.slice(wake.end).replace(/^[,\s.?!:;-]+/, '').trim();
        }
      }
      text = mergeTranscript(text, segmentText);
    }
    return mergeTranscript(carriedTextRef.current, text);
  }, []);

  const updateTurnFromResult = useCallback((event) => {
    if (captureSessionIdRef.current !== sessionIdRef.current) {
      // Browser ended in the middle of speech. Keep the captured prefix, but
      // start a fresh result-index map for the replacement recognizer session.
      turnSegmentsRef.current.clear();
      captureSessionIdRef.current = sessionIdRef.current;
      captureStartIndexRef.current = 0;
      captureWakePhraseRef.current = null;
    }

    const startIndex = Math.max(Number(event.resultIndex) || 0, captureStartIndexRef.current);
    for (let index = startIndex; index < event.results.length; index += 1) {
      turnSegmentsRef.current.set(index, {
        text: resultText(
          event.results[index],
          index === captureStartIndexRef.current ? captureAltRef.current : 0,
        ),
        isFinal: Boolean(event.results[index]?.isFinal),
      });
    }
    for (const index of turnSegmentsRef.current.keys()) {
      if (index >= event.results.length) turnSegmentsRef.current.delete(index);
    }

    const latest = event.results[event.results.length - 1];
    latestResultFinalRef.current = Boolean(latest?.isFinal);
    return buildTurnText();
  }, [buildTurnText]);

  const dispatch = useCallback((rawCommand) => {
    if (dispatchingRef.current) return false;
    const command = cleanText(rawCommand);
    if (!command) {
      resetTurn(false);
      return false;
    }

    dispatchingRef.current = true;
    resetTurn(false, true);
    setHeardText(command);
    onCommandRef.current?.(command);
    return true;
  }, [resetTurn]);
  dispatchRef.current = dispatch;

  const armSilenceFlush = useCallback((command) => {
    clearTimer(silenceTimerRef);
    silenceTimerRef.current = setTimeout(() => {
      if (!capturingRef.current || !commandTextRef.current.trim()) return;
      if (!latestResultFinalRef.current && !interimGraceUsedRef.current) {
        interimGraceUsedRef.current = true;
        silenceTimerRef.current = setTimeout(() => {
          if (capturingRef.current && commandTextRef.current.trim()) {
            dispatchRef.current(commandTextRef.current);
          }
        }, INTERIM_SETTLE_GRACE_MS);
        return;
      }
      dispatchRef.current(commandTextRef.current);
    }, silenceDelay(command));
  }, [clearTimer]);

  const armWakeWait = useCallback(() => {
    clearTimer(wakeTimerRef);
    wakeTimerRef.current = setTimeout(() => {
      if (capturingRef.current && !commandTextRef.current.trim()) resetTurn(false);
    }, WAKE_WAIT_MS);
  }, [clearTimer, resetTurn]);

  const armRecoveryGrace = useCallback(() => {
    clearTimer(recoveryTimerRef);
    recoveryTimerRef.current = setTimeout(() => {
      if (
        recognizerRunningRef.current
        && capturingRef.current
        && commandTextRef.current.trim()
      ) {
        dispatchRef.current(commandTextRef.current);
      }
    }, RESTART_RECOVERY_GRACE_MS);
  }, [clearTimer]);

  const beginWakeTurn = useCallback((event, resultIndex, wakePhrase, alt = 0) => {
    capturingRef.current = true;
    captureAltRef.current = alt;
    captureSessionIdRef.current = sessionIdRef.current;
    captureStartIndexRef.current = resultIndex;
    captureWakePhraseRef.current = wakePhrase;
    turnSegmentsRef.current.clear();
    carriedTextRef.current = '';
    commandTextRef.current = '';
    lastHeardTextRef.current = '';
    latestResultFinalRef.current = false;
    interimGraceUsedRef.current = false;
    dispatchingRef.current = false;
    setWakeDetected(true);
    setConversationActive(true);

    const command = updateTurnFromResult(event);
    commandTextRef.current = command;
    lastHeardTextRef.current = command;
    setHeardText(command);
    if (command) armSilenceFlush(command);
    else armWakeWait();
  }, [armSilenceFlush, armWakeWait, updateTurnFromResult]);

  const start = useCallback(() => {
    if (typeof window === 'undefined') return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      fatalRef.current = true;
      setVoiceError('Voice recognition is unavailable in this browser. Use Google Chrome or Microsoft Edge.');
      return;
    }
    if (window.isSecureContext === false) {
      fatalRef.current = true;
      setVoiceError(
        `The microphone only works on https or localhost. Open Ultron at http://localhost:${window.location?.port || '5173'} on this PC instead of ${window.location?.host || 'a network address'}.`,
      );
      return;
    }

    if (recRef.current) {
      if (!recognizerRunningRef.current && !pausedRef.current && !fatalRef.current) {
        try { recRef.current.start(); } catch (_error) { scheduleRestart(recRef.current); }
      }
      return;
    }

    const recognizer = new SpeechRecognition();
    recognizer.continuous = true;
    recognizer.interimResults = true;
    recognizer.maxAlternatives = 3;
    recognizer.lang = RECOG_LANG;

    recognizer.onresult = (event) => {
      if (recRef.current !== recognizer || pausedRef.current || !enabledRef.current) return;
      networkErrorsRef.current = 0;

      if (capturingRef.current) {
        const command = updateTurnFromResult(event);
        commandTextRef.current = command;
        if (command !== lastHeardTextRef.current) {
          lastHeardTextRef.current = command;
          interimGraceUsedRef.current = false;
          setHeardText(command);
        }
        clearTimer(wakeTimerRef);
        clearTimer(recoveryTimerRef);
        if (command) armSilenceFlush(command);
        else armWakeWait();
        return;
      }

      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const wake = matchWakeInResult(event.results[index]);
        if (!wake.matched) continue;
        beginWakeTurn(event, index, wake.matched, wake.alt);
        return;
      }
    };

    recognizer.onerror = (event) => {
      if (recRef.current !== recognizer || event.error === 'aborted') return;
      if (event.error === 'no-speech') {
        setVoiceError('');
        return;
      }

      const fatalMessages = {
        'not-allowed': 'Microphone permission was denied.',
        'audio-capture': 'No microphone input is available in this browser or remote desktop.',
        'language-not-supported': 'The selected voice recognition language is unsupported.',
        'bad-grammar': 'The browser rejected the voice recognition configuration.',
      };
      const message = fatalMessages[event.error];
      if (message) {
        fatalRef.current = true;
        clearRestartTimer();
        resetTurn(false);
        setIsListening(false);
        setVoiceError(message);
        try { recognizer.abort(); } catch (_error) {}
        return;
      }

      if (event.error === 'network' || event.error === 'service-not-allowed') {
        // A single blip is recoverable (bounded onend restart). But onstart
        // resets the restart counter, so a browser WITHOUT a speech service
        // used to loop "reconnecting…" forever. Count consecutive failures.
        networkErrorsRef.current += 1;
        if (networkErrorsRef.current >= NETWORK_ERROR_FATAL_COUNT) {
          fatalRef.current = true;
          clearRestartTimer();
          resetTurn(false);
          setIsListening(false);
          setVoiceError(
            event.error === 'service-not-allowed'
              ? 'Speech recognition is blocked here. Open Ultron in Google Chrome or Microsoft Edge at http://localhost (or https) and allow the microphone.'
              : 'This browser cannot reach its speech service. Use Google Chrome or Microsoft Edge with internet on (Brave, Opera, Firefox and the Electron shell have no working speech recognition).',
          );
          try { recognizer.abort(); } catch (_error) {}
          return;
        }
        setVoiceError('Browser speech recognition is reconnecting…');
        try { recognizer.abort(); } catch (_error) {}
        return;
      }

      setVoiceError(`Voice recognition failed (${event.error || 'unknown'}).`);
      try { recognizer.abort(); } catch (_error) {}
    };

    recognizer.onstart = () => {
      if (recRef.current !== recognizer) return;
      clearRestartTimer();
      restartAttemptRef.current = 0;
      recognizerRunningRef.current = true;
      sessionIdRef.current += 1;
      if (pausedRef.current || !enabledRef.current) {
        try { recognizer.abort(); } catch (_error) {}
        return;
      }
      setIsListening(true);
      setVoiceError('');
    };

    recognizer.onend = () => {
      if (recRef.current !== recognizer) return;
      recognizerRunningRef.current = false;
      setIsListening(false);
      if (fatalRef.current) return;

      if (capturingRef.current) {
        if (commandTextRef.current.trim()) {
          carriedTextRef.current = commandTextRef.current;
          turnSegmentsRef.current.clear();
          captureSessionIdRef.current = -1;
          captureStartIndexRef.current = 0;
          captureWakePhraseRef.current = null;
          clearTimer(silenceTimerRef);
          armRecoveryGrace();
        }
        // A wake-only turn remains open across an unexpected browser restart.
        scheduleRestart(recognizer);
        return;
      }
      scheduleRestart(recognizer);
    };

    recRef.current = recognizer;
    try {
      recognizer.start();
    } catch (_error) {
      recognizerRunningRef.current = false;
      scheduleRestart(recognizer);
    }
  }, [
    armRecoveryGrace,
    armSilenceFlush,
    armWakeWait,
    beginWakeTurn,
    clearRestartTimer,
    clearTimer,
    resetTurn,
    scheduleRestart,
    updateTurnFromResult,
  ]);

  const stop = useCallback(() => {
    clearTurnTimers();
    clearRestartTimer();
    restartAttemptRef.current = 0;
    const recognizer = recRef.current;
    recRef.current = null;
    recognizerRunningRef.current = false;
    if (recognizer) {
      try { recognizer.abort(); } catch (_error) {}
      try { recognizer.stop(); } catch (_error) {}
    }
    resetTurn(true);
    setIsListening(false);
    setVoiceError('');
  }, [clearRestartTimer, clearTurnTimers, resetTurn]);

  useEffect(() => {
    if (enabled) {
      fatalRef.current = false;
      networkErrorsRef.current = 0;
      start();
    } else {
      stop();
    }
    return () => { stop(); };
  }, [enabled, start, stop]);

  // Processing/TTS remains an explicit App-level pause in this private project.
  // Option A does not preserve a follow-up conversation during the pause; after
  // a response the owner says a wake phrase again for the next command.
  useEffect(() => {
    const recognizer = recRef.current;
    if (!enabled || !recognizer) return;

    if (paused) {
      clearRestartTimer();
      restartAttemptRef.current = 0;
      resetTurn(false);
      recognizerRunningRef.current = false;
      setIsListening(false);
      try { recognizer.abort(); } catch (_error) {}
      return;
    }

    if (!fatalRef.current && !recognizerRunningRef.current) {
      try { recognizer.start(); } catch (_error) { scheduleRestart(recognizer); }
    }
  }, [clearRestartTimer, enabled, paused, resetTurn, scheduleRestart]);

  useEffect(() => () => {
    clearTurnTimers();
    clearRestartTimer();
  }, [clearRestartTimer, clearTurnTimers]);

  return {
    isListening,
    wakeDetected,
    conversationActive,
    heardText,
    voiceError,
    supported,
    start,
    stop,
  };
}
