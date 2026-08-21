import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { apiBase } from '../../api';

/**
 * CalendarWidget Component
 * Interacts with backend manage_calendar tool.
 * Fetches real planner events and provides un-mocked Smart Time-Block Suggestions.
 */
export default function CalendarWidget() {
  const [events, setEvents] = useState([]);
  const [title, setTitle] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [category, setCategory] = useState('work');
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchEvents = async () => {
    setError('');
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_calendar',
          arguments: { action: 'list' }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Calendar unavailable.');
      setEvents(data.data.events || []);
    } catch (err) {
      setEvents([]);
      setError(err.message || 'Calendar unavailable.');
    }
  };

  const handleAddEvent = async (e) => {
    e.preventDefault();
    if (!title.trim() || !startTime || !endTime) return;

    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_calendar',
          arguments: {
            action: 'create',
            title: title.trim(),
            start_time: startTime,
            end_time: endTime,
            category: category
          }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Calendar event creation failed.');
      setTitle('');
      setStartTime('');
      setEndTime('');
      setError('');
      fetchEvents();
    } catch (err) {
      setError(err.message || 'Calendar event creation failed.');
    }
  };

  const getSmartFreeTime = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_calendar',
          arguments: {
            action: 'smart_schedule',
            duration_hours: 2.0
          }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Smart schedule unavailable.');
      setSuggestions(data.data.suggestions || []);
      setError('');
    } catch (err) {
      setSuggestions([]);
      setError(err.message || 'Smart schedule unavailable.');
    } finally {
      setLoading(false);
    }
  };

  const deleteEvent = async (id) => {
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_calendar',
          arguments: { action: 'delete', event_id: id }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Calendar event deletion failed.');
      setError('');
      fetchEvents();
    } catch (err) {
      setError(err.message || 'Calendar event deletion failed.');
    }
  };

  const bookSuggestedSlot = async (slot) => {
    if (!title.trim()) {
      setError('Enter an event title before booking a suggested slot.');
      return;
    }
    try {
      const response = await fetch(`${apiBase}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: 'manage_calendar',
          arguments: {
            action: 'create',
            title: title.trim(),
            start_time: slot.start_time,
            end_time: slot.end_time,
            category: 'development'
          }
        })
      });
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'Suggested slot booking failed.');
      setSuggestions([]);
      setTitle('');
      setError('');
      fetchEvents();
    } catch (err) {
      setError(err.message || 'Suggested slot booking failed.');
    }
  };

  const formatTime = (isoString) => {
    try {
      const dt = new Date(isoString);
      return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + " - " + dt.toLocaleDateString([], { month: 'short', day: '2-digit' });
    } catch (e) {
      return isoString;
    }
  };

  useEffect(() => {
    fetchEvents();
  }, []);

  return (
    <div className="space-y-3 font-mono text-[10px] text-white/90 p-1 overflow-y-auto max-h-[220px] custom-scrollbar">
      
      {/* Date Header Indicator */}
      <div className="flex justify-between items-center bg-white/[0.01] border border-white/5 p-2 rounded-sm text-[#8B8B96] uppercase text-[8px] tracking-wider font-bold">
        <span>Planner Schedule</span>
        <button 
          onClick={getSmartFreeTime}
          disabled={loading}
          className="bg-[#7DD3FC]/10 border border-[#7DD3FC]/20 text-[#7DD3FC] px-1.5 py-0.5 rounded-sm uppercase text-[7px]"
        >
          {loading ? 'Solving...' : 'Smart Schedule Solver'}
        </button>
      </div>

      {/* Suggested Slots Presentation */}
      {suggestions.length > 0 && (
        <div className="bg-[#7DD3FC]/5 border border-[#7DD3FC]/10 p-2 rounded-sm space-y-1">
          <span className="text-white/40 block text-[7px] uppercase font-bold">Suggested 2-Hour Open Slots</span>
          {suggestions.map((slot, index) => (
            <div key={index} className="flex justify-between items-center bg-white/5 p-1 rounded-sm text-[7px] uppercase">
              <span>{slot.day_string} @ {new Date(slot.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              <button 
                onClick={() => bookSuggestedSlot(slot)}
                className="bg-[#7DD3FC]/25 border border-[#7DD3FC]/40 text-[#7DD3FC] px-1 rounded-sm text-[6px] uppercase"
              >
                Book
              </button>
            </div>
          ))}
        </div>
      )}

      {error && <p className="text-[8px] text-rose-300">Unavailable: {error}</p>}

      {/* Chronological events loop */}
      <div className="space-y-2 flex-1 max-h-[100px] overflow-y-auto custom-scrollbar">
        {!error && events.length === 0 ? (
          <div className="text-center py-4 text-white/25 text-[8px] border border-dashed border-white/5 uppercase">
            No events scheduled
          </div>
        ) : (
          events.map((item, idx) => (
            <div 
              key={item.id}
              className="flex justify-between items-center bg-white/[0.01] hover:bg-white/[0.02] border border-white/5 p-1.5 rounded-sm"
            >
              <div className="flex items-start gap-2 min-w-0">
                <div className={`w-1.5 h-1.5 rounded-full mt-1.5 ${
                  item.category === "meeting" ? "bg-[#7DD3FC]" :
                  item.category === "personal" ? "bg-amber-400" :
                  "bg-emerald-400"
                }`} />
                <div className="min-w-0">
                  <span className="text-[7px] text-[#8B8B96] tracking-widest uppercase font-bold">{formatTime(item.start_time)}</span>
                  <p className="text-[9px] text-[#F5F5F7] mt-0.5 truncate">{item.title}</p>
                </div>
              </div>
              <button 
                onClick={() => deleteEvent(item.id)}
                className="text-rose-400 hover:text-rose-500 bg-rose-500/5 px-1 py-0.5 border border-rose-500/10 rounded-sm text-[6px]"
                aria-label="Delete calendar event"
                title="Delete calendar event"
              >
                <X size={11} strokeWidth={1.8} aria-hidden="true" />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Add Event Form */}
      <form onSubmit={handleAddEvent} className="space-y-1.5 bg-white/[0.01] border border-white/5 p-2 rounded-sm text-[8px] uppercase">
        <input 
          type="text" 
          placeholder="Event Title..."
          value={title}
          onChange={e => setTitle(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded-sm px-2 py-1 focus:outline-none focus:border-[#7DD3FC]/50 text-white placeholder-white/20 text-[8px]"
        />
        <div className="grid grid-cols-2 gap-1">
          <div>
            <label className="text-white/40 block mb-0.5">Start Time</label>
            <input 
              type="datetime-local" 
              value={startTime}
              onChange={e => setStartTime(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-1 py-0.5 text-white text-[8px]"
            />
          </div>
          <div>
            <label className="text-white/40 block mb-0.5">End Time</label>
            <input 
              type="datetime-local" 
              value={endTime}
              onChange={e => setEndTime(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-sm px-1 py-0.5 text-white text-[8px]"
            />
          </div>
        </div>
        <button
          type="submit"
          className="w-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/20 py-0.5 rounded-sm tracking-wider font-bold"
        >
          Add Event
        </button>
      </form>

    </div>
  );
}
