/**
 * QUAEST.TECH — usePolling Hook
 * Poll an API endpoint at intervals.
 */

import { useEffect, useRef, useCallback, useState } from 'react';

/**
 * @param {Function} fetchFn - Async function to poll
 * @param {number} intervalMs - Polling interval in ms
 * @param {Object} options - { enabled: true, immediate: true }
 * @returns {{ data, loading, start, stop }}
 */
export function usePolling(fetchFn, intervalMs = 5000, options = {}) {
  const { enabled = true, immediate = true } = options;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef(null);
  const mountedRef = useRef(true);

  const poll = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchFn();
      if (mountedRef.current) {
        setData(result);
      }
    } catch {
      // Ignore polling errors
    }
    if (mountedRef.current) setLoading(false);
  }, [fetchFn]);

  const start = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (immediate) poll();
    timerRef.current = setInterval(poll, intervalMs);
  }, [poll, intervalMs, immediate]);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) start();
    return () => {
      mountedRef.current = false;
      stop();
    };
  }, [enabled, start, stop]);

  return { data, loading, start, stop };
}
