import { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../constants';

/**
 * Loads `/api/schedule/generate` when email, degree/concentration, or refreshKey change.
 * Calls onSuccess after a successful response (e.g. reset combination/variant indices and messages).
 */
export function useScheduleGeneration({ email, degree, concentration, refreshKey, onSuccess }) {
  const [generatedSchedule, setGeneratedSchedule] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  useEffect(() => {
    if (!email) return undefined;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({
      email,
      degree,
      concentration,
      max_credits: '15',
      max_schedule_variants: '16',
    });
    const ac = new AbortController();
    fetch(`${API_BASE}/api/schedule/generate?${params.toString()}`, { signal: ac.signal })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Failed to generate schedule.');
        return data.schedule;
      })
      .then((sched) => {
        setGeneratedSchedule(sched);
        onSuccessRef.current?.();
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setGeneratedSchedule(null);
        setError(err.message || 'Request failed.');
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [email, degree, concentration, refreshKey]);

  return { generatedSchedule, loading, error };
}
