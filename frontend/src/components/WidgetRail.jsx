import React, { useState } from 'react';
import { Plus, Settings, X } from 'lucide-react';
import { WIDGET_REGISTRY } from './widgets/WidgetManager';

const RAIL_CATEGORY_TONES = Object.freeze({
  productivity: "text-emerald-300/50 hover:text-emerald-200/80",
  system: "text-cyan-300/50 hover:text-cyan-200/80",
  developer: "text-sky-300/50 hover:text-sky-200/80",
  music: "text-pink-300/50 hover:text-pink-200/80",
  research: "text-violet-300/50 hover:text-violet-200/80",
  memory: "text-amber-300/50 hover:text-amber-200/80",
});

/**
 * Far-left launcher rail. It only opens/closes existing centre overlays; widget
 * rendering, dragging, sizing, and backend contracts remain owned elsewhere.
 */
export default function WidgetRail({ widgetState, toggleWidget, activePersonality }) {
  const [expanded, setExpanded] = useState(false);
  const [hoveredLauncher, setHoveredLauncher] = useState(null);
  const isZora = activePersonality === "zora";
  const activeText = isZora ? "text-pink-400" : "text-emerald-400";
  const activeBorder = isZora ? "border-pink-400/35" : "border-emerald-400/35";
  const activeBackground = isZora ? "bg-pink-500/10" : "bg-emerald-500/10";
  const activeIndicator = isZora ? "bg-pink-400" : "bg-emerald-400";

  const showLauncherName = (event, label) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    setHoveredLauncher({ label, top: bounds.top + (bounds.height / 2) });
  };

  const hideLauncherName = () => setHoveredLauncher(null);

  return (
    <aside
      className="relative z-[1200] h-screen w-14 shrink-0 border-r border-white/[0.06]"
      aria-label="Widget launcher"
    >
      <div className={`absolute inset-y-0 left-0 flex h-full flex-col bg-[#080B0F]/95 px-1.5 py-3 font-mono backdrop-blur-xl transition-[width] duration-200 ${
        expanded ? "w-52" : "w-14"
      } ${expanded ? "shadow-[12px_0_30px_rgba(0,0,0,0.45)]" : ""}`}>
        <div className="flex-1 space-y-1 overflow-x-hidden overflow-y-auto pr-0.5 no-visible-scrollbar">
          {Object.entries(WIDGET_REGISTRY).map(([widgetId, config]) => {
            const Icon = config.icon;
            const isVisible = Boolean(widgetState[widgetId]?.visible);
            const idleTone = RAIL_CATEGORY_TONES[config.category] || "text-white/45 hover:text-white/75";
            return (
              <button
                key={widgetId}
                type="button"
                onClick={() => toggleWidget(widgetId)}
                onMouseDown={hideLauncherName}
                onMouseEnter={(event) => showLauncherName(event, config.title)}
                onMouseLeave={hideLauncherName}
                onFocus={(event) => showLauncherName(event, config.title)}
                onBlur={hideLauncherName}
                aria-label={`Open ${config.title}`}
                aria-pressed={isVisible}
                title={config.title}
                className={`group relative flex h-10 w-full items-center rounded-lg border transition-colors duration-150 2xl:h-11 ${
                  expanded ? "justify-start gap-3 px-2.5" : "justify-center px-0"
                } ${
                  isVisible
                    ? `${activeBorder} ${activeBackground} ${activeText}`
                    : `${idleTone} border-transparent hover:border-white/10 hover:bg-white/[0.04]`
                }`}
              >
                {isVisible && (
                  <span
                    className={`absolute -left-1.5 h-5 w-0.5 rounded-r-full ${activeIndicator}`}
                    aria-hidden="true"
                  />
                )}
                <Icon size={18} strokeWidth={1.7} aria-hidden="true" className="h-[18px] w-[18px] shrink-0 2xl:h-5 2xl:w-5" />
                {expanded && (
                  <span className="truncate text-left text-[10px] font-semibold tracking-wide">
                    {config.title}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex shrink-0 flex-col gap-2 border-t border-white/[0.07] px-0.5 pt-3 2xl:gap-2.5">
          <button
            type="button"
            onClick={() => {
              hideLauncherName();
              setExpanded((current) => !current);
            }}
            onMouseEnter={(event) => showLauncherName(event, expanded ? "Collapse widget names" : "Show widget names")}
            onMouseLeave={hideLauncherName}
            onFocus={(event) => showLauncherName(event, expanded ? "Collapse widget names" : "Show widget names")}
            onBlur={hideLauncherName}
            aria-label={expanded ? "Collapse widget labels" : "Expand widget labels"}
            title={expanded ? "Collapse widget labels" : "Expand widget labels"}
            className={`flex h-10 w-full items-center rounded-lg border border-white/[0.06] bg-white/[0.02] text-white/45 transition-colors hover:border-white/15 hover:bg-white/[0.05] hover:text-white/80 2xl:h-11 ${
              expanded ? "justify-start gap-3 px-2.5" : "justify-center"
            }`}
          >
            {expanded ? <X size={18} strokeWidth={1.7} className="2xl:h-5 2xl:w-5" /> : <Plus size={18} strokeWidth={1.7} className="2xl:h-5 2xl:w-5" />}
            {expanded && <span className="text-[10px] font-semibold">Collapse labels</span>}
          </button>

          <button
            type="button"
            onClick={() => {
              hideLauncherName();
              toggleWidget('system');
            }}
            onMouseEnter={(event) => showLauncherName(event, "System widget")}
            onMouseLeave={hideLauncherName}
            onFocus={(event) => showLauncherName(event, "System widget")}
            onBlur={hideLauncherName}
            aria-label="Open system widget"
            aria-pressed={Boolean(widgetState.system?.visible)}
            title="Open system widget"
            className={`flex h-10 w-full items-center rounded-lg border transition-colors 2xl:h-11 ${
              expanded ? "justify-start gap-3 px-2.5" : "justify-center"
            } ${
              widgetState.system?.visible
                ? `${activeBorder} ${activeBackground} ${activeText}`
                : "border-white/[0.06] bg-white/[0.02] text-white/45 hover:border-white/15 hover:bg-white/[0.05] hover:text-white/80"
            }`}
          >
            <Settings size={18} strokeWidth={1.7} aria-hidden="true" className="2xl:h-5 2xl:w-5" />
            {expanded && <span className="text-[10px] font-semibold">System widget</span>}
          </button>
        </div>
      </div>

      {!expanded && hoveredLauncher && (
        <div
          role="tooltip"
          className="pointer-events-none fixed left-16 z-[1300] -translate-y-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#10161A]/96 px-2.5 py-1.5 font-mono text-[10px] font-semibold tracking-wide text-white/85 shadow-[0_8px_24px_rgba(0,0,0,0.45)] backdrop-blur-xl"
          style={{ top: hoveredLauncher.top }}
        >
          <span className={`mr-2 inline-block h-1.5 w-1.5 rounded-full ${activeIndicator}`} aria-hidden="true" />
          {hoveredLauncher.label}
        </div>
      )}
    </aside>
  );
}
