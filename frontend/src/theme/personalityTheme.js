const THEMES = Object.freeze({
  ultron: Object.freeze({
    id: 'ultron',
    name: 'ULTRON',
    primary: '#10B981',
    secondary: '#38BDF8',
    text: '#BAE6FD',
    surface: 'rgba(14, 165, 233, 0.055)',
    border: 'rgba(56, 189, 248, 0.14)',
    glow: 'rgba(16, 185, 129, 0.22)',
    coreParticle: 'rgba(52, 211, 153, 0.88)',
    coreGlow: 'rgba(56, 189, 248, 0.18)',
    coreOrbit: 'rgba(110, 231, 183, 0.25)',
    coreLine: 'rgba(56, 189, 248, 0.12)',
  }),
  zora: Object.freeze({
    id: 'zora',
    name: 'ZORA',
    primary: '#EC4899',
    secondary: '#F472B6',
    text: '#FBCFE8',
    surface: 'rgba(236, 72, 153, 0.065)',
    border: 'rgba(244, 114, 182, 0.16)',
    glow: 'rgba(236, 72, 153, 0.24)',
    coreParticle: 'rgba(236, 72, 153, 0.9)',
    coreGlow: 'rgba(244, 114, 182, 0.2)',
    coreOrbit: 'rgba(251, 113, 133, 0.3)',
    coreLine: 'rgba(244, 114, 182, 0.14)',
  }),
});

export function getPersonalityTheme(personality) {
  return personality === 'zora' ? THEMES.zora : THEMES.ultron;
}

export const PERSONALITY_THEMES = THEMES;
