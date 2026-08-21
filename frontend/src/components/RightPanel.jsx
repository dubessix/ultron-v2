import React, { useState, useRef, useEffect } from 'react';
import { ChevronRight, CircleCheck, Send } from 'lucide-react';
import { getPersonalityTheme } from '../theme/personalityTheme';

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

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    logScrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <aside className="ultron-right-panel col-span-12 flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-hidden rounded-xl border border-white/[0.07] bg-[#0B1112]/72 p-4 backdrop-blur-xl md:col-span-3 lg:col-span-3 2xl:gap-4 2xl:p-5">
      
      {/* Header + Chat/Log tabs */}
      <div className="ultron-right-header flex shrink-0 items-center justify-between border-b border-white/5 pb-3 2xl:pb-4">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setTab("chat")}
            className={`text-[9px] uppercase font-bold tracking-widest px-3 py-1 rounded-full border transition-colors 2xl:px-4 2xl:py-1.5 2xl:text-[10px] ${
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
            className={`text-[9px] uppercase font-bold tracking-widest px-3 py-1 rounded-full transition-colors 2xl:px-4 2xl:py-1.5 2xl:text-[10px] ${
              tab === "log" ? "bg-[#7DD3FC]/10 text-[#7DD3FC] border border-[#7DD3FC]/20" : "text-white/40 hover:text-white/70"
            }`}
          >
            Log
          </button>
        </div>
        <span className={`max-w-24 truncate text-[8px] border px-2 py-0.5 rounded-full font-mono tracking-wider 2xl:max-w-28 2xl:px-2.5 2xl:py-1 2xl:text-[9px] ${backendStatus === 'CONNECTED' ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400' : 'border-amber-500/20 bg-amber-500/5 text-amber-300'}`}>
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
              <p className="text-[10px] text-[#8B8B96] leading-relaxed uppercase tracking-wider font-mono 2xl:text-[11px]">
                {backendStatus === 'CONNECTED'
                  ? 'Backend connected. Tap the mic or type below to begin.'
                  : 'Backend is not connected. Start the local service before sending a message.'}
              </p>
            </div>
          ) : (
            messages.map((msg) => {
              const isUser = msg.sender === "user";
              const messageTheme = getPersonalityTheme(msg.personality);
              return (
                <div key={msg.id} className={`flex min-w-0 flex-col ${isUser ? "items-end" : "items-start"}`}>
                  <div
                    className={`min-w-0 rounded-2xl border p-4 backdrop-blur-md transition-all 2xl:p-5 ${
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
                    <span className="mb-2 block text-[8px] font-bold uppercase tracking-widest opacity-50 2xl:text-[9px]">
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
      <form onSubmit={handleSendMessage} className="flex min-w-0 shrink-0 gap-2 border-t border-white/[0.07] pt-3">
        <div className="flex min-w-0 flex-1 items-center rounded-full border border-white/[0.10] bg-white/[0.045] px-3.5 py-2.5 shadow-inner shadow-black/20 transition-colors focus-within:border-[#7DD3FC]/40 focus-within:bg-white/[0.06] 2xl:px-4 2xl:py-3">
          <input 
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isProcessing}
            placeholder={isProcessing ? "Processing..." : "Ask anything, Ultron is listening..."}
            className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-[#F5F5F7] placeholder-white/35 focus:outline-none 2xl:text-[12px]"
          />
          <button
            type="submit"
            disabled={isProcessing || !inputValue.trim()}
            className="text-xs ml-2 transition-all disabled:opacity-20"
            style={{ color: activeTheme.primary }}
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
