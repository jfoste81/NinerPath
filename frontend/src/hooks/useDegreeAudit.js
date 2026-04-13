import { useState, useEffect } from 'react';
import { API_BASE } from '../constants';

/**
 * Loads `/api/degree-audit` for the current email, degree, concentration, and optional user_id.
 */
export function useDegreeAudit({ email, userId, selectedDegree, selectedConcentration }) {
  const [audit, setAudit] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!email) return undefined;
    const ac = new AbortController();
    const q = new URLSearchParams({
      email,
      degree: selectedDegree,
      concentration: selectedConcentration,
      user_id: userId,
    });
    setLoading(true);
    setError('');
    fetch(`${API_BASE}/api/degree-audit?${q.toString()}`, { signal: ac.signal })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || res.statusText || 'Audit failed');
        return data.audit;
      })
      .then(setAudit)
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setAudit(null);
        setError(err.message || 'Could not load degree audit.');
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [email, userId, selectedDegree, selectedConcentration]);

  return { audit, loading, error };
}
