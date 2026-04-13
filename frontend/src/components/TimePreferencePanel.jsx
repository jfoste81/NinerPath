export default function TimePreferencePanel({
  prefsLoading,
  prefsUi,
  blockedRows,
  setBlockedRows,
  onSavePreferences,
  addBlockedRow,
  removeBlockedRow,
}) {
  const prefsSaving = prefsUi.saving;
  const prefsMessage = prefsUi.message;
  const prefsError = prefsUi.error;
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-sm font-bold text-gray-900">Blocked class times</h2>
          <p className="text-xs text-gray-600 mt-0.5">
            The scheduler will not place sections that overlap these windows (same day codes as the catalog: M T W R F).
          </p>
        </div>
        <button
          type="button"
          onClick={onSavePreferences}
          disabled={prefsSaving || prefsLoading}
          className="rounded-lg bg-gray-800 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-900 disabled:bg-gray-400"
        >
          {prefsSaving ? 'Saving…' : 'Save preferences'}
        </button>
      </div>
      {prefsLoading && <p className="text-xs text-gray-500">Loading saved preferences…</p>}
      {prefsMessage && (
        <p className="text-xs text-emerald-800 bg-emerald-50 border border-emerald-100 rounded-lg px-3 py-2">{prefsMessage}</p>
      )}
      {prefsError && (
        <p className="text-xs text-red-800 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{prefsError}</p>
      )}
      <div className="space-y-2">
        {blockedRows.length === 0 ? (
          <p className="text-sm text-gray-600">
            No blocked windows — all section times are allowed. Add a row to block meeting times, or leave empty
            and save to clear saved blocks.
          </p>
        ) : (
          blockedRows.map((row, idx) => (
            <div key={idx} className="flex flex-wrap items-end gap-2">
              <div className="flex flex-col gap-0.5 min-w-[120px] flex-1">
                <label className="text-[10px] font-semibold text-gray-500">Days</label>
                <input
                  type="text"
                  value={row.days}
                  onChange={(e) =>
                    setBlockedRows((rows) => rows.map((r, i) => (i === idx ? { ...r, days: e.target.value } : r)))
                  }
                  placeholder="e.g. MWF"
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm uppercase"
                />
              </div>
              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] font-semibold text-gray-500">From</label>
                <input
                  type="time"
                  value={row.start}
                  onChange={(e) =>
                    setBlockedRows((rows) => rows.map((r, i) => (i === idx ? { ...r, start: e.target.value } : r)))
                  }
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
                />
              </div>
              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] font-semibold text-gray-500">To</label>
                <input
                  type="time"
                  value={row.end}
                  onChange={(e) =>
                    setBlockedRows((rows) => rows.map((r, i) => (i === idx ? { ...r, end: e.target.value } : r)))
                  }
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
                />
              </div>
              <button
                type="button"
                onClick={() => removeBlockedRow(idx)}
                className="text-xs text-red-700 hover:underline mb-1"
              >
                Remove
              </button>
            </div>
          ))
        )}
      </div>
      <button type="button" onClick={addBlockedRow} className="text-sm font-semibold text-teal-800 hover:underline">
        + Add window
      </button>
    </div>
  );
}
