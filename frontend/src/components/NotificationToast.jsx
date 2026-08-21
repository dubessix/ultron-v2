import React, { useEffect } from 'react';
import { X } from 'lucide-react';

/**
 * NotificationToast Component
 * Renders an elegant, glassmorphic toast notification.
 * Supports four priority levels: low (blue) | medium (green) | high (gold) | critical (rose).
 * Automatically fades and dismisses after 4 seconds.
 */
export default function NotificationToast({ 
  id, 
  title, 
  message, 
  priority = "low", 
  onDismiss 
}) {
  useEffect(() => {
    // Auto-dismiss notification after 4 seconds to prevent cluttering the viewport
    const timer = setTimeout(() => {
      onDismiss(id);
    }, 4000);
    return () => clearTimeout(timer);
  }, [id, onDismiss]);

  // Map priority accent colors (Requirement: Notification Prioritization)
  let priorityBorder = "border-l-sky-400";
  let priorityBadgeBg = "bg-sky-400/10 text-sky-400";
  
  if (priority === "medium") {
    priorityBorder = "border-l-emerald-400";
    priorityBadgeBg = "bg-emerald-400/10 text-emerald-400";
  } else if (priority === "high") {
    priorityBorder = "border-l-amber-400";
    priorityBadgeBg = "bg-amber-400/10 text-amber-400";
  } else if (priority === "critical") {
    priorityBorder = "border-l-rose-400";
    priorityBadgeBg = "bg-rose-400/10 text-rose-400";
  }

  return (
    <div 
      className={`w-72 bg-[#14141E]/90 border border-white/5 border-l-[3px] ${priorityBorder} rounded-sm p-4 backdrop-blur-3xl shadow-[0_0_20px_rgba(0,0,0,0.3)] flex flex-col gap-2 transition-all duration-300 transform animate-fade-in font-mono`}
    >
      <div className="flex justify-between items-center">
        <span className={`text-[7px] uppercase tracking-widest font-bold px-1.5 py-0.5 rounded-sm ${priorityBadgeBg}`}>
          {priority} Priority
        </span>
        <button
          onClick={() => onDismiss(id)}
          aria-label="Dismiss notification"
          title="Dismiss notification"
          className="text-[#8B8B96] hover:text-white transition-colors"
        >
          <X size={13} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>
      <div>
        <h3 className="text-[10px] font-bold text-[#F5F5F7] uppercase tracking-wider">{title}</h3>
        <p className="text-[9px] text-[#8B8B96] mt-1 leading-relaxed">{message}</p>
      </div>
    </div>
  );
}
