export default function SavedSchedulesSidebar({ dashboardLoading, upcoming, session, onDownloadScheduleIcs }) {
  return (
    <aside className="w-full lg:w-80 shrink-0">
      <div className="rounded-xl border border-gray-200 bg-white shadow-md p-5">
        <h3 className="text-lg font-bold text-gray-900 border-b border-gray-100 pb-3 mb-4">Saved schedules</h3>
        {dashboardLoading ? (
          <div className="animate-pulse h-24 bg-gray-100 rounded" />
        ) : (upcoming ?? []).length > 0 ? (
          <ul className="space-y-3">
            {(upcoming ?? []).map((sch) => (
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
                {session?.user?.id && sch.id && (
                  <div className="mt-3 pt-2 border-t border-teal-100 space-y-1.5">
                    <button
                      type="button"
                      onClick={() => onDownloadScheduleIcs(sch.id, sch.term)}
                      className="w-full rounded-lg bg-white border border-teal-300 px-3 py-2 text-xs font-semibold text-teal-900 hover:bg-teal-100/80 shadow-sm"
                    >
                      Download .ics (Google Calendar)
                    </button>
                    <p className="text-[10px] leading-snug text-gray-600">
                      In Google Calendar: Settings → Import &amp; Export → Import, then upload this file.
                    </p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-600">No saved schedules yet. Use the Schedule page to explore Fall 2026 options.</p>
        )}
      </div>
    </aside>
  );
}
