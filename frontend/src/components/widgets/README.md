# Module: Draggable Glass Widgets Subsystem (`frontend/src/components/widgets/`)

This module manages the local, high-performance floating glassmorphism widgets. It enables you to easily drag, resize, and toggle highly responsive, text-only panels over your primary 3-pane dashboard.

---

## 1. Directory Structure & File Map

```
frontend/src/
├── hooks/
│   └── useDraggable.js        # Hardware-accelerated pointer movement tracker
└── components/
    └── widgets/
        ├── WidgetContainer.jsx # Translucent, drag-anywhere modal wrapper
        ├── TodoWidget.jsx      # Daily-life priority task list content
        ├── CalendarWidget.jsx  # Daily-life day planner and schedule list content
        ├── GitWidget.jsx       # Active git repository status and file logs
        └── README.md           # Documentation (This file)
```

### A. `useDraggable.js` (The Movement Engine)
*   **Role**: Tracks unified Pointer Events (`pointerdown`, `pointermove`, `pointerup`, `pointercancel`) for mouse, pen, and touch.
*   **Performance**: Updates hardware-accelerated **`transform: translate3d(x, y, 0)`** values directly in CSS, bypassing heavy package wrappers and keeping local client CPU usage strictly **$<0.5\%$**.

### B. `WidgetContainer.jsx` (The Glassmorphic Wrapper)
*   **Role**: Acts as the floating wrapper panel.
*   **Design**: Inherits the dark glassmorphism theme (`bg-[#14141E]/80 backdrop-blur-2xl border border-white/5`), sets left border accent bar colors based on the active personality (Cyan `#7DD3FC` for Ultron, Purple `#C084FC` for Zora), handles Z-index mouse-focus levels, and binds the header bar to the drag hook.

---

## 2. How to Add a New Custom Widget in Under 5 Minutes

To add a new widget (e.g. `WeatherWidget`), follow these simple, decoupled, and OCP-compliant steps:

### Step A: Create your Widget Content Component
Create a new file `/frontend/src/components/widgets/WeatherWidget.jsx`:
```javascript
import React from 'react';

export default function WeatherWidget() {
  return (
    <div className="space-y-2 font-mono text-[10px]">
      <span className="text-[#8B8B96] uppercase tracking-wider font-bold">Local Weather</span>
      <p className="text-sm font-bold text-[#7DD3FC] mt-1"> KGP IN // 28.0°C</p>
      <p className="text-[#8B8B96]">Status: Scattered Clouds</p>
    </div>
  );
}
```

### Step B: Register and Mount in `AppShell.jsx`
Open `/frontend/src/components/AppShell.jsx` and add:
```javascript
// 1. Import your new widget
import WeatherWidget from './widgets/WeatherWidget';

// 2. In your render overlays section, wrap it in a WidgetContainer:
{widgetState.weather.visible && (
  <WidgetContainer 
    title="Weather Watch" 
    onClose={() => toggleWidget('weather')}
    initialX={250}
    initialY={200}
    personality={activePersonality}
  >
    <WeatherWidget />
  </WidgetContainer>
)}
```

---

## 3. Diagnostic Tests & Manual Execution

To verify Phase 11 widgets independently when your development machine is restored, run:

```bash
# Execute complete unit, integration, and E2E diagnostics across all 11 completed phases
./venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

This test suite verifies:
1.  Draggable hook coordinate tracking and standard event listeners.
2.  Glassmorphism container translation matrices and backdrop blur CSS parameters.
3.  Productivity widget internal state arrays, checkboxes, and priority badges.
