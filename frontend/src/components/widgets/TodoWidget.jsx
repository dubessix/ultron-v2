import React, { useState, useEffect } from 'react';
import { Check, X } from 'lucide-react';
import { apiBase } from '../../api';

/**
 * TodoWidget Content Component
 * Renders developer tasks from SQLite with user-defined project/module scopes.
 */
export default function TodoWidget() {
  const [todos, setTodos] = useState([]);
  const [newTodoText, setNewTodoText] = useState("");
  const [project, setProject] = useState("General");
  const [module, setModule] = useState("Root");
  const [priority, setPriority] = useState("medium");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchTodos = async () => {
    setError("");
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_task',
          arguments: { action: 'list', project_name: project }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Task list unavailable.');
      setTodos(data.data.tasks || []);
    } catch (err) {
      setTodos([]);
      setError(err.message || 'Task list unavailable.');
    }
  };

  useEffect(() => {
    fetchTodos();
  }, [project]);

  const handleAddTodo = async (e) => {
    e.preventDefault();
    if (!newTodoText.trim() || loading) return;

    setLoading(true);
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_task',
          arguments: {
            action: 'create',
            project_name: project,
            module_name: module,
            title: newTodoText.trim(),
            priority: priority,
            status: 'todo'
          }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Task creation failed.');
      setNewTodoText("");
      setError("");
      fetchTodos();
    } catch (err) {
      setError(err.message || 'Task creation failed.');
    } finally {
      setLoading(false);
    }
  };

  const toggleTodo = async (id, currentStatus) => {
    const nextStatus = currentStatus === 'done' ? 'todo' : 'done';
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_task',
          arguments: {
            action: 'update_status',
            task_id: id,
            status: nextStatus
          }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Task update failed.');
      setError("");
      fetchTodos();
    } catch (err) {
      setError(err.message || 'Task update failed.');
    }
  };

  const deleteTask = async (id) => {
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_task',
          arguments: {
            action: 'delete',
            task_id: id
          }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Task deletion failed.');
      setError("");
      fetchTodos();
    } catch (err) {
      setError(err.message || 'Task deletion failed.');
    }
  };

  return (
    <div className="space-y-3 font-mono text-[10px] text-white/90 p-1 overflow-y-auto max-h-[220px] custom-scrollbar">
      
      {/* User-defined scope; no sample projects/modules are preloaded. */}
      <div className="grid grid-cols-2 gap-1 bg-white/5 p-1 rounded-sm text-[8px] uppercase">
        <label className="text-white/40 text-[6px]">
          Project scope
          <input value={project} onChange={e => setProject(e.target.value)}
            className="mt-1 w-full bg-transparent border border-white/10 text-[#7DD3FC] px-1 py-0.5 focus:outline-none text-[8px]" />
        </label>
        <label className="text-white/40 text-[6px]">
          Module
          <input value={module} onChange={e => setModule(e.target.value)}
            className="mt-1 w-full bg-transparent border border-white/10 text-[#7DD3FC] px-1 py-0.5 focus:outline-none text-[8px]" />
        </label>
      </div>

      {/* Add Todo input bar */}
      <form onSubmit={handleAddTodo} className="flex gap-2">
        <input 
          type="text"
          value={newTodoText}
          onChange={(e) => setNewTodoText(e.target.value)}
          placeholder="New priority backlog task..."
          className="flex-1 bg-white/[0.02] border border-white/10 rounded-sm px-2 py-1 text-[9px] text-[#F5F5F7] focus:outline-none focus:border-sky-400/30 placeholder-white/20"
        />
        <select
          value={priority}
          onChange={e => setPriority(e.target.value)}
          className="bg-white/5 border border-white/10 rounded-sm text-[8px]"
        >
          <option value="high" className="bg-[#1E1E24]">High</option>
          <option value="medium" className="bg-[#1E1E24]">Med</option>
          <option value="low" className="bg-[#1E1E24]">Low</option>
        </select>
        <button 
          type="submit"
          disabled={loading}
          className="px-3 py-1 border border-white/10 rounded-sm text-[8px] uppercase hover:bg-white/5"
        >
          Add
        </button>
      </form>

      {error && <p className="text-[8px] text-rose-300">Unavailable: {error}</p>}

      {/* Structured prioritized list */}
      <div className="space-y-1.5 flex-1 max-h-[120px] overflow-y-auto custom-scrollbar">
        {!error && todos.length === 0 ? (
          <div className="text-center py-4 text-white/25 text-[8px] border border-dashed border-white/5 uppercase">
            No active sprint backlog tasks
          </div>
        ) : (
          todos.map(todo => (
            <div 
              key={todo.id}
              className="flex items-center justify-between hover:bg-white/[0.01] p-1 rounded-sm border border-white/5 transition-all"
            >
              <div 
                onClick={() => toggleTodo(todo.id, todo.status)}
                className="flex items-start gap-2.5 cursor-pointer flex-1 min-w-0"
              >
                {/* Custom Checkbox */}
                <div className={`w-3 h-3 rounded-sm border flex items-center justify-center mt-0.5 ${
                  todo.status === 'done' ? "border-emerald-500 bg-emerald-500/10 text-emerald-400" : "border-white/10"
                }`}>
                  {todo.status === 'done' && <Check size={9} strokeWidth={2} aria-hidden="true" />}
                </div>
                
                {/* Title & Priority Badge */}
                <div className="flex-1 min-w-0">
                  <p className={`truncate text-[9px] uppercase ${todo.status === 'done' ? "line-through text-[#8B8B96]" : "text-white"}`}>
                    {todo.title}
                  </p>
                  <div className="flex gap-1.5 mt-0.5 items-center">
                    <span className={`text-[5px] uppercase tracking-widest font-bold px-1 py-0.2 rounded-sm ${
                      todo.priority === "high" ? "bg-rose-500/10 text-rose-400 border border-rose-500/20" :
                      todo.priority === "medium" ? "bg-[#7DD3FC]/10 text-[#7DD3FC] border border-[#7DD3FC]/20" :
                      "bg-white/5 text-[#8B8B96]"
                    }`}>
                      {todo.priority}
                    </span>
                    <span className="text-[5px] text-white/30 uppercase">{todo.module_name}</span>
                  </div>
                </div>
              </div>

              {/* Action buttons */}
              <button 
                onClick={() => deleteTask(todo.id)}
                className="text-rose-400 hover:text-rose-500 bg-rose-500/5 hover:bg-rose-500/10 px-1 py-0.5 border border-rose-500/10 rounded-sm text-[7px]"
                aria-label="Delete task"
                title="Delete task"
              >
                <X size={11} strokeWidth={1.8} aria-hidden="true" />
              </button>
            </div>
          ))
        )}
      </div>

    </div>
  );
}
