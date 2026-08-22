import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  Check,
  Clock3,
  Database,
  Download,
  History,
  Pencil,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import { api, executeTool } from '../../api';

const CATEGORY_LABELS = Object.freeze({
  explicit: 'Explicit',
  owner_preference: 'Owner preference',
  decision: 'Decision',
  project_fact: 'Project fact',
  task: 'Task',
  goal: 'Goal',
  problem: 'Problem',
  solution: 'Solution',
  session_event: 'Session event',
});

const formatTime = (value) => {
  if (!value) return 'Time unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

const cleanFilenamePart = (value) => String(value || 'personal').replace(/[^a-z0-9._-]+/gi, '-').slice(0, 80);

/** M4 project-scoped memory browser with local search and exact destructive confirmation. */
export default function MemoryWidget({ personality = 'ultron' }) {
  const isZora = personality === 'zora';
  const accentText = isZora ? 'text-pink-300' : 'text-emerald-300';
  const accentBorder = isZora ? 'border-pink-400/25' : 'border-emerald-400/25';
  const accentSurface = isZora ? 'bg-pink-500/[0.07]' : 'bg-emerald-500/[0.07]';
  const accentButton = isZora
    ? 'border-pink-400/30 bg-pink-500/10 text-pink-200 hover:bg-pink-500/15'
    : 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/15';

  const [draft, setDraft] = useState({ project: 'personal', query: '', category: '', importance: '' });
  const [filters, setFilters] = useState({ project: 'personal', query: '', category: '', importance: '' });
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [operation, setOperation] = useState('');
  const [editing, setEditing] = useState(null);
  const [pending, setPending] = useState(null);

  const load = async (activeFilters = filters) => {
    setStatus('loading');
    setError('');
    try {
      const params = new URLSearchParams({
        project_id: activeFilters.project || 'personal',
        query: activeFilters.query || '',
        limit: '40',
      });
      if (activeFilters.category) params.set('category', activeFilters.category);
      if (activeFilters.importance) params.set('importance', activeFilters.importance);
      const result = await api(`/api/memory/ui?${params.toString()}`);
      setData(result);
      setStatus('ready');
    } catch (err) {
      setData(null);
      setStatus('unavailable');
      setError(err.message || 'Memory query unavailable.');
    }
  };

  useEffect(() => {
    load(filters);
  }, [filters.project, filters.query, filters.category, filters.importance]);

  const applyFilters = (event) => {
    event.preventDefault();
    const project = draft.project.trim() || 'personal';
    setNotice('');
    setEditing(null);
    setFilters({ ...draft, project });
  };

  const clearFilters = () => {
    const clean = { project: filters.project || 'personal', query: '', category: '', importance: '' };
    setDraft(clean);
    setFilters(clean);
    setNotice('Filters cleared.');
  };

  const requestExactConfirmation = async (action, memory, replacement = '') => {
    setOperation(`${action}:${memory.id}`);
    setError('');
    setNotice('');
    const args = {
      action,
      project_id: filters.project,
      memory_id: memory.id,
    };
    if (action === 'correct') {
      args.content = replacement.trim();
      args.category = memory.category;
      args.importance = memory.importance;
    }
    try {
      const first = await executeTool('manage_memory', args, { sessionId: 'memory-ui' });
      if (first.status !== 'PENDING_CONFIRMATION' || !first.confirmation_token) {
        if (!first.success) throw new Error(first.error || 'The backend did not issue an exact confirmation.');
        setNotice(action === 'correct' ? 'Memory corrected.' : 'Memory forgotten.');
        setEditing(null);
        await load(filters);
        return;
      }
      setPending({
        action,
        args,
        memory,
        confirmation_token: first.confirmation_token,
        arguments_hash: first.arguments_hash,
      });
    } catch (err) {
      setError(err.message || `Could not prepare ${action}.`);
    } finally {
      setOperation('');
    }
  };

  const confirmExactAction = async () => {
    if (!pending?.confirmation_token) return;
    setOperation(`confirm:${pending.memory.id}`);
    setError('');
    try {
      const result = await executeTool('manage_memory', pending.args, {
        sessionId: 'memory-ui',
        confirmationToken: pending.confirmation_token,
      });
      if (!result.success) {
        throw new Error(result.error || result.message || 'Exact confirmation was rejected.');
      }
      setNotice(pending.action === 'correct' ? 'Memory corrected and revision updated.' : 'Memory forgotten.');
      setPending(null);
      setEditing(null);
      await load(filters);
    } catch (err) {
      setError(err.message || 'Confirmed memory action failed.');
    } finally {
      setOperation('');
    }
  };

  const exportMemories = async () => {
    setOperation('export');
    setError('');
    setNotice('');
    try {
      const result = await executeTool('manage_memory', {
        action: 'export',
        project_id: filters.project,
        limit: 500,
      }, { sessionId: 'memory-ui' });
      if (!result.success) throw new Error(result.error || 'Memory export failed.');
      const blob = new Blob([JSON.stringify(result.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `ultron-memory-${cleanFilenamePart(filters.project)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setNotice(`Exported ${result.data?.count || 0} redacted memory records.`);
    } catch (err) {
      setError(err.message || 'Memory export failed.');
    } finally {
      setOperation('');
    }
  };

  const memories = data?.memories || [];
  const summaries = data?.summaries || [];
  const counts = data?.counts || {};

  return (
    <div data-testid="memory-ui" className="relative flex h-full min-h-[440px] flex-col gap-3 font-mono text-[10px] text-white/75">
      <section className={`shrink-0 rounded-lg border ${accentBorder} ${accentSurface} p-3`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Database size={15} className={accentText} aria-hidden="true" />
              <h2 className="text-[11px] font-bold uppercase tracking-[0.18em] text-white/90">Project memory</h2>
            </div>
            <p className="mt-1 text-[8px] leading-relaxed text-white/35">
              Local SQLite records only · exact search · secrets redacted
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => load(filters)}
              disabled={status === 'loading'}
              aria-label="Refresh memory dashboard"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2.5 text-[8px] font-bold uppercase tracking-wider text-white/55 hover:text-white/85 disabled:opacity-40"
            >
              <RefreshCw size={12} className={status === 'loading' ? 'animate-spin' : ''} aria-hidden="true" />
              Refresh
            </button>
            <button
              type="button"
              onClick={exportMemories}
              disabled={Boolean(operation)}
              className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-[8px] font-bold uppercase tracking-wider disabled:opacity-40 ${accentButton}`}
            >
              <Download size={12} aria-hidden="true" />
              Export
            </button>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2" aria-label="Memory totals">
          {[
            ['Stored memories', counts.memories ?? '—', Database],
            ['Important', counts.important ?? '—', ShieldCheck],
            ['Sessions', counts.sessions ?? '—', History],
          ].map(([label, value, Icon]) => (
            <div key={label} className="rounded-md border border-white/[0.07] bg-black/15 px-2.5 py-2">
              <div className="flex items-center gap-1.5 text-[7px] font-bold uppercase tracking-wider text-white/35">
                <Icon size={10} aria-hidden="true" />
                {label}
              </div>
              <div className={`mt-1 text-base font-black ${accentText}`}>{value}</div>
            </div>
          ))}
        </div>
      </section>

      <form onSubmit={applyFilters} className="grid shrink-0 grid-cols-12 gap-2 rounded-lg border border-white/[0.07] bg-black/15 p-2.5" aria-label="Memory filters">
        <label className="col-span-3 min-w-0">
          <span className="mb-1 block text-[7px] font-bold uppercase tracking-wider text-white/35">Project</span>
          <input
            value={draft.project}
            onChange={(event) => setDraft((current) => ({ ...current, project: event.target.value }))}
            maxLength={128}
            aria-label="Memory project"
            className="h-8 w-full rounded-md border border-white/10 bg-[#080B0F] px-2 text-[9px] text-white/80 outline-none focus:border-white/25"
          />
        </label>
        <label className="col-span-4 min-w-0">
          <span className="mb-1 block text-[7px] font-bold uppercase tracking-wider text-white/35">Search exact memory</span>
          <span className="relative block">
            <Search size={11} className="pointer-events-none absolute left-2 top-2.5 text-white/30" aria-hidden="true" />
            <input
              value={draft.query}
              onChange={(event) => setDraft((current) => ({ ...current, query: event.target.value }))}
              maxLength={240}
              placeholder="SQLite, owner style, next step…"
              aria-label="Search exact memory"
              className="h-8 w-full rounded-md border border-white/10 bg-[#080B0F] pl-7 pr-2 text-[9px] text-white/80 outline-none placeholder:text-white/20 focus:border-white/25"
            />
          </span>
        </label>
        <label className="col-span-2 min-w-0">
          <span className="mb-1 block text-[7px] font-bold uppercase tracking-wider text-white/35">Category</span>
          <select
            value={draft.category}
            onChange={(event) => setDraft((current) => ({ ...current, category: event.target.value }))}
            aria-label="Memory category"
            className="h-8 w-full rounded-md border border-white/10 bg-[#080B0F] px-1.5 text-[8px] text-white/70 outline-none focus:border-white/25"
          >
            <option value="">All</option>
            {Object.entries(CATEGORY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="col-span-2 min-w-0">
          <span className="mb-1 block text-[7px] font-bold uppercase tracking-wider text-white/35">Importance</span>
          <select
            value={draft.importance}
            onChange={(event) => setDraft((current) => ({ ...current, importance: event.target.value }))}
            aria-label="Memory importance"
            className="h-8 w-full rounded-md border border-white/10 bg-[#080B0F] px-1.5 text-[8px] text-white/70 outline-none focus:border-white/25"
          >
            <option value="">All</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </select>
        </label>
        <div className="col-span-1 flex items-end gap-1">
          <button type="submit" aria-label="Apply memory filters" className={`flex h-8 flex-1 items-center justify-center rounded-md border ${accentButton}`}>
            <Search size={12} aria-hidden="true" />
          </button>
          {(filters.query || filters.category || filters.importance) && (
            <button type="button" onClick={clearFilters} aria-label="Clear memory filters" className="flex h-8 w-7 items-center justify-center rounded-md border border-white/10 text-white/40 hover:text-white/75">
              <X size={11} aria-hidden="true" />
            </button>
          )}
        </div>
      </form>

      {(error || notice) && (
        <div className={`flex shrink-0 items-start gap-2 rounded-md border px-3 py-2 text-[8px] leading-relaxed ${
          error ? 'border-rose-400/20 bg-rose-500/[0.07] text-rose-200' : `${accentBorder} ${accentSurface} ${accentText}`
        }`} role="status">
          {error ? <AlertTriangle size={12} className="shrink-0" aria-hidden="true" /> : <Check size={12} className="shrink-0" aria-hidden="true" />}
          <span>{error || notice}</span>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-2 gap-3">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-white/[0.07] bg-black/15" aria-labelledby="important-memories-title">
          <header className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-3 py-2.5">
            <div>
              <h3 id="important-memories-title" className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-white/80">
                <ShieldCheck size={12} className={accentText} aria-hidden="true" />
                Important memories
              </h3>
              <p className="mt-1 text-[7px] text-white/25">Critical and high first · filtered records follow</p>
            </div>
            <span className={`rounded-full border ${accentBorder} px-2 py-1 text-[7px] font-bold ${accentText}`}>{counts.shown_memories ?? memories.length}</span>
          </header>
          <div data-testid="memory-list" className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2.5 no-visible-scrollbar">
            {status === 'loading' && <p className="px-1 py-4 text-center text-[8px] text-white/30">Loading stored memories…</p>}
            {status === 'ready' && memories.length === 0 && <p className="px-1 py-4 text-center text-[8px] text-white/30">No memory matches these filters.</p>}
            {memories.map((memory) => {
              const important = memory.importance === 'critical' || memory.importance === 'high';
              return (
                <article key={memory.id} className={`rounded-md border p-2.5 ${important ? `${accentBorder} ${accentSurface}` : 'border-white/[0.06] bg-white/[0.015]'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5 text-[7px] font-bold uppercase tracking-wider">
                      <span className={important ? accentText : 'text-sky-300/70'}>{CATEGORY_LABELS[memory.category] || memory.category}</span>
                      <span className="text-white/20">·</span>
                      <span className={memory.importance === 'critical' ? 'text-rose-300' : 'text-white/40'}>{memory.importance}</span>
                    </div>
                    <span className="shrink-0 text-[7px] text-white/25">rev {memory.revision}</span>
                  </div>
                  <p className="mt-2 whitespace-pre-wrap break-words text-[9px] leading-[1.55] text-white/80">{memory.content}</p>
                  <div className="mt-2 flex items-center justify-between gap-2 border-t border-white/[0.05] pt-2">
                    <div className="min-w-0 text-[7px] leading-relaxed text-white/30">
                      <span className="block truncate">memory · {memory.source}</span>
                      <span className="flex items-center gap-1"><Clock3 size={8} aria-hidden="true" />{formatTime(memory.updated_at || memory.created_at)}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setEditing({ ...memory, replacement: memory.content })}
                        aria-label={`Correct memory ${memory.id}`}
                        className="flex h-7 items-center gap-1 rounded border border-white/10 px-2 text-[7px] font-bold uppercase text-white/45 hover:border-sky-400/25 hover:text-sky-200"
                      >
                        <Pencil size={9} aria-hidden="true" /> Correct
                      </button>
                      <button
                        type="button"
                        onClick={() => requestExactConfirmation('forget', memory)}
                        disabled={Boolean(operation)}
                        aria-label={`Forget memory ${memory.id}`}
                        className="flex h-7 items-center gap-1 rounded border border-rose-400/15 px-2 text-[7px] font-bold uppercase text-rose-300/65 hover:border-rose-400/35 hover:text-rose-200 disabled:opacity-40"
                      >
                        <Trash2 size={9} aria-hidden="true" /> Forget
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-white/[0.07] bg-black/15" aria-labelledby="session-summaries-title">
          <header className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-3 py-2.5">
            <div>
              <h3 id="session-summaries-title" className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-white/80">
                <BookOpen size={12} className={accentText} aria-hidden="true" />
                Session summaries
              </h3>
              <p className="mt-1 text-[7px] text-white/25">Deterministic digest · canonical chat retained</p>
            </div>
            <span className={`rounded-full border ${accentBorder} px-2 py-1 text-[7px] font-bold ${accentText}`}>{counts.shown_sessions ?? summaries.length}</span>
          </header>
          <div data-testid="session-summary-list" className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2.5 no-visible-scrollbar">
            {status === 'loading' && <p className="px-1 py-4 text-center text-[8px] text-white/30">Loading session summaries…</p>}
            {status === 'ready' && summaries.length === 0 && <p className="px-1 py-4 text-center text-[8px] text-white/30">No session summary matches this search.</p>}
            {summaries.map((summary) => (
              <article key={summary.session_id} className="rounded-md border border-white/[0.06] bg-white/[0.015] p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5 text-[7px] font-bold uppercase tracking-wider">
                    <span className={accentText}>{summary.personality}</span>
                    <span className="text-white/20">·</span>
                    <span className={summary.status === 'active' ? 'text-sky-300' : 'text-white/40'}>{summary.status}</span>
                  </div>
                  <span className="shrink-0 text-[7px] text-white/30">{summary.turn_count} turns</span>
                </div>
                <p className="mt-2 break-words text-[9px] leading-[1.55] text-white/75">{summary.summary_text}</p>
                <div className="mt-2 border-t border-white/[0.05] pt-2 text-[7px] leading-relaxed text-white/30">
                  <span className="block truncate">session summary · {summary.session_id}</span>
                  <span className="flex items-center gap-1"><Clock3 size={8} aria-hidden="true" />{formatTime(summary.last_activity_at || summary.updated_at)}</span>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>

      {editing && !pending && (
        <div className="absolute inset-x-2 bottom-2 z-20 rounded-lg border border-sky-400/25 bg-[#0B1117]/98 p-3 shadow-[0_18px_50px_rgba(0,0,0,0.65)] backdrop-blur-xl" data-testid="memory-correction-editor">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-wider text-sky-200">Correct stored memory</p>
              <p className="mt-1 text-[7px] text-white/35">A new revision is written only after exact confirmation.</p>
            </div>
            <button type="button" onClick={() => setEditing(null)} aria-label="Close memory correction editor" className="text-white/35 hover:text-white/80"><X size={14} /></button>
          </div>
          <textarea
            value={editing.replacement}
            onChange={(event) => setEditing((current) => ({ ...current, replacement: event.target.value }))}
            maxLength={4000}
            rows={4}
            aria-label="Corrected memory content"
            className="mt-3 w-full resize-none rounded-md border border-white/10 bg-black/30 p-2 text-[9px] leading-relaxed text-white/80 outline-none focus:border-sky-400/30"
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-[7px] text-white/25">{editing.replacement.length}/4000</span>
            <button
              type="button"
              onClick={() => requestExactConfirmation('correct', editing, editing.replacement)}
              disabled={!editing.replacement.trim() || editing.replacement.trim() === editing.content.trim() || Boolean(operation)}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-sky-400/30 bg-sky-500/10 px-3 text-[8px] font-bold uppercase tracking-wider text-sky-200 disabled:opacity-35"
            >
              <ShieldCheck size={11} aria-hidden="true" /> Review exact change
            </button>
          </div>
        </div>
      )}

      {pending && (
        <div className="absolute inset-0 z-30 flex items-center justify-center rounded-lg bg-black/70 p-6 backdrop-blur-sm" data-testid="memory-exact-confirmation">
          <div className="w-full max-w-sm rounded-xl border border-amber-400/25 bg-[#11100B]/98 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.75)]">
            <div className="flex items-start gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-amber-400/25 bg-amber-500/10 text-amber-300"><ShieldCheck size={15} /></span>
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-[0.14em] text-amber-200">Exact confirmation required</h4>
                <p className="mt-1.5 text-[8px] leading-relaxed text-white/50">
                  {pending.action === 'forget'
                    ? 'This permanently removes the selected memory from storage and recall.'
                    : 'This replaces the selected text and creates a corrected revision.'}
                </p>
              </div>
            </div>
            <div className="mt-3 rounded-md border border-white/[0.07] bg-black/20 p-2 text-[7px] leading-relaxed text-white/35">
              One-time token · same session · same tool · same exact arguments<br />
              Bound hash: {String(pending.arguments_hash || '').slice(0, 16)}…
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setPending(null)} disabled={Boolean(operation)} className="h-8 rounded-md border border-white/10 px-3 text-[8px] font-bold uppercase text-white/45 hover:text-white/80">Cancel</button>
              <button type="button" onClick={confirmExactAction} disabled={Boolean(operation)} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-400/30 bg-amber-500/10 px-3 text-[8px] font-bold uppercase text-amber-200 disabled:opacity-40">
                <Check size={11} aria-hidden="true" /> Confirm once
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
