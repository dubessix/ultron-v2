export const FIBONACCI_ANGLE = Math.PI * (3 - Math.sqrt(5));

export function particleCountForViewport(width, height) {
  if (width >= 1700 && height >= 900) return 1300;
  if (width < 1100 || height < 650) return 700;
  return 1050;
}

/** Deterministic near-uniform distribution on a unit sphere. */
export function createFibonacciSphere(count) {
  const safeCount = Math.max(1, Math.floor(count));
  return Array.from({ length: safeCount }, (_, index) => {
    const y = 1 - (2 * (index + 0.5)) / safeCount;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = FIBONACCI_ANGLE * index;
    return {
      x: Math.cos(angle) * radial,
      y,
      z: Math.sin(angle) * radial,
      phase: (index * 0.618033988749895) % 1,
    };
  });
}

/** Rotate around Y, then X, then Z. */
export function rotateSpherePoint(point, yaw, pitch, roll) {
  const cosY = Math.cos(yaw);
  const sinY = Math.sin(yaw);
  let x = point.x * cosY - point.z * sinY;
  let z = point.x * sinY + point.z * cosY;
  let y = point.y;

  const cosX = Math.cos(pitch);
  const sinX = Math.sin(pitch);
  const rotatedY = y * cosX - z * sinX;
  const rotatedZ = y * sinX + z * cosX;
  y = rotatedY;
  z = rotatedZ;

  const cosZ = Math.cos(roll);
  const sinZ = Math.sin(roll);
  return {
    x: x * cosZ - y * sinZ,
    y: x * sinZ + y * cosZ,
    z,
    phase: point.phase,
  };
}

export function projectSpherePoint(point, centerX, centerY, radius, radialScale = 1) {
  const depth = (point.z + 1) / 2;
  const perspective = 1 + point.z * 0.09;
  return {
    x: centerX + point.x * radius * perspective * radialScale,
    y: centerY + point.y * radius * perspective * radialScale,
    z: point.z,
    depth,
    phase: point.phase,
  };
}

export function mixRgb(farRgb, nearRgb, amount) {
  const t = Math.max(0, Math.min(1, amount));
  return farRgb.map((value, index) => Math.round(value + (nearRgb[index] - value) * t));
}
