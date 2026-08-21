import React, { useState } from 'react';
import { Zap } from 'lucide-react';
import { executeToolWithConfirmation } from '../../api';

/**
 * CodeOptimizerWidget Component
 * Allows audit scanning of target Python or JS/TS files in the workspace.
 * Reports on SOLID principle violations, security flaws (eval/exec), and lines counts.
 */
export default function CodeOptimizerWidget() {
  const [filepath, setFilepath] = useState('backend/app/main.py');
  const [optType, setOptType] = useState('solid');
  const [applyChanges, setApplyChanges] = useState(false);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);

  const handleOptimize = async (e) => {
    e.preventDefault();
    if (!filepath.trim()) return;

    setLoading(true);
    setResults(null);
    setError(null);

    try {
      const data = await executeToolWithConfirmation(
        'optimize_code',
        {
          filepath: filepath.trim(),
          optimization_type: optType,
          apply_changes: applyChanges,
        },
        'code_optimizer_widget',
      );
      if (data.success) {
        setResults(data.data);
      } else {
        setError(data.status === 'PENDING_CONFIRMATION' ? 'Confirmation cancelled.' : (data.error || 'Failed to complete optimization.'));
      }
    } catch (err) {
      setError('Connection failed. Server offline.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full w-full font-mono text-[10px] text-white/90 p-4 space-y-4 overflow-y-auto custom-scrollbar">
      
      {/* Header */}
      <div className="flex justify-between items-center border-b border-white/5 pb-2">
        <span className="flex items-center gap-1.5 text-[11px] font-bold tracking-widest text-[#7DD3FC] uppercase">
          <Zap size={13} strokeWidth={1.8} aria-hidden="true" />
          SOLID Code Optimizer
        </span>
      </div>

      {/* Inputs Form */}
      <form onSubmit={handleOptimize} className="space-y-2 bg-white/[0.01] border border-white/5 p-2 rounded-sm text-[8px] uppercase">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-white/40 block mb-1">Target Code Path</label>
            <input 
              type="text" 
              placeholder="e.g. backend/app/main.py"
              value={filepath}
              onChange={e => setFilepath(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-2 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white placeholder-white/20 text-[9px]"
            />
          </div>
          <div>
            <label className="text-white/40 block mb-1">Optimization Goal</label>
            <select
              value={optType}
              onChange={e => setOptType(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-1 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white text-[9px]"
            >
              <option value="solid" className="bg-[#1E1E24]">SOLID Rules</option>
              <option value="performance" className="bg-[#1E1E24]">Performance</option>
              <option value="readability" className="bg-[#1E1E24]">Readability</option>
              <option value="security" className="bg-[#1E1E24]">Security checks</option>
            </select>
          </div>
        </div>

        <div className="flex items-center justify-between py-1">
          <div className="flex items-center gap-2">
            <input 
              type="checkbox"
              id="applyCheck"
              checked={applyChanges}
              onChange={e => setApplyChanges(e.target.checked)}
              className="rounded-sm accent-[#7DD3FC] border-white/10"
            />
            <label htmlFor="applyCheck" className="text-white/50 cursor-pointer">Apply Optimization & Backup</label>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-[#7DD3FC]/10 border border-[#7DD3FC]/20 text-[#7DD3FC] hover:bg-[#7DD3FC]/20 px-3 py-1 rounded-sm tracking-wider font-bold"
          >
            {loading ? 'Analyzing...' : 'Audit File'}
          </button>
        </div>
      </form>

      {/* Errors or Results Panel */}
      {error && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-2 rounded-sm text-[8px] uppercase">
          {error}
        </div>
      )}

      {results && (
        <div className="space-y-3 flex-1 overflow-y-auto max-h-[160px] custom-scrollbar text-[8px] uppercase">
          
          {/* Metadata Grid */}
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-white/5 p-1 rounded-sm">
              <div className="text-white/40">Classes</div>
              <div className="font-bold text-white text-[10px]">{results.ast_metrics.num_classes}</div>
            </div>
            <div className="bg-white/5 p-1 rounded-sm">
              <div className="text-white/40">Functions</div>
              <div className="font-bold text-white text-[10px]">{results.ast_metrics.num_functions}</div>
            </div>
            <div className="bg-white/5 p-1 rounded-sm">
              <div className="text-white/40">Complexity</div>
              <div className="font-bold text-[#7DD3FC] truncate">{results.ast_metrics.complexity_score}</div>
            </div>
          </div>

          {/* Feedback messages */}
          <div className="bg-[#7DD3FC]/5 border border-[#7DD3FC]/10 p-2 rounded-sm text-white/80 lowercase first-letter:uppercase">
            {results.message}
          </div>

          {/* SOLID warnings list */}
          {results.ast_metrics.solid_violations.length > 0 && (
            <div className="space-y-1">
              <span className="text-amber-400/60 block font-bold">SOLID Compliance Warnings:</span>
              {results.ast_metrics.solid_violations.map((vi, index) => (
                <div key={index} className="bg-amber-500/5 border border-amber-500/10 p-1.5 rounded-sm text-amber-300">
                  <span className="font-bold">[{vi.principle}]</span> {vi.detail}
                </div>
              ))}
            </div>
          )}

          {/* Raw findings */}
          {results.ast_findings.length > 0 && (
            <div className="space-y-1">
              <span className="text-rose-400/60 block font-bold">Structural Findings:</span>
              {results.ast_findings.map((f, index) => (
                <div key={index} className="bg-rose-500/5 border border-rose-500/10 p-1 rounded-sm text-rose-300">
                  {f}
                </div>
              ))}
            </div>
          )}

        </div>
      )}

    </div>
  );
}
