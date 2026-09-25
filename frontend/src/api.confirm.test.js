// @vitest-environment jsdom

import { describe, it, expect, vi, afterEach } from 'vitest';
import { executeToolWithConfirmation } from './api';

const json = (body) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

describe('widget confirm uses the Ultron bar, not the browser pop-up', () => {
  afterEach(() => { window.__ultronConfirmBar = false; vi.restoreAllMocks(); });

  it('asks through the app bar and returns the real result', async () => {
    window.__ultronConfirmBar = true;
    window.confirm = window.confirm || (() => false);
    const popup = vi.spyOn(window, 'confirm');
    vi.stubGlobal('fetch', vi.fn(() => json({
      status: 'PENDING_CONFIRMATION', confirmation_token: 'tok-1234567890abcdef',
      message: 'Should I run this command: rm x, Sir? Say yes or no.',
    })));
    window.addEventListener('ultron:confirm', (event) => {
      expect(event.detail.pending.message).toContain('Should I run');
      expect(event.detail.sessionId).toBe('terminal_widget');
      event.detail.resolve({ success: true, data: { stdout: 'done' } });
    }, { once: true });
    const result = await executeToolWithConfirmation('terminal_run', { command: 'rm x' }, 'terminal_widget');
    expect(result.data.stdout).toBe('done');
    expect(popup).not.toHaveBeenCalled();
  });
});
