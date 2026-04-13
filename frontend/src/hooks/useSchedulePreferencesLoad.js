import { useState, useEffect } from 'react';
import { API_BASE } from '../constants';

/**
 * GET `/api/student/schedule-preferences` and maps blocked_time_windows into local row shape.
 * `onPrefsLoadStart` runs when a fetch begins (e.g. clear prefs error in parent UI state).
 */
export function useSchedulePreferencesLoad(email, setBlockedRows, onPrefsLoadStart) {
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!email) return undefined;
    setLoading(true);
    onPrefsLoadStart?.();
    const pAc = new AbortController();
    const pParams = new URLSearchParams({ email });
    fetch(`${API_BASE}/api/student/schedule-preferences?${pParams.toString()}`, { signal: pAc.signal })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Failed to load preferences.');
        return data;
      })
      .then((data) => {
        const wins = data?.schedule_preferences?.blocked_time_windows;
        if (Array.isArray(wins) && wins.length > 0) {
          setBlockedRows(
            wins.map((w) => ({
              days: typeof w.days === 'string' ? w.days : '',
              start: typeof w.start === 'string' ? w.start : '09:00',
              end: typeof w.end === 'string' ? w.end : '12:00',
            })),
          );
        } else {
          setBlockedRows([]);
        }
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setBlockedRows([]);
      })
      .finally(() => setLoading(false));
    return () => pAc.abort();
  }, [email, setBlockedRows, onPrefsLoadStart]);

  return { prefsLoading: loading };
}
