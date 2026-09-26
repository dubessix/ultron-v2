// "Stop" while Ultron is working (V2 Step D).
//
// Used ONLY while a job is running, like a Stop button: the whole message must
// be a stop word ("stop", "ruko", "bas", "cancel"...), optionally with his name.
// "stop the music" or anything longer is a normal order for the brain, and when
// nothing is running every message goes to the brain as usual.

const NAMES = /^(?:(?:hey|ok|okay|oye|arre)\s+)?(?:ultron|zora)\b[\s,!.]*/;
const STOP_PHRASES = new Set([
  'stop', 'stop it', 'stop now', 'stop stop', 'please stop', 'stop please', 'just stop', 'wait stop',
  'cancel', 'cancel it', 'abort', 'halt', 'enough', 'leave it',
  'ruko', 'ruk', 'ruk jao', 'ruko ruko', 'ruk ja', 'bas', 'bas karo', 'bas kar', 'band karo', 'rehne do',
  'thamo', 'thamiye',
  'रुको', 'रुक जाओ', 'बस', 'बस करो', 'बंद करो', 'থামো', 'থামুন',
]);

export function normalizeStop(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[.,!?;:'"`~\-–—।]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(NAMES, '')
    .replace(/\s+(?:sir|now|please|na|yaar)$/, '')
    .trim();
}

export function isStopCommand(text) {
  const said = normalizeStop(text);
  return Boolean(said) && STOP_PHRASES.has(said);
}

// Ask the backend to stop the running job. Never throws.
export async function requestStop(apiBase = '') {
  try {
    const response = await fetch(`${apiBase}/api/stop`, { method: 'POST' });
    return response.ok;
  } catch (_error) {
    return false;
  }
}
