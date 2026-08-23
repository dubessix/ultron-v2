import { useRef, useState, useCallback, useEffect } from 'react';

/**
 * Browser Web Speech lifecycle for the owner-controlled microphone session.
 *
 * C2 correctness boundaries:
 *  - only the approved Ultron wake phrases enter command capture;
 *  - punctuation around a wake phrase is accepted without substring matches;
 *  - interim hypotheses replace one another instead of being appended;
 *  - the live recognizer always dispatches through the latest callback;
 *  - one approved wake phrase opens a multi-turn conversation until Stop Mic.
 *
 * Processing/TTS pause and delayed restart are later dedicated phases; do not
 * hide those lifecycle states inside transcript parsing.
 */
const WAKE_WORDS = ["hey ultron", "ultron"];

// Recognition language remains lightweight/browser-side for the owner's 8 GB,
// dual-core class laptop. Override only through the existing frontend setting.
const RECOG_LANG = (import.meta.env.VITE_VOICE_LANG || "en-IN");
const SILENCE_FLUSH_MS = 1400;
const RESTART_BASE_MS = 500;
const RESTART_MAX_MS = 4000;
const RESTART_MAX_ATTEMPTS = 5;

function isWordCharacter(value) {
  return Boolean(value) && /[a-z0-9_]/i.test(value);
}

function matchesWakeWord(transcript) {
  const lowTranscript = String(transcript || "").toLowerCase();
  for (const phrase of WAKE_WORDS) {
    let fromIndex = 0;
    while (fromIndex < lowTranscript.length) {
      const idx = lowTranscript.indexOf(phrase, fromIndex);
      if (idx < 0) break;
      const before = idx > 0 ? lowTranscript[idx - 1] : "";
      const afterIndex = idx + phrase.length;
      const after = afterIndex < lowTranscript.length ? lowTranscript[afterIndex] : "";
      if (!isWordCharacter(before) && !isWordCharacter(after)) {
        return { matched: phrase, idx };
      }
      fromIndex = idx + 1;
    }
  }
  return { matched: null, idx: -1 };
}

function normalizedResultText(result) {
  return String(result?.[0]?.transcript || "").trim();
}

export default function useVoice({ onCommand, enabled, paused = false }) {
  const [isListening, setIsListening] = useState(false);
  const [wakeDetected, setWakeDetected] = useState(false);
  const [conversationActive, setConversationActive] = useState(false);
  const [heardText, setHeardText] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const supported = typeof window !== 'undefined' && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);

  const recRef = useRef(null);
  const capturingRef = useRef(false);
  const captureStartIndexRef = useRef(0);
  const captureWakePhraseRef = useRef(null);
  const finalTextRef = useRef("");
  const silenceTimerRef = useRef(null);
  const restartTimerRef = useRef(null);
  const restartAttemptRef = useRef(0);
  const restartSchedulerRef = useRef(null);
  const fatalRef = useRef(false);
  const enabledRef = useRef(enabled);
  const pausedRef = useRef(paused);
  const recognizerRunningRef = useRef(false);
  const conversationActiveRef = useRef(false);
  const onCommandRef = useRef(onCommand);

  enabledRef.current = enabled;
  pausedRef.current = paused;
  onCommandRef.current = onCommand;

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const clearRestartTimer = useCallback(() => {
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
  }, []);

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
      conversationActiveRef.current = false;
      setConversationActive(false);
      setVoiceError("Voice recognition could not restart. Use Stop and Start Voice to retry.");
      return;
    }

    const delay = Math.min(
      RESTART_BASE_MS * (2 ** restartAttemptRef.current),
      RESTART_MAX_MS,
    );
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

  const dispatch = useCallback((rawCmd) => {
    const cmd = String(rawCmd || "").trim();
    if (cmd) {
      setHeardText(cmd);
      onCommandRef.current?.(cmd);
    }
    capturingRef.current = false;
    captureStartIndexRef.current = 0;
    captureWakePhraseRef.current = null;
    finalTextRef.current = "";
    setWakeDetected(false);
    clearSilenceTimer();
  }, [clearSilenceTimer]);

  const armSilenceFlush = useCallback(() => {
    clearSilenceTimer();
    silenceTimerRef.current = setTimeout(() => {
      if (capturingRef.current && finalTextRef.current.trim()) {
        dispatch(finalTextRef.current);
      }
    }, SILENCE_FLUSH_MS);
  }, [clearSilenceTimer, dispatch]);

  const buildCapturedCommand = useCallback((event) => {
    const segments = [];
    const startIndex = captureStartIndexRef.current;
    const wakePhrase = captureWakePhraseRef.current;

    for (let index = startIndex; index < event.results.length; index++) {
      let text = normalizedResultText(event.results[index]);
      if (index === startIndex && wakePhrase) {
        const match = matchesWakeWord(text);
        if (match.matched) {
          text = text
            .slice(match.idx + match.matched.length)
            .replace(/^[,\s.?!:;-]+/, "")
            .trim();
        }
      }
      if (text) segments.push(text);
    }
    return segments.join(" ").replace(/\s+/g, " ").trim();
  }, []);

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    setVoiceError("");
    if (!SR) {
      const message = "Voice recognition is unavailable in this browser.";
      setVoiceError(message);
      console.warn(`[VOICE] ${message}`);
      return;
    }

    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = RECOG_LANG;

    rec.onresult = (event) => {
      // A late browser result can arrive after abort(). Never let buffered TTS or
      // processing-time audio become an owner command.
      if (pausedRef.current || !enabledRef.current) return;

      if (capturingRef.current) {
        const command = buildCapturedCommand(event);
        finalTextRef.current = command;
        setHeardText(command);

        let changedFinal = false;
        const firstChanged = Math.max(event.resultIndex, captureStartIndexRef.current);
        for (let index = firstChanged; index < event.results.length; index++) {
          if (event.results[index].isFinal) {
            changedFinal = true;
            break;
          }
        }

        if (changedFinal && command) {
          dispatch(command);
        } else if (command) {
          armSilenceFlush();
        }
        return;
      }

      // Once the owner has said the wake phrase, each later browser result is a
      // direct conversational turn until Stop Mic resets the session. Per-turn
      // capture state is still cleared after dispatch; conversation state is not.
      if (conversationActiveRef.current) {
        for (let index = event.resultIndex; index < event.results.length; index++) {
          const result = event.results[index];
          const transcript = normalizedResultText(result);
          if (!transcript) continue;

          capturingRef.current = true;
          captureStartIndexRef.current = index;
          captureWakePhraseRef.current = null;
          finalTextRef.current = transcript;
          setHeardText(transcript);

          if (result.isFinal) {
            dispatch(transcript);
          } else {
            armSilenceFlush();
          }
          return;
        }
      }

      // Scan only changed hypotheses. An approved wake phrase can either carry
      // its command in the same final result or arm capture for the next result.
      for (let index = event.resultIndex; index < event.results.length; index++) {
        const result = event.results[index];
        const transcript = normalizedResultText(result);
        const { matched, idx } = matchesWakeWord(transcript);
        if (!matched) continue;

        conversationActiveRef.current = true;
        setConversationActive(true);
        setWakeDetected(true);
        capturingRef.current = true;
        captureStartIndexRef.current = index;
        captureWakePhraseRef.current = matched;

        const rest = transcript
          .slice(idx + matched.length)
          .replace(/^[,\s.?!:;-]+/, "")
          .trim();
        finalTextRef.current = rest;
        setHeardText(rest);

        if (result.isFinal && rest) {
          dispatch(rest);
        } else if (rest) {
          armSilenceFlush();
        }
        return;
      }
    };

    rec.onerror = (event) => {
      // abort is expected when C4 pauses processing/TTS or the owner stops.
      if (event.error === "aborted") return;

      let message = "";
      if (event.error === "not-allowed") {
        message = "Microphone permission was denied.";
      } else if (event.error === "audio-capture") {
        message = "No microphone input is available in this browser or remote desktop.";
      } else if (event.error === "network" || event.error === "service-not-allowed") {
        message = "Browser speech recognition service is unavailable.";
      } else if (event.error === "language-not-supported") {
        message = "The selected voice recognition language is unsupported.";
      } else if (event.error === "bad-grammar") {
        message = "The browser rejected the voice recognition configuration.";
      } else if (event.error !== "no-speech") {
        message = `Voice recognition failed (${event.error || "unknown"}).`;
      }

      if (message) {
        fatalRef.current = true;
        conversationActiveRef.current = false;
        capturingRef.current = false;
        finalTextRef.current = "";
        clearSilenceTimer();
        clearRestartTimer();
        setConversationActive(false);
        setWakeDetected(false);
        setVoiceError(message);
        console.warn(`[VOICE] ${message}`);
      } else {
        // no-speech is an ordinary recoverable end; do not alarm the owner.
        setVoiceError("");
      }
      try { rec.stop(); } catch (_e) {}
    };

    rec.onstart = () => {
      clearRestartTimer();
      restartAttemptRef.current = 0;
      recognizerRunningRef.current = true;
      if (pausedRef.current || !enabledRef.current) {
        try { rec.abort(); } catch (_e) {}
        return;
      }
      setIsListening(true);
      setVoiceError("");
    };

    rec.onend = () => {
      recognizerRunningRef.current = false;
      setIsListening(false);
      scheduleRestart(rec);
    };

    recRef.current = rec;
    try {
      rec.start();
    } catch (_error) {
      fatalRef.current = true;
      setIsListening(false);
      setVoiceError("Voice recognition could not start in this browser.");
    }
  }, [
    armSilenceFlush,
    buildCapturedCommand,
    clearRestartTimer,
    clearSilenceTimer,
    dispatch,
    scheduleRestart,
  ]);

  const stop = useCallback(() => {
    clearSilenceTimer();
    clearRestartTimer();
    restartAttemptRef.current = 0;
    if (recRef.current) {
      try { recRef.current.abort(); } catch (_e) {}
      try { recRef.current.stop(); } catch (_e) {}
      recRef.current = null;
    }
    recognizerRunningRef.current = false;
    capturingRef.current = false;
    captureStartIndexRef.current = 0;
    captureWakePhraseRef.current = null;
    conversationActiveRef.current = false;
    finalTextRef.current = "";
    setIsListening(false);
    setWakeDetected(false);
    setConversationActive(false);
    setHeardText("");
  }, [clearRestartTimer, clearSilenceTimer]);

  useEffect(() => {
    if (enabled) {
      fatalRef.current = false;
      start();
    } else {
      stop();
    }
    return () => { stop(); };
  }, [enabled, start, stop]);

  // Web Speech has no pause primitive. abort() is deliberate here: unlike
  // stop(), it does not ask the browser to return buffered recognition text.
  // Conversation state survives; only the in-flight turn is discarded.
  useEffect(() => {
    const recognizer = recRef.current;
    if (!enabled || !recognizer) return;

    if (paused) {
      clearSilenceTimer();
      clearRestartTimer();
      restartAttemptRef.current = 0;
      capturingRef.current = false;
      captureStartIndexRef.current = 0;
      captureWakePhraseRef.current = null;
      finalTextRef.current = "";
      setWakeDetected(false);
      recognizerRunningRef.current = false;
      setIsListening(false);
      try { recognizer.abort(); } catch (_e) {}
      return;
    }

    if (!fatalRef.current && !recognizerRunningRef.current) {
      try {
        recognizer.start();
      } catch (_error) {
        scheduleRestart(recognizer);
      }
    }
  }, [clearRestartTimer, clearSilenceTimer, enabled, paused, scheduleRestart]);

  useEffect(() => () => {
    clearSilenceTimer();
    clearRestartTimer();
  }, [clearRestartTimer, clearSilenceTimer]);

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
