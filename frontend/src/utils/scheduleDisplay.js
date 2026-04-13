/** One line from mock section rows: e.g. "MWF · 10:00 AM - 10:50 AM" */
export function meetingSummary(section) {
  if (!section) return '';
  const d = (section.days || '').trim();
  const t = (section.time || '').trim();
  if (!d && !t) return '';
  if (!d) return t;
  if (!t) return d;
  return `${d} · ${t}`;
}

export function sectionMapFromVariant(variant) {
  const m = new Map();
  for (const s of variant?.sections ?? []) {
    if (s.course_id) m.set(s.course_id, s);
  }
  return m;
}
