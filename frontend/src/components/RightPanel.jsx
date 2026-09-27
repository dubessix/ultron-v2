import React, { useState, useRef, useEffect } from 'react';
import { ChevronRight, CircleCheck, Send } from 'lucide-react';
import { getPersonalityTheme } from '../theme/personalityTheme';

// One size for every pill in the header (Chat, Log, Connected): same height,
// text centred both ways, so the row lines up.
const PILL = 'inline-flex h-7 items-center justify-center rounded-full border text-[9px] uppercase leading-none tracking-widest transition-colors 2xl:text-[10px]';

/**
 * RightPanel — Chat + Log tabs.
 * Chat = conversation (as before). Log = Ultron's real-time operational
 * activity (tool calls, results, errors) streamed from the backend.
 */
export default function RightPanel({ 
  messages, 
  inputValue, 
  setInputValue, 
  handleSendMessage, 
  isProcessing, 
  activePersonality,
  backendStatus,
  logs = []
}) {
  const [tab, setTab] = useState("chat");
  const scrollRef = useRef(null);
  const logScrollRef = useRef(null);
  const activeTheme = getPersonalityTheme(activePersonality);
  const rawName = String(activeTheme.name || "Ultron");
  const displayName = rawName.charAt(0).toUpperCase() + rawName.slice(1).toLowerCase();

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    logScrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <aside className="ultron-right-panel col-span-12 flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-hidden rounded-xl border border-white/[0.07] bg-[#0B1112]/72 p-4 backdrop-blur-xl md:col-span-3 lg:col-span-3 2xl:gap-4 2xl:p-5">
      
      {/* Header + Chat/Log tabs */}
      <div className="ultron-right-header flex h-10 shrink-0 items-center justify-between border-b border-white/5 pb-3 2xl:pb-4">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setTab("chat")}
            className={`${PILL} w-16 font-bold ${
              tab === "chat" ? "" : "border-transparent text-white/40 hover:text-white/70"
            }`}
            style={tab === "chat" ? {
              color: activeTheme.primary,
              backgroundColor: activeTheme.surface,
              borderColor: activeTheme.border,
            } : undefined}
          >
            Chat
          </button>
          <button
            onClick={() => setTab("log")}
            className={`${PILL} w-16 font-bold ${
              tab === "log" ? "bg-[#7DD3FC]/10 text-[#7DD3FC] border-[#7DD3FC]/20" : "border-transparent text-white/40 hover:text-white/70"
            }`}
          >
            Log
          </button>
        </div>
        <span className={`${PILL} max-w-28 truncate px-3 font-mono ${backendStatus === 'CONNECTED' ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400' : 'border-amber-500/20 bg-amber-500/5 text-amber-300'}`}>
          {backendStatus || 'UNKNOWN'}
        </span>
      </div>

      {/* CHAT TAB */}
      {tab === "chat" && (
        <div className="ultron-chat-scroll min-h-0 min-w-0 flex-1 space-y-3 overflow-x-hidden overflow-y-auto pr-1 no-visible-scrollbar 2xl:space-y-4">
          {messages.length === 0 ? (
            <div className="ultron-chat-empty flex h-full flex-col items-center justify-center gap-4 p-4 text-center 2xl:gap-5 2xl:p-6">
              <div className="w-8 h-8 rounded-full border border-[#7DD3FC]/10 bg-[#7DD3FC]/5 flex items-center justify-center text-[#7DD3FC] animate-pulse 2xl:h-10 2xl:w-10">
                <CircleCheck size={16} strokeWidth={1.8} aria-hidden="true" className="2xl:h-[18px] 2xl:w-[18px]" />
              </div>
              <p className="max-w-[16rem] font-mono text-[10px] leading-relaxed text-[#8B8B96] 2xl:text-[11px]">
                {backendStatus === 'CONNECTED'
                  ? 'Type below or tap the mic.'
                  : 'Backend is not connected. Start Ultron first.'}
              </p>
            </div>
          ) : (
            messages.map((msg) => {
              const isUser = msg.sender === "user";
              const messageTheme = getPersonalityTheme(msg.personality);
              return (
                <div key={msg.id} className={`flex min-w-0 flex-col ${isUser ? "items-end" : "items-start"}`}>
                  <div
                    className={`min-w-0 rounded-2xl border px-3.5 py-3 backdrop-blur-md transition-all 2xl:px-4 2xl:py-3.5 ${
                      isUser
                        ? "max-w-[92%] bg-[#10B981]/5 border-emerald-500/10 text-[#F5F5F7] rounded-tr-none"
                        : "w-full max-w-full rounded-tl-none"
                    }`}
                    style={isUser ? undefined : {
                      backgroundColor: messageTheme.surface,
                      borderColor: messageTheme.border,
                      color: messageTheme.text,
                    }}
                  >
                    <span className="mb-1.5 block text-[8px] font-bold uppercase tracking-widest opacity-50 2xl:text-[9px]">
                      {isUser ? "Debjeet" : msg.personality ? msg.personality : "System"}
                    </span>
                    <p className="select-text whitespace-pre-wrap break-words [overflow-wrap:anywhere] font-mono text-[11px] leading-[1.7] text-white/90 2xl:text-[12px]">{msg.text}</p>
                    {msg.sender === "ai" && msg.response_ms !== undefined && (
                      <span className="mt-2 block text-right font-mono text-[7px] uppercase tracking-wider opacity-35">
                        {msg.response_ms}ms
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          )}
          <div ref={scrollRef} />
        </div>
      )}

      {/* LOG TAB — real-time operational activity */}
      {tab === "log" && (
        <div className="min-h-0 min-w-0 flex-1 space-y-1 overflow-x-hidden overflow-y-auto rounded-lg border border-white/[0.07] bg-black/30 p-2.5 pr-1 font-mono text-[10px] no-visible-scrollbar 2xl:p-3 2xl:text-[11px]">
          {logs.length === 0 ? (
            <p className="text-white/30">No activity yet. Ask Ultron to run a tool — you'll see real-time logs here.</p>
          ) : (
            logs.map((l, i) => (
              <div key={i} className="flex min-w-0 items-start gap-2">
                <span className={`shrink-0 ${l.level === "error" ? "text-rose-400" : l.level === "success" ? "text-emerald-400" : "text-[#7DD3FC]"}`}>
                  <ChevronRight size={12} strokeWidth={1.8} aria-hidden="true" />
                </span>
                <span className={`min-w-0 break-words [overflow-wrap:anywhere] leading-relaxed ${l.level === "error" ? "text-rose-300" : l.level === "success" ? "text-emerald-300" : "text-white/70"}`}>
                  {l.message}
                </span>
              </div>
            ))
          )}
          <div ref={logScrollRef} />
        </div>
      )}

      {/* Rounded text query input box (shared) */}
      <form onSubmit={handleSendMessage} className="flex min-w-0 shrink-0 border-t border-white/[0.07] pt-3">
        <div className="flex h-11 min-w-0 flex-1 items-center gap-2 rounded-full border border-white/[0.10] bg-white/[0.045] pl-4 pr-1.5 shadow-inner shadow-black/20 transition-colors focus-within:border-[#7DD3FC]/40 focus-within:bg-white/[0.06]">
          <input 
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={isProcessing ? "Working… type stop" : `Message ${displayName}…`}
            aria-label="Message"
            className="h-full min-w-0 flex-1 truncate bg-transparent font-mono text-[11px] leading-none text-[#F5F5F7] placeholder-white/35 focus:outline-none 2xl:text-[12px]"
          />
          <button
            type="submit"
            disabled={!inputValue.trim()}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition-all disabled:opacity-25"
            style={{ color: activeTheme.primary, borderColor: activeTheme.border, backgroundColor: activeTheme.surface }}
            aria-label="Send message"
            title="Send message"
          >
            <Send size={14} strokeWidth={1.8} aria-hidden="true" />
          </button>
        </div>
      </form>
    </aside>
  );
}
