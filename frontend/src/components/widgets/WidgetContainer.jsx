import React, { useState } from 'react';
import useDraggable from '../../hooks/useDraggable';
import { getPersonalityTheme } from '../../theme/personalityTheme';

/**
 * WidgetContainer Component
 * Renders a draggable, collapsible glassmorphic wrapper modal.
 * Uses useDraggable hook for pointer tracking, supports double-click collapse states,
 * and configures active personality-based neon border accents.
 */
export default function WidgetContainer({ 
  widgetId,
  title, 
  onClose, 
  initialX = 150, 
  initialY = 150, 
  initialWidth = 320,
  initialHeight = 280,
  personality = "ultron", 
  children 
}) {
  const { position, handlePointerDown, isDragging } = useDraggable(
    initialX,
    initialY,
    initialWidth,
    initialHeight,
  );
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Map active colors dynamically from the shared personality contract.
  const theme = getPersonalityTheme(personality);

  // Double-click header bar to toggle collapsed/expanded states (Requirement: remember collapsed state)
  const handleHeaderDoubleClick = () => {
    setIsCollapsed(!isCollapsed);
    console.log(`[WIDGET_CONTAINER] Widget '${widgetId}' collapsed state set to: ${!isCollapsed}`);
  };

  return (
    <div 
      style={{
        transform: `translate3d(${position.x}px, ${position.y}px, 0)`,
        position: 'absolute',
        zIndex: isDragging ? 1000 : 50,
        width: `min(${initialWidth}px, calc(100% - 16px))`,
        height: isCollapsed ? 'auto' : `min(${initialHeight}px, calc(100% - 16px))`,
        maxWidth: 'calc(100% - 16px)',
        maxHeight: 'calc(100% - 16px)',
        borderLeftColor: theme.primary,
        boxShadow: `0 0 20px ${theme.glow}`,
      }}
      className="ultron-widget-container flex flex-col overflow-hidden rounded-lg border border-l-[3px] border-white/5 bg-[#14141E]/85 font-mono cursor-default select-none backdrop-blur-2xl transition-shadow duration-300"
    >
      {/* Draggable Header Drag Bar */}
      <div 
        onPointerDown={handlePointerDown}
        onDoubleClick={handleHeaderDoubleClick}
        className="flex touch-none justify-between items-center bg-white/[0.02] border-b border-white/5 px-4 py-2.5 cursor-grab active:cursor-grabbing text-[#8B8B96]"
        title="Drag header to move. Double-click to collapse/expand."
      >
        <span className="text-[9px] uppercase font-bold tracking-widest text-[#F5F5F7]">
          {title} {isCollapsed && "(Collapsed)"}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${title}`}
          className="no-drag text-[9px] text-[#8B8B96] hover:text-rose-400 uppercase tracking-widest transition-colors"
        >
          Close
        </button>
      </div>

      {/* Embedded Inner Children Viewport (Lazy rendered/hidden on collapse) */}
      {!isCollapsed && (
        <div className="max-h-60 flex-1 overflow-x-hidden overflow-y-auto p-4 select-text no-visible-scrollbar">
          {children}
        </div>
      )}
    </div>
  );
}
