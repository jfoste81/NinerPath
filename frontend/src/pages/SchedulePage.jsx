import { useState, useEffect, useMemo, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import ScheduleCalendar from '../ScheduleCalendar';
import CombinationSelector from '../components/CombinationSelector';
import TimePreferencePanel from '../components/TimePreferencePanel';
import { API_BASE, CONCENTRATIONS_BY_DEGREE } from '../constants';
import { useSchedulePageFeedback } from '../hooks/schedulePageUi';
import { useScheduleGeneration } from '../hooks/useScheduleGeneration';
import { useSchedulePreferencesLoad } from '../hooks/useSchedulePreferencesLoad';
import { meetingSummary, sectionMapFromVariant } from '../utils/scheduleDisplay';

export default function SchedulePage({ session, onSignOut }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const degree = searchParams.get('degree') || 'bs_computer_science';
  const concentration = searchParams.get('concentration') || 'systems_and_networks';

  const [selectedCombinationIndex, setSelectedCombinationIndex] = useState(0);
  const [selectedVariantIndex, setSelectedVariantIndex] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [blockedRows, setBlockedRows] = useState([]);
  const { prefsUi, setPrefsUi, saveUi, setSaveUi, onPrefsLoadStart } = useSchedulePageFeedback();

  const onScheduleGenerationSuccess = useCallback(() => {
    setSelectedCombinationIndex(0);
    setSelectedVariantIndex(0);
    setSaveUi((s) => ({ ...s, message: '', error: '' }));
    setPrefsUi((p) => ({ ...p, message: '' }));
  }, []);

  const { generatedSchedule, loading, error } = useScheduleGeneration({
    email: session?.user?.email,
    degree,
    concentration,
    refreshKey,
    onSuccess: onScheduleGenerationSuccess,
  });

  const { prefsLoading } = useSchedulePreferencesLoad(session?.user?.email, setBlockedRows, onPrefsLoadStart);

  const combinationOptions = useMemo(() => {
    const from = generatedSchedule?.combination_options;
    if (Array.isArray(from) && from.length > 0) return from;
    const rec = generatedSchedule?.recommended_courses;
    if (Array.isArray(rec) && rec.length > 0 && generatedSchedule) {
      return [
        {
          combination_id: 1,
          combination_label: 'Combination A',
          recommended_courses: rec,
          generated_credits: generatedSchedule.generated_credits,
          meets_full_time_target: generatedSchedule.meets_full_time_target,
          remaining_required_count: generatedSchedule.remaining_required_count,
          remaining_elective_count: generatedSchedule.remaining_elective_count,
          schedule_variants: generatedSchedule.schedule_variants,
          schedule_calendar_sections_term: generatedSchedule.schedule_calendar_sections_term,
          schedule_calendar_omitted_courses: generatedSchedule.schedule_calendar_omitted_courses,
        },
      ];
    }
    return [];
  }, [generatedSchedule]);

  const activeCombination = useMemo(() => {
    if (!combinationOptions.length) return null;
    const idx = Math.min(Math.max(0, selectedCombinationIndex), combinationOptions.length - 1);
    return combinationOptions[idx];
  }, [combinationOptions, selectedCombinationIndex]);

  const scheduleVariants = useMemo(
    () => activeCombination?.schedule_variants ?? generatedSchedule?.schedule_variants ?? [],
    [activeCombination, generatedSchedule?.schedule_variants],
  );

  const activeSectionMap = useMemo(
    () => sectionMapFromVariant(scheduleVariants[selectedVariantIndex]),
    [scheduleVariants, selectedVariantIndex],
  );

  const omittedIds = useMemo(() => {
    const o = activeCombination?.schedule_calendar_omitted_courses;
    return Array.isArray(o) ? new Set(o) : new Set();
  }, [activeCombination?.schedule_calendar_omitted_courses]);

  useEffect(() => {
    setSelectedCombinationIndex((i) => {
      const n = combinationOptions.length;
      if (n === 0) return 0;
      return Math.min(Math.max(0, i), n - 1);
    });
  }, [combinationOptions]);

  useEffect(() => {
    setSelectedVariantIndex((vi) => {
      const n = scheduleVariants.length;
      if (n === 0) return 0;
      return Math.min(Math.max(0, vi), n - 1);
    });
  }, [scheduleVariants, selectedCombinationIndex]);

  const saveSchedule = () => {
    if (!session?.user?.id) {
      setSaveUi((s) => ({ ...s, error: 'You must be signed in to save a schedule.' }));
      return;
    }
    const variant = scheduleVariants[selectedVariantIndex];
    const fromVariant = variant?.sections?.map((s) => s.course_id).filter(Boolean);
    const fromRecommended = activeCombination?.recommended_courses?.map((c) => c.id).filter(Boolean);
    const courseIds = (fromVariant?.length ? fromVariant : fromRecommended) ?? [];
    if (!courseIds.length) {
      setSaveUi((s) => ({ ...s, error: 'Nothing to save yet — generate a schedule with at least one course.' }));
      return;
    }
    setSaveUi((s) => ({ ...s, saving: true, message: '', error: '' }));
    fetch(`${API_BASE}/api/schedules/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: session.user.id,
        term_label: generatedSchedule?.term_label || 'Fall 2026',
        course_ids: courseIds,
        variant_index: selectedVariantIndex,
        combination_index: selectedCombinationIndex,
      }),
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Save failed.');
        return data;
      })
      .then((data) => {
        const src = data.source === 'supabase' ? 'cloud' : 'this device';
        setSaveUi((s) => ({
          ...s,
          message: `Schedule saved (${src}). Open Degree audit to see blue dots on planned courses.`,
        }));
      })
      .catch((err) => setSaveUi((s) => ({ ...s, error: err.message || 'Save failed.' })))
      .finally(() => setSaveUi((s) => ({ ...s, saving: false })));
  };

  const saveSchedulePreferences = () => {
    if (!session?.user?.email) return;
    const windows = blockedRows
      .filter((r) => (r.days || '').trim())
      .map((r) => ({
        days: r.days.trim().toUpperCase(),
        start: r.start || '09:00',
        end: r.end || '12:00',
      }));
    setPrefsUi((p) => ({ ...p, saving: true, message: '', error: '' }));
    fetch(`${API_BASE}/api/student/schedule-preferences`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: session.user.email,
        blocked_time_windows: windows,
      }),
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Save failed.');
        return data;
      })
      .then((data) => {
        const wins = data?.schedule_preferences?.blocked_time_windows;
        if (Array.isArray(wins)) {
          if (wins.length > 0) {
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
        }
        setPrefsUi((p) => ({
          ...p,
          message: 'Schedule preferences saved. Regenerating options…',
        }));
        setRefreshKey((k) => k + 1);
      })
      .catch((err) => setPrefsUi((p) => ({ ...p, error: err.message || 'Save failed.' })))
      .finally(() => setPrefsUi((p) => ({ ...p, saving: false })));
  };

  const addBlockedRow = () => {
    setBlockedRows((rows) => [...rows, { days: '', start: '09:00', end: '12:00' }]);
  };

  const removeBlockedRow = (index) => {
    setBlockedRows((rows) => rows.filter((_, i) => i !== index));
  };

  const appliedBlocks = generatedSchedule?.blocked_time_windows_applied;

  return (
    <div className="min-h-screen bg-slate-100 font-sans text-gray-900">
      <nav className="bg-teal-900 text-white px-4 py-3 shadow-lg flex flex-wrap justify-between items-center gap-3 sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <img src="/ninerpath-logo.png" alt="" className="h-9 w-auto" />
          <h1 className="text-xl font-bold">Fall 2026 schedule options</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to="/"
            className="rounded-lg bg-white/10 px-4 py-2 text-sm font-semibold hover:bg-white/20 border border-white/30"
          >
            Degree audit
          </Link>
          <span className="text-xs text-teal-200 max-w-[160px] truncate">{session.user.email}</span>
          <button
            type="button"
            onClick={onSignOut}
            className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded font-bold text-sm"
          >
            Sign Out
          </button>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
        <div className="flex flex-col sm:flex-row flex-wrap gap-3 items-stretch sm:items-end bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-gray-500">Degree</label>
            <select
              value={degree}
              onChange={(e) => {
                const d = e.target.value;
                setSearchParams({ degree: d, concentration: CONCENTRATIONS_BY_DEGREE[d][0].value });
              }}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white min-w-[200px]"
            >
              <option value="bs_computer_science">B.S. Computer Science</option>
              <option value="ba_computer_science">B.A. Computer Science</option>
            </select>
          </div>
          <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
            <label className="text-xs font-semibold text-gray-500">Concentration</label>
            <select
              value={concentration}
              onChange={(e) => setSearchParams({ degree, concentration: e.target.value })}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white w-full"
            >
              {CONCENTRATIONS_BY_DEGREE[degree].map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
            className="rounded-lg bg-teal-700 px-5 py-2.5 text-sm font-bold text-white shadow hover:bg-teal-800 disabled:bg-gray-400"
          >
            {loading ? 'Loading…' : 'Refresh options'}
          </button>
        </div>

        {session?.user?.email && (
          <TimePreferencePanel
            prefsLoading={prefsLoading}
            prefsUi={prefsUi}
            blockedRows={blockedRows}
            setBlockedRows={setBlockedRows}
            onSavePreferences={saveSchedulePreferences}
            addBlockedRow={addBlockedRow}
            removeBlockedRow={removeBlockedRow}
          />
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-900 text-sm">{error}</div>
        )}

        {generatedSchedule && (
          <div className="bg-white rounded-xl border border-gray-200 shadow-md p-5 sm:p-6">
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
              <div>
                <h2 className="text-xl font-bold text-teal-900">
                  {generatedSchedule.term_label || 'Fall 2026'} recommendations (
                  {activeCombination?.generated_credits ?? generatedSchedule.generated_credits} credits)
                </h2>
                <p className="text-sm text-gray-600 mt-1">{generatedSchedule.concentration_label}</p>
                {Array.isArray(appliedBlocks) && appliedBlocks.length > 0 && (
                  <p className="text-xs text-amber-900 bg-amber-50 border border-amber-100 rounded-lg px-2 py-1.5 mt-2 max-w-xl">
                    Avoiding class meetings:{' '}
                    {appliedBlocks.map((b, i) => (
                      <span key={i}>
                        {i > 0 ? '; ' : ''}
                        {b.days} {b.start}–{b.end}
                      </span>
                    ))}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={saveSchedule}
                disabled={saveUi.saving}
                className="shrink-0 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-bold text-white shadow hover:bg-blue-700 disabled:bg-gray-400"
              >
                {saveUi.saving ? 'Saving…' : 'Save this schedule'}
              </button>
            </div>
            {saveUi.message && (
              <p className="mb-3 text-sm text-emerald-800 bg-emerald-50 border border-emerald-100 rounded-lg px-3 py-2">
                {saveUi.message}
              </p>
            )}
            {saveUi.error && (
              <p className="mb-3 text-sm text-red-800 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{saveUi.error}</p>
            )}

            {combinationOptions.length > 0 && activeCombination?.recommended_courses?.length > 0 ? (
              <>
                <CombinationSelector
                  combinationOptions={combinationOptions}
                  selectedCombinationIndex={selectedCombinationIndex}
                  onSelectCombination={(idx) => {
                    setSelectedCombinationIndex(idx);
                    setSelectedVariantIndex(0);
                  }}
                />
                <ul className="space-y-2 border-b border-gray-100 pb-4 mb-4">
                  {(activeCombination.recommended_courses ?? []).map((course) => {
                    const sec = activeSectionMap.get(course.id);
                    const sched = omittedIds.has(course.id) ? '' : meetingSummary(sec);
                    let scheduleCell = '';
                    if (sched) scheduleCell = sched;
                    else if (omittedIds.has(course.id))
                      scheduleCell = 'No meeting time in mock catalog';
                    else if (scheduleVariants.length === 0) scheduleCell = 'No section schedule';
                    return (
                      <li
                        key={course.id}
                        className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm sm:text-base"
                      >
                        <span className="font-semibold text-gray-800 min-w-0 flex-1 basis-[min(100%,14rem)]">
                          {course.id}: {course.name}
                        </span>
                        <div className="flex flex-wrap items-baseline justify-end gap-x-4 gap-y-0.5 shrink-0 text-right ml-auto">
                          {scheduleCell ? (
                            <span
                              className={`text-xs max-w-[min(100%,16rem)] ${
                                omittedIds.has(course.id) || scheduleVariants.length === 0
                                  ? 'text-amber-800'
                                  : 'text-gray-600'
                              }`}
                            >
                              {scheduleCell}
                            </span>
                          ) : null}
                          <span className="text-gray-500 tabular-nums whitespace-nowrap">{course.credits} cr</span>
                        </div>
                      </li>
                    );
                  })}
                </ul>

                {scheduleVariants.length > 0 ? (
                  <div>
                    <p className="mb-2 text-sm font-semibold text-gray-800">
                      2. Section schedules for {activeCombination.combination_label || 'this mix'} (
                      {scheduleVariants.length} conflict-free option{scheduleVariants.length === 1 ? '' : 's'})
                    </p>
                    {activeCombination.schedule_calendar_sections_term && (
                      <p className="mb-2 text-xs text-gray-500">
                        Section times from {activeCombination.schedule_calendar_sections_term} catalog.
                      </p>
                    )}
                    {Array.isArray(activeCombination.schedule_calendar_omitted_courses) &&
                      activeCombination.schedule_calendar_omitted_courses.length > 0 && (
                        <p className="mb-3 text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded px-2 py-1.5">
                          No section row for: {activeCombination.schedule_calendar_omitted_courses.join(', ')}.
                        </p>
                      )}
                    <div className="mb-4 flex flex-wrap gap-2">
                      {scheduleVariants.map((v, idx) => (
                        <button
                          key={v.variant_id ?? idx}
                          type="button"
                          onClick={() => setSelectedVariantIndex(idx)}
                          className={`rounded-full px-3 py-1 text-sm font-medium transition ${
                            idx === selectedVariantIndex
                              ? 'bg-teal-800 text-white shadow'
                              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                          }`}
                        >
                          Time layout {idx + 1}
                        </button>
                      ))}
                    </div>
                    <ScheduleCalendar variant={scheduleVariants[selectedVariantIndex]} />
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">
                    No weekly calendar variants (no sections or all combinations conflict).
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-gray-500">No eligible courses for this plan under the Fall 2026 rules.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
