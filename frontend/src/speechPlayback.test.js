import { describe, expect, it } from 'vitest';
import { isPlaybackBlocked, playbackProblem } from './speechPlayback';

describe('autoplay block is not a broken voice', () => {
  it('detects the browser autoplay refusal', () => {
    expect(isPlaybackBlocked({ status: 'error', error: 'playback_blocked' })).toBe(true);
    expect(isPlaybackBlocked({ status: 'error', error: "play() failed because the user didn't interact with the document first." })).toBe(true);
    expect(isPlaybackBlocked({ error: 'NotAllowedError' })).toBe(true);
  });

  it('does not treat real failures or success as blocked', () => {
    expect(isPlaybackBlocked({ status: 'ended' })).toBe(false);
    expect(isPlaybackBlocked({ status: 'error', error: 'HTTP 500' })).toBe(false);
    expect(isPlaybackBlocked(null)).toBe(false);
  });

  it('shows simple words instead of the raw browser error with a link', () => {
    const [title, body, level] = playbackProblem({ name: 'NotAllowedError', message: "play() failed ... https://goo.gl/xX8pDD" });
    expect(title).toBe('Voice paused');
    expect(body).not.toMatch(/goo\.gl|play\(\)/);
    expect(level).toBe('low');
    expect(playbackProblem({ message: 'decode error' })[0]).toBe('Voice unavailable');
  });
});
