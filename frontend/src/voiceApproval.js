// V2 Step 7 (Tony mode) - approve or cancel by voice / chat instead of clicking.
// Only a SHORT reply that is purely yes/no counts, and only while something is
// waiting for approval. "No, open the other folder" goes to the brain as usual.
const clean = (text) => String(text || '')
  .toLowerCase()
  .replace(/[.,!?।]/g, ' ')
  .replace(/\b(ultron|zora|sir|please|pls|bhai|boss)\b/g, ' ')
  .replace(/\s+/g, ' ')
  .trim();

const ALWAYS = [
  'always', 'yes always', 'always allow', 'always allow it', 'allow always', 'yes always allow',
  'haan hamesha', 'hamesha', 'hamesha karo', 'hamesha allow', 'sob somoy', 'always do it',
];
const YES = [
  'yes', 'yes do it', 'yeah', 'yep', 'yup', 'ok', 'okay', 'ok do it', 'okay do it', 'go ahead', 'do it',
  'confirm', 'confirmed', 'sure', 'proceed', 'approved', 'approve', 'yes go ahead', 'yes please', 'go',
  'haan', 'haan karo', 'haan kar do', 'ha', 'han', 'haa', 'kar do', 'karo', 'theek hai', 'thik hai',
  'ji', 'ji haan', 'hya', 'hyan', 'kor', 'koro', 'kore dao', 'haan ji', 'chalo', 'done',
];
const NO = [
  'no', 'nope', 'nah', 'cancel', 'cancel it', 'stop', "don't", 'dont', 'do not', 'no thanks', 'never mind',
  'nevermind', 'nahi', 'nahin', 'mat karo', 'rehne do', 'rehne de', 'na', 'naa', 'thak', 'koro na',
  'no dont', "no don't", 'leave it', 'skip', 'not now',
];

export function approvalIntent(text) {
  const phrase = clean(text);
  if (!phrase || phrase.split(' ').length > 5) return null;
  if (ALWAYS.includes(phrase)) return 'always';
  if (YES.includes(phrase)) return 'yes';
  if (NO.includes(phrase)) return 'no';
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
