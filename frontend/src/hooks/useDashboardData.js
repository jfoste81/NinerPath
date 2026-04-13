import { useState, useEffect } from 'react';
import { API_BASE } from '../constants';

/**
 * Loads `/api/dashboard/:userId` when session identifiers and degree selection are available.
 */
export function useDashboardData({ userId, email, selectedDegree, selectedConcentration }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!userId || !email) return undefined;
    const ac = new AbortController();
    const q = new URLSearchParams({
      email,
      degree: selectedDegree,
      concentration: selectedConcentration,
      max_schedule_variants: '16',
    });
    setLoading(true);
    setError('');
    fetch(`${API_BASE}/api/dashboard/${userId}?${q.toString()}`, { signal: ac.signal })
      .then(async (res) => {
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
          const msg =
            typeof payload?.detail === 'string'
              ? payload.detail
              : Array.isArray(payload?.detail)
                ? payload.detail.map((d) => d.msg || d).join(' ')
                : res.statusText || 'Dashboard request failed';
          throw new Error(msg);
        }
        return payload;
      })
      .then(setData)
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setData(null);
        setError(err.message || 'Could not load dashboard.');
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [userId, email, selectedDegree, selectedConcentration]);

  return { data, loading, error };
}
