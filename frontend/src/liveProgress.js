// V2 Step C7: Ultron talks while he works.
// The backend sends { type: "ultron_progress", text, speak, tool, session_id } on /ws/events.
// Shown at once in the activity line; spoken only when `speak` is true (slow step or the
// brain's own words) and only while this screen is waiting for an answer, so nothing is
// ever said after the answer arrives.

export function progressAction(event, { processing, sessionId } = {}) {
  if (!event || event.type !== 'ultron_progress' || !processing) return null;
  if (sessionId && event.session_id && event.session_id !== sessionId) return null;
  const text = String(event.text || '').replace(/[_#*`~<>{}[\]|\\/]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 160);
  if (!text) return null;
  return { text, speak: Boolean(event.speak) };
}
