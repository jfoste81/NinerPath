import { meetingSummary, sectionMapFromVariant } from '../utils/scheduleDisplay';

export default function CombinationSelector({
  combinationOptions,
  selectedCombinationIndex,
  onSelectCombination,
}) {
  return (
    <div className="border-b border-gray-100 pb-4 mb-4">
      <p className="text-sm font-semibold text-gray-800 mb-2">1. Pick a class combination</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {combinationOptions.map((combo, idx) => {
          const cardPreviewMap = sectionMapFromVariant(combo.schedule_variants?.[0]);
          const cardOmitted = new Set(combo.schedule_calendar_omitted_courses ?? []);
          return (
            <button
              key={combo.combination_id ?? idx}
              type="button"
              onClick={() => onSelectCombination(idx)}
              className={`text-left rounded-xl border-2 p-4 transition shadow-sm ${
                idx === selectedCombinationIndex
                  ? 'border-teal-700 bg-teal-50 ring-2 ring-teal-200'
                  : 'border-gray-200 bg-white hover:border-teal-300 hover:bg-gray-50'
              }`}
            >
              <div className="flex justify-between items-start gap-2 mb-2">
                <span className="font-bold text-teal-900">{combo.combination_label || `Option ${idx + 1}`}</span>
                <span className="text-xs font-semibold text-gray-600 shrink-0">{combo.generated_credits} cr</span>
              </div>
              <ul className="text-xs text-gray-700 space-y-1.5">
                {(combo.recommended_courses ?? []).map((course) => {
                  const sec = cardPreviewMap.get(course.id);
                  const sched = cardOmitted.has(course.id) ? '' : meetingSummary(sec);
                  const rightNote = sched ? sched : cardOmitted.has(course.id) ? 'No time in catalog' : '';
                  return (
                    <li
                      key={course.id}
                      className="flex justify-between gap-2 items-baseline min-w-0"
                      title={`${course.id}: ${course.name}`}
                    >
                      <div className="min-w-0 truncate">
                        <span className="font-semibold text-gray-800">{course.id}</span>
                        <span className="text-gray-500"> ({course.credits} cr)</span>
                      </div>
                      {rightNote ? (
                        <span className="text-[10px] text-gray-600 text-right shrink-0 max-w-[52%] leading-tight">
                          {cardOmitted.has(course.id) ? (
                            <span className="text-amber-800/90">{rightNote}</span>
                          ) : (
                            rightNote
                          )}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </button>
          );
        })}
      </div>
    </div>
  );
}
