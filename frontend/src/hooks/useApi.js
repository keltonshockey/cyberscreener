/**
 * QUAEST.TECH — useApi Hook
 * Generic data-fetching hook with loading/error states.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * @param {Function} fetchFn - Async function that returns data (from endpoints.js)
 * @param {Array} deps - Dependency array for re-fetching
 * @param {Object} options - { enabled: true, initialData: null }
 * @returns {{ data, loading, error, refetch }}
 */
export function useApi(fetchFn, deps = [], options = {}) {
  const { enabled = true, initialData = null } = options;
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchFn();
      if (mountedRef.current) {
        setData(result);
        setLoading(false);
      }
      return result;
    } catch (err) {
      if (mountedRef.current) {
        setError(err);
        setLoading(false);
      }
      return null;
    }
  }, [fetchFn]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) refetch();
    return () => { mountedRef.current = false; };
  }, [...deps, enabled]);

  return { data, loading, error, refetch, setData };
}
