import { useState, useCallback } from 'react';

/** Default UI feedback for schedule preferences (save flow + messages). */
export const INITIAL_PREFS_UI = { saving: false, message: '', error: '' };

/** Default UI feedback for persisting the generated schedule to the server. */
export const INITIAL_SAVE_UI = { saving: false, message: '', error: '' };

/**
 * Pairs preferences + schedule-save feedback so updates can batch naturally and child props stay stable.
 */
export function useSchedulePageFeedback() {
  const [prefsUi, setPrefsUi] = useState(INITIAL_PREFS_UI);
  const [saveUi, setSaveUi] = useState(INITIAL_SAVE_UI);

  const onPrefsLoadStart = useCallback(() => {
    setPrefsUi((p) => ({ ...p, error: '' }));
  }, []);

  return { prefsUi, setPrefsUi, saveUi, setSaveUi, onPrefsLoadStart };
}
