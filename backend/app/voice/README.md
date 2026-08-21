# Module: Duplex Voice & Interruption System (`backend/app/voice/`)

This module manages the local, asynchronous non-blocking speech synthesis (TTS), client transcription (STT) gateways, and real-time interruption (barge-in) processing loops.

---

## 1. Directory File Map & Responsibilities

```
backend/app/voice/
├── base_voice_provider.py  # Abstract BaseVoiceProvider ABC (OCP compliant Strategy)
├── edge_tts_provider.py    # Deployed concrete EdgeTTSProvider streaming MS Edge neural TTS
├── interrupt_handler.py    # Manages async task cancellations for instant client-side barge-ins
├── voice_system.py         # Central voice lifecycle engine, config loader, and Event Bus publisher
└── README.md               # Documentation (This file)
```

### A. `base_voice_provider.py` (The Speech Abstraction)
*   **Role**: Abstract base class `BaseVoiceProvider`. Declares `generate_speech(text, voice_id, rate, pitch) -> AsyncGenerator[bytes, None]` as a unified interface contract (Strategy pattern).

### B. `edge_tts_provider.py` (The Neural Synthesizer)
*   **Role**: Concrete implementation. Connects asynchronously to Microsoft's Edge neural TTS engine, streaming MP3 binary packets in real-time, completely bypassing local model footprints.

### C. `interrupt_handler.py` (The Interruption Boundary)
*   **Role**: Registers active asyncio speech tasks. When a user barge-in is caught, it **instantly cancels the task**, halting sound generation on the server.

### D. `voice_system.py` (The Central Director)
*   **Role**: Pulls voice configurations from `config.yaml` dynamically (e.g. mapping `en-US-GuyNeural` to Ultron at `+10%` speed, and `en-US-EmmaNeural` to Zora at `-5%` speed, with zero code duplication).
*   **Lifecycle Event Publications**: Publishes seven standardized voice events directly to the Event Bus:
    *   `listening_started` / `speech_detected` / `thinking_started` / `speaking_started` / `interrupted` / `playback_finished` / `idle`.

---

## 2. Diagnostic Tests & Manual Execution

To verify Phase 9 Voice systems independently when your development machine is restored, run:

```bash
# Execute complete unit, integration, and E2E diagnostics across all 9 completed phases
./venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

This test suite verifies:
1.  Dynamic custom subclassing of `BaseVoiceProvider` (Strategy pattern verification).
2.  Config-driven personality loading (Ultron vs Zora separate voice attributes).
3.  Asynchronous Event Bus lifecycle progression matches requirements.
4.  Instant barge-in task cancellation, confirming that active speech tasks immediately abort on user interrupt triggers.
