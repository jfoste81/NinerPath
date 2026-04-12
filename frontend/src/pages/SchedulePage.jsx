import { useState, useEffect, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import ScheduleCalendar from '../ScheduleCalendar';
import { API_BASE, CONCENTRATIONS_BY_DEGREE } from '../constants';

export default function SchedulePage({ session, onSignOut }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const degree = searchParams.get('degree') || 'bs_computer_science';
  const concentration = searchParams.get('concentration') || 'systems_and_networks';

  const [generatedSchedule, setGeneratedSchedule] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedVariantIndex, setSelectedVariantIndex] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const scheduleVariants = useMemo(
    () => generatedSchedule?.schedule_variants ?? [],
    [generatedSchedule?.schedule_variants],
  );

  useEffect(() => {
    setSelectedVariantIndex((i) => {
      const n = scheduleVariants.length;
      if (n === 0) return 0;
      return Math.min(Math.max(0, i), n - 1);
    });
  }, [scheduleVariants]);

  useEffect(() => {
    if (!session?.user?.email) return undefined;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({
      email: session.user.email,
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
        setSelectedVariantIndex(0);
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setGeneratedSchedule(null);
        setError(err.message || 'Request failed.');
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [session?.user?.email, degree, concentration, refreshKey]);

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
        <p className="text-sm text-gray-600 bg-white border border-gray-200 rounded-lg px-4 py-3 shadow-sm">
          All recommendations use the <strong>Fall 2026</strong> mock course catalog and section times. Only courses
          with demo sections appear on the weekly calendar.
        </p>

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

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-900 text-sm">{error}</div>
        )}

        {generatedSchedule && (
          <div className="bg-white rounded-xl border border-gray-200 shadow-md p-5 sm:p-6">
            <h2 className="text-xl font-bold text-teal-900">
              {generatedSchedule.term_label || 'Fall 2026'} recommendations ({generatedSchedule.generated_credits}{' '}
              credits)
            </h2>
            <p className="text-sm text-gray-600 mt-1 mb-4">{generatedSchedule.concentration_label}</p>

            {generatedSchedule.recommended_courses?.length > 0 ? (
              <>
                <ul className="space-y-2 border-b border-gray-100 pb-4 mb-4">
                  {generatedSchedule.recommended_courses.map((course) => (
                    <li key={course.id} className="flex justify-between gap-3 text-sm sm:text-base">
                      <span className="font-semibold text-gray-800">
                        {course.id}: {course.name}
                      </span>
                      <span className="text-gray-500 shrink-0">{course.credits} cr</span>
                    </li>
                  ))}
                </ul>

                {scheduleVariants.length > 0 ? (
                  <div>
                    <p className="mb-2 text-sm font-semibold text-gray-800">
                      Weekly calendars ({scheduleVariants.length} conflict-free options)
                    </p>
                    {generatedSchedule.schedule_calendar_sections_term && (
                      <p className="mb-2 text-xs text-gray-500">
                        Section times from {generatedSchedule.schedule_calendar_sections_term} mock catalog.
                      </p>
                    )}
                    {Array.isArray(generatedSchedule.schedule_calendar_omitted_courses) &&
                      generatedSchedule.schedule_calendar_omitted_courses.length > 0 && (
                        <p className="mb-3 text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded px-2 py-1.5">
                          No mock section row for: {generatedSchedule.schedule_calendar_omitted_courses.join(', ')}.
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
                          Option {idx + 1}
                        </button>
                      ))}
                    </div>
                    <ScheduleCalendar variant={scheduleVariants[selectedVariantIndex]} />
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">
                    No weekly calendar variants (no mock sections or all combinations conflict).
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-gray-500">No eligible courses for this plan under the Fall 2026 mock rules.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
