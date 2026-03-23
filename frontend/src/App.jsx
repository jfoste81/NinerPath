import { useState, useEffect } from 'react';
import { supabase } from './supabaseClient';

export default function App() {
  const [session, setSession] = useState(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [dashboardData, setDashboardData] = useState(null);

  // AUTHENTICATION LISTENER
  useEffect(() => {
    // Check if the user is already logged in when the page loads
    supabase.auth.getSession().then(({ data: { session } }) => setSession(session));
    
    // Listen for anytime the user logs in or out
    supabase.auth.onAuthStateChange((_event, session) => setSession(session));
  }, []);

  // DATA FETCHING 
  useEffect(() => {
    // Only try to fetch data if the user is actively logged in
    if (session?.user?.id && session?.user?.email) {
      const userId = session.user.id;
      const userEmail = session.user.email;
      
      // Call Python FastAPI Backend
      fetch(`http://127.0.0.1:8000/api/dashboard/${userId}?email=${userEmail}`)
        .then(res => res.json())
        .then(data => setDashboardData(data))
        .catch(err => console.error("API Error:", err));
    }
  }, [session]);

  // 3. FORM HANDLERS
  const handleLogin = async (e) => {
    e.preventDefault();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) alert(error.message);
  };

  const handleSignUp = async (e) => {
    e.preventDefault();
    const { error } = await supabase.auth.signUp({ email, password });
    if (error) alert(error.message);
    else alert("Success! Check your email to confirm your account.");
  };

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
            placeholder="Email (e.g., sarah@uncc.edu)" 
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
            <h2 className="text-2xl font-bold text-gray-800">Academic History</h2>
            {dashboardData?.history?.gpa > 0 && (
              <span className="text-teal-900 font-extrabold bg-teal-100 px-4 py-2 rounded-lg border border-teal-200 shadow-sm">
                Cumulative GPA: {dashboardData.history.gpa}
              </span>
            )}
          </div>
          
          {dashboardData ? (
            dashboardData.history.completed_courses.length > 0 ? (
              <ul className="space-y-4">
                {dashboardData.history.completed_courses.map((course, idx) => (
                  <li key={idx} className="flex justify-between items-center p-4 bg-gray-50 rounded-lg border border-gray-200 hover:shadow-sm transition">
                    <div>
                      <span className="font-bold text-gray-900 block text-lg">{course.id}</span>
                      <span className="text-sm text-gray-500 font-medium">{course.term}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-gray-400">Grade:</span>
                      <span className="font-bold text-teal-700 text-xl">{course.grade}</span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-center py-10 bg-gray-50 rounded-lg border border-dashed border-gray-300">
                <p className="text-gray-500 font-medium">No course history found for this email.</p>
                <p className="text-sm text-gray-400 mt-1">Make sure you used an email from the mock JSON data.</p>
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
              <div className="text-center py-12 bg-gray-50 rounded-lg border border-dashed border-gray-300 flex flex-col items-center">
                <p className="text-gray-600 font-medium mb-6 text-lg">You haven't saved any schedules yet.</p>
                <button className="bg-teal-700 hover:bg-teal-800 text-white font-bold py-3 px-6 rounded-lg shadow-md transition transform hover:-translate-y-0.5">
                  Generate New Schedule
                </button>
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