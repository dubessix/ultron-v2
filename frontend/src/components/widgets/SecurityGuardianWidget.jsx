import React, { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { executeToolWithConfirmation } from '../../api';

/**
 * SecurityGuardianWidget Component
 * Renders results from bounded secret-pattern, high-memory process, and limited manifest checks.
 */
export default function SecurityGuardianWidget() {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');

  const runAudit = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await executeToolWithConfirmation(
        'security_scan',
        {
          scan_workspace_secrets: true,
          scan_active_processes: true,
          scan_dependency_manifests: true,
        },
        'security_guardian_widget',
      );
      if (!data.success) throw new Error(data.error || data.message || 'Security checks unavailable.');
      setResults(data.data);
    } catch (e) {
      setResults(null);
      setError(e.message || 'Security checks unavailable.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full w-full font-mono text-[10px] text-white/90 p-4 space-y-4 overflow-y-auto custom-scrollbar">
      
      {/* Header */}
      <div className="flex justify-between items-center border-b border-white/5 pb-2">
        <span className="flex items-center gap-1.5 text-[11px] font-bold tracking-widest text-rose-400 uppercase">
          <ShieldCheck size={13} strokeWidth={1.8} aria-hidden="true" />
          Security Shield
        </span>
        <button
          onClick={runAudit}
          disabled={loading}
          className="bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 text-rose-400 text-[8px] px-2 py-0.5 rounded-sm uppercase tracking-wider"
        >
          {loading ? 'Auditing...' : 'Run Audit'}
        </button>
      </div>

      {/* Main Panel Content */}
      {!results ? (
        <div className="flex-1 flex flex-col items-center justify-center py-6 text-center text-white/30 space-y-2 uppercase">
          <span>{error ? `Checks unavailable: ${error}` : 'Not checked yet. Run the limited local security checks.'}</span>
        </div>
      ) : (
        <div className="space-y-3 flex-1 overflow-y-auto max-h-[220px] custom-scrollbar">
          
          {/* Summary */}
          <div className="grid grid-cols-4 gap-2 text-center text-[8px] uppercase">
            <div className="bg-white/5 p-1 rounded-sm">
              <div className="text-white/40 mb-0.5">Total</div>
              <div className="font-bold text-white text-[10px]">{results.statistics.total_findings}</div>
            </div>
            <div className="bg-rose-500/5 p-1 rounded-sm border border-rose-500/10">
              <div className="text-rose-400/40 mb-0.5">Critical</div>
              <div className="font-bold text-rose-400 text-[10px]">{results.statistics.critical_count}</div>
            </div>
            <div className="bg-amber-500/5 p-1 rounded-sm border border-amber-500/10">
              <div className="text-amber-400/40 mb-0.5">High</div>
              <div className="font-bold text-amber-400 text-[10px]">{results.statistics.high_count}</div>
            </div>
            <div className="bg-sky-500/5 p-1 rounded-sm border border-sky-500/10">
              <div className="text-sky-400/40 mb-0.5">Medium</div>
              <div className="font-bold text-sky-400 text-[10px]">{results.statistics.medium_count}</div>
            </div>
          </div>

          {/* Verdict Message */}
          <div className="bg-white/[0.01] border border-white/5 p-2 rounded-sm text-[8px] uppercase text-white/70">
            {results.message}
          </div>

          {/* Finding items list */}
          <div className="space-y-2">
            {results.findings.length === 0 ? (
              <div className="text-center py-4 text-emerald-400 text-[8px] uppercase border border-dashed border-emerald-500/10 bg-emerald-500/5">
                No findings in selected checks — not a complete safety guarantee
              </div>
            ) : (
              results.findings.map((item, idx) => (
                <div 
                  key={idx} 
                  className={`p-2 rounded-sm border text-[8px] uppercase space-y-1 ${
                    item.severity === 'CRITICAL' 
                      ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' 
                      : item.severity === 'HIGH'
                        ? 'bg-amber-500/10 border-amber-500/20 text-amber-300'
                        : 'bg-white/5 border-white/10 text-white/80'
                  }`}
                >
                  <div className="flex justify-between items-center font-bold">
                    <span>[{item.severity}] {item.category}</span>
                    <span className="text-[7px] text-white/30">{item.file}</span>
                  </div>
                  <div className="text-white/60 leading-normal lowercase first-letter:uppercase">
                    {item.detail}
                  </div>
                  <div className="text-white/40 leading-normal border-t border-white/5 pt-1 uppercase text-[7px]">
                    Remedy: {item.remediation}
                  </div>
                </div>
              ))
            )}
          </div>

        </div>
      )}

    </div>
  );
}
