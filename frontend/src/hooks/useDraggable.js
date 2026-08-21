import { useEffect, useRef, useState } from 'react';

const clamp = (value, minimum, maximum) => Math.min(Math.max(value, minimum), Math.max(minimum, maximum));

/** Mouse, pen, and touch drag engine with viewport-safe widget bounds. */
export default function useDraggable(
  initialX = 100,
  initialY = 100,
  itemWidth = 320,
  itemHeight = 280,
) {
  const initialPosition = () => ({
    x: clamp(initialX, 0, (typeof window === 'undefined' ? initialX : window.innerWidth - itemWidth - 80)),
    y: clamp(initialY, 0, (typeof window === 'undefined' ? initialY : window.innerHeight - itemHeight - 16)),
  });
  const [position, setPosition] = useState(initialPosition);
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef({
    pointerId: null,
    offsetX: 0,
    offsetY: 0,
    maxX: 0,
    maxY: 0,
    target: null,
  });

  const handlePointerDown = (event) => {
    if ((event.pointerType === 'mouse' && event.button !== 0) || event.target.closest?.('.no-drag')) {
      return;
    }

    event.preventDefault();
    const widget = event.currentTarget.parentElement;
    const workspace = widget?.offsetParent;
    const maxX = Math.max(0, (workspace?.clientWidth || window.innerWidth - 64) - (widget?.offsetWidth || itemWidth) - 8);
    const maxY = Math.max(0, (workspace?.clientHeight || window.innerHeight) - (widget?.offsetHeight || itemHeight) - 8);
    dragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - position.x,
      offsetY: event.clientY - position.y,
      maxX,
      maxY,
      target: event.currentTarget,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setIsDragging(true);
  };

  useEffect(() => {
    const constrainToViewport = () => {
      setPosition((current) => ({
        x: clamp(current.x, 0, window.innerWidth - itemWidth - 80),
        y: clamp(current.y, 0, window.innerHeight - itemHeight - 16),
      }));
    };
    window.addEventListener('resize', constrainToViewport);
    return () => window.removeEventListener('resize', constrainToViewport);
  }, [itemHeight, itemWidth]);

  useEffect(() => {
    if (!isDragging) return undefined;

    const handlePointerMove = (event) => {
      if (event.pointerId !== dragRef.current.pointerId) return;
      event.preventDefault();
      setPosition({
        x: clamp(event.clientX - dragRef.current.offsetX, 0, dragRef.current.maxX),
        y: clamp(event.clientY - dragRef.current.offsetY, 0, dragRef.current.maxY),
      });
    };

    const finishPointerDrag = (event) => {
      if (event.pointerId !== dragRef.current.pointerId) return;
      dragRef.current.target?.releasePointerCapture?.(event.pointerId);
      dragRef.current = {
        pointerId: null,
        offsetX: 0,
        offsetY: 0,
        maxX: 0,
        maxY: 0,
        target: null,
      };
      setIsDragging(false);
    };

    window.addEventListener('pointermove', handlePointerMove, { passive: false });
    window.addEventListener('pointerup', finishPointerDrag);
    window.addEventListener('pointercancel', finishPointerDrag);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', finishPointerDrag);
      window.removeEventListener('pointercancel', finishPointerDrag);
    };
  }, [isDragging]);

  return { position, handlePointerDown, isDragging };
}
