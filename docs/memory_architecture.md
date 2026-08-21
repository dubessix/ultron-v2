# Memory Architecture

## Layers

- Short-term: bounded per-session LRU conversation buffers.
- Persistent relational: sessions and conversations in SQLite WAL.
- Project state: key/value facts scoped by project.
- Vector memory: episodic, semantic, and emotional rows stored as float32 BLOBs.

## Embeddings

Default cloud embedding model: `gemini-embedding-001`, default 768 dimensions. Model/dimensions are stored in metadata. Without a Gemini key, deterministic SHAKE-based offline vectors support local tests/basic storage behavior; they are labelled by effective embedding metadata and can be re-embedded later.

## Project scoping

Memory metadata includes project ID, session ID, category, importance, model, and dimensions. Recall/list/dedup/correction/deletion/re-embedding apply the active project filter. Legacy missing project metadata maps to `personal`.

## Explicit controls

`manage_memory` supports remember, list, export, correct, forget, restore, and re-embed. Correct/forget/restore/re-embed use permission-specific exact confirmation when invoked through the registry.

## Retention and durability

Vector rows are bounded per memory type. SQLite online backups include memory; restore maintenance blocks database/tool writes and verifies/rolls back the database. Tests use isolated temporary SQLite files.

No latency, RAM, or recall-quality guarantee is implied without measurement on the target dataset and laptop.
