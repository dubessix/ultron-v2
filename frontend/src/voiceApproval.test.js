import { describe, it, expect } from 'vitest';
import { approvalIntent, routeApproval } from './voiceApproval';

const pending = { pendingAction: { confirmation_token: 't1', tool_id: 'delete_folder' } };

describe('voice approval (V2 Step 7)', () => {
  it('understands yes / always / no in English, Hindi and Bengali', () => {
    for (const t of ['Yes, do it', 'haan karo', 'Ultron, go ahead', 'theek hai', 'kor', 'OK.']) expect(approvalIntent(t)).toBe('yes');
    for (const t of ['yes always', 'haan hamesha', 'Always allow']) expect(approvalIntent(t)).toBe('always');
    for (const t of ['no', 'nahi', 'rehne do', 'cancel it', 'thak', 'Sir, never mind']) expect(approvalIntent(t)).toBe('no');
  });

  it('longer sentences are normal commands, not approvals', () => {
    expect(approvalIntent('no, open the other folder')).toBe(null);
    expect(approvalIntent('yes and also play some music after that please')).toBe(null);
    expect(approvalIntent('open downloads')).toBe(null);
  });

  it('acts only when something is waiting', () => {
    expect(routeApproval('yes', {})).toBe(null);
    expect(routeApproval('haan karo', pending)).toBe('confirm');
    expect(routeApproval('yes always', pending)).toBe('confirm');
    expect(routeApproval('nahi', pending)).toBe('cancel');
    expect(routeApproval('open downloads', pending)).toBe(null);
  });

  it('answers the "always allow?" offer', () => {
    const offer = { trustOffer: { tool_id: 'organize_folder', kind: 'folder', value: '/home/d/Downloads' } };
    expect(routeApproval('yes', offer)).toBe('accept_trust');
    expect(routeApproval('no', offer)).toBe('decline_trust');
  });
});
