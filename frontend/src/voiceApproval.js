// Approve or cancel by voice / chat instead of clicking (same rules as backend/app/core/approval.py).
// Only a SHORT reply counts, and only while something is waiting for approval.
// "ok do", "yes create it", "haan kar do", "hya koro" = yes.
// "ok close YouTube" or "no, open the other folder" = a new request for Ultron.
const FILLER = /\b(ultron|zora|sir|please|pls|plz|bhai|boss|jarvis|dear|then|now|ji)\b/g;

const YES_START = new Set([
  'yes', 'yeah', 'yep', 'yup', 'ya', 'yea', 'ok', 'okay', 'okey', 'k', 'sure', 'fine', 'alright',
  'go', 'do', 'proceed', 'confirm', 'confirmed', 'approve', 'approved', 'right', 'correct', 'absolutely',
  'haan', 'han', 'ha', 'haa', 'theek', 'thik', 'thick', 'karo', 'kar', 'kardo', 'chalo',
  'hya', 'hyan', 'hae', 'ho', 'koro', 'kor', 'done', 'definitely', 'course', 'please',
]);
const GENERIC = new Set([
  'it', 'that', 'this', 'them', 'those', 'do', 'does', 'go', 'ahead', 'now', 'same', 'one', 'then', 'again',
  'create', 'make', 'open', 'run', 'write', 'save', 'start', 'play', 'send', 'move', 'copy', 'rename',
  'close', 'delete', 'remove', 'install', 'download', 'apply', 'continue', 'finish', 'all', 'both',
  'karo', 'kar', 'kardo', 'de', 'dijiye', 'dijye', 'diya', 'dao', 'diye', 'koro', 'kore', 'kor',
  'banao', 'bana', 'kholo', 'khol', 'chalao', 'chala', 'hai', 'hain', 'ji', 'bhai', 'haan', 'yes', 'ok',
  'okay', 'sure', 'yeah', 'please', 'right', 'away', 'fine', 'i', 'want', 'you', 'can', 'yup',
]);
const NO_WORDS = new Set([
  'no', 'nope', 'nah', 'cancel', 'stop', 'dont', "don't", 'not', 'never', 'nahi', 'nahin', 'mat',
  'rehne', 'rehnedo', 'leave', 'skip', 'wait', 'hold', 'abort', 'na', 'naa', 'thak', 'later',
]);
const ALWAYS = ['always', 'hamesha', 'every time', 'sob somoy', 'always allow', 'allow always'];
const YES_PHRASES = new Set(['go ahead', 'do it', 'of course', 'kar do', 'kore dao', 'why not']);
const NO_PHRASES = new Set(['mat karo', 'rehne do', 'not now', 'no thanks']);

const words = (text) => String(text || '')
  .toLowerCase()
  .replace(/’/g, "'")
  .replace(/[.,!?।;:"()]+/g, ' ')
  .replace(FILLER, ' ')
  .split(/\s+/)
  .filter(Boolean);

export function approvalIntent(text) {
  const w = words(text);
  if (!w.length || w.length > 6) return null;
  const phrase = w.join(' ');
  const negated = w.some(x => ['no', 'not', 'never', 'dont', "don't"].includes(x));
  if (ALWAYS.some(a => phrase.includes(a)) && !negated) return 'always';
  if (NO_WORDS.has(w[0]) || NO_PHRASES.has(phrase)) return w.length <= 3 ? 'no' : null;
  if (w.some(x => NO_WORDS.has(x) && x !== 'na' && x !== 'wait')) return null;
  if (YES_START.has(w[0]) || YES_PHRASES.has(phrase)) {
    return w.slice(1).every(x => YES_START.has(x) || GENERIC.has(x)) ? 'yes' : null;
  }
  return null;
}

// What should happen with this reply? null = send to Ultron as a normal message.
export function routeApproval(text, { pendingAction, trustOffer } = {}) {
  const intent = approvalIntent(text);
  if (!intent) return null;
  if (pendingAction?.confirmation_token) {
    return intent === 'no' ? 'cancel' : 'confirm';
  }
  if (trustOffer) {
    return intent === 'no' ? 'decline_trust' : 'accept_trust';
  }
  return null;
}
