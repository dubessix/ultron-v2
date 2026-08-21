import React, { useRef, useEffect, useState } from 'react';
import { getPersonalityTheme } from '../theme/personalityTheme';

/**
 * BlobCanvas Component (HTML5 Canvas 2D)
 * Renders a high-performance particle sphere and concentric orbital loops.
 * Reacts dynamically to 8 distinct cognitive states:
 * [idle | listening | thinking | planning | working | speaking | interrupted | background]
 * Refined with smooth mathematical transitions, noise offsets, and 60 FPS requestAnimationFrame.
 */
export default function BlobCanvas({ 
  aiState = "idle", 
  personality = "ultron", 
  amplitude = 0.0 
}) {
  const canvasRef = useRef(null);
  const animationRef = useRef(null);
  const [isFullHdViewport, setIsFullHdViewport] = useState(() => (
    typeof window !== 'undefined' && window.innerWidth >= 1700 && window.innerHeight >= 900
  ));

  useEffect(() => {
    const updatePresentationSize = () => {
      setIsFullHdViewport(window.innerWidth >= 1700 && window.innerHeight >= 900);
    };
    window.addEventListener('resize', updatePresentationSize);
    return () => window.removeEventListener('resize', updatePresentationSize);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // High-DPI hardware scaling with a roomier presentation on full-HD laptops.
    const scale = window.devicePixelRatio || 1;
    const canvasSize = isFullHdViewport ? 640 : 520;
    const presentationScale = isFullHdViewport ? 1.2 : 1;
    canvas.width = canvasSize * scale;
    canvas.height = canvasSize * scale;
    ctx.scale(scale, scale);

    const width = canvasSize;
    const height = canvasSize;
    const center = { x: width / 2, y: height / 2 };

    // Initialize 200 standard coordinate nodes forming a sphere
    const particleCount = 200;
    const particles = [];
    for (let i = 0; i < particleCount; i++) {
      const theta = (i / particleCount) * 2 * Math.PI;
      particles.push({
        theta,
        phi: Math.acos((Math.random() * 2) - 1),
        speed: 0.008 + Math.random() * 0.008,
        size: 1.0 + Math.random() * 1.5,
        drift: Math.random() * 2 * Math.PI
      });
    }

    let angle = 0;
    let time = 0;

    const renderLoop = () => {
      ctx.clearRect(0, 0, width, height);
      time += 0.04; // Smoother, slower physics delta step

      const theme = getPersonalityTheme(personality);
      const primaryColor = theme.coreParticle;
      const glowColor = theme.coreGlow;

      // Setup state-machine physics multipliers (Requirement: Unique animation profiles)
      let rotationSpeed = 0.004;
      let noiseAmplitude = 5.0;
      let orbitRingVisible = false;
      let connectivityLinesVisible = false;
      let coreScale = 1.0;
      let alphaMultiplier = 1.0;

      const state_clean = (aiState || "idle").toLowerCase();

      switch (state_clean) {
        case "thinking":
          rotationSpeed = 0.025;
          noiseAmplitude = 16.0;
          coreScale = 1.08;
          break;
        case "listening":
        case "wake_word_detected":
          rotationSpeed = 0.001;
          noiseAmplitude = 4.0 + amplitude * 18.0;
          coreScale = 1.15; // Expands slightly on wake
          orbitRingVisible = true;
          break;
        case "speaking":
          rotationSpeed = 0.006;
          noiseAmplitude = 6.0 + Math.sin(time * 2.5) * 14.0; // Synchronized speech rhythm
          coreScale = 1.05;
          break;
        case "planning":
          rotationSpeed = 0.003;
          orbitRingVisible = true; // Orbit rings appear
          break;
        case "working":
          rotationSpeed = 0.012;
          connectivityLinesVisible = true; // Random network lines appear
          break;
        case "interrupted":
          rotationSpeed = 0.018;
          noiseAmplitude = 22.0; // Brief distortion wave
          alphaMultiplier = 0.35;  // Quick fade
          break;
        case "background":
        case "sleep":
          rotationSpeed = 0.0003;
          noiseAmplitude = 0.8; // Dim, almost motionless
          alphaMultiplier = 0.22;
          break;
        default: // idle
          rotationSpeed = 0.004;
          noiseAmplitude = 5.0;
          coreScale = 1.0;
          break;
      }

      angle += rotationSpeed;

      // Draw concentric elliptical orbital rings (Concentric loops)
      if (orbitRingVisible || state_clean === "planning" || state_clean === "idle" || state_clean === "working") {
        ctx.save();
        ctx.translate(center.x, center.y);
        ctx.rotate(time * 0.015);
        ctx.strokeStyle = theme.coreOrbit;
        ctx.lineWidth = 1;

        // Ellipse Loop 1
        ctx.beginPath();
        ctx.ellipse(0, 0, 210 * presentationScale * coreScale, 72 * presentationScale * coreScale, Math.PI / 4, 0, 2 * Math.PI);
        ctx.stroke();

        // Ellipse Loop 2 (Counter tilted)
        ctx.rotate(-time * 0.025);
        ctx.beginPath();
        ctx.ellipse(0, 0, 215 * presentationScale * coreScale, 77 * presentationScale * coreScale, -Math.PI / 6, 0, 2 * Math.PI);
        ctx.stroke();

        ctx.restore();
      }

      // Draw backing glowing neon core
      ctx.beginPath();
      const glowRadius = 170 * presentationScale * coreScale;
      const radialGlow = ctx.createRadialGradient(center.x, center.y, 12, center.x, center.y, glowRadius);
      radialGlow.addColorStop(0, glowColor);
      radialGlow.addColorStop(1, "rgba(10, 10, 15, 0)");
      ctx.fillStyle = radialGlow;
      ctx.globalAlpha = alphaMultiplier;
      ctx.arc(center.x, center.y, glowRadius, 0, 2 * Math.PI);
      ctx.fill();

      // Draw particle coordinate array
      particles.forEach((p, idx) => {
        const x_rot = Math.sin(p.phi) * Math.cos(p.theta + angle);
        const y_rot = Math.cos(p.phi);
        
        // Compute current coordinates
        const radialOffset = (138 + Math.sin(time + p.drift) * noiseAmplitude) * presentationScale * coreScale;
        
        const x = center.x + x_rot * radialOffset;
        const y = center.y + y_rot * radialOffset;

        ctx.beginPath();
        ctx.fillStyle = primaryColor;
        ctx.arc(x, y, p.size * presentationScale, 0, 2 * Math.PI);
        ctx.fill();

        // Dynamic network lines (Working state)
        if (connectivityLinesVisible && idx < particles.length - 1 && idx % 10 === 0) {
          const nextP = particles[idx + 1];
          const nx_rot = Math.sin(nextP.phi) * Math.cos(nextP.theta + angle);
          const ny_rot = Math.cos(nextP.phi);
          const n_offset = (138 + Math.sin(time + nextP.drift) * noiseAmplitude) * presentationScale * coreScale;
          const nx = center.x + nx_rot * n_offset;
          const ny = center.y + ny_rot * n_offset;

          ctx.beginPath();
          ctx.strokeStyle = theme.coreLine;
          ctx.lineWidth = 0.5;
          ctx.moveTo(x, y);
          ctx.lineTo(nx, ny);
          ctx.stroke();
        }
      });
      
      ctx.globalAlpha = 1.0; // Reset alpha values
      animationRef.current = requestAnimationFrame(renderLoop);
    };

    renderLoop();

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [aiState, personality, amplitude, isFullHdViewport]);

  const displaySize = isFullHdViewport ? 640 : 520;

  return (
    <canvas 
      ref={canvasRef} 
      style={{ '--core-size': `${displaySize}px` }}
      className="ultron-core-canvas max-w-full aspect-square"
    />
  );
}
