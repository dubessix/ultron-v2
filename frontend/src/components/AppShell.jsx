import React, { useState } from 'react';
import { Check, Code2, KeyRound, Mic, Orbit, Server } from 'lucide-react';
import LeftPanel from './LeftPanel';
import RightPanel from './RightPanel';
import BlobCanvas from './BlobCanvas';
import WidgetRail from './WidgetRail';
import useVoice from '../hooks/useVoice';
import { getPersonalityTheme } from '../theme/personalityTheme';

// Import dynamic widget registry structures (Requirement: Never hardcode widgets in AppShell)
import { WIDGET_REGISTRY } from './widgets/WidgetManager';
import WidgetContainer from './widgets/WidgetContainer';

/**
 * AppShell Component
 * Implements the responsive 3-panel widescreen dashboard layout.
 * Houses left system stats, center canvas particle core, right chat dialogues,
 * and dynamically iterates over the WIDGET_REGISTRY to render open draggable widgets.
 * The identity name + accent color switch dynamically between Ultron (emerald)
 * and Zora (pink). The bottom mic toggles browser-native wake-word listening.
 */
export default function AppShell({ 
  messages, 
  inputValue, 
  setInputValue, 
  handleSendMessage, 
  isProcessing, 
  activePersonality,
  backendStatus,
  providerStatus,
  systemMetrics,
  aiState,
  activityText,
  setAiState,
  togglePersonality,
  personalitySaving,
  widgetState,
  toggleWidget,
  handleVoiceCommand,
  codingMode,
  toggleCodingMode,
  codingModeSaving,
  codingLog,
  onConfirmRun,
  pendingAction,
  confirmingAction,
  logs
}) {
  const isZora = activePersonality === "zora";
  const theme = getPersonalityTheme(activePersonality);
  const accentText = isZora ? "text-pink-400" : "text-emerald-400";
  const accentRing = isZora ? "border-pink-400/30" : "border-emerald-400/30";
  const accentBg = isZora ? "bg-pink-500/10" : "bg-emerald-500/10";
  const accentDot = isZora ? "bg-pink-400" : "bg-emerald-400";
  const aiName = theme.name;
  const backendConnected = backendStatus === "CONNECTED";
  const providerEntries = Object.entries(providerStatus?.providers || {});
  const configuredProviderCount = providerEntries.filter(([, item]) => item?.configured).length;
  const providerCount = providerEntries.length;
  const providerReported = providerStatus?.state === 'reported' && providerCount > 0;
  const providerUnavailable = backendConnected && providerStatus?.state === 'unavailable';
  const providerLabel = !backendConnected
    ? 'AI status offline'
    : providerUnavailable
      ? 'AI status unavailable'
      : !providerReported
        ? 'Checking AI status'
        : configuredProviderCount === 0
          ? 'No AI Provider'
          : `${configuredProviderCount}/${providerCount} AI Providers`;
  const providerTitle = providerReported
    ? providerEntries.map(([name, item]) => `${name.toUpperCase()}: ${item.configured ? 'configured' : 'not configured'}`).join(' · ')
    : providerLabel;

  // Voice control: wake-word listening wired to the bottom mic toggle.
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const voice = useVoice({
    enabled: voiceEnabled,
    onCommand: (cmd) => {
      if (handleVoiceCommand) handleVoiceCommand(cmd);
    }
  });

  const handleMicToggle = () => {
    setVoiceEnabled((prev) => !prev);
  };

  return (
    <div
      className="relative flex h-screen w-screen select-none overflow-hidden bg-transparent text-[#F5F5F7]"
      style={{
        '--identity-primary': theme.primary,
        '--identity-secondary': theme.secondary,
        '--identity-glow': theme.glow,
      }}
    >
      <WidgetRail
        widgetState={widgetState}
        toggleWidget={toggleWidget}
        activePersonality={activePersonality}
      />

      <div className="ultron-workspace relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-4 2xl:p-5">
      {/* ==============================================================================
          1. SYSTEM HEADER & TOP NAVIGATION (Dynamic assistant identity)
         ============================================================================== */}
      <header className="ultron-header relative z-10 mb-4 flex items-center justify-between border-b border-white/[0.06] pb-3 font-mono 2xl:mb-5 2xl:pb-4">
        <div className="flex min-w-0 items-center gap-3">
          <span
            role="img"
            aria-label={`${aiName} identity`}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border transition-all duration-500 2xl:h-10 2xl:w-10"
            style={{
              color: theme.primary,
              borderColor: theme.border,
              backgroundColor: theme.surface,
              boxShadow: `0 0 18px ${theme.glow}`,
            }}
          >
            <Orbit size={18} strokeWidth={1.8} aria-hidden="true" className="2xl:h-5 2xl:w-5" />
          </span>
          <span
            className={`text-2xl 2xl:text-3xl font-black italic tracking-tight uppercase transition-all duration-500 ${accentText}`}
            style={{
              fontFamily: "'Arial Black', 'Segoe UI', system-ui, sans-serif",
              color: theme.primary,
              textShadow: `0 0 18px ${theme.glow}`,
            }}
          >
            {aiName}
          </span>
          <span className="ultron-header-subtitle hidden border-l border-white/10 pl-3 text-[8px] uppercase tracking-[0.16em] text-white/38 xl:inline 2xl:text-[9px]">
            Personal Desktop Assistant
          </span>
        </div>

        {/* Claude-Code-style honest live activity text from real frontend/backend events. */}
        <div className="ultron-header-activity absolute left-1/2 -translate-x-1/2 max-w-[48%] text-center text-[9px] text-[#7DD3FC] tracking-wide truncate 2xl:text-[10px]" title={activityText}>
          {activityText || 'Ready'}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {/* Provider badge reports redacted configured-key state; it never implies a live check. */}
          <div
            className={`ultron-header-provider flex items-center gap-1.5 rounded-full border px-2 py-1.5 text-[7px] backdrop-blur-3xl 2xl:px-3 2xl:py-2 2xl:text-[8px] ${
              providerUnavailable || !backendConnected
                ? 'border-amber-400/20 bg-amber-500/5 text-amber-300'
                : configuredProviderCount > 0
                  ? `${accentRing} ${accentBg} ${accentText}`
                  : 'border-white/[0.08] bg-white/[0.025] text-white/45'
            }`}
            title={providerTitle}
            data-provider-state={providerStatus?.state || 'offline'}
          >
            <KeyRound size={11} strokeWidth={1.8} aria-hidden="true" />
            <span className="max-w-32 truncate font-bold uppercase tracking-wider">{providerLabel}</span>
          </div>

          {/* Backend status comes from the real /api/health poll. */}
          <div className={`ultron-header-backend flex items-center gap-1.5 rounded-full border px-2 py-1.5 text-[8px] backdrop-blur-3xl 2xl:px-3 2xl:py-2 2xl:text-[9px] ${backendConnected ? `${accentRing} ${accentBg}` : 'border-amber-400/20 bg-amber-500/5'}`}>
            <Server size={11} strokeWidth={1.8} className={backendConnected ? accentText : 'text-amber-300'} aria-hidden="true" />
            <div className={`h-1.5 w-1.5 rounded-full ${backendConnected ? accentDot : 'bg-amber-400'}`} />
            <span className={`font-bold tracking-widest uppercase ${backendConnected ? accentText : 'text-amber-300'}`}>
              Backend {backendStatus || 'UNKNOWN'}
            </span>
          </div>
        </div>
      </header>

      {/* 2. THREE-PANEL CORE GRID WORKSPACE */}
      <div className="ultron-grid z-10 grid min-h-0 flex-1 grid-cols-12 items-stretch gap-4 overflow-hidden 2xl:gap-5">
        
        {/* Left column: Relational resource meters */}
        <LeftPanel systemMetrics={systemMetrics} backendStatus={backendStatus} />

        {/* Center column: HTML5 Canvas particle loop & concentric orbital rings */}
        <main className="ultron-core-panel relative col-span-12 flex min-h-0 min-w-0 flex-col items-center justify-center overflow-hidden rounded-xl border border-white/[0.07] bg-[#080C0F]/60 p-6 backdrop-blur-xl md:col-span-6 lg:col-span-6 2xl:p-8">
          
          {/* Header context indicators */}
          <div className="ultron-core-status absolute top-6 left-6 font-mono text-[9px] text-[#8B8B96] flex items-center gap-2 2xl:left-8 2xl:top-8 2xl:text-[10px]">
            <span>CORE STATUS:</span>
            <span className={`uppercase tracking-wider font-bold ${voice.wakeDetected ? accentText : "text-[#7DD3FC]"}`}>
              {voice.wakeDetected ? "WAKED" : aiState}
            </span>
          </div>

          {/* Core Canvas particle loop component */}
          <div className="ultron-core-stage flex min-h-0 w-full flex-1 items-center justify-center overflow-hidden">
            <BlobCanvas 
              aiState={voice.wakeDetected ? "wake_word_detected" : (voice.isListening ? "listening" : aiState)} 
              personality={activePersonality} 
              amplitude={0.0}
            />
          </div>

          {/* Center Bottom floating pill control bar */}
          <div className="ultron-core-controls absolute bottom-5 flex items-center gap-2 rounded-full border border-white/[0.09] bg-[#0A0F12]/88 px-2.5 py-2 font-mono text-[9px] shadow-[0_12px_35px_rgba(0,0,0,0.38)] backdrop-blur-3xl 2xl:bottom-8 2xl:scale-110">
            {/* Personality selection control. */}
            <button
              onClick={togglePersonality}
              disabled={personalitySaving}
              aria-label={`Switch assistant from ${aiName}`}
              className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[8px] font-bold uppercase tracking-widest transition-all duration-500 disabled:cursor-wait disabled:opacity-60 ${
                isZora
                  ? "bg-pink-500/10 border-pink-400/25 text-pink-300 shadow-[0_0_15px_rgba(236,72,153,0.15)]"
                  : "bg-emerald-500/10 border-emerald-400/25 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.15)]"
              }`}
            >
              <Orbit size={12} strokeWidth={1.8} aria-hidden="true" />
              <span>{personalitySaving ? "Saving" : isZora ? "Zora Selected" : "Ultron Selected"}</span>
            </button>

            <span className="h-5 w-px bg-white/[0.08]" aria-hidden="true" />

            {/* Coding Mode toggle — NVIDIA coding brain */}
            <button
              onClick={toggleCodingMode}
              disabled={codingModeSaving}
              aria-label={codingMode ? "Disable coding mode" : "Enable coding mode"}
              className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[8px] font-bold uppercase tracking-widest transition-all duration-500 disabled:cursor-wait disabled:opacity-60 ${
                codingMode
                  ? "bg-sky-500/10 border-sky-400/30 text-sky-300 shadow-[0_0_15px_rgba(56,189,248,0.2)]"
                  : "border-white/[0.10] bg-white/[0.02] text-white/45 hover:border-white/20 hover:text-white/75"
              }`}
              title={codingMode ? "Coding Mode ON (NVIDIA brain for all turns). Click to revert to auto." : "Coding Mode OFF (auto-detect). Click to force NVIDIA coding brain."}
            >
              <Code2 size={12} strokeWidth={1.8} aria-hidden="true" />
              <span>{codingModeSaving ? "Updating" : codingMode ? "Coding ON" : "Coding"}</span>
            </button>

            <span className="h-5 w-px bg-white/[0.08]" aria-hidden="true" />

            {/* Shown only for a real, exact, one-time backend pending action. */}
            {pendingAction?.confirmation_token && (
              <button
                onClick={onConfirmRun}
                disabled={confirmingAction}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[8px] font-bold tracking-widest uppercase transition-all duration-500 border border-amber-400/40 bg-amber-500/10 text-amber-300 shadow-[0_0_15px_rgba(251,191,36,0.2)] disabled:opacity-40"
                title={pendingAction.message || `Confirm ${pendingAction.tool_id}`}
              >
                {!confirmingAction && <Check size={12} strokeWidth={1.8} aria-hidden="true" />}
                <span>{confirmingAction ? 'Confirming…' : `Confirm ${pendingAction.tool_id}`}</span>
              </button>
            )}

            {/* Mic icon — real wake-word listening toggle with pulse-ring effect */}
            <button
              onClick={handleMicToggle}
              aria-label={voice.isListening ? "Stop voice listening" : "Enable voice listening"}
              className={`relative flex h-8 w-8 items-center justify-center rounded-full border transition-all duration-500 ${
                voice.voiceError
                  ? "border-rose-400/35 bg-rose-500/10 text-rose-300"
                  : voice.isListening
                    ? isZora
                      ? "text-pink-400 border-pink-400/40 bg-pink-500/10"
                      : "text-emerald-400 border-emerald-400/40 bg-emerald-500/10"
                    : "border-white/[0.10] bg-white/[0.025] text-white/40 hover:border-white/20 hover:text-white/75"
              }`}
              title={voice.voiceError || (voice.isListening ? "Listening for wake word... (click to stop)" : "Enable voice (click to start listening)")}
            >
              <Mic size={15} strokeWidth={1.8} aria-hidden="true" className={voice.isListening ? "animate-pulse" : ""} />
              {voice.isListening && (
                <span className={`absolute inset-0 rounded-full animate-ping opacity-40 ${isZora ? "bg-pink-400/40" : "bg-emerald-400/40"}`} />
              )}
            </button>
          </div>

          {/* Voice listening hint */}
          {voice.isListening && (
            <div className={`absolute bottom-6 right-6 text-[8px] font-mono uppercase tracking-widest ${isZora ? "text-pink-300/80" : "text-emerald-300/80"}`}>
              {voice.wakeDetected ? "Wake word heard — speak your command..." : "Listening for wake word..."}
            </div>
          )}
          {voice.voiceError && (
            <div className="absolute bottom-6 right-6 max-w-52 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-right font-mono text-[8px] leading-relaxed text-rose-200">
              {voice.voiceError}
            </div>
          )}

        </main>

        {/* Right column: Monospace dialogue history and textbox */}
        <RightPanel 
          messages={messages}
          inputValue={inputValue}
          setInputValue={setInputValue}
          handleSendMessage={handleSendMessage}
          isProcessing={isProcessing}
          activePersonality={activePersonality}
          backendStatus={backendStatus}
          logs={logs}
        />

      </div>

      {/* ==============================================================================
          3. DYNAMIC FLOATING OVERLAYS (Requirement: Loop over WIDGET_REGISTRY - No Hardcoding)
         ============================================================================== */}
      
      {Object.keys(widgetState).map(key => {
        const widget = widgetState[key];
        if (!widget.visible) return null;
        
        const config = WIDGET_REGISTRY[key];
        if (!config) return null;
        
        return (
          <WidgetContainer 
            key={key}
            widgetId={key}
            title={config.title} 
            onClose={() => toggleWidget(key)}
            initialX={widget.x}
            initialY={widget.y}
            initialWidth={config.defaultWidth}
            initialHeight={config.defaultHeight}
            personality={activePersonality}
          >
            <React.Suspense fallback={
              <div className="p-4 text-[9px] font-mono text-white/40 uppercase tracking-widest flex items-center gap-2">
                <div className="w-1.5 h-1.5 bg-[#7DD3FC] rounded-full animate-ping" />
                Lazy loading assets...
              </div>
            }>
              {key === "coding" ? (
                <config.Component log={codingLog || []} />
              ) : (
                <config.Component />
              )}
            </React.Suspense>
          </WidgetContainer>
        );
      })}

      </div>
    </div>
  );
}

