import React, { useState, useEffect, useRef, useCallback } from 'react';
import AppShell from './components/AppShell';
import NotificationToast from './components/NotificationToast';
import { api, executeTool } from './api';

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
  // Coding Mode (NVIDIA brain) — manual toggle synced to backend /api/coding-mode
  const [codingMode, setCodingMode] = useState(false);
  const [codingModeSaving, setCodingModeSaving] = useState(false);
  // Coding activity log shown in the CodingWidget; auto-opened on coding turns.
  const [codingLog, setCodingLog] = useState([]);
  // Exact one-time action returned by the backend; never regenerate on confirm.
  const [pendingAction, setPendingAction] = useState(null);
  const [confirmingAction, setConfirmingAction] = useState(false);
  // Real-time operational log (Log tab)
  const [logs, setLogs] = useState([]);
  // One first-open briefing attempt per browser page; localStorage prevents repeats that day.
  const briefingAttemptedRef = useRef(false);

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
    memory: { visible: false, x: 260, y: 180 },
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
  const addNotification = (title, message, priority = "low") => {
    const newId = "notif_" + Date.now() + "_" + Math.random().toString(36).substr(2, 5);
    setNotifications(prev => [...prev, { id: newId, title, message, priority }]);
  };

  // Dismiss an active notification toast
  const dismissNotification = (id) => {
    setNotifications(prev => prev.filter(notif => notif.id !== id));
  };

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
        const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
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
        addNotification('Daily briefing ready', 'Jarvis briefing loaded from current local and live sources.', 'low');
        setAiState('speaking');
        speakResponse(text, activePersonality);
        setActivityText("Daily briefing ready.");
        setTimeout(() => {
          setAiState('idle');
          setActivityText("Ready — ask Ultron anything.");
        }, 1200);
      } catch (error) {
        setActivityText(`Daily briefing unavailable: ${error.message || 'no sourced data'}`);
        addNotification('Daily briefing unavailable', error.message || 'No values were substituted.', 'medium');
      }
    };
    runFirstOpenBriefing();
  }, [backendStatus]);

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
    setActivityText(`${next ? 'Enabling' : 'Disabling'} coding mode…`);
    try {
      const result = await api('/api/coding-mode', {
        method: 'POST',
        body: JSON.stringify({ enabled: next }),
      });
      if (!result.success) throw new Error('Backend rejected the coding-mode update.');
      setCodingMode(Boolean(result.coding_mode));
      setActivityText(`Coding mode ${result.coding_mode ? 'enabled' : 'disabled'}.`);
      addNotification('Coding Mode', `Coding mode ${result.coding_mode ? 'enabled' : 'disabled'}.`, 'low');
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
  const handleConfirmRun = async () => {
    if (!pendingAction?.confirmation_token || confirmingAction) return;
    setConfirmingAction(true);
    setActivityText(`Running confirmed action: ${pendingAction.tool_id}…`);
    try {
      const result = await api('/api/actions/confirm', {
        method: 'POST',
        body: JSON.stringify({
          confirmation_token: pendingAction.confirmation_token,
          session_id: sessionId,
        }),
      });
      if (result.success) {
        const message = result.data?.message || `Confirmed action ${pendingAction.tool_id} completed.`;
        setMessages(prev => [...prev, {
          id: `confirmed_${Date.now()}`,
          sender: 'ai',
          text: message,
          personality: activePersonality,
          response_ms: result.metadata?.execution_time_ms || 0,
        }]);
        setPendingAction(null);
        setActivityText(`Confirmed action completed: ${pendingAction.tool_id}.`);
        addNotification('Action completed', message, 'medium');
      } else {
        setActivityText(`Confirmed action failed: ${result.error || 'not executed'}`);
        addNotification('Confirmation failed', result.error || 'The pending action was not executed.', 'high');
        if (result.status === 'CONFIRMATION_REJECTED') setPendingAction(null);
      }
    } catch (err) {
      setActivityText(`Confirmation failed: ${err.message || 'backend unavailable'}`);
      addNotification('Confirmation failed', err.message || 'Backend unavailable.', 'high');
    } finally {
      setConfirmingAction(false);
    }
  };

  // P1: speak the AI response aloud via /api/speak (real TTS).
  // A module-level ref tracks the current Audio so barge-in / new speech can stop
  // any in-progress playback (no overlapping voices).
  const audioRef = useRef(null);

  const stopSpeaking = useCallback(() => {
    if (audioRef.current) {
      try { audioRef.current.pause(); } catch (_e) {}
      try { audioRef.current.src = ""; } catch (_e) {}
      audioRef.current = null;
    }
  }, []);

  const speakResponse = async (text, personality = "ultron") => {
    if (!text || text.startsWith("[Offline]")) return; // no synthesized speech for unavailable AI output
    try {
      // Stop any currently-playing TTS before starting a new one (barge-in / no overlap).
      stopSpeaking();
      const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, personality })
      });
      if (!res.ok) {
        addNotification('Voice unavailable', `TTS request failed with status ${res.status}.`, 'medium');
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      await audio.play().catch(() => {});
      audio.onended = () => {
        if (audioRef.current === audio) audioRef.current = null;
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        if (audioRef.current === audio) audioRef.current = null;
        URL.revokeObjectURL(url);
      };
    } catch (err) {
      addNotification('Voice unavailable', err.message || 'TTS playback failed.', 'medium');
    }
  };

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
    if (!text.trim() || isProcessing) return;
    // Barge-in: the user is speaking — stop any in-progress TTS immediately.
    stopSpeaking();
    const userText = text.trim();
    setInputValue("");
    setIsProcessing(true);
    setAiState("thinking");
    setActivityText("Sending voice command to the backend…");

    const localUserMsgId = "user_" + Date.now();
    setMessages(prev => [...prev, { id: localUserMsgId, sender: "user", text: userText }]);

    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
      const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, content: userText })
      });

      if (response.ok) {
        const data = await response.json();
        if (!sessionId) setSessionId(data.session_id);
        setMessages(prev => [...prev, {
          id: data.id,
          sender: "ai",
          text: data.content,
          personality: data.personality,
          response_ms: data.response_ms
        }]);
        setAiState("speaking");
        setActivityText("Voice command processed — speaking the response…");
        speakResponse(data.content, data.personality || "ultron");
        setTimeout(() => {
          setAiState("idle");
          if (!data.pending_confirmation?.confirmation_token) {
            setActivityText("Ready — ask Ultron anything.");
          }
        }, 1200);
        const structured = data.structured_action;
        if (structured && structured.action === "open_widget") {
          const targetWidgetId = structured.widget_id;
          setWidgetState(prev => ({
            ...prev,
            [targetWidgetId]: { ...prev[targetWidgetId], visible: true }
          }));
        }
        handleCodingResponse(data);
        if (data.pending_confirmation?.confirmation_token) {
          setPendingAction(data.pending_confirmation);
          setActivityText(`Waiting for confirmation: ${data.pending_confirmation.tool_id}.`);
          addNotification('Confirmation required', data.pending_confirmation.message, 'high');
        }
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
      setIsProcessing(false);
    }
  };

  // Dispatch REST messages
  // C-1: real WebSocket streaming for chat (Jarvis-style token-by-token).
  const wsRef = useRef(null);
  const sendViaWS = (text) => {
    return new Promise((resolve) => {
      const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
      const wsBase = apiUrl.replace(/^http/, "ws");
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
          setActivityText("Ultron is streaming the response…");
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
            pending_confirmation: msg.pending_confirmation || null
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

        setMessages(prev => [...prev, {
          id: data.id || ("ai_" + Date.now()),
          sender: "ai",
          text: data.content || "",
          personality: data.personality || "ultron",
          response_ms: data.response_ms
        }]);
        
        setAiState("speaking");
        setActivityText(data.coding ? "Coding response ready — updating coding tools…" : "Response ready — speaking…");
        speakResponse(data.content, data.personality || "ultron");
        setTimeout(() => {
          setAiState("idle");
          if (!data.pending_confirmation?.confirmation_token) {
            setActivityText("Ready — ask Ultron anything.");
          }
        }, 1200);
        handleCodingResponse(data);
        if (data.pending_confirmation?.confirmation_token) {
          setPendingAction(data.pending_confirmation);
          setActivityText(`Waiting for confirmation: ${data.pending_confirmation.tool_id}.`);
          addNotification('Confirmation required', data.pending_confirmation.message, 'high');
        }
        // Open widgets driven ONLY by the backend structured action (never keyword guesses).
        const structured = data.structured_action;
        if (structured && structured.action === "open_widget" && structured.widget_id) {
          setWidgetState(prev => ({
            ...prev,
            [structured.widget_id]: { ...prev[structured.widget_id], visible: true }
          }));
        }
        // Log tab: collect real-time tool/activity events
        if (data.events && data.events.length) {
          const logLines = data.events.filter(e => e.type === "log").map(e => ({ level: e.log.level, message: e.log.message }));
          if (logLines.length) {
            setLogs(prev => [...prev, ...logLines].slice(-80));
            // Speak the Jarvis narration live (info lines only, skip the final Done.)
            const narration = logLines.find(l => l.level === "info");
            if (narration) speakResponse(narration.message, data.personality || "ultron");
          }
        }
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
        codingMode={codingMode}
        toggleCodingMode={toggleCodingMode}
        codingModeSaving={codingModeSaving}
        codingLog={codingLog}
        onConfirmRun={handleConfirmRun}
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
