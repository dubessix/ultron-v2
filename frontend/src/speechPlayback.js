// Browsers refuse to play sound until the owner has clicked or pressed a key
// on the page once (autoplay rule). That is not a broken voice, so it gets a
// friendly message and the daily briefing waits for the first click instead.
export function isPlaybackBlocked(outcome) {
  if (outcome?.status && outcome.status !== 'error') return false;
  const reason = String(outcome?.error || '');
  return reason === 'playback_blocked' || /NotAllowed|didn.t interact|user gesture|not allowed/i.test(reason);
}

export function playbackProblem(error) {
  if (isPlaybackBlocked({ error: error?.name || error?.message })) {
    return ['Voice paused', 'Click anywhere once so the browser lets Ultron speak.', 'low'];
  }
  return ['Voice unavailable', error?.message || 'TTS playback was blocked.', 'medium'];
}
