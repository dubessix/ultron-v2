# Existing Voice System

Ultron keeps one TTS engine: **Edge TTS**. No second engine or local speech model is bundled.

- `edge_tts_provider.py` lazily imports the online Edge service and yields only real MP3 packets.
- `voice_system.py` selects the configured Ultron/Zora voice, rate, and pitch and exposes an async byte generator.
- `interrupt_handler.py` cancels an active synthesis task owned by that `VoiceSystem` instance.
- `POST /api/speak` preflights the first real packet, streams `audio/mpeg`, disables caching, and closes the provider generator when the client disconnects.

The frontend owns browser Web Speech recognition. Stop Voice aborts an in-flight TTS fetch and stops playback. Browsers supporting Media Source `audio/mpeg` can begin playback from progressive chunks; other browsers use the complete verified blob fallback. Object URLs and handlers are cleaned on end, error, replacement, stop, and unmount.

This is dependable half-duplex turn-taking, not a claim of acoustic echo cancellation or true talk-over barge-in. Real microphone pickup, audible playback, browser codec support, and speaker echo remain owner-device checks. Provider failure returns an explicit error; fake audio is never generated.
