// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const voiceHarness = vi.hoisted(() => ({
  state: {},
  options: null,
}));

vi.mock('../hooks/useVoice', () => ({
  default: (options) => {
    voiceHarness.options = options;
    return {
      isListening: false,
      wakeDetected: false,
      conversationActive: false,
      heardText: '',
      voiceError: '',
      supported: true,
      start: vi.fn(),
      stop: vi.fn(),
      ...voiceHarness.state,
    };
  },
}));
vi.mock('./LeftPanel', () => ({ default: () => <div /> }));
vi.mock('./RightPanel', () => ({ default: () => <div /> }));
vi.mock('./BlobCanvas', () => ({ default: () => <div /> }));
vi.mock('./WidgetRail', () => ({ default: () => <div /> }));
vi.mock('./widgets/WidgetContainer', () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock('./widgets/WidgetManager', () => ({ WIDGET_REGISTRY: {} }));

import AppShell from './AppShell';

const baseProps = {
  messages: [],
  inputValue: '',
  setInputValue: vi.fn(),
  handleSendMessage: vi.fn(),
  isProcessing: false,
  activePersonality: 'ultron',
  backendStatus: 'CONNECTED',
  providerStatus: { state: 'reported', providers: {} },
  systemMetrics: {},
  aiState: 'idle',
  activityText: 'Ready',
  setAiState: vi.fn(),
  togglePersonality: vi.fn(),
  personalitySaving: false,
  widgetState: {},
  toggleWidget: vi.fn(),
  handleVoiceCommand: vi.fn(),
  voicePaused: false,
  onVoiceStop: vi.fn(),
  voiceClarification: null,
  onVoiceClarificationChoice: vi.fn(),
  onVoicePreferenceSave: vi.fn(),
  voicePreferenceSaving: false,
  codingMode: false,
  toggleCodingMode: vi.fn(),
  codingModeSaving: false,
  codingLog: [],
  onConfirmRun: vi.fn(),
  pendingAction: null,
  confirmingAction: false,
  logs: [],
};

function openVoiceSession(props = {}) {
  render(<AppShell {...baseProps} {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Start voice session' }));
}

beforeEach(() => {
  voiceHarness.state = {};
  voiceHarness.options = null;
  baseProps.onVoiceStop.mockClear();
});

afterEach(cleanup);

describe('Voice Option A — truthful owner-facing states', () => {
  it('shows the wake-every-command instruction while armed', () => {
    voiceHarness.state = { isListening: true, conversationActive: false };
    openVoiceSession();

    expect(screen.getByRole('button', { name: 'Stop voice session' })).toBeTruthy();
    expect(screen.getByTestId('voice-status').textContent).toContain('Say “Ultron” to start a voice command');
  });

  it('shows active single-command capture and the real heard transcript', () => {
    voiceHarness.state = {
      isListening: true,
      conversationActive: true,
      heardText: 'show my important memories',
    };
    openVoiceSession();

    expect(screen.getByTestId('voice-status').textContent).toContain('Wake phrase heard — speak your command');
    expect(screen.getByTestId('voice-heard-text').textContent).toContain('show my important memories');
  });

  it('keeps Stop Voice available while recognition is paused for TTS', () => {
    voiceHarness.state = {
      isListening: false,
      conversationActive: true,
      heardText: 'what is next',
    };
    openVoiceSession({ voicePaused: true, aiState: 'speaking' });

    expect(screen.getByRole('button', { name: 'Stop voice session' })).toBeTruthy();
    expect(screen.getByTestId('voice-status').textContent).toContain('Voice paused — Ultron is speaking');
  });

  it('reports a browser reconnect without pretending to listen', () => {
    voiceHarness.state = { isListening: false, conversationActive: true };
    openVoiceSession();

    expect(screen.getByTestId('voice-status').textContent).toContain('Voice reconnecting');
    expect(screen.queryByText('Listening for wake word...')).toBeNull();
  });

  it('shows only backend-approved clarification choices and returns the exact selection', () => {
    const choose = vi.fn();
    render(
      <AppShell
        {...baseProps}
        voiceClarification={{
          question: 'I heard open code. Did you mean VS Code, Code Optimizer, or Code Graph?',
          options: ['Open VS Code', 'Open Code Optimizer', 'Open Code Graph'],
          reason: 'open_code_ambiguous',
        }}
        onVoiceClarificationChoice={choose}
      />
    );

    expect(screen.getByTestId('voice-clarification').textContent).toContain('I heard open code');
    fireEvent.click(screen.getByRole('button', { name: 'Open Code Optimizer' }));
    expect(choose).toHaveBeenCalledWith('Open Code Optimizer');
  });

  it('offers alias memory only after the owner explicitly presses remember', () => {
    const save = vi.fn();
    const offer = { alias: 'jora', canonical: 'Zora', label: 'Remember Jora means Zora' };
    render(
      <AppShell
        {...baseProps}
        voiceClarification={{
          question: 'Did you mean Zora, sir?',
          options: ['Yes, switch to Zora', 'No, I meant something else'],
          reason: 'personality_alias',
          preference_offer: offer,
        }}
        onVoicePreferenceSave={save}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Remember Jora means Zora' }));
    expect(save).toHaveBeenCalledWith(offer);
  });

  it('stops the complete voice session and current speech from one control', () => {
    voiceHarness.state = { isListening: true, conversationActive: true };
    openVoiceSession();

    fireEvent.click(screen.getByRole('button', { name: 'Stop voice session' }));
    expect(baseProps.onVoiceStop).toHaveBeenCalledWith('voice_session_stopped');
    expect(screen.getByRole('button', { name: 'Start voice session' })).toBeTruthy();
  });
});
