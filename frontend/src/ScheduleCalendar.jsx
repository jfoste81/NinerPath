const DAY_HEADERS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const START_HOUR = 8;
const END_HOUR = 23;
const PX_PER_HOUR = 48;

const BLOCK_COLORS = [
  'bg-sky-200/95 border-sky-300',
  'bg-emerald-200/95 border-emerald-300',
  'bg-violet-200/95 border-violet-300',
  'bg-pink-200/95 border-pink-300',
  'bg-amber-200/95 border-amber-300',
  'bg-cyan-200/95 border-cyan-300',
  'bg-lime-200/95 border-lime-300',
  'bg-orange-200/95 border-orange-300',
];

function formatMinutes(mins) {
  const h24 = Math.floor(mins / 60);
  const m = mins % 60;
  const ap = h24 >= 12 ? 'PM' : 'AM';
  const h12 = h24 % 12 || 12;
  return `${h12}:${m.toString().padStart(2, '0')} ${ap}`;
}

function flattenVariant(variant) {
  if (!variant?.sections?.length) return [];
  const rows = [];
  for (const sec of variant.sections) {
    const label = sec.title || sec.course_id;
    const ci = typeof sec.color_index === 'number' ? sec.color_index : 0;
    for (const b of sec.calendar_blocks || []) {
      rows.push({
        weekday: b.weekday,
        start_minutes: b.start_minutes,
        end_minutes: b.end_minutes,
        label,
        colorIndex: ci,
        course_id: sec.course_id,
        section: sec.section,
      });
    }
  }
  return rows;
}

export default function ScheduleCalendar({ variant }) {
  const blocks = flattenVariant(variant);
  const totalMinutes = (END_HOUR - START_HOUR) * 60;
  const gridHeight = (END_HOUR - START_HOUR) * PX_PER_HOUR;
  const hours = [];
  for (let h = START_HOUR; h <= END_HOUR; h++) {
    hours.push(h);
  }

  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="flex min-w-[720px]">
        <div
          className="w-12 flex-shrink-0 border-r border-gray-200 bg-gray-50 text-right text-xs text-gray-500"
          style={{ paddingTop: 28 }}
        >
          {hours.slice(0, -1).map((h) => {
            const display = h > 12 ? h - 12 : h === 0 ? 12 : h;
            const ap = h >= 12 ? 'pm' : 'am';
            return (
              <div
                key={h}
                style={{ height: PX_PER_HOUR }}
                className="pr-1 pt-0 font-medium text-gray-600"
              >
                {display}
                {ap}
              </div>
            );
          })}
        </div>
        <div className="grid flex-1 grid-cols-7 gap-px bg-gray-200">
          {DAY_HEADERS.map((name, colIdx) => (
            <div key={name} className="flex flex-col bg-white">
              <div className="border-b border-gray-200 py-1 text-center text-xs font-semibold text-gray-700">
                {name}
              </div>
              <div
                className="relative border-l border-gray-100"
                style={{ height: gridHeight }}
              >
                {hours.slice(0, -1).map((h) => (
                  <div
                    key={h}
                    className="absolute left-0 right-0 border-b border-dashed border-gray-100"
                    style={{
                      top: (h - START_HOUR) * PX_PER_HOUR,
                      height: PX_PER_HOUR,
                    }}
                  />
                ))}
                {blocks
                  .filter((b) => b.weekday === colIdx)
                  .map((b, i) => {
                    const top = ((b.start_minutes - START_HOUR * 60) / totalMinutes) * gridHeight;
                    const h =
                      ((b.end_minutes - b.start_minutes) / totalMinutes) * gridHeight;
                    const colorClass =
                      BLOCK_COLORS[b.colorIndex % BLOCK_COLORS.length];
                    return (
                      <div
                        key={`${b.course_id}-${b.section}-${i}`}
                        className={`absolute left-0.5 right-0.5 overflow-hidden rounded-md border px-1 py-0.5 text-xs shadow-sm ${colorClass}`}
                        style={{
                          top: Math.max(0, top),
                          height: Math.max(h, 22),
                          zIndex: 2,
                        }}
                        title={`${b.course_id} ${b.section ?? ''} · ${formatMinutes(b.start_minutes)}–${formatMinutes(b.end_minutes)}`}
                      >
                        <div className="flex items-start gap-0.5">
                          <span className="mt-0.5 inline-flex h-3 w-3 flex-shrink-0 items-center justify-center rounded-sm bg-green-600 text-[8px] font-bold text-white">
                            ✓
                          </span>
                          <span className="line-clamp-3 font-semibold leading-tight text-gray-900">
                            {b.label}
                          </span>
                        </div>
                        <div className="mt-0.5 text-[10px] font-medium text-gray-700">
                          {formatMinutes(b.start_minutes)} – {formatMinutes(b.end_minutes)}
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
