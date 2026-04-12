import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE, CONCENTRATIONS_BY_DEGREE } from '../constants';

function StatusIcon({ status }) {
  if (status === 'completed') {
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300" title="Completed">
        ✓
      </span>
    );
  }
  if (status === 'registered') {
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-sky-100 text-sky-700 ring-1 ring-sky-300" title="Registered / in progress">
        ◐
      </span>
    );
  }
  if (status === 'planned') {
    return (
      <span
        className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 shadow-sm ring-2 ring-blue-200"
        title="Saved in your Fall schedule plan"
        aria-label="Planned in saved schedule"
      />
    );
  }
  return (
    <span className="inline-flex h-7 w-7 items-center justify-center rounded-full border-2 border-rose-400 bg-white text-transparent" title="Not completed">
      ○
    </span>
  );
}

const auditTableHead = (
  <thead>
    <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-600">
      <th className="px-3 py-2 w-12"></th>
      <th className="px-3 py-2 font-semibold">Course / requirement</th>
      <th className="px-3 py-2 font-semibold">Title</th>
      <th className="px-3 py-2 font-semibold">Grade</th>
      <th className="px-3 py-2 font-semibold">Credits</th>
      <th className="px-3 py-2 font-semibold">Term</th>
    </tr>
  </thead>
);

function AuditRow({ row, rowKey }) {
  if (row.kind === 'still_needed_pool') {
    const plannedSet = new Set(row.planned_in_pool || []);
    return (
      <tr key={rowKey} className="border-b border-gray-100 hover:bg-gray-50/80">
        <td className="px-3 py-2.5 align-middle">
          <StatusIcon status={row.status} />
        </td>
        <td className="px-3 py-2.5 text-sm text-gray-800" colSpan={5}>
          <span className="font-bold text-gray-900">Still needed: </span>
          <span className="text-gray-700">
            {row.deficit_count != null && row.deficit_count > 0
              ? `${row.deficit_count} course(s) from `
              : `${row.deficit_credits ?? 0} cr from `}
          </span>
          {(row.alternatives || []).map((a, i) => (
            <span key={a}>
              {i > 0 ? <span className="text-gray-400"> or </span> : null}
              <span className={`font-semibold ${plannedSet.has(a) ? 'text-teal-800' : 'text-teal-700'}`}>{a}</span>
              {plannedSet.has(a) ? (
                <span className="ml-0.5 text-blue-600" title="In saved Fall schedule">
                  ◉
                </span>
              ) : null}
            </span>
          ))}
        </td>
      </tr>
    );
  }

  return (
    <tr key={rowKey} className="border-b border-gray-100 hover:bg-gray-50/80">
      <td className="px-3 py-2.5 align-middle">
        <StatusIcon status={row.status} />
      </td>
      <td className="px-3 py-2.5 font-semibold text-gray-900 whitespace-nowrap">
        {row.requirement_group && (
          <div className="text-[11px] font-bold uppercase tracking-wide text-gray-500 mb-1">{row.requirement_group}</div>
        )}
        {row.kind === 'choice' && row.alternatives ? (
          row.requirement_label ? (
            <span className="text-teal-800">{row.requirement_label}</span>
          ) : (
            <span className="text-teal-800">
              {row.alternatives.map((a, i) => (
                <span key={a}>
                  {i > 0 ? ' or ' : ''}
                  {a}
                </span>
              ))}
            </span>
          )
        ) : (
          row.course_id
        )}
      </td>
      <td className="px-3 py-2.5 text-gray-700 max-w-md">{row.title}</td>
      <td className="px-3 py-2.5 font-medium text-gray-800">{row.grade}</td>
      <td className="px-3 py-2.5 text-gray-700">{row.credits}</td>
      <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">{row.term}</td>
    </tr>
  );
}

function SubsectionsAuditSection({ section }) {
  const [open, setOpen] = useState(true);
  const subsections = section.subsections || [];
  return (
    <div className="border border-gray-200 rounded-lg bg-white shadow-sm overflow-hidden mb-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left font-bold text-gray-900 bg-gray-50 hover:bg-gray-100 border-b border-gray-200"
      >
        <span>{section.title}</span>
        <span className={`text-teal-800 transition-transform ${open ? 'rotate-180' : ''}`}>⌄</span>
      </button>
      {open && (
        <div className="overflow-x-auto">
          {section.subtitle && (
            <p className="px-4 py-2 text-sm text-gray-600 bg-teal-50/50 border-b border-gray-100">{section.subtitle}</p>
          )}
          <div className="divide-y divide-gray-200">
            {subsections.map((sub, sidx) => (
              <div key={`${sub.title}-${sidx}`} className="bg-white">
                <div className="flex items-center gap-3 px-4 py-2.5 bg-gray-50/90 border-b border-gray-100">
                  <StatusIcon status={sub.header_status} />
                  <span className="font-bold uppercase tracking-wide text-xs sm:text-sm text-gray-900 flex-1 min-w-0">
                    {sub.title}
                  </span>
                  {!sub.hide_progress && (
                    <span className="text-xs font-semibold text-gray-600 shrink-0">
                      {typeof sub.picks_required === 'number' && sub.picks_required > 0
                        ? `${sub.picks_applied ?? 0}/${sub.picks_required} course${sub.picks_required === 1 ? '' : 's'}`
                        : `${sub.credits_applied ?? 0}/${sub.credits_required ?? 0} cr`}
                    </span>
                  )}
                </div>
                <table className="min-w-full text-sm">
                  {auditTableHead}
                  <tbody>
                    {(sub.rows || []).map((row, idx) => (
                      <AuditRow key={`${sub.title}-${idx}-${row.course_id || row.kind}`} row={row} rowKey={`${sub.title}-${idx}`} />
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AuditSection({ section }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="border border-gray-200 rounded-lg bg-white shadow-sm overflow-hidden mb-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left font-bold text-gray-900 bg-gray-50 hover:bg-gray-100 border-b border-gray-200"
      >
        <span>{section.title}</span>
        <span className={`text-teal-800 transition-transform ${open ? 'rotate-180' : ''}`}>⌄</span>
      </button>
      {open && (
        <div className="overflow-x-auto">
          {section.subtitle && <p className="px-4 py-2 text-sm text-gray-600 bg-teal-50/50 border-b border-gray-100">{section.subtitle}</p>}
          <table className="min-w-full text-sm">
            {auditTableHead}
            <tbody>
              {section.rows.map((row, idx) => (
                <AuditRow key={`${section.id}-${idx}-${row.course_id}`} row={row} rowKey={`${section.id}-${idx}-${row.course_id}`} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function DegreeHomePage({ session, onSignOut }) {
  const [dashboardData, setDashboardData] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState('');
  const [audit, setAudit] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState('');
  const [selectedDegree, setSelectedDegree] = useState('bs_computer_science');
  const [selectedConcentration, setSelectedConcentration] = useState('systems_and_networks');
  const [mockPrefsApplied, setMockPrefsApplied] = useState(false);

  useEffect(() => {
    if (!session?.user?.id || !session?.user?.email) return undefined;
    const ac = new AbortController();
    const q = new URLSearchParams({
      email: session.user.email,
      degree: selectedDegree,
      concentration: selectedConcentration,
      max_schedule_variants: '16',
    });
    setDashboardLoading(true);
    setDashboardError('');
    fetch(`${API_BASE}/api/dashboard/${session.user.id}?${q.toString()}`, { signal: ac.signal })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const msg =
            typeof data?.detail === 'string'
              ? data.detail
              : Array.isArray(data?.detail)
                ? data.detail.map((d) => d.msg || d).join(' ')
                : res.statusText || 'Dashboard request failed';
          throw new Error(msg);
        }
        return data;
      })
      .then(setDashboardData)
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setDashboardData(null);
        setDashboardError(err.message || 'Could not load dashboard.');
      })
      .finally(() => setDashboardLoading(false));
    return () => ac.abort();
  }, [session, selectedDegree, selectedConcentration]);

  useEffect(() => {
    if (!session?.user?.email) return undefined;
    const ac = new AbortController();
    const q = new URLSearchParams({
      email: session.user.email,
      degree: selectedDegree,
      concentration: selectedConcentration,
      user_id: session.user.id,
    });
    setAuditLoading(true);
    setAuditError('');
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
        setAuditError(err.message || 'Could not load degree audit.');
      })
      .finally(() => setAuditLoading(false));
    return () => ac.abort();
  }, [session?.user?.email, session?.user?.id, selectedDegree, selectedConcentration]);

  useEffect(() => {
    const h = dashboardData?.history;
    if (!session || mockPrefsApplied || !h?.degree_plan) return;
    const opts = CONCENTRATIONS_BY_DEGREE[h.degree_plan];
    if (!opts) return;
    setSelectedDegree(h.degree_plan);
    if (h.concentration && opts.some((c) => c.value === h.concentration)) {
      setSelectedConcentration(h.concentration);
    }
    setMockPrefsApplied(true);
  }, [dashboardData, session, mockPrefsApplied]);

  const scheduleHref = `/schedule?degree=${encodeURIComponent(selectedDegree)}&concentration=${encodeURIComponent(selectedConcentration)}`;

  return (
    <div className="bg-slate-100 min-h-screen font-sans text-gray-900">
      <nav className="bg-teal-900 text-white px-4 py-3 shadow-lg flex flex-wrap justify-between items-center gap-3 sticky top-0 z-10">
        <div className="flex items-center gap-3 min-w-0">
          <img src="/ninerpath-logo.png" alt="" className="h-9 w-auto shrink-0" />
          <h1 className="text-xl font-bold tracking-wide truncate">NinerPath</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-4">
          <Link
            to={scheduleHref}
            className="rounded-lg bg-amber-400 px-4 py-2 text-sm font-bold text-teal-950 shadow hover:bg-amber-300 transition"
          >
            Schedule
          </Link>
          <span className="text-xs sm:text-sm font-medium bg-teal-800 px-2 sm:px-3 py-1 rounded-full border border-teal-700 max-w-[200px] truncate">
            {session.user.email}
          </span>
          <button
            type="button"
            onClick={onSignOut}
            className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded font-bold text-sm transition shadow"
          >
            Sign Out
          </button>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-4 py-6">
        {(dashboardError || auditError) && (
          <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 text-sm">
            {dashboardError && <p>{dashboardError}</p>}
            {auditError && <p>{auditError}</p>}
          </div>
        )}

        <div className="flex flex-col lg:flex-row gap-6">
          <div className="flex-1 min-w-0">
            <div className="rounded-xl border border-gray-200 bg-white shadow-md overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-200 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-xl sm:text-2xl font-bold text-gray-900">
                      {audit?.major_title || 'Degree audit'}
                    </h2>
                    {audit && (
                      <span
                        className={`text-xs font-bold uppercase tracking-wide px-2 py-1 rounded border ${
                          audit.status_badge === 'COMPLETE'
                            ? 'border-emerald-500 text-emerald-800 bg-emerald-50'
                            : 'border-rose-500 text-rose-800 bg-rose-50'
                        }`}
                      >
                        {audit.status_badge}
                      </span>
                    )}
                  </div>
                  {audit && (
                    <p className="mt-2 text-sm text-gray-600">
                      <span className="font-semibold text-gray-800">Degree credit hours:</span>{' '}
                      {audit.degree_credits_applied ?? audit.credits_applied} /{' '}
                      {audit.degree_total_credits ?? audit.credits_required} toward the{' '}
                      {audit.degree_total_credits ?? audit.credits_required}-hour program
                      {' · '}
                      <span className="font-semibold text-gray-800">Catalog year:</span> {audit.catalog_year}
                      {typeof audit.gpa === 'number' && (
                        <>
                          {' · '}
                          <span className="font-semibold text-gray-800">GPA:</span> {audit.gpa.toFixed(2)}
                        </>
                      )}
                    </p>
                  )}
                  {audit?.footnote && <p className="mt-2 text-xs text-gray-500">{audit.footnote}</p>}
                </div>
                <div className="flex flex-col gap-2 w-full sm:w-auto">
                  <select
                    value={selectedDegree}
                    onChange={(e) => {
                      const d = e.target.value;
                      setSelectedDegree(d);
                      setSelectedConcentration(CONCENTRATIONS_BY_DEGREE[d][0].value);
                    }}
                    className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
                  >
                    <option value="bs_computer_science">B.S. Computer Science</option>
                    <option value="ba_computer_science">B.A. Computer Science</option>
                  </select>
                  <select
                    value={selectedConcentration}
                    onChange={(e) => setSelectedConcentration(e.target.value)}
                    className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white max-w-xs"
                  >
                    {CONCENTRATIONS_BY_DEGREE[selectedDegree].map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="p-4 sm:p-5">
                {auditLoading && !audit && (
                  <div className="animate-pulse space-y-3">
                    <div className="h-4 bg-gray-200 rounded w-2/3" />
                    <div className="h-32 bg-gray-100 rounded" />
                  </div>
                )}
                {audit?.sections?.map((sec) =>
                  sec.layout === 'subsections' ? (
                    <SubsectionsAuditSection key={sec.id} section={sec} />
                  ) : (
                    <AuditSection key={sec.id} section={sec} />
                  ),
                )}
                {audit?.footer_note && <p className="mt-4 text-xs text-gray-500 border-t border-gray-100 pt-3">{audit.footer_note}</p>}
              </div>
            </div>
          </div>

          <aside className="w-full lg:w-80 shrink-0">
            <div className="rounded-xl border border-gray-200 bg-white shadow-md p-5">
              <h3 className="text-lg font-bold text-gray-900 border-b border-gray-100 pb-3 mb-4">Saved schedules</h3>
              {dashboardLoading ? (
                <div className="animate-pulse h-24 bg-gray-100 rounded" />
              ) : (dashboardData?.upcoming ?? []).length > 0 ? (
                <ul className="space-y-3">
                  {(dashboardData.upcoming ?? []).map((sch) => (
                    <li key={sch.id} className="rounded-lg border border-teal-200 bg-teal-50 px-3 py-3 text-sm">
                      <span className="font-bold text-teal-900">{sch.term || '—'}</span>
                      <p className="text-gray-700 mt-1">
                        {Array.isArray(sch.course_ids) && sch.course_ids.length > 0
                          ? `${sch.course_ids.length} course${sch.course_ids.length === 1 ? '' : 's'}`
                          : 'No course list in record'}
                      </p>
                      {sch.created_at && (
                        <p className="text-xs text-gray-500 mt-1">{new Date(sch.created_at).toLocaleString()}</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-600">No saved schedules yet. Use the Schedule page to explore Fall 2026 options.</p>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
