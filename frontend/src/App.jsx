import { useState, useEffect, useMemo } from 'react';
import { supabase } from './supabaseClient';
import ScheduleCalendar from './ScheduleCalendar';

/** Used for term GPA when transcript rows omit credits (matches backend catalog where possible). */
const COURSE_CREDITS_FALLBACK = {
  'ITSC 1212': 4,
  'ITSC 1213': 4,
  'PHYS 1101': 4,
  'CHEM 1251': 4,
  'BIOL 1110': 4,
};

function creditsForCourse(course) {
  if (typeof course.credits === 'number' && course.credits > 0) return course.credits;
  return COURSE_CREDITS_FALLBACK[course.id] ?? 3;
}

function gradeToPoints(grade) {
  const key = String(grade).trim().toUpperCase();
  const table = {
    'A+': 4,
    A: 4,
    'A-': 3.67,
    'B+': 3.33,
    B: 3,
    'B-': 2.67,
    'C+': 2.33,
    C: 2,
    'C-': 1.67,
    'D+': 1.33,
    D: 1,
    'D-': 0.67,
    F: 0,
  };
  const pts = table[key];
  return typeof pts === 'number' ? pts : null;
}

function termSortKey(term) {
  const m = String(term).match(/^(Fall|Spring|Summer|Winter)\s+(\d{4})$/i);
  if (!m) return 0;
  const seasonOrder = { spring: 1, summer: 2, fall: 3, winter: 4 };
  const y = parseInt(m[2], 10);
  const s = seasonOrder[m[1].toLowerCase()] ?? 0;
  return y * 10 + s;
}

function groupCompletedCoursesByTerm(completedCourses) {
  const byTerm = new Map();
  for (const c of completedCourses) {
    const t = c.term || 'Unknown term';
    if (!byTerm.has(t)) byTerm.set(t, []);
    byTerm.get(t).push(c);
  }
  return Array.from(byTerm.entries())
    .map(([term, courses]) => {
      let qualityPoints = 0;
      let creditAttempted = 0;
      for (const row of courses) {
        const cr = creditsForCourse(row);
        const gp = gradeToPoints(row.grade);
        if (gp != null && cr > 0) {
          qualityPoints += gp * cr;
          creditAttempted += cr;
        }
      }
      const termGpa =
        creditAttempted > 0 ? Math.round((qualityPoints / creditAttempted) * 100) / 100 : null;
      return {
        term,
        courses: [...courses].sort((a, b) => a.id.localeCompare(b.id)),
        termGpa,
        termCredits: creditAttempted,
      };
    })
    .sort((a, b) => termSortKey(b.term) - termSortKey(a.term));
}

const CONCENTRATIONS_BY_DEGREE = {
  bs_computer_science: [
    { value: 'systems_and_networks', label: 'Systems and Networks' },
    { value: 'ai_robotics_and_gaming', label: 'AI, Robotics and Gaming' },
    { value: 'bioinformatics', label: 'Bioinformatics' },
    { value: 'cybersecurity', label: 'Cybersecurity' },
    { value: 'data_science', label: 'Data Science' },
    { value: 'web_mobile_and_software_engineering', label: 'Web/Mobile Development & Software Engineering' },
  ],
  ba_computer_science: [
    { value: 'information_technology', label: 'Information Technology' },
    { value: 'human_computer_interaction', label: 'Human-Computer Interaction' },
    { value: 'bioinformatics', label: 'Bioinformatics' },
  ],
};

export default function App() {
  const [session, setSession] = useState(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [dashboardData, setDashboardData] = useState(null);
  const [generatedSchedule, setGeneratedSchedule] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatorError, setGeneratorError] = useState('');
  const [selectedDegree, setSelectedDegree] = useState('bs_computer_science');
  const [selectedConcentration, setSelectedConcentration] = useState('systems_and_networks');
  const [mockPrefsApplied, setMockPrefsApplied] = useState(false);
  /** Empty = server uses calendar term; set to e.g. Fall 2026 to match mock section catalog. */
  const [planningTermLabel, setPlanningTermLabel] = useState('');
  const [selectedVariantIndex, setSelectedVariantIndex] = useState(0);

  // AUTHENTICATION LISTENER
  useEffect(() => {
    // Check if the user is already logged in when the page loads
    supabase.auth.getSession().then(({ data: { session } }) => setSession(session));
    
    // Listen for anytime the user logs in or out
    supabase.auth.onAuthStateChange((_event, session) => setSession(session));
  }, []);

  useEffect(() => {
    if (!session) setMockPrefsApplied(false);
  }, [session]);

  // Apply degree/concentration hints from mock student_history (one-time per session)
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

  // DATA FETCHING
  useEffect(() => {
    if (session?.user?.id && session?.user?.email) {
      const userId = session.user.id;
      const userEmail = session.user.email;
      const q = new URLSearchParams({
        email: userEmail,
        degree: selectedDegree,
        concentration: selectedConcentration,
        max_schedule_variants: '16',
      });
      if (planningTermLabel.trim()) {
        q.set('term_label', planningTermLabel.trim());
      }
      fetch(`http://127.0.0.1:8000/api/dashboard/${userId}?${q.toString()}`)
        .then((res) => res.json())
        .then((data) => {
          setDashboardData(data);
          if (data?.mock_generated_schedule) {
            setGeneratedSchedule(data.mock_generated_schedule);
            setSelectedVariantIndex(0);
          }
        })
        .catch((err) => console.error('API Error:', err));
    }
  }, [session, selectedDegree, selectedConcentration, planningTermLabel]);

  const handleGenerateSchedule = async () => {
    if (!session?.user?.email) return;
    setGeneratorError('');
    setIsGenerating(true);

    try {
      const params = new URLSearchParams({
        email: session.user.email,
        degree: selectedDegree,
        concentration: selectedConcentration,
        max_credits: '15',
        max_schedule_variants: '16',
      });
      if (planningTermLabel.trim()) {
        params.set('term_label', planningTermLabel.trim());
      }

      const response = await fetch(`http://127.0.0.1:8000/api/schedule/generate?${params.toString()}`);
      if (!response.ok) {
        throw new Error('Failed to generate schedule.');
      }

      const data = await response.json();
      setGeneratedSchedule(data.schedule);
      setSelectedVariantIndex(0);
    } catch (err) {
      setGeneratorError(err.message || 'Unexpected error during generation.');
    } finally {
      setIsGenerating(false);
    }
  };

  // 3. FORM HANDLERS
  const handleLogin = async (e) => {
    e.preventDefault();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) alert(error.message);
  };

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

  const handleSignUp = async (e) => {
    e.preventDefault();
    const { error } = await supabase.auth.signUp({ email, password });
    if (error) alert(error.message);
    else alert("Success! Check your email to confirm your account.");
  };

  const semestersGrouped = useMemo(() => {
    const list = dashboardData?.history?.completed_courses;
    if (!list?.length) return [];
    return groupCompletedCoursesByTerm(list);
  }, [dashboardData?.history?.completed_courses]);

  // ==========================================
  // VIEW 1: THE LOGGED-OUT SCREEN (Login Page)
  // ==========================================
  if (!session) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-teal-900 text-white font-sans">
        <div className="flex items-center gap-4 mb-8">
          <img src="/ninerpath-logo.png" alt="NinerPath Logo" className="h-16 w-auto" />
          <h1 className="text-5xl font-extrabold tracking-tight">NinerPath</h1>
        </div>
        
        <form className="flex flex-col gap-5 bg-teal-800 p-10 rounded-xl shadow-2xl w-96 border border-teal-700">
          <h2 className="text-xl font-semibold text-center mb-2">Student Portal Login</h2>
          <input 
            type="email" 
            placeholder="Email (e.g., john@charlotte.edu)" 
            onChange={e => setEmail(e.target.value)} 
            className="p-3 text-black rounded shadow-inner focus:outline-none focus:ring-2 focus:ring-teal-500" 
          />
          <input 
            type="password" 
            placeholder="Password" 
            onChange={e => setPassword(e.target.value)} 
            className="p-3 text-black rounded shadow-inner focus:outline-none focus:ring-2 focus:ring-teal-500" 
          />
          <div className="flex flex-col gap-3 mt-4">
            <button onClick={handleLogin} className="bg-white text-teal-900 px-4 py-3 rounded font-bold hover:bg-gray-100 transition shadow">
              Log In
            </button>
            <button onClick={handleSignUp} className="bg-transparent border-2 border-white px-4 py-3 rounded font-semibold hover:bg-teal-700 transition">
              Create Account
            </button>
          </div>
        </form>
      </div>
    );
  }

  // ==========================================
  // VIEW 2: THE LOGGED-IN SCREEN (Dashboard)
  // ==========================================
  return (
    <div className="bg-gray-100 min-h-screen font-sans text-gray-900">
      
      {/* Top Navigation Bar */}
      <nav className="bg-teal-900 text-white p-4 shadow-lg flex justify-between items-center sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <img src="/ninerpath-logo.png" alt="NinerPath Logo" className="h-10 w-auto" />
          <h1 className="text-2xl font-bold tracking-wide">NinerPath Dashboard</h1>
        </div>
        <div className="flex items-center gap-6">
          <span className="text-sm font-medium bg-teal-800 px-3 py-1 rounded-full border border-teal-700">
            {session.user.email}
          </span>
          <button 
            onClick={() => supabase.auth.signOut()} 
            className="bg-red-500 hover:bg-red-600 text-white px-5 py-2 rounded font-bold transition shadow"
          >
            Sign Out
          </button>
        </div>
      </nav>

      {/* Main Content Area */}
      <div className="p-8 max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-8 mt-4">
        
        {/* LEFT COLUMN: Class History (From JSON Mock Data) */}
        <div className="bg-white p-8 rounded-xl shadow-md border-t-4 border-teal-700">
          <div className="flex justify-between items-end border-b-2 border-gray-100 pb-4 mb-6">
            <div>
              <h2 className="text-2xl font-bold text-gray-800">Academic History</h2>
              {dashboardData?.history?.display_name && (
                <p className="text-sm text-gray-500 mt-1">{dashboardData.history.display_name}</p>
              )}
            </div>
            {dashboardData?.history?.gpa > 0 && (
              <span className="text-teal-900 font-extrabold bg-teal-100 px-4 py-2 rounded-lg border border-teal-200 shadow-sm">
                Cumulative GPA: {dashboardData.history.gpa}
              </span>
            )}
          </div>
          
          {dashboardData ? (
            dashboardData.history.completed_courses.length > 0 ? (
              <div className="space-y-2">
                {semestersGrouped.map(({ term, courses, termGpa, termCredits }) => (
                  <details
                    key={term}
                    className="rounded-lg border border-gray-200 bg-gray-50 shadow-sm transition-shadow open:bg-white open:shadow-md open:[&_.semester-chevron]:rotate-90"
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-gray-900 hover:bg-gray-100/80 rounded-lg [&::-webkit-details-marker]:hidden">
                      <span className="flex min-w-0 flex-1 items-center gap-2">
                        <span
                          className="semester-chevron inline-flex h-6 w-6 shrink-0 items-center justify-center text-teal-700 transition-transform duration-200"
                          aria-hidden
                        >
                          ▸
                        </span>
                        <span className="truncate font-semibold">{term}</span>
                        <span className="shrink-0 text-sm font-normal text-gray-500">
                          {termCredits} cr
                        </span>
                      </span>
                      <span className="shrink-0 rounded-md border border-teal-200 bg-teal-50 px-3 py-1 text-sm font-bold text-teal-900">
                        {termGpa != null ? `Term GPA: ${termGpa.toFixed(2)}` : 'Term GPA: —'}
                      </span>
                    </summary>
                    <ul className="space-y-2 border-t border-gray-100 px-4 py-3">
                      {courses.map((course) => (
                        <li
                          key={`${term}-${course.id}`}
                          className="flex items-center justify-between gap-3 rounded-md border border-gray-100 bg-white px-3 py-2.5"
                        >
                          <div className="min-w-0">
                            <span className="font-bold text-gray-900">{course.id}</span>
                            <span className="ml-2 text-sm text-gray-500">
                              {creditsForCourse(course)} cr
                            </span>
                          </div>
                          <span className="shrink-0 font-bold text-teal-700">{course.grade}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            ) : (
              <div className="text-center py-10 bg-gray-50 rounded-lg border border-dashed border-gray-300">
                <p className="text-gray-500 font-medium">No course history found for this email.</p>
                <p className="text-sm text-gray-400 mt-1">
                  Try a mock profile: sarah@charlotte.edu, john@charlotte.edu, or jfoste81@charlotte.edu
                </p>
              </div>
            )
          ) : (
             <div className="animate-pulse flex space-x-4">
               <div className="flex-1 space-y-4 py-1">
                 <div className="h-4 bg-gray-200 rounded w-3/4"></div>
                 <div className="space-y-2">
                   <div className="h-4 bg-gray-200 rounded"></div>
                   <div className="h-4 bg-gray-200 rounded w-5/6"></div>
                 </div>
               </div>
             </div>
          )}
        </div>

        {/* RIGHT COLUMN: Upcoming Schedule (From PostgreSQL Database) */}
        <div className="bg-white p-8 rounded-xl shadow-md border-t-4 border-teal-700">
          <h2 className="text-2xl font-bold text-gray-800 border-b-2 border-gray-100 pb-4 mb-6">Saved Schedules</h2>
          
          {dashboardData ? (
             dashboardData.upcoming.length > 0 ? (
              <ul className="space-y-4">
                {dashboardData.upcoming.map((schedule) => (
                  <li key={schedule.id} className="p-4 bg-teal-50 rounded-lg border border-teal-200 hover:shadow-md transition cursor-pointer">
                    <div className="flex justify-between items-center">
                      <span className="font-bold text-teal-900 text-lg">Term: {schedule.term}</span>
                      <span className="text-teal-600 bg-white px-3 py-1 rounded text-sm font-bold shadow-sm border border-teal-100">View &rarr;</span>
                    </div>
                    <p className="text-sm text-gray-600 mt-2 font-medium">Status: Generated by NinerPath</p>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="py-8 bg-gray-50 rounded-lg border border-dashed border-gray-300">
                <p className="text-gray-600 font-medium mb-4 text-lg text-center">You haven't saved any schedules yet.</p>

                <div className="flex flex-col md:flex-row flex-wrap gap-3 justify-center items-center mb-4 px-4">
                  <select
                    value={planningTermLabel}
                    onChange={(e) => setPlanningTermLabel(e.target.value)}
                    className="border border-gray-300 rounded px-3 py-2 bg-white text-gray-700 max-w-xs"
                    aria-label="Semester to plan for"
                  >
                    <option value="">Calendar term (from today&apos;s date)</option>
                    <option value="Fall 2026">Fall 2026 (mock section list)</option>
                  </select>
                  <select
                    value={selectedDegree}
                    onChange={(e) => {
                      const d = e.target.value;
                      setSelectedDegree(d);
                      setSelectedConcentration(CONCENTRATIONS_BY_DEGREE[d][0].value);
                    }}
                    className="border border-gray-300 rounded px-3 py-2 bg-white text-gray-700 max-w-xs"
                  >
                    <option value="bs_computer_science">B.S. Computer Science</option>
                    <option value="ba_computer_science">B.A. Computer Science</option>
                  </select>
                  <select
                    value={selectedConcentration}
                    onChange={(e) => setSelectedConcentration(e.target.value)}
                    className="border border-gray-300 rounded px-3 py-2 bg-white text-gray-700 max-w-md"
                  >
                    {CONCENTRATIONS_BY_DEGREE[selectedDegree].map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={handleGenerateSchedule}
                    disabled={isGenerating}
                    className="bg-teal-700 hover:bg-teal-800 text-white font-bold py-3 px-6 rounded-lg shadow-md transition disabled:bg-gray-400"
                  >
                    {isGenerating ? 'Generating...' : 'Generate New Schedule'}
                  </button>
                </div>

                {generatorError && (
                  <p className="text-center text-red-600 text-sm mb-3">{generatorError}</p>
                )}

                {generatedSchedule && (
                  <div className="mx-4 mt-4 bg-white rounded-lg border border-teal-200 p-4">
                    <h3 className="font-bold text-teal-900 text-lg">
                      {(generatedSchedule.term_label || generatedSchedule.target_term)}{' '}
                      Recommendations ({generatedSchedule.generated_credits} credits)
                    </h3>
                    <p className="text-sm text-gray-600 mb-3">{generatedSchedule.concentration_label}</p>
                    {generatedSchedule.recommended_courses.length > 0 ? (
                      <>
                        <ul className="space-y-2">
                          {generatedSchedule.recommended_courses.map((course) => (
                            <li key={course.id} className="flex justify-between border-b border-gray-100 pb-2">
                              <span className="font-semibold text-gray-800">
                                {course.id}: {course.name}
                              </span>
                              <span className="text-sm text-gray-500">{course.credits} cr</span>
                            </li>
                          ))}
                        </ul>
                        {scheduleVariants.length > 0 ? (
                          <div className="mt-6 border-t border-teal-100 pt-4">
                            <p className="mb-2 text-sm font-semibold text-gray-800">
                              Weekly calendars ({scheduleVariants.length} conflict-free options)
                            </p>
                            {generatedSchedule.schedule_calendar_sections_term && (
                              <p className="mb-2 text-xs text-gray-500">
                                Demo meeting times from {generatedSchedule.schedule_calendar_sections_term}{' '}
                                mock catalog (illustrative).
                              </p>
                            )}
                            {Array.isArray(generatedSchedule.schedule_calendar_omitted_courses) &&
                              generatedSchedule.schedule_calendar_omitted_courses.length > 0 && (
                                <p className="mb-3 text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded px-2 py-1.5">
                                  Not drawn on the calendar (no mock section row for this course in the
                                  demo file):{' '}
                                  {generatedSchedule.schedule_calendar_omitted_courses.join(', ')}.
                                </p>
                              )}
                            <div className="mb-3 flex flex-wrap gap-2">
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
                          <div className="mt-4 space-y-2 text-sm text-gray-500">
                            <p>
                              No weekly calendar options were found: either there are no mock section
                              times for these courses, or every combination of demo sections has a time
                              conflict.
                            </p>
                            {Array.isArray(generatedSchedule.schedule_calendar_omitted_courses) &&
                              generatedSchedule.schedule_calendar_omitted_courses.length > 0 && (
                                <p className="text-xs text-gray-600">
                                  Missing demo sections for:{' '}
                                  {generatedSchedule.schedule_calendar_omitted_courses.join(', ')}.
                                </p>
                              )}
                          </div>
                        )}
                      </>
                    ) : (
                      <p className="text-sm text-gray-500">
                        No eligible classes were found for this term. Try another concentration or term.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )
          ) : (
             <div className="animate-pulse flex space-x-4">
               <div className="flex-1 space-y-4 py-1">
                 <div className="h-4 bg-gray-200 rounded w-3/4"></div>
                 <div className="space-y-2">
                   <div className="h-4 bg-gray-200 rounded"></div>
                   <div className="h-4 bg-gray-200 rounded w-5/6"></div>
                 </div>
               </div>
             </div>
          )}
        </div>

      </div>
    </div>
  );
}