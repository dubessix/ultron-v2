// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const shellCapture = vi.hoisted(() => ({ props: null }));
const apiMocks = vi.hoisted(() => ({
  api: vi.fn(async (path) => {
    if (path === '/api/providers/status') {
      return { providers: {}, live_checked: false };
    }
    return { success: true };
  }),
  executeTool: vi.fn(async () => ({ success: false, error: 'not used in voice tests' })),
}));

vi.mock('./components/AppShell', () => ({
  default: (props) => {
    shellCapture.props = props;
    return <div data-testid="mock-app-shell" />;
  },
}));
vi.mock('./components/NotificationToast', () => ({ default: () => null }));
vi.mock('./api', () => ({
  api: apiMocks.api,
  executeTool: apiMocks.executeTool,
}));

import App from './App';

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
    blob: async () => new Blob(),
  };
}

function voiceResponse(content, overrides = {}) {
  return {
    id: `voice-${content}`,
    session_id: 'voice-session-c6',
    project_id: 'personal',
    content: `[Offline] ${content}`,
    personality: 'ultron',
    response_ms: 14,
    structured_action: { action: 'open_widget', widget_id: 'memory' },
    coding: true,
    intent: 'MEMORY',
    events: [{ type: 'log', log: { level: 'info', message: 'Voice event preserved' } }],
    pending_confirmation: {
      confirmation_token: 'c6-exact-token-1234567890',
      tool_id: 'manage_memory',
      message: 'Exact confirmation required.',
    },
    provider_route: { provider: null, model: null, offline: true },
    memory_provenance: [{ source_type: 'memory', source_id: 'memory-c6' }],
    ...overrides,
  };
}

function setBriefingAlreadySeen() {
  const now = new Date();
  const dateKey = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
  ].join('-');
  localStorage.setItem('ultron_daily_briefing_date', dateKey);
}

async function renderConnectedApp(fetchImplementation) {
  setBriefingAlreadySeen();
  global.fetch = vi.fn(fetchImplementation);
  render(<App />);
  await waitFor(() => expect(shellCapture.props?.backendStatus).toBe('CONNECTED'));
}

beforeEach(() => {
  shellCapture.props = null;
  apiMocks.api.mockClear();
  apiMocks.executeTool.mockClear();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete global.fetch;
});

describe('Voice C6 — canonical transport and response preservation', () => {
  it('reuses the resolved session/project and keeps canonical response metadata', async () => {
    let voiceTurn = 0;
    await renderConnectedApp(async (url, options = {}) => {
      if (String(url).endsWith('/api/health')) {
        return jsonResponse({ status: 'healthy', system_metrics: {} });
      }
      if (String(url).endsWith('/api/chat')) {
        voiceTurn += 1;
        return jsonResponse(voiceResponse(`turn ${voiceTurn}`));
      }
      throw new Error(`Unexpected fetch: ${url} ${options.method || 'GET'}`);
    });

    await act(async () => {
      await shellCapture.props.handleVoiceCommand('remember the first voice turn');
    });
    await act(async () => {
      await shellCapture.props.handleVoiceCommand('show the next remembered turn');
    });

    const chatCalls = global.fetch.mock.calls.filter(([url]) => String(url).endsWith('/api/chat'));
    expect(chatCalls).toHaveLength(2);
    const firstBody = JSON.parse(chatCalls[0][1].body);
    const secondBody = JSON.parse(chatCalls[1][1].body);
    expect(firstBody).toEqual({
      session_id: null,
      project_id: 'personal',
      content: 'remember the first voice turn',
    });
    expect(secondBody).toEqual({
      session_id: 'voice-session-c6',
      project_id: 'personal',
      content: 'show the next remembered turn',
    });

    const latestAi = shellCapture.props.messages.filter((message) => message.sender === 'ai').at(-1);
    expect(latestAi).toMatchObject({
      project_id: 'personal',
      intent: 'MEMORY',
      provider_route: { offline: true },
      memory_provenance: [{ source_type: 'memory', source_id: 'memory-c6' }],
    });
    expect(shellCapture.props.logs).toContainEqual({ level: 'info', message: 'Voice event preserved' });
    expect(shellCapture.props.pendingAction).toMatchObject({
      confirmation_token: 'c6-exact-token-1234567890',
      tool_id: 'manage_memory',
    });
    expect(shellCapture.props.widgetState.memory.visible).toBe(true);
  });

  it('uses a synchronous in-flight guard so same-tick voice turns cannot overlap', async () => {
    await renderConnectedApp(async (url) => {
      if (String(url).endsWith('/api/health')) {
        return jsonResponse({ status: 'healthy', system_metrics: {} });
      }
      if (String(url).endsWith('/api/chat')) {
        return jsonResponse(voiceResponse('guarded response', {
          structured_action: { action: 'none' },
          pending_confirmation: null,
          coding: false,
          events: [],
        }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    await act(async () => {
      const first = shellCapture.props.handleVoiceCommand('first same-tick turn');
      const second = shellCapture.props.handleVoiceCommand('second same-tick turn');
      await Promise.all([first, second]);
    });

    const chatCalls = global.fetch.mock.calls.filter(([url]) => String(url).endsWith('/api/chat'));
    expect(chatCalls).toHaveLength(1);
    expect(JSON.parse(chatCalls[0][1].body).content).toBe('first same-tick turn');
  });
});
