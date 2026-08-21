import React, { useState, useEffect } from 'react';
import { Clock3, X } from 'lucide-react';
import { apiBase } from '../../api';

/**
 * ReminderWidget Component
 * Displays a list of active alarms and reminders in SQLite.
 * Allows interactive creating, snoozing, dismissing, and deleting of timers.
 * Utilizes standard glassmorphism elements with responsive action triggers.
 */
export default function ReminderWidget() {
  const [reminders, setReminders] = useState([]);
  const [title, setTitle] = useState('');
  const [type, setType] = useState('reminder');
  const [targetTime, setTargetTime] = useState('5m');
  const [recurrence, setRecurrence] = useState('one_time');
  const [loading, setLoading] = useState(false);
  const [listAvailable, setListAvailable] = useState(null);
  const [message, setMessage] = useState(null);

  // Fetch all reminders from the backend
  const fetchReminders = async () => {
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_reminder',
          arguments: { action: 'list' }
        })
      });
      const resData = await response.json();
      if (!resData.success) throw new Error(resData.error || 'Reminder list unavailable.');
      setReminders(resData.data.reminders || []);
      setListAvailable(true);
    } catch (err) {
      setReminders([]);
      setListAvailable(false);
      setMessage({ text: err.message || 'Reminder list unavailable.', type: 'error' });
    }
  };

  useEffect(() => {
    fetchReminders();
    // Poll reminders every 5 seconds for live status updates
    const interval = setInterval(fetchReminders, 5000);
    return () => clearInterval(interval);
  }, []);

  // Handle reminder creation
  const handleCreate = async (e) => {
    e.preventDefault();
    if (!title.trim() || !targetTime.trim()) return;

    setLoading(true);
    setMessage(null);

    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_reminder',
          arguments: {
            action: 'create',
            type,
            title,
            target_time: targetTime,
            recurrence
          }
        })
      });
      const resData = await response.json();
      if (resData.success) {
        setTitle('');
        setMessage({ text: 'Alert scheduled successfully!', type: 'success' });
        fetchReminders();
      } else {
        setMessage({ text: resData.error || 'Failed to create alert.', type: 'error' });
      }
    } catch (err) {
      setMessage({ text: 'Network connection failed.', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  // Dismiss/Snooze/Delete Action Router
  const handleAction = async (action, id) => {
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_reminder',
          arguments: { action, reminder_id: id }
        })
      });
      const resData = await response.json();
      if (!resData.success) throw new Error(resData.error || `${action} failed.`);
      fetchReminders();
    } catch (err) {
      setMessage({ text: err.message || `${action} failed.`, type: 'error' });
    }
  };

  const formatTime = (isoString) => {
    try {
      const dt = new Date(isoString);
      return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) {
      return isoString;
    }
  };

  return (
    <div className="flex flex-col h-full w-full font-mono text-[10px] text-white/90 p-4 space-y-4 overflow-y-auto custom-scrollbar">
      
      {/* 1. Header and Quick Stats */}
      <div className="flex justify-between items-center border-b border-white/5 pb-2">
        <span className="flex items-center gap-1.5 text-[11px] font-bold tracking-widest text-[#7DD3FC] uppercase">
          <Clock3 size={13} strokeWidth={1.8} aria-hidden="true" />
          Scheduler Cache
        </span>
        <span className="bg-white/5 px-2 py-0.5 rounded-full text-[8px] text-white/50 uppercase">
          {listAvailable === true
            ? `${reminders.filter(r => r.status === 'pending' || r.status === 'snoozed').length} Pending`
            : listAvailable === false ? 'Unavailable' : 'Loading'}
        </span>
      </div>

      {/* 2. Feedback Message */}
      {message && (
        <div className={`p-2 rounded-sm border text-[8px] uppercase ${
          message.type === 'success' 
            ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
            : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
        }`}>
          {message.text}
        </div>
      )}

      {/* 3. Creation Form */}
      <form onSubmit={handleCreate} className="space-y-2 bg-white/[0.01] border border-white/5 p-2 rounded-sm">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[8px] text-white/40 block mb-1 uppercase">Alert Subject</label>
            <input 
              type="text" 
              placeholder="e.g. Commit code"
              value={title}
              onChange={e => setTitle(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-2 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white placeholder-white/20"
            />
          </div>
          <div>
            <label className="text-[8px] text-white/40 block mb-1 uppercase">Target Time / Offset</label>
            <input 
              type="text" 
              placeholder="e.g. 10m, 1h, 30s"
              value={targetTime}
              onChange={e => setTargetTime(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-2 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white placeholder-white/20"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[8px] text-white/40 block mb-1 uppercase">Recurrence</label>
            <select
              value={recurrence}
              onChange={e => setRecurrence(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-1.5 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white"
            >
              <option value="one_time" className="bg-[#1E1E24]">One-Time</option>
              <option value="daily" className="bg-[#1E1E24]">Daily Recur</option>
              <option value="weekly" className="bg-[#1E1E24]">Weekly Recur</option>
            </select>
          </div>
          <div>
            <label className="text-[8px] text-white/40 block mb-1 uppercase">Type</label>
            <select
              value={type}
              onChange={e => setType(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-1.5 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white"
            >
              <option value="reminder" className="bg-[#1E1E24]">Reminder</option>
              <option value="alarm" className="bg-[#1E1E24]">Alarm</option>
            </select>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-[#7DD3FC]/10 border border-[#7DD3FC]/20 text-[#7DD3FC] hover:bg-[#7DD3FC]/20 py-1 rounded-sm text-[8px] uppercase tracking-wider font-bold transition-all"
        >
          {loading ? 'Scheduling...' : 'Queue Alert'}
        </button>
      </form>

      {/* 4. Active Alarms / Reminders Queue */}
      <div className="space-y-2 flex-1 overflow-y-auto max-h-[140px] custom-scrollbar">
        <span className="text-[8px] text-white/40 block uppercase">Upcoming Triggers</span>
        
        {listAvailable === true && reminders.length === 0 ? (
          <div className="text-center py-4 text-white/25 text-[8px] border border-dashed border-white/5 uppercase">
            No active schedules
          </div>
        ) : (
          reminders.map(rem => (
            <div 
              key={rem.id} 
              className={`flex items-center justify-between p-2 rounded-sm border transition-all ${
                rem.status === 'snoozed'
                  ? 'bg-amber-500/5 border-amber-500/20 text-amber-300'
                  : rem.status === 'triggered'
                    ? 'bg-rose-500/15 border-rose-500/30 text-rose-400 animate-pulse'
                    : 'bg-white/[0.01] border-white/5'
              }`}
            >
              <div className="space-y-0.5 max-w-[65%]">
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    rem.type === 'alarm' ? 'bg-rose-400' : 'bg-[#7DD3FC]'
                  }`} />
                  <span className="font-bold truncate max-w-[120px] uppercase">
                    {rem.title}
                  </span>
                  {rem.recurrence !== 'one_time' && (
                    <span className="bg-purple-500/15 border border-purple-500/20 text-[6px] text-purple-300 px-1 py-0.2 rounded-full uppercase">
                      {rem.recurrence}
                    </span>
                  )}
                </div>
                <div className="text-[8px] text-white/40">
                  Target: {formatTime(rem.target_time)}
                </div>
              </div>

              <div className="flex gap-1">
                {rem.status === 'triggered' || rem.status === 'snoozed' ? (
                  <>
                    <button
                      onClick={() => handleAction('dismiss', rem.id)}
                      className="px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 text-emerald-400 rounded-sm text-[8px] uppercase"
                    >
                      Ok
                    </button>
                    <button
                      onClick={() => handleAction('snooze', rem.id)}
                      className="px-1.5 py-0.5 bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/20 text-amber-400 rounded-sm text-[8px] uppercase"
                    >
                      Snooze
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => handleAction('dismiss', rem.id)}
                      className="px-1.5 py-0.5 bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 hover:text-white rounded-sm text-[8px] uppercase"
                      title="Dismiss this reminder"
                    >
                      Dismiss
                    </button>
                    <button
                      onClick={() => handleAction('delete', rem.id)}
                      className="px-1.5 py-0.5 bg-rose-500/5 hover:bg-rose-500/15 border border-rose-500/10 text-rose-400 rounded-sm text-[8px]"
                      aria-label="Delete reminder"
                      title="Delete reminder"
                    >
                      <X size={11} strokeWidth={1.8} aria-hidden="true" />
                    </button>
                  </>
                )}
              </div>
            </div>
          ))
        )}
      </div>

    </div>
  );
}
