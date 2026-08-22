import React, { useEffect, useRef, useState } from 'react';
import { getPersonalityTheme } from '../theme/personalityTheme';
import {
  createFibonacciSphere,
  mixRgb,
  particleCountForViewport,
  projectSpherePoint,
  rotateSpherePoint,
} from '../utils/sphereGeometry';

function viewportClass() {
  if (typeof window === 'undefined') return 'normal';
  if (window.innerWidth >= 1700 && window.innerHeight >= 900) return 'fullhd';
  if (window.innerWidth < 1100 || window.innerHeight < 650) return 'compact';
  return 'normal';
}

function stateProfile(aiState, amplitude) {
  const state = String(aiState || 'idle').toLowerCase();
  const voiceAmplitude = Math.max(0, Math.min(1, Number(amplitude) || 0));
  const profile = {
    state,
    speed: 0.00022,
    alpha: 1,
    scale: 1,
    pulse: 0,
    distortion: 0,
    halo: false,
    connections: false,
  };
  if (state === 'listening' || state === 'wake_word_detected') {
    return { ...profile, speed: 0.00034, pulse: 0.045, halo: true };
  }
  if (state === 'thinking') {
    return { ...profile, speed: 0.00078, scale: 1.025, distortion: 0.014 };
  }
  if (state === 'planning') {
    return { ...profile, speed: 0.00042, scale: 1.015 };
  }
  if (state === 'working') {
    return { ...profile, speed: 0.00055, connections: true };
  }
  if (state === 'speaking') {
    return {
      ...profile,
      speed: 0.00035,
      pulse: 0.02 + voiceAmplitude * 0.06,
      distortion: 0.004 + voiceAmplitude * 0.012,
    };
  }
  if (state === 'interrupted') {
    return { ...profile, speed: 0.001, alpha: 0.35, distortion: 0.075 };
  }
  if (state === 'background' || state === 'sleep') {
    return { ...profile, speed: 0.00007, alpha: 0.24, scale: 0.98 };
  }
  return profile;
}

/** Deterministic dense 3D point sphere rendered with Canvas 2D. */
export default function BlobCanvas({
  aiState = 'idle',
  personality = 'ultron',
  amplitude = 0,
}) {
  const canvasRef = useRef(null);
  const animationRef = useRef(null);
  const [presentation, setPresentation] = useState(viewportClass);
  const isFullHdViewport = presentation === 'fullhd';
  const theme = getPersonalityTheme(personality);

  useEffect(() => {
    const updatePresentationSize = () => setPresentation(viewportClass());
    window.addEventListener('resize', updatePresentationSize);
    return () => window.removeEventListener('resize', updatePresentationSize);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;

    const canvasSize = isFullHdViewport ? 640 : 520;
    const presentationScale = isFullHdViewport ? 1.2 : 1;
    const deviceScale = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = canvasSize * deviceScale;
    canvas.height = canvasSize * deviceScale;
    ctx.setTransform(deviceScale, 0, 0, deviceScale, 0, 0);

    const width = canvasSize;
    const height = canvasSize;
    const centerX = width / 2;
    const centerY = height / 2;
    const baseRadius = canvasSize * 0.385;
    const particleCount = particleCountForViewport(window.innerWidth, window.innerHeight);
    const particles = createFibonacciSphere(particleCount);
    const profile = stateProfile(aiState, amplitude);
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const motionFactor = reduceMotion ? 0.25 : 1;
    const pointScale = presentation === 'compact' ? 0.9 : presentationScale;
    const startedAt = performance.now();

    const renderLoop = (now) => {
      const elapsed = now - startedAt;
      const activeTheme = getPersonalityTheme(personality);
      const pulse = 1 + Math.sin(elapsed * 0.006) * profile.pulse * motionFactor;
      const yaw = elapsed * profile.speed * motionFactor;
      const pitch = -0.18 + Math.sin(elapsed * 0.00009 * motionFactor) * 0.08;
      const roll = Math.sin(elapsed * 0.00006 * motionFactor) * 0.07;

      ctx.clearRect(0, 0, width, height);
      const glowRadius = baseRadius * 0.92 * profile.scale * pulse;
      const glow = ctx.createRadialGradient(centerX, centerY, 8, centerX, centerY, glowRadius);
      glow.addColorStop(0, activeTheme.coreGlow);
      glow.addColorStop(0.58, activeTheme.coreInnerGlow);
      glow.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = glow;
      ctx.globalAlpha = profile.alpha;
      ctx.beginPath();
      ctx.arc(centerX, centerY, glowRadius, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      const projected = particles.map((point) => {
        const rotated = rotateSpherePoint(point, yaw, pitch, roll);
        const distortion = profile.distortion
          ? Math.sin(elapsed * 0.004 + point.phase * Math.PI * 2) * profile.distortion
          : 0;
        return projectSpherePoint(
          rotated,
          centerX,
          centerY,
          baseRadius,
          profile.scale * pulse + distortion,
        );
      }).sort((left, right) => left.z - right.z);

      for (const point of projected) {
        const depth = point.depth;
        const [red, green, blue] = mixRgb(
          activeTheme.coreFarRgb,
          activeTheme.coreNearRgb,
          depth,
        );
        let alpha = (0.1 + depth * 0.8) * profile.alpha;
        if (profile.state === 'thinking') alpha *= 1.07;
        if (profile.state === 'listening' && depth > 0.62) alpha *= 1.14;
        const pointRadius = (0.45 + depth * 1.5) * pointScale;
        ctx.shadowBlur = depth > 0.84 ? 5 * pointScale : 0;
        ctx.shadowColor = activeTheme.coreParticle;
        ctx.fillStyle = `rgba(${red}, ${green}, ${blue}, ${Math.min(1, alpha)})`;
        ctx.beginPath();
        ctx.arc(point.x, point.y, pointRadius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;

      if (profile.halo) {
        ctx.globalAlpha = 0.55 * profile.alpha;
        ctx.strokeStyle = activeTheme.coreOrbit;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(centerX, centerY, baseRadius * profile.scale * pulse * 1.04, 0, Math.PI * 2);
        ctx.stroke();
      }

      if (profile.connections) {
        const front = projected.filter((point) => point.depth > 0.58);
        ctx.strokeStyle = activeTheme.coreLine;
        ctx.lineWidth = 0.55;
        ctx.globalAlpha = 0.65;
        for (let index = 0; index + 37 < front.length; index += 84) {
          const first = front[index];
          const second = front[index + 37];
          const distance = Math.hypot(first.x - second.x, first.y - second.y);
          if (distance > baseRadius * 0.72) continue;
          ctx.beginPath();
          ctx.moveTo(first.x, first.y);
          ctx.lineTo(second.x, second.y);
          ctx.stroke();
        }
      }

      ctx.globalAlpha = 1;
      animationRef.current = requestAnimationFrame(renderLoop);
    };

    animationRef.current = requestAnimationFrame(renderLoop);
    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
    };
  }, [aiState, personality, amplitude, isFullHdViewport, presentation]);

  const displaySize = isFullHdViewport ? 640 : 520;
  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={`${theme.name} dense particle core`}
      style={{ '--core-size': `${displaySize}px` }}
      className="ultron-core-canvas max-w-full aspect-square"
    />
  );
}
