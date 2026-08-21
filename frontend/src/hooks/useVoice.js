import { useRef, useState, useCallback, useEffect } from 'react';

/**
 * useVoice Hook — human-like wake-word voice (Phase 7).
 *
 * Command-catching reliability fixes:
 *  1. Mic lifecycle is managed in useEffect (start on enable, clean stop/abort
 *     on disable/unmount) — no `setTimeout` side-effects in the render body, no
 *     duplicate recognizers.
 *  2. Commands are dispatched on a short SILENCE PAUSE (~1.4s) even if the
 *     browser never marks a result `final`, so a command is never lost.
 *  3. Recognition language is configurable via VITE_VOICE_LANG (default en-IN),
 *     instead of being hardcoded to hi-IN (which mangles English/Bengali).
 *  4. Fatal errors (permission denied / not allowed) stop auto-restart instead
 *     of spinning forever.
 *  5. Wake words are matched on word boundaries to avoid false positives.
 */
const WAKE_WORDS = [
  "ultron", "jarvis", "zora", "hey ultron", "hi ultron",
  "ok ultron", "wake up", "iron man", "activate"
];

// Recognition language: configurable, defaults to English-India which handles
// mixed English/Hinglish commands well. Override with VITE_VOICE_LANG.
const RECOG_LANG = (import.meta.env.VITE_VOICE_LANG || "en-IN");

// Send the captured command after this many ms of silence (pause in speech).
const SILENCE_FLUSH_MS = 1400;

function normalizeWordBoundary(word) {
  return word.split(/\s+/).map(w => w.trim()).filter(Boolean);
}

function matchesWakeWord(lowTranscript) {
  const words = normalizeWordBoundary(lowTranscript);
  if (!words.length) return { matched: null, idx: -1 };

  // Multi-word wake phrases like "hey ultron" or "wake up".
  for (const phrase of WAKE_WORDS) {
    const parts = normalizeWordBoundary(phrase);
    if (!parts.length) continue;
    const joined = parts.join(" ");
    const idx = lowTranscript.indexOf(joined);
    if (idx >= 0) {
      // Ensure it's at a word boundary.
      const before = idx === 0 ? " " : lowTranscript[idx - 1];
      const after = idx + joined.length >= lowTranscript.length ? " " : lowTranscript[idx + joined.length];
      if (/\s/.test(before) && /\s/.test(after)) {
        return { matched: phrase, idx };
      }
    }
    // Single word at a boundary.
    const w = parts.length === 1 ? parts[0] : null;
    if (w) {
      const wIdx = lowTranscript.indexOf(w);
      if (wIdx >= 0) {
        const before = wIdx === 0 ? " " : lowTranscript[wIdx - 1];
        const after = wIdx + w.length >= lowTranscript.length ? " " : lowTranscript[wIdx + w.length];
        if (/\s/.test(before) && /\s/.test(after)) {
          return { matched: w, idx: wIdx };
        }
      }
    }
  }
  return { matched: null, idx: -1 };
}

export default function useVoice({ onCommand, enabled }) {
  const [isListening, setIsListening] = useState(false);
  const [wakeDetected, setWakeDetected] = useState(false);
  const [heardText, setHeardText] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const supported = typeof window !== 'undefined' && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  const recRef = useRef(null);
  const capturingRef = useRef(false);
  const finalTextRef = useRef("");
  const silenceTimerRef = useRef(null);
  const fatalRef = useRef(false);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const dispatch = useCallback((rawCmd) => {
    const cmd = (rawCmd || "").replace(/^\s*(hey|ok|please|ultron|jarvis|zora)\s+/i, "").trim();
    if (cmd) {
      setHeardText(cmd);
      if (onCommand) onCommand(cmd);
    }
    capturingRef.current = false;
    finalTextRef.current = "";
    setWakeDetected(false);
    clearSilenceTimer();
  }, [onCommand]);

  const clearSilenceTimer = () => {
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
  };

  const armSilenceFlush = () => {
    clearSilenceTimer();
    silenceTimerRef.current = setTimeout(() => {
      // Flush whatever was accumulated, even if the browser never finalized it.
      if (capturingRef.current && finalTextRef.current.trim()) {
        dispatch(finalTextRef.current);
      }
    }, SILENCE_FLUSH_MS);
  };

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
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        if (res.isFinal) final += res[0].transcript;
        else interim += res[0].transcript;
      }
      const transcript = (final || interim || "").trim();
      const low = transcript.toLowerCase();

      // 1. Command-capture mode: accumulate + send on a pause.
      if (capturingRef.current) {
        finalTextRef.current = (finalTextRef.current + " " + transcript).trim();
        setHeardText(finalTextRef.current);
        armSilenceFlush();
        if (final) dispatch(finalTextRef.current);
        return;
      }

      // 2. Wake-word detection — capture the WHOLE line in one shot.
      if (low) {
        const { matched, idx } = matchesWakeWord(low);
        if (matched) {
          setWakeDetected(true);
          const rest = transcript.slice(idx + matched.length).replace(/^[,\s.]+/, "").trim();
          if (rest.length >= 2) {
            // Dispatch immediately (one-line command after the wake word).
            dispatch(rest);
            return;
          }
          // No command in this utterance yet → capture the next phrase.
          capturingRef.current = true;
          finalTextRef.current = "";
          armSilenceFlush();
        }
      }
    };

    rec.onerror = (event) => {
      let message = "";
      if (event.error === "not-allowed") {
        message = "Microphone permission was denied.";
      } else if (event.error === "audio-capture") {
        message = "No microphone input is available in this browser or remote desktop.";
      } else if (event.error === "network" || event.error === "service-not-allowed") {
        message = "Browser speech recognition service is unavailable.";
      }
      if (message) {
        fatalRef.current = true;
        setVoiceError(message);
        console.warn(`[VOICE] ${message}`);
      }
      try { rec.stop(); } catch (_e) {}
    };

    rec.onstart = () => {
      setIsListening(true);
      setVoiceError("");
    };

    rec.onend = () => {
      setIsListening(false);
      if (enabledRef.current && !fatalRef.current) {
        try { rec.start(); } catch (_e) {}
      }
    };

    recRef.current = rec;
    try {
      rec.start();
    } catch (_error) {
      fatalRef.current = true;
      setIsListening(false);
      setVoiceError("Voice recognition could not start in this browser.");
    }
  }, [dispatch]);

  const stop = useCallback(() => {
    clearSilenceTimer();
    if (recRef.current) {
      try { recRef.current.abort(); } catch (_e) {}
      try { recRef.current.stop(); } catch (_e) {}
      recRef.current = null;
    }
    capturingRef.current = false;
    finalTextRef.current = "";
    setIsListening(false);
    setWakeDetected(false);
    setHeardText("");
  }, []);

  // Mic lifecycle in an effect: start when enabled, cleanly stop otherwise.
  useEffect(() => {
    if (enabled) {
      fatalRef.current = false;
      start();
    } else {
      stop();
    }
    return () => { stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // Cleanup on unmount.
  useEffect(() => () => { clearSilenceTimer(); }, []);

  return { isListening, wakeDetected, heardText, voiceError, supported, start, stop };
}
