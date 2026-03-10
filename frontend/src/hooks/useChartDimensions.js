import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Hook that uses ResizeObserver to track the pixel dimensions of a container.
 * Returns a ref to attach to the container and the current { width, height }.
 */
export function useChartDimensions(defaultHeight = 300) {
  const ref = useRef(null);
  const [dims, setDims] = useState({ width: 0, height: defaultHeight });
  const timerRef = useRef(null);

  const handleResize = useCallback((entries) => {
    // Debounce resize events (100ms)
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        if (width > 0) {
          setDims(prev => {
            if (prev.width === Math.round(width)) return prev;
            return { width: Math.round(width), height: defaultHeight };
          });
        }
      }
    }, 100);
  }, [defaultHeight]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Initial measurement
    const rect = el.getBoundingClientRect();
    if (rect.width > 0) {
      setDims({ width: Math.round(rect.width), height: defaultHeight });
    }

    const observer = new ResizeObserver(handleResize);
    observer.observe(el);

    return () => {
      observer.disconnect();
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [handleResize, defaultHeight]);

  return { ref, width: dims.width, height: dims.height };
}
