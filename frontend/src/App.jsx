import React, { useState, useEffect, useRef, useCallback } from 'react';
import { applyWidgetAction } from './widgetActions';
import { createPresenceTracker } from './arrival';
import AppShell from './components/AppShell';
import NotificationToast from './components/NotificationToast';
import { api, apiBase, executeTool, websocketBase } from './api';
import { progressAction } from './liveProgress';
import { connectEvents, planForEvent, planForReturn } from './reminderAlerts';
import { isPlaybackBlocked, playbackProblem } from './speechPlayback';

/**
 * Ultron Web Client Root App
 * Coordinates websocket connections, local state parameters, and maps
 * standard data flows, notification toast systems, and keyboard fallbacks.
 * Dynamically launches and positions all registry-backed widgets.
 */
export default function App() {
  const [backendStatus, setBackendStatus] = useState("DISCONNECTED");
  const [providerStatus, setProviderStatus] = useState(null);
  const [systemMetrics, setSystemMetrics] = useState(null);
  
  const [sessionId, setSessionId] = useState(null);
  const [activePersonality, setActivePersonality] = useState("ultron");
  const [personalitySaving, setPersonalitySaving] = useState(false);
  const [aiState, setAiState] = useState("idle");
  const [activityText, setActivityText] = useState("Connecting to the local Ultron backend…");
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const processingRef = useRef(false);
  useEffect(() => { processingRef.current = isProcessing; }, [isProcessing]);
  const [isSpeaking, setIsSpeaking] = useState(false);
  // Coding Mode (NVIDIA brain) — manual toggle synced to backend /api/coding-mode
  const [codingMode, setCodingMode] = useState(false);
  const [codingModeSaving, setCodingModeSaving] = useState(false);
  // Coding activity log shown in the CodingWidget; auto-opened on coding turns.
  const [codingLog, setCodingLog] = useState([]);
  // Exact one-time action returned by the backend; never regenerate on confirm.
  const [pendingAction, setPendingAction] = useState(null);
  const [confirmingAction, setConfirmingAction] = useState(false);
  // Present only when the backend explicitly says a voice transcript has more
  // than one safe meaning. Normal clear requests never show this card.
  const [voiceClarification, setVoiceClarification] = useState(null);
  const [voicePreferenceSaving, setVoicePreferenceSaving] = useState(false);
  // Real-time operational log (Log tab)
  const [logs, setLogs] = useState([]);
  // One first-open briefing attempt per browser page; localStorage prevents repeats that day.
  const briefingAttemptedRef = useRef(false);
  // Voice dispatch uses refs for same-tick exclusion and the latest canonical
  // session, avoiding React render timing gaps without replaying a sent turn.
  const sessionIdRef = useRef(sessionId);
  const voiceRequestInFlightRef = useRef(false);
  sessionIdRef.current = sessionId;

  // Widget floating toggle states (Requirement: Remember coordinates & state)
  const [widgetState, setWidgetState] = useState({
    todo: { visible: false, x: 120, y: 150 },
    calendar: { visible: false, x: 450, y: 120 },
    reminder: { visible: false, x: 320, y: 140 },
    code_optimizer: { visible: false, x: 340, y: 160 },
    semantic_code_graph: { visible: false, x: 360, y: 180 },
    security_guardian: { visible: false, x: 380, y: 200 },
    daily_briefing: { visible: false, x: 400, y: 220 },
    git: { visible: false, x: 220, y: 320 },
    file_explorer: { visible: false, x: 140, y: 180 },
    universal_search: { visible: false, x: 160, y: 220 },
    deep_research: { visible: false, x: 180, y: 240 },
    weather: { visible: false, x: 200, y: 120 },
    market: { visible: false, x: 220, y: 140 },
    terminal: { visible: false, x: 240, y: 160 },
    memory: { visible: false, x: 300, y: 110 },
    notification: { visible: false, x: 280, y: 200 },
    system: { visible: false, x: 300, y: 220 },
    coding: { visible: false, x: 360, y: 300 },
    music: { visible: false, x: 380, y: 320 },
    world_monitor: { visible: false, x: 400, y: 340 },
    github_search: { visible: false, x: 420, y: 360 },
    git_clone: { visible: false, x: 440, y: 380 }
  });

  // Dynamic Notification Toasts Queue (Requirement: Notification Prioritization)
  const [notifications, setNotifications] = useState([]);

  // Add a new notification toast
  const addNotification = useCallback((title, message, priority = "low") => {
    const newId = "notif_" + Date.now() + "_" + Math.random().toString(36).substr(2, 5);
    setNotifications(prev => [...prev, { id: newId, title, message, priority }]);
  }, []);

  // Stable callback prevents NotificationToast's four-second timer from being
  // restarted by unrelated health/metric renders.
  const dismissNotification = useCallback((id) => {
    setNotifications(prev => prev.filter(notif => notif.id !== id));
  }, []);

  // Keyboard Shortcuts (Requirement: Optional Fallback Controls)
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Toggle widgets on Ctrl+Alt key bounds
      if (e.ctrlKey && e.altKey) {
        if (e.key.toLowerCase() === 't') {
          toggleWidget('todo');
        } else if (e.key.toLowerCase() === 'c') {
          toggleWidget('calendar');
        } else if (e.key.toLowerCase() === 'g') {
          toggleWidget('git');
        }
      }
      // Escape closes all open widgets instantly (Clean workspace helper)
      if (e.key === 'Escape') {
        setWidgetState(prev => {
          const reset = {};
          Object.keys(prev).forEach(key => {
            reset[key] = { ...prev[key], visible: false };
          });
          return reset;
        });
        addNotification("Workspace Cleaned", "All floating widgets have been collapsed.", "low");
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Poll normally while visible; hidden tabs wake less often and refresh immediately on return.
  useEffect(() => {
    let timer = null;
    let cancelled = false;
    let inFlight = false;

    const scheduleNext = () => {
      if (cancelled) return;
      clearTimeout(timer);
      timer = setTimeout(checkHealth, document.hidden ? 30000 : 5000);
    };

    const checkHealth = async () => {
      if (inFlight || cancelled) return;
      inFlight = true;
      try {
        const apiUrl = apiBase;
        const requestStarted = performance.now();
        const response = await fetch(`${apiUrl}/api/health`);
        if (response.ok) {
          const data = await response.json();
          const healthLatencyMs = Math.max(0, performance.now() - requestStarted);
          setBackendStatus("CONNECTED");
          setSystemMetrics({
            ...(data.system_metrics || {}),
            health_latency_ms: Math.round(healthLatencyMs * 10) / 10,
            sampled_at_ms: Date.now(),
          });
          setActivityText(prev => prev.startsWith("Connecting") || prev.startsWith("Backend")
            ? "Ready — local backend connected."
            : prev);
        } else {
          setBackendStatus("ERROR");
          setSystemMetrics(null);
          setActivityText("Backend health check returned an error.");
        }
      } catch (err) {
        setBackendStatus("DISCONNECTED");
        setSystemMetrics(null);
        setActivityText("Backend disconnected — waiting for the local service.");
      } finally {
        inFlight = false;
        scheduleNext();
      }
    };

    const handleVisibility = () => {
      clearTimeout(timer);
      if (document.hidden) scheduleNext();
      else checkHealth();
    };

    checkHealth();
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, []);

  // Read redacted provider configuration only after the local backend is healthy.
  // This is configuration state, not a claim that any provider was live-tested.
  useEffect(() => {
    let cancelled = false;
    if (backendStatus !== 'CONNECTED') {
      setProviderStatus(null);
      return () => { cancelled = true; };
    }

    const loadProviderStatus = async () => {
      try {
        const report = await api('/api/providers/status');
        if (!cancelled) setProviderStatus({ ...report, state: 'reported' });
      } catch (_error) {
        if (!cancelled) setProviderStatus({ providers: {}, state: 'unavailable' });
      }
    };
    loadProviderStatus();
    return () => { cancelled = true; };
  }, [backendStatus]);

  // Jarvis-style briefing once on the first successful UI open of each local calendar day.
  useEffect(() => {
    if (backendStatus !== 'CONNECTED' || briefingAttemptedRef.current) return;

    const now = new Date();
    const dateKey = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, '0'),
      String(now.getDate()).padStart(2, '0'),
    ].join('-');
    try {
      if (window.localStorage.getItem('ultron_daily_briefing_date') === dateKey) {
        briefingAttemptedRef.current = true;
        return;
      }
    } catch (_error) {
      // Storage can be blocked by browser privacy settings; page-level guard still prevents repeats.
    }

    briefingAttemptedRef.current = true;
    const runFirstOpenBriefing = async () => {
      setActivityText("Preparing today’s first-open Jarvis briefing…");
      try {
        const result = await executeTool('daily_briefing', {
          include_weather: true,
          include_tasks: true,
          include_schedule: true,
          include_news: true,
        });
        if (!result.success) throw new Error(result.error || 'Daily briefing unavailable.');
        try {
          window.localStorage.setItem('ultron_daily_briefing_date', dateKey);
        } catch (_error) {
          // Briefing still works when persistent browser storage is unavailable.
        }
        const text = result.data?.briefing_text || 'Daily briefing returned no text.';
        setMessages(prev => [...prev, {
          id: `daily_briefing_${dateKey}`,
          sender: 'ai',
          text,
          personality: activePersonality,
          response_ms: 0,
        }]);
        // Speak the short natural version; the chat shows the full text.
        const spoken = result.data?.speech || text;
        const speakBriefing = async () => {
          setAiState('speaking');
          setActivityText("Daily briefing — speaking…");
          const outcome = await speakResponse(spoken, activePersonality, { quietBlocked: true });
          setAiState('idle');
          setActivityText("Ready — ask Ultron anything.");
          return outcome;
        };
        const outcome = await speakBriefing();
        if (isPlaybackBlocked(outcome)) {
          // Browsers block sound until the owner touches the page once. Wait
          // for that first click/key and then speak — the briefing is not lost.
          addNotification('Your briefing is ready', 'Click anywhere or press any key and I will read it.', 'low');
          setActivityText("Briefing ready — click anywhere to hear it.");
          const replay = () => {
            window.removeEventListener('pointerdown', replay, true);
            window.removeEventListener('keydown', replay, true);
            speakBriefing();
          };
          window.addEventListener('pointerdown', replay, true);
          window.addEventListener('keydown', replay, true);
        }
      } catch (error) {
        setActivityText(`Daily briefing unavailable: ${error.message || 'no sourced data'}`);
        addNotification('Daily briefing unavailable', error.message || 'No values were substituted.', 'medium');
      }
    };
    runFirstOpenBriefing();
  }, [backendStatus]);

  // The backend decides who answered ("Hey Zora", "back to work", stress
  // handoff). Mirror it so the screen, theme and next toggle stay truthful.
  const followPersonality = useCallback((personality) => {
    if (personality === 'ultron' || personality === 'zora') setActivePersonality(personality);
  }, []);

  // Persist UI personality selection; never claim a switch that the backend rejected.
  const togglePersonality = async () => {
    if (personalitySaving) return;
    const nextPers = activePersonality === "ultron" ? "zora" : "ultron";
    setPersonalitySaving(true);
    setAiState("planning");
    setActivityText(`Saving ${nextPers} as the active personality…`);
    try {
      const result = await api('/api/personality', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, personality: nextPers }),
      });
      if (!result.success) throw new Error('Personality update was not accepted.');
      setSessionId(result.session_id);
      setActivePersonality(result.personality);
      setActivityText(`${result.personality} selected and saved for this session.`);
      addNotification('Personality selected', `${result.personality} will answer the next turn.`, 'low');
    } catch (err) {
      setActivityText(`Personality unchanged: ${err.message || 'backend unavailable'}`);
      addNotification('Personality unchanged', err.message || 'Backend unavailable.', 'medium');
    } finally {
      setPersonalitySaving(false);
      setAiState("idle");
    }
  };

  // Toggle Coding Mode (manual override -> NVIDIA brain for all turns)
  const toggleCodingMode = async () => {
    if (codingModeSaving) return;
    const next = !codingMode;
    setCodingModeSaving(true);
    setActivityText(next ? 'Enabling forced NVIDIA coding mode…' : 'Returning coding mode to Auto…');
    try {
      const result = await api('/api/coding-mode', {
        method: 'POST',
        body: JSON.stringify({ enabled: next }),
      });
      if (!result.success) throw new Error('Backend rejected the coding-mode update.');
      setCodingMode(Boolean(result.coding_mode));
      const modeLabel = result.coding_mode ? 'Forced NVIDIA' : 'Auto';
      setActivityText(`Coding mode: ${modeLabel}.`);
      addNotification('Coding Mode', `Coding mode: ${modeLabel}.`, 'low');
    } catch (err) {
      setActivityText(`Coding mode unchanged: ${err.message || 'backend offline'}`);
      addNotification('Coding Mode unchanged', err.message || 'Backend offline.', 'medium');
    } finally {
      setCodingModeSaving(false);
    }
  };

  // Handle a coding response: auto-open the coding panel + log it (so the user
  // doesn't have to go click a button — it follows the conversation).
  const handleCodingResponse = (data) => {
    if (!data.coding) return;
    const short = (data.content || "").slice(0, 220);
    setCodingLog(prev => [...prev.slice(-19), short]);
    setWidgetState(prev => ({
      ...prev,
      coding: { ...prev.coding, visible: true }
    }));
  };

  // Execute the exact stored action. No prompt replay and no second LLM decision.
  // Ultron then finishes the job (or tries another way) and the outcome is saved
  // into chat memory by the backend. A lock stops click + voice running it twice.
  const confirmLockRef = useRef(false);
  const handleConfirmRun = async (options) => {
    const spoken = Boolean(options && options.spoken === true);
    const action = pendingAction;
    if (!action?.confirmation_token || confirmingAction || confirmLockRef.current) return;
    confirmLockRef.current = true;
    setConfirmingAction(true);
    setActivityText('Working on it…');
    const say = (text, priority = 'medium', title = 'Ultron') => {
      if (!text) return;
      setMessages(prev => [...prev, {
        id: `confirmed_${Date.now()}`, sender: 'ai', text, personality: activePersonality,
      }]);
      if (spoken || priority === 'high') void speakResponse(text, activePersonality);
      addNotification(title, text, priority);
    };
    try {
      const result = await api('/api/actions/confirm', {
        method: 'POST',
        body: JSON.stringify({
          confirmation_token: action.confirmation_token,
          session_id: action.session_id || sessionIdRef.current || sessionId,
        }),
      });
      action.onResult?.(result);
      const nextPending = result.pending_confirmation?.confirmation_token
        ? { ...result.pending_confirmation, session_id: action.session_id || sessionIdRef.current }
        : null;
      setPendingAction(nextPending);
      const message = result.data?.message || '';
      if (result.status === 'ALREADY_DONE') {
        setActivityText('Already done.');
      } else if (result.success) {
        const offer = result.trust_offer || null;
        say(offer?.question ? `${message || 'Done, Sir.'} ${offer.question}` : (message || 'Done, Sir.'));
        setActivityText(nextPending ? (nextPending.message || 'One more step needs your OK.') : 'Done.');
      } else if (result.status === 'CONFIRMATION_REJECTED') {
        say(result.error || 'That request is no longer waiting, Sir. Say it again.', 'high', 'Please ask again');
        setActivityText('Please ask again.');
      } else {
        // The OK worked; the job itself failed. Ultron's own explanation comes first.
        say(message || `That did not work, Sir. ${result.error || ''}`.trim(), 'high', "Couldn't finish");
        setActivityText("Couldn't finish.");
      }
    } catch (err) {
      action.onResult?.({ success: false, error: err.message || 'backend unavailable' });
      setActivityText(`Ultron is offline: ${err.message || 'backend unavailable'}`);
      addNotification('Ultron is offline', err.message || 'Backend unavailable.', 'high');
    } finally {
      confirmLockRef.current = false;
      setConfirmingAction(false);
    }
  };

  // Widgets (Terminal, Code optimizer...) ask through this same confirm bar.
  useEffect(() => {
    window.__ultronConfirmBar = true;
    const onWidgetConfirm = (event) => {
      const { pending, sessionId: widgetSession, resolve } = event.detail || {};
      if (!pending?.confirmation_token) return;
      setPendingAction({ ...pending, session_id: widgetSession, onResult: resolve });
      setActivityText(pending.message || 'Waiting for your OK.');
      addNotification('Your OK is needed', pending.message || 'Say yes or no.', 'high');
    };
    window.addEventListener('ultron:confirm', onWidgetConfirm);
    return () => {
      window.removeEventListener('ultron:confirm', onWidgetConfirm);
      window.__ultronConfirmBar = false;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Owner said no (voice/chat): drop the stored action for good.
  const cancelPendingAction = async () => {
    const action = pendingAction;
    setPendingAction(null);
    if (!action?.confirmation_token) return;
    action.onResult?.({ success: false, status: 'CANCELLED', error: 'Cancelled.' });
    try {
      await api('/api/actions/cancel', {
        method: 'POST',
        body: JSON.stringify({
          confirmation_token: action.confirmation_token,
          session_id: action.session_id || sessionIdRef.current || sessionId,
        }),
      });
    } catch { /* token expires by itself */ }
    const text = 'Cancelled, Sir. Nothing was changed.';
    setMessages(prev => [...prev, { id: `cancel_${Date.now()}`, sender: 'ai', text, personality: activePersonality }]);
    setActivityText(`Cancelled: ${action.tool_id}.`);
    void speakResponse(text, activePersonality);
  };

  // "Always allow?" is answered by voice or text: the brain calls owner_reply(always).

  // Owner answers ("ok do", "haan karo", "no leave it") are NOT caught here by a
  // word list any more: they go to the brain, which calls owner_reply itself.

  // Existing Edge-TTS lifecycle. Stop Voice aborts both the browser fetch and
  // playback. Browsers with MSE audio/mpeg support begin from streamed chunks;
  // others use the verified complete-blob fallback.
  const audioRef = useRef(null);
  const speechFetchControllerRef = useRef(null);
  const speechRequestRef = useRef(0);

  const stopSpeaking = useCallback((reason = "interrupted") => {
    speechRequestRef.current += 1;
    const fetchController = speechFetchControllerRef.current;
    speechFetchControllerRef.current = null;
    try { fetchController?.abort(); } catch (_e) {}

    const current = audioRef.current;
    audioRef.current = null;
    if (current) {
      try { current.audio.pause(); } catch (_e) {}
      current.finish(reason);
      try { current.audio.src = ""; } catch (_e) {}
      try { current.audio.load?.(); } catch (_e) {}
    }
    setIsSpeaking(false);
    return Boolean(current || fetchController);
  }, []);

  // Watchdog: if a browser never fires "ended" (stalled MSE stream, blocked
  // autoplay, sleeping tab), voice listening would stay paused forever with
  // "Ultron is speaking". Force-finish after a generous, length-aware limit.
  const speechWatchdogRef = useRef(null);
  const speechExpectedMsRef = useRef(0);
  useEffect(() => {
    if (speechWatchdogRef.current) {
      clearTimeout(speechWatchdogRef.current);
      speechWatchdogRef.current = null;
    }
    if (!isSpeaking) return undefined;
    const limit = Math.max(15000, speechExpectedMsRef.current || 0);
    speechWatchdogRef.current = setTimeout(() => {
      speechWatchdogRef.current = null;
      stopSpeaking("watchdog_timeout");
    }, limit);
    return () => {
      if (speechWatchdogRef.current) clearTimeout(speechWatchdogRef.current);
      speechWatchdogRef.current = null;
    };
  }, [isSpeaking, stopSpeaking]);

  const speakResponse = useCallback(async (text, personality = "ultron", options = {}) => {
    stopSpeaking("replaced");
    const requestId = speechRequestRef.current;
    if (!text || text.startsWith("[Offline]")) return { status: "skipped" };
    // ~13 spoken characters per second, doubled, plus network/start-up slack.
    speechExpectedMsRef.current = 10000 + Math.ceil(String(text).length / 13) * 2000;

    const fetchController = new AbortController();
    speechFetchControllerRef.current = fetchController;
    setIsSpeaking(true);
    try {
      const apiUrl = apiBase;
      const response = await fetch(`${apiUrl}/api/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, personality }),
        signal: fetchController.signal,
      });
      if (requestId !== speechRequestRef.current) return { status: "replaced" };
      if (!response.ok) {
        speechFetchControllerRef.current = null;
        setIsSpeaking(false);
        addNotification('Voice unavailable', `TTS request failed with status ${response.status}.`, 'medium');
        return { status: "error", error: `HTTP ${response.status}` };
      }

      const canStream = Boolean(
        response.body?.getReader
        && typeof MediaSource !== 'undefined'
        && MediaSource.isTypeSupported?.('audio/mpeg')
      );

      if (canStream) {
        return await new Promise((resolve) => {
          const mediaSource = new MediaSource();
          const url = URL.createObjectURL(mediaSource);
          const audio = new Audio(url);
          let settled = false;
          let reader = null;
          let sourceBuffer = null;
          let playbackStarted = false;

          const controller = {
            audio,
            finish: (status, error = null) => {
              if (settled) return;
              settled = true;
              audio.onended = null;
              audio.onerror = null;
              try { reader?.cancel(); } catch (_e) {}
              if (audioRef.current === controller) audioRef.current = null;
              if (speechFetchControllerRef.current === fetchController) {
                speechFetchControllerRef.current = null;
              }
              URL.revokeObjectURL(url);
              if (requestId === speechRequestRef.current) setIsSpeaking(false);
              resolve({ status, error });
            },
          };
          audioRef.current = controller;
          audio.onended = () => controller.finish("ended");
          audio.onerror = () => {
            addNotification('Voice unavailable', 'TTS audio playback failed.', 'medium');
            controller.finish("error", "audio_playback_failed");
          };

          const startPlayback = () => {
            if (playbackStarted || settled) return;
            playbackStarted = true;
            try {
              const playResult = audio.play();
              Promise.resolve(playResult).catch((error) => {
                if (!(options.quietBlocked && isPlaybackBlocked({ error: error?.name || error?.message }))) {
                  addNotification(...playbackProblem(error));
                }
                controller.finish("error", error?.name === 'NotAllowedError' ? 'playback_blocked' : (error?.message || "playback_blocked"));
              });
            } catch (error) {
              controller.finish("error", error?.message || "playback_failed");
            }
          };

          mediaSource.addEventListener('sourceopen', async () => {
            try {
              sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
              reader = response.body.getReader();
              while (!settled) {
                const { value, done } = await reader.read();
                if (done) break;
                if (!value?.byteLength) continue;
                await new Promise((appendResolve, appendReject) => {
                  const onEnd = () => {
                    sourceBuffer.removeEventListener('error', onError);
                    appendResolve();
                  };
                  const onError = () => {
                    sourceBuffer.removeEventListener('updateend', onEnd);
                    appendReject(new Error('TTS stream append failed.'));
                  };
                  sourceBuffer.addEventListener('updateend', onEnd, { once: true });
                  sourceBuffer.addEventListener('error', onError, { once: true });
                  sourceBuffer.appendBuffer(value);
                });
                startPlayback();
              }
              if (!settled && mediaSource.readyState === 'open') mediaSource.endOfStream();
              if (speechFetchControllerRef.current === fetchController) {
                speechFetchControllerRef.current = null;
              }
            } catch (error) {
              if (!settled && error?.name !== 'AbortError') {
                addNotification('Voice unavailable', error?.message || 'TTS stream failed.', 'medium');
                controller.finish("error", error?.message || "stream_failed");
              }
            }
          }, { once: true });
        });
      }

      const blob = await response.blob();
      if (speechFetchControllerRef.current === fetchController) {
        speechFetchControllerRef.current = null;
      }
      if (requestId !== speechRequestRef.current) return { status: "replaced" };
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);

      return await new Promise((resolve) => {
        let settled = false;
        const controller = {
          audio,
          finish: (status, error = null) => {
            if (settled) return;
            settled = true;
            audio.onended = null;
            audio.onerror = null;
            if (audioRef.current === controller) audioRef.current = null;
            URL.revokeObjectURL(url);
            if (requestId === speechRequestRef.current) setIsSpeaking(false);
            resolve({ status, error });
          },
        };
        audioRef.current = controller;
        audio.onended = () => controller.finish("ended");
        audio.onerror = () => {
          addNotification('Voice unavailable', 'TTS audio playback failed.', 'medium');
          controller.finish("error", "audio_playback_failed");
        };
        try {
          const playResult = audio.play();
          Promise.resolve(playResult).catch((error) => {
            if (!(options.quietBlocked && isPlaybackBlocked({ error: error?.name || error?.message }))) {
                  addNotification(...playbackProblem(error));
                }
            controller.finish("error", error?.name === 'NotAllowedError' ? 'playback_blocked' : (error?.message || "playback_blocked"));
          });
        } catch (error) {
          controller.finish("error", error?.message || "playback_failed");
        }
      });
    } catch (err) {
      if (speechFetchControllerRef.current === fetchController) {
        speechFetchControllerRef.current = null;
      }
      if (err?.name === 'AbortError' || requestId !== speechRequestRef.current) {
        return { status: "interrupted" };
      }
      if (requestId === speechRequestRef.current) setIsSpeaking(false);
      addNotification('Voice unavailable', err.message || 'TTS playback failed.', 'medium');
      return { status: "error", error: err.message || "tts_failed" };
    }
  }, [addNotification, stopSpeaking]);

  useEffect(() => () => { stopSpeaking("unmounted"); }, [stopSpeaking]);

  // ── V2 Step 2: reminders reach the owner (live, or "while you were away") ──
  const personalityRef = useRef(activePersonality);
  useEffect(() => { personalityRef.current = activePersonality; }, [activePersonality]);
  const speakRef = useRef(speakResponse);
  useEffect(() => { speakRef.current = speakResponse; }, [speakResponse]);

  const announceReminders = useCallback((plan) => {
    if (!plan || plan.action !== 'speak') return;
    const count = plan.items.length;
    const heading = plan.heading
      || (count > 1 ? `${count} reminders` : (plan.items[0].kind === 'alarm' ? 'Alarm' : 'Reminder'));
    setMessages(prev => [...prev, {
      id: `reminder_${plan.items.map(item => item.key).join('_')}`,
      sender: 'ai',
      text: plan.text,
      personality: personalityRef.current,
      response_ms: 0,
    }]);
    addNotification(heading, plan.items.map(item => item.title).join(', '), 'high');
    speakRef.current?.(plan.text, personalityRef.current);
  }, [addNotification]);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.WebSocket !== 'function') return undefined;
    const isHidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';
    const stop = connectEvents(`${websocketBase()}/ws/events?client_id=web-reminders`, (event) => {
      if (event?.type === 'ultron_progress') {
        // V2 Step C7: say along while working (spoken only for slow steps).
        const step = progressAction(event, { processing: processingRef.current, sessionId: sessionIdRef.current });
        if (step) {
          setActivityText(`${step.text}…`);
          if (step.speak) speakRef.current?.(step.text, personalityRef.current);
        }
        return;
      }
      const plan = planForEvent(event, { hidden: isHidden() });
      if (plan.action === 'queue') {
        // Away: a quiet system notification now, the spoken summary on return.
        try {
          if ('Notification' in window && window.Notification.permission === 'granted') {
            new window.Notification('Ultron reminder', { body: plan.items.map(item => item.title).join(', ') });
          }
        } catch (_error) { /* notifications unsupported */ }
        return;
      }
      announceReminders(plan);
    });
    const onVisible = () => { if (!isHidden()) announceReminders(planForReturn()); };
    document.addEventListener('visibilitychange', onVisible);
    onVisible();  // anything queued before a reload
    try {
      if ('Notification' in window && window.Notification.permission === 'default') {
        window.Notification.requestPermission().catch?.(() => {});
      }
    } catch (_error) { /* notifications unsupported */ }
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [announceReminders]);

  // V2 Step 8: welcome-back briefing when the owner shows up after 2+ hours
  // (app opened, or first click / key / mouse move after being idle).
  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    let cancelled = false;
    const tracker = createPresenceTracker();
    const check = async () => {
      try {
        const result = await api('/api/arrival');
        const briefing = result?.data;
        if (!cancelled && briefing?.type === 'arrival_briefing') {
          announceReminders(planForEvent(briefing, { hidden: false }));
        }
      } catch { /* backend offline: nothing to say */ }
    };
    const onActivity = () => { if (tracker.activity()) void check(); };
    const onVisible = () => { if (document.visibilityState !== 'hidden') onActivity(); };
    const events = ['pointerdown', 'keydown', 'mousemove', 'touchstart'];
    events.forEach(name => window.addEventListener(name, onActivity, { passive: true }));
    document.addEventListener('visibilitychange', onVisible);
    void check();  // app just opened: the backend knows how long he was gone
    return () => {
      cancelled = true;
      events.forEach(name => window.removeEventListener(name, onActivity));
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [announceReminders]);

  // Toggle individual widget visibility
  const toggleWidget = (widgetId) => {
    setWidgetState(prev => ({
      ...prev,
      [widgetId]: {
        ...prev[widgetId],
        visible: !prev[widgetId].visible
      }
    }));
  };

  // Submit a command directly (used by wake-word voice input)
  const handleVoiceCommand = async (text) => {
    const userText = String(text || "").trim();
    if (!userText || isProcessing || voiceRequestInFlightRef.current) return;
    voiceRequestInFlightRef.current = true;
    // Barge-in: the user is speaking — stop any in-progress TTS immediately.
    stopSpeaking();
    setVoiceClarification(null);
    setInputValue("");
    setIsProcessing(true);
    setAiState("thinking");
    setActivityText("Sending voice command to the backend…");

    const localUserMsgId = "user_" + Date.now();
    setMessages(prev => [...prev, { id: localUserMsgId, sender: "user", text: userText }]);

    try {
      const apiUrl = apiBase;
      const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          project_id: "personal",
          content: userText,
          // Provenance only. Browser STT text is sent; raw microphone audio is not.
          input_source: "voice",
        })
      });

      if (response.ok) {
        const data = await response.json();
        if (data.session_id) {
          sessionIdRef.current = data.session_id;
          setSessionId(data.session_id);
        }
        followPersonality(data.personality);
        setMessages(prev => [...prev, {
          id: data.id,
          sender: "ai",
          text: data.content,
          personality: data.personality,
          response_ms: data.response_ms,
          project_id: data.project_id || "personal",
          intent: data.intent || "",
          provider_route: data.provider_route || {},
          input_source: data.input_source || "voice",
          voice_alias_suggestions: data.voice_alias_suggestions || [],
          voice_clarification: data.voice_clarification || null,
          memory_provenance: data.memory_provenance || [],
          events: data.events || [],
          pending_confirmation: data.pending_confirmation || null,
        }]);
        setAiState("speaking");
        setActivityText("Voice command processed — speaking the response…");
        void speakResponse(data.content, data.personality || "ultron").then(() => {
          if (data.arrival?.speech) announceReminders(planForEvent(data.arrival, { hidden: false }));
          setAiState("idle");
          if (!data.pending_confirmation?.confirmation_token) {
            setActivityText("Ready — listening for your next turn.");
          }
        });
        const structured = data.structured_action;
        if (structured && structured.action && structured.action !== "none") {
          setWidgetState(prev => applyWidgetAction(prev, structured));
        }
        handleCodingResponse(data);
        if (data.events?.length) {
          const voiceLogs = data.events
            .filter(event => event.type === "log" && event.log)
            .map(event => ({ level: event.log.level, message: event.log.message }));
          if (voiceLogs.length) {
            setLogs(prev => [...prev, ...voiceLogs].slice(-80));
          }
        }
        if (data.pending_confirmation?.confirmation_token) {
          setPendingAction({ ...data.pending_confirmation, session_id: data.session_id || sessionIdRef.current });
          setActivityText(`Waiting for confirmation: ${data.pending_confirmation.tool_id}.`);
          addNotification('Confirmation required', data.pending_confirmation.message, 'high');
        } else {
          // The brain answered the question (or moved on): the chat's yellow bar closes.
          // A widget's own confirm (it has onResult) stays until its buttons are used.
          setPendingAction(prev => (prev?.onResult ? prev : null));
        }
        setVoiceClarification(data.voice_clarification || null);
      } else {
        setMessages(prev => [...prev, {
          id: "error_" + Date.now(), sender: "system_error",
          text: "System communication error."
        }]);
        setAiState("idle");
        setActivityText("Voice command failed — backend returned an error.");
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        id: "error_" + Date.now(), sender: "system_error",
        text: "Dropped. Backend server is offline."
      }]);
      setAiState("idle");
      setActivityText("Voice command dropped — backend is offline.");
    } finally {
      voiceRequestInFlightRef.current = false;
      setIsProcessing(false);
    }
  };

  // A clarification option is explicit owner input. Send the exact selected
  // wording back through the same canonical voice transport; no tool is picked
  // by the browser/UI itself.
  const handleVoiceClarificationChoice = (choice) => {
    const selected = String(choice || '').trim();
    if (!selected || isProcessing) return;
    setVoiceClarification(null);
    void handleVoiceCommand(selected);
  };

  const handleVoicePreferenceSave = async (offer) => {
    if (!offer?.alias || !offer?.canonical || voicePreferenceSaving) return;
    setVoicePreferenceSaving(true);
    try {
      const result = await api('/api/voice/preferences', {
        method: 'POST',
        body: JSON.stringify({ alias: offer.alias, canonical: offer.canonical }),
      });
      if (!result.success) throw new Error('Voice preference was not saved.');
      setVoiceClarification((current) => current
        ? { ...current, preference_offer: null }
        : current);
      addNotification('Voice preference saved', `I will understand ${offer.alias} as ${offer.canonical}.`, 'low');
    } catch (error) {
      addNotification('Voice preference not saved', error.message || 'Please try again.', 'medium');
    } finally {
      setVoicePreferenceSaving(false);
    }
  };

  // Dispatch REST messages through canonical WebSocket/REST transport.
  // The provider finishes first; the backend then sends one exact completed-content
  // frame plus real progress/events instead of simulated token timing.
  const wsRef = useRef(null);
  const sendViaWS = (text) => {
    return new Promise((resolve) => {
      const apiUrl = apiBase;
      const wsBase = websocketBase();
      let ws;
      let openedAndSent = false;
      let settled = false;
      let timeoutId = null;
      let acc = "";

      const finish = (data, canFallback, error = null) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutId);
        if (wsRef.current === ws) wsRef.current = null;
        try { ws?.close(); } catch {}
        if (error) setActivityText(error);
        resolve({ data, canFallback, error });
      };

      try {
        ws = new WebSocket(`${wsBase}/ws/chat?client_id=web`);
      } catch (error) {
        finish(null, true, error.message || 'WebSocket could not be created.');
        return;
      }
      wsRef.current = ws;
      ws.onopen = () => {
        try {
          ws.send(JSON.stringify({ content: text, session_id: sessionId || "" }));
          openedAndSent = true;
        } catch (error) {
          finish(null, true, error.message || 'WebSocket send failed.');
        }
      };
      ws.onmessage = (ev) => {
        let msg; try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === "progress") {
          setActivityText(msg.detail || "Backend is processing the request…");
          return;
        }
        if (msg.type === "token") {
          acc += msg.content;
          setActivityText("Receiving the completed response…");
        } else if (msg.type === "error") {
          setActivityText(`Chat stream error: ${msg.message || 'backend error'}`);
          finish(null, false, msg.message || 'Backend WebSocket returned an error.');
        } else if (msg.type === "done") {
          setActivityText("Response received — updating the workspace…");
          finish({
            id: msg.message_id,
            content: acc,
            personality: msg.active_personality,
            response_ms: msg.response_ms,
            coding: msg.coding,
            intent: msg.intent,
            events: msg.events || [],
            structured_action: msg.structured_action || {},
            session_id: msg.session_id || null,
            provider_route: msg.provider_route || {},
            pending_confirmation: msg.pending_confirmation || null,
            memory_provenance: msg.memory_provenance || [],
            arrival: msg.arrival || null
          }, false);
        }
      };
      ws.onerror = () => finish(
        null,
        !openedAndSent,
        openedAndSent ? 'WebSocket failed after the request was sent; it was not replayed.' : 'WebSocket connection failed.'
      );
      ws.onclose = () => finish(
        null,
        !openedAndSent,
        openedAndSent ? 'WebSocket closed before completion; it was not replayed.' : 'WebSocket did not connect.'
      );
      timeoutId = setTimeout(
        () => finish(null, false, 'WebSocket timed out after the request was sent; it was not replayed.'),
        90000,
      );
    });
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!inputValue.trim() || isProcessing) return;

    const userText = inputValue.trim();
    setInputValue("");
    setIsProcessing(true);
    setAiState("thinking");
    setActivityText("Connecting to chat stream…");

    const localUserMsgId = "user_" + Date.now();
    setMessages(prev => [...prev, { id: localUserMsgId, sender: "user", text: userText }]);

    // NOTE: CONSTITUTIONAL COMPLIANCE (Rule 7, 8)
    // Removed all local client-side keyword-based widget toggling checks.
    // The backend's Structured AI Action is the sole trigger governing the UI.

    try {
      // Stream through WebSocket. REST fallback is allowed only if the request
      // was never sent, preventing duplicate tool/chat side effects.
      const wsResult = await sendViaWS(userText);
      let data = wsResult.data;
      if (!data && wsResult.canFallback) {
        data = await api('/api/chat', {
          method: 'POST',
          body: JSON.stringify({
            session_id: sessionId,
            project_id: 'personal',
            content: userText,
          }),
        });
      }
      if (data) {
        // Reconcile session with the backend's resolved session id (if any).
        if (data.session_id) setSessionId(data.session_id);
        followPersonality(data.personality);

        setMessages(prev => [...prev, {
          id: data.id || ("ai_" + Date.now()),
          sender: "ai",
          text: data.content || "",
          personality: data.personality || "ultron",
          response_ms: data.response_ms
        }]);
        
        setAiState("speaking");
        setActivityText(data.coding ? "Coding response ready — updating coding tools…" : "Response ready — speaking…");
        let speechSequence = speakResponse(data.content, data.personality || "ultron");
        handleCodingResponse(data);
        if (data.pending_confirmation?.confirmation_token) {
          setPendingAction({ ...data.pending_confirmation, session_id: data.session_id || sessionIdRef.current });
          setActivityText(`Waiting for confirmation: ${data.pending_confirmation.tool_id}.`);
          addNotification('Confirmation required', data.pending_confirmation.message, 'high');
        } else {
          // The brain answered the question (or moved on): the chat's yellow bar closes.
          // A widget's own confirm (it has onResult) stays until its buttons are used.
          setPendingAction(prev => (prev?.onResult ? prev : null));
        }
        // Open widgets driven ONLY by the backend structured action (never keyword guesses).
        // (open_widget / close_widget / close_all_widgets, refresh reloads an open panel).
        const structured = data.structured_action;
        if (structured && structured.action && structured.action !== "none") {
          setWidgetState(prev => applyWidgetAction(prev, structured));
        }
        // Log tab: collect real-time tool/activity events
        if (data.events && data.events.length) {
          const logLines = data.events.filter(e => e.type === "log").map(e => ({ level: e.log.level, message: e.log.message }));
          if (logLines.length) {
            // Logs are for the Log tab only; Ultron already spoke live while working.
            setLogs(prev => [...prev, ...logLines].slice(-80));
          }
        }
        if (data.arrival?.speech) {
          // Back after 2+ hours: the welcome-back briefing follows the answer.
          speechSequence = speechSequence.then(() => announceReminders(planForEvent(data.arrival, { hidden: false })));
        }
        void speechSequence.then(() => {
          setAiState("idle");
          if (!data.pending_confirmation?.confirmation_token) {
            setActivityText("Ready — ask Ultron anything.");
          }
        });
      } else {
        setMessages(prev => [...prev, {
          id: "error_" + Date.now(),
          sender: "system_error",
          text: wsResult.error || "System communication error."
        }]);
        setAiState("idle");
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        id: "error_" + Date.now(),
        sender: "system_error",
        text: err.message || "Backend request failed."
      }]);
      setAiState("idle");
      setActivityText(`Request failed: ${err.message || 'backend unavailable'}`);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-transparent">
      {/* 3-Panel Main Widescreen Layout */}
      <AppShell 
        messages={messages}
        inputValue={inputValue}
        setInputValue={setInputValue}
        handleSendMessage={handleSendMessage}
        isProcessing={isProcessing}
        activePersonality={activePersonality}
        backendStatus={backendStatus}
        providerStatus={providerStatus}
        systemMetrics={systemMetrics}
        aiState={aiState}
        activityText={activityText}
        setAiState={setAiState}
        togglePersonality={togglePersonality}
        personalitySaving={personalitySaving}
        widgetState={widgetState}
        toggleWidget={toggleWidget}
        handleVoiceCommand={handleVoiceCommand}
        voicePaused={isProcessing || isSpeaking}
        onVoiceStop={stopSpeaking}
        voiceClarification={voiceClarification}
        onVoiceClarificationChoice={handleVoiceClarificationChoice}
        onVoicePreferenceSave={handleVoicePreferenceSave}
        voicePreferenceSaving={voicePreferenceSaving}
        codingMode={codingMode}
        toggleCodingMode={toggleCodingMode}
        codingModeSaving={codingModeSaving}
        codingLog={codingLog}
        onConfirmRun={handleConfirmRun}
        onCancelPending={cancelPendingAction}
        pendingAction={pendingAction}
        confirmingAction={confirmingAction}
        logs={logs}
      />

      {/* ==============================================================================
          4. FLOATING NOTIFICATION TOAST OVERLAYS (Requirement: Notification Prioritization)
         ============================================================================== */}
      <div className="absolute top-6 right-6 z-[1000] flex flex-col gap-3 pointer-events-none font-mono">
        {notifications.map(notif => (
          <div key={notif.id} className="pointer-events-auto animate-slide-in">
            <NotificationToast 
              id={notif.id}
              title={notif.title}
              message={notif.message}
              priority={notif.priority}
              onDismiss={dismissNotification}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
