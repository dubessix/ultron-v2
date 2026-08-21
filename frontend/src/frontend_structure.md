# Ultron V1: Frontend File Structure & Interface Manual
*Document Version: 1.0.5 — Sprints 0-11 Frontend Interface*

This document provides a highly detailed, professional engineering manual of the React, Vite, and Tailwind frontend client.

---

## 1. Client Repository File Map

```
frontend/
├── package.json               # Frontend npm package dependencies
├── vite.config.js             # Vite compiler parameters
├── postcss.config.js          # PostCSS Tailwind binder
├── tailwind.config.js         # Custom color scheme, fonts, and animations
├── index.html                 # Root entry HTML viewport
└── src/
    ├── main.jsx               # React entry mounting hook
    ├── index.css              # Custom base styling and SVG gooey filter layers
    ├── App.jsx                # Core chat interface, polling loop, and canvas morphs
    ├── hooks/                 # Custom react hooks directory
    │   └── useDraggable.js    # Hardware accelerated pointer coordinate tracker
    └── components/            # [NEW] Glassmorphism Layout Components
        ├── AppShell.jsx       # Global 3-panel widescreen grid layout with widget overlays
        ├── LeftPanel.jsx      # Monitors network latency, CPU, and RAM
        ├── RightPanel.jsx     # Monospace message bubbles and query text box
        ├── BlobCanvas.jsx     # Asynchronous Canvas 2D Particle Core
        └── widgets/           # Glassmorphic floating components
            ├── WidgetContainer.jsx # Draggable container and double-click collapse triggers
            ├── TodoWidget.jsx      # Daily life priority task tracker
            ├── CalendarWidget.jsx  # Scheduling day planner list
            ├── GitWidget.jsx       # Repository active branch status watcher (no mock)
            ├── FileExplorerWidget.jsx # Connected local directory filesystem explorer (no mock)
            ├── UniversalSearchWidget.jsx # Central unified search indexer (no mock)
            ├── DeepResearchWidget.jsx # Connected Tavily search widget (no mock)
            ├── WeatherWidget.jsx   # Connected keyless Open-Meteo weather (no mock)
            ├── MarketWidget.jsx    # Connected live stock watch (no mock)
            ├── TerminalWidget.jsx  # Connected terminal logs view (no mock)
            ├── MemoryWidget.jsx    # Connected memory browser (no mock)
            ├── NotificationWidget.jsx # Connected background tasks view (no mock)
            ├── SystemWidget.jsx    # Connected psutil metrics view (no mock)
            └── README.md           # Developer manual of widget additions
```

---

## 2. Component Design & Interactivity: App Components

The user interface of Ultron V1 is divided into highly cohesive, decoupled React components under `/frontend/src/components/`:

### A. `AppShell.jsx` (Global Grid Layout)
*   **Role**: Manages the responsive 3-panel widescreen grid layout (`grid grid-cols-12 gap-6 h-screen w-screen p-6`). It features a standardized top header tracking connected network links.
*   **Draggable Overlays**: Dynamically mounts the floating `WidgetContainer` structures based on client-side active toggles or backend webhook pushes.

### B. `LeftPanel.jsx` (System status meters)
*   **Role**: Displays live local telemetries. Monitors network links, TX/RX signal loads, CPU load, RAM usage, temperature, and operating system status. (Vision Feed completely omitted).

### C. `RightPanel.jsx` (Dialogue Viewport)
*   **Role**: Displays chronological monospace chat bubbles with personality-specific borders and custom latency footnotes (e.g. `12ms // fast`). Provides a clean input text bar.

### D. `BlobCanvas.jsx` (HTML5 Canvas 2D Particle Core)
*   **Role**: Renders a floating, breathing, and rotating particle sphere of 200 coordinate nodes and concentric tilted orbital rings using standard 2D vector mathematics. Runs locked at **60 FPS** using native `requestAnimationFrame` while consuming **$<15\text{MB}$ of memory**.

### E. `NotificationToast.jsx` (Floating Notification Overlays)
*   **Role**: Renders translucent, glassmorphic toast notification cards. Supports 4 priority levels (low, medium, high, critical) and auto-dismisses after exactly 4 seconds.

---

## 3. Draggable Glass Containers Subsystem

To offer high-fidelity local multitasking capabilities without adding heavy library overheads, we designed an isolated **Draggable Glass Widgets Subsystem**:

### A. `useDraggable.js` (The Movement Hook)
A custom React hook tracking unified Pointer Events (`pointerdown`, `pointermove`, `pointerup`, `pointercancel`) for mouse, pen, and touch. It computes displacement coordinates and updates hardware-accelerated **`transform: translate3d(x, y, 0)`** coordinates directly.

### B. `WidgetContainer.jsx` (The Glassmorphic Wrapper)
A floating wrapper panel displaying close triggers and dynamic left-accent border colors matching the active personality (Technical Blue `#7DD3FC` for Ultron, Warm Purple `#C084FC` for Zora). Supports double-clicking the header bar to collapse or expand the inner widget.

### C. Productivity Widgets Deployed:
1.  **`TodoWidget`**: Monitors high, medium, and low priority daily tasks.
2.  **`CalendarWidget`**: Displays chronologically structured day planner items and reminder schedules.
3.  **`GitWidget`**: Tracks local repository branch statuses and lists uncommitted modified files.
