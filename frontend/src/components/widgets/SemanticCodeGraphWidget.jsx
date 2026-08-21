import React, { useState, useEffect } from 'react';
import { Workflow } from 'lucide-react';
import { apiBase } from '../../api';

/**
 * SemanticCodeGraphWidget Component
 * Interacts with SemanticGraphTool to render local repository AST call graphs,
 * import structures, dependencies, and search indices.
 */
export default function SemanticCodeGraphWidget() {
  const [queryType, setQueryType] = useState('summary');
  const [targetSymbol, setTargetSymbol] = useState('');
  const [targetPath, setTargetPath] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');

  const runQuery = async (type = queryType) => {
    setLoading(true);
    setResults(null);
    setError('');

    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'semantic_code_graph',
          arguments: {
            query_type: type,
            target_symbol: targetSymbol ? targetSymbol.trim() : undefined,
            target_path: targetPath ? targetPath.trim() : undefined
          }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Semantic graph query failed.');
      setResults(data.data);
    } catch (e) {
      setError(e.message || 'Semantic graph query failed.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runQuery('summary');
  }, []);

  return (
    <div className="flex flex-col h-full w-full font-mono text-[10px] text-white/90 p-4 space-y-4 overflow-y-auto custom-scrollbar">
      
      {/* Header */}
      <div className="flex justify-between items-center border-b border-white/5 pb-2">
        <span className="flex items-center gap-1.5 text-[11px] font-bold tracking-widest text-[#7DD3FC] uppercase">
          <Workflow size={13} strokeWidth={1.8} aria-hidden="true" />
          Semantic Code Graph
        </span>
        <div className="flex gap-1.5">
          <button
            onClick={() => runQuery('build')}
            disabled={loading}
            className="bg-[#7DD3FC]/10 border border-[#7DD3FC]/30 text-[#7DD3FC] px-1.5 py-0.5 rounded-sm text-[7px] uppercase"
            title="Force refresh of index tree"
          >
            Rebuild Index
          </button>
        </div>
      </div>

      {/* Inputs selector panel */}
      <div className="space-y-2 bg-white/[0.01] border border-white/5 p-2 rounded-sm text-[8px] uppercase">
        <div className="flex justify-between items-center gap-2">
          <select
            value={queryType}
            onChange={e => {
              setQueryType(e.target.value);
              setResults(null);
            }}
            className="bg-white/5 border border-white/10 rounded-sm px-1 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white text-[9px] flex-1"
          >
            <option value="summary" className="bg-[#1E1E24]">Codebase Summary</option>
            <option value="search" className="bg-[#1E1E24]">Symbol Search</option>
            <option value="callers" className="bg-[#1E1E24]">Trace Callers</option>
            <option value="dependencies" className="bg-[#1E1E24]">File Dependencies</option>
          </select>
          <button
            onClick={() => runQuery()}
            disabled={loading}
            className="bg-[#7DD3FC]/15 hover:bg-[#7DD3FC]/25 text-[#7DD3FC] font-bold py-1 px-3 rounded-sm border border-[#7DD3FC]/20"
          >
            {loading ? 'Querying...' : 'Query'}
          </button>
        </div>

        {/* Dynamic fields based on selection */}
        {queryType === 'search' || queryType === 'callers' ? (
          <div>
            <label className="text-white/40 block mb-1">Target Symbol</label>
            <input 
              type="text" 
              placeholder="e.g. get_db_connection"
              value={targetSymbol}
              onChange={e => setTargetSymbol(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-2 py-1 text-white placeholder-white/20 text-[9px] focus:outline-none focus:border-[#7DD3FC]"
            />
          </div>
        ) : null}

        {queryType === 'dependencies' ? (
          <div>
            <label className="text-white/40 block mb-1">Target Module Path</label>
            <input 
              type="text" 
              placeholder="e.g. backend/app/main.py"
              value={targetPath}
              onChange={e => setTargetPath(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-2 py-1 text-white placeholder-white/20 text-[9px] focus:outline-none focus:border-[#7DD3FC]"
            />
          </div>
        ) : null}
      </div>

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-300 p-2 rounded-sm text-[8px] uppercase">
          {error}
        </div>
      )}

      {/* Query Results presentation */}
      {results && (
        <div className="space-y-3 flex-1 overflow-y-auto max-h-[160px] custom-scrollbar text-[8px] uppercase">
          
          {/* Summary Details */}
          {results.stats && (
            <div className="space-y-2">
              <div className="grid grid-cols-4 gap-2 text-center text-[7px]">
                <div className="bg-white/5 p-1 rounded-sm">
                  <div className="text-white/40">Files</div>
                  <div className="font-bold text-white text-[9px]">{results.stats.files_indexed}</div>
                </div>
                <div className="bg-white/5 p-1 rounded-sm">
                  <div className="text-white/40">Classes</div>
                  <div className="font-bold text-white text-[9px]">{results.stats.total_classes}</div>
                </div>
                <div className="bg-white/5 p-1 rounded-sm">
                  <div className="text-white/40">Funcs</div>
                  <div className="font-bold text-white text-[9px]">{results.stats.total_functions}</div>
                </div>
                <div className="bg-white/5 p-1 rounded-sm">
                  <div className="text-white/40">Imports</div>
                  <div className="font-bold text-white text-[9px]">{results.stats.total_imports}</div>
                </div>
              </div>

              {results.top_called_symbols && (
                <div className="space-y-1">
                  <span className="text-white/40 block font-bold">Top Interconnected Symbols:</span>
                  {results.top_called_symbols.map((item, idx) => (
                    <div key={idx} className="flex justify-between items-center bg-white/[0.02] border border-white/5 p-1 px-2 rounded-sm">
                      <span className="font-bold text-sky-300">{item.symbol}</span>
                      <span className="text-[7px] text-white/40">{item.call_count} calls</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Symbol Search results */}
          {results.definitions && (
            <div className="space-y-2">
              <span className="text-white/40 block font-bold">Symbol Definitions:</span>
              {results.definitions.length === 0 ? (
                <div className="text-center text-white/30 py-2">No definitions found for '{results.symbol}'</div>
              ) : (
                results.definitions.map((def, idx) => (
                  <div key={idx} className="bg-white/5 p-1.5 rounded-sm border border-white/5 flex justify-between items-center">
                    <div>
                      <span className="font-bold text-[#7DD3FC]">{results.symbol}</span>
                      <span className="text-[7px] text-white/40 ml-1.5">{def.type}</span>
                    </div>
                    <span className="text-white/30 text-[7px]">{def.file}:{def.line}</span>
                  </div>
                ))
              )}

              <span className="text-white/40 block font-bold mt-2">Symbol Usages ({results.usages_count}):</span>
              {results.usages && results.usages.map((use, idx) => (
                <div key={idx} className="bg-white/[0.01] border border-white/5 p-1 rounded-sm flex justify-between items-center text-[7px]">
                  <span className="text-white/70 font-mono font-bold truncate max-w-[140px]">{use.full_expression}</span>
                  <span className="text-white/30">{use.file}:{use.line}</span>
                </div>
              ))}
            </div>
          )}

          {/* Trace Callers results */}
          {results.callers && (
            <div className="space-y-1.5">
              <span className="text-white/40 block font-bold">Trace Callers ({results.callers_count}):</span>
              {results.callers.length === 0 ? (
                <div className="text-center text-white/30 py-2">No callers detected for symbol '{results.symbol}'</div>
              ) : (
                results.callers.map((use, idx) => (
                  <div key={idx} className="bg-white/5 p-1.5 rounded-sm border border-white/5 flex justify-between items-center">
                    <span className="font-mono text-amber-300 font-bold truncate max-w-[150px]">{use.full_expression}</span>
                    <span className="text-[7px] text-white/30">{use.file}:{use.line}</span>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Dependencies results */}
          {results.imports && (
            <div className="space-y-2">
              <span className="text-white/40 block font-bold">File: {results.file}</span>
              <div className="grid grid-cols-2 gap-1 bg-white/5 p-1.5 rounded-sm text-[7px]">
                <div>Definitions: {results.classes_defined.length} Classes</div>
                <div>Functions: {results.functions_defined.length} Defs</div>
              </div>
              
              <span className="text-white/40 block font-bold mt-1">Imported modules:</span>
              {results.imports.length === 0 ? (
                <div className="text-center text-white/30">No imports detected</div>
              ) : (
                results.imports.map((imp, idx) => (
                  <div key={idx} className="bg-white/[0.01] border border-white/5 p-1 rounded-sm text-[7px] flex justify-between items-center">
                    <span className="text-white/80">{imp.name}</span>
                    {imp.alias && <span className="text-white/30">as {imp.alias}</span>}
                  </div>
                ))
              )}
            </div>
          )}

        </div>
      )}

    </div>
  );
}
