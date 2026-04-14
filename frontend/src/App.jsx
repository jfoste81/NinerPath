import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { supabase } from './supabaseClient';
import DegreeHomePage from './pages/DegreeHomePage';
import SchedulePage from './pages/SchedulePage';

function formatLoginError(error) {
  if (!error) return null;
  const code = String(error.code || '').toLowerCase();
  const msg = String(error.message || '').toLowerCase();

  if (code === 'email_not_confirmed' || msg.includes('email not confirmed')) {
    return 'Please confirm your email before signing in. Check your inbox for the link.';
  }
  if (
    code === 'user_not_found' ||
    code === 'user_not_found_error' ||
    msg.includes('user not found') ||
    msg.includes('no user found')
  ) {
    return 'No account found for this email. Create an account or check the address you entered.';
  }
  if (
    code === 'invalid_login_credentials' ||
    code === 'invalid_credentials' ||
    code === 'invalid_grant' ||
    msg.includes('invalid login credentials') ||
    msg.includes('invalid credentials')
  ) {
    return 'No account found for this email, or the password is wrong. Please try again.';
  }
  if (code === 'too_many_requests' || msg.includes('too many requests') || msg.includes('rate limit')) {
    return 'Too many sign-in attempts. Please wait a moment and try again.';
  }
  return error.message || 'Something went wrong. Please try again.';
}

const MOCK_STUDENT_PASSWORD = 'Testing123!';

const MOCK_STUDENT_DEMOS = [
  {
    email: 'sarah@charlotte.edu',
    name: 'Sarah Thompson',
    description: 'Freshman B.S. Computer Science student (Systems & Networks)',
  },
  {
    email: 'john@charlotte.edu',
    name: 'John Doe',
    description: 'Junior B.S. Computer Science student (Data Science)',
  },
  {
    email: 'emily@charlotte.edu',
    name: 'Emily Chen',
    description: 'Sophomore B.A. Computer Science student (Bioinformatics)',
  },
  {
    email: 'marcus@charlotte.edu',
    name: 'Marcus Johnson',
    description: 'Junior B.A. Computer Science student (Information Technology)',
  },
];

export default function App() {
  const [session, setSession] = useState(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState(null);

  useEffect(() => {
    document.title = "NinerPath | Login";
  }, []);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session: s } }) => setSession(s));
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      if (event === 'SIGNED_OUT') {
        setEmail('');
        setPassword('');
        setLoginError(null);
      }
    });
    return () => subscription.unsubscribe();
  }, []);

  const handleLogin = async (e) => {
    e?.preventDefault?.();
    setLoginError(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) setLoginError(formatLoginError(error));
  };

  const handleSignUp = async (e) => {
    e.preventDefault();
    const { error } = await supabase.auth.signUp({ email, password });
    if (error) alert(error.message);
    else alert('Success! Check your email to confirm your account.');
  };

  const onSignOut = () => supabase.auth.signOut();

  const applyMockStudent = (demoEmail) => {
    setEmail(demoEmail);
    setPassword(MOCK_STUDENT_PASSWORD);
    setLoginError(null);
  };

  if (!session) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-teal-900 text-white font-sans px-4 py-10">
        <div className="flex items-center gap-4 mb-8">
          <img src="/ninerpath-logo.png" alt="NinerPath Logo" className="h-16 w-auto" />
          <h1 className="text-5xl font-extrabold tracking-tight">NinerPath</h1>
        </div>

        <div className="flex flex-col lg:flex-row items-stretch gap-8 w-full max-w-4xl justify-center">
          <form
            className="flex flex-col gap-5 bg-teal-800 p-10 rounded-xl shadow-2xl flex-1 min-w-0 max-w-md mx-auto lg:mx-0 border border-teal-700"
            onSubmit={handleLogin}
          >
            <h2 className="text-xl font-semibold text-center mb-2">Student Portal Login</h2>
            <input
              type="email"
              placeholder="Email (e.g., john@charlotte.edu)"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setLoginError(null);
              }}
              className="p-3 text-black rounded shadow-inner focus:outline-none focus:ring-2 focus:ring-teal-500"
              autoComplete="email"
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setLoginError(null);
              }}
              className="p-3 text-black rounded shadow-inner focus:outline-none focus:ring-2 focus:ring-teal-500"
              autoComplete="current-password"
            />
            {loginError ? (
              <p
                className="text-sm text-red-200 bg-red-950/60 border border-red-400/50 rounded-lg px-3 py-2"
                role="alert"
              >
                {loginError}
              </p>
            ) : null}
            <div className="flex flex-col gap-3 mt-4">
              <button
                type="submit"
                className="bg-white text-teal-900 px-4 py-3 rounded font-bold hover:bg-gray-100 transition shadow"
              >
                Log In
              </button>
              <button
                type="button"
                onClick={handleSignUp}
                className="bg-transparent border-2 border-white px-4 py-3 rounded font-semibold hover:bg-teal-700 transition"
              >
                Create Account
              </button>
            </div>
          </form>

          <aside
            className="flex flex-col gap-4 bg-teal-800/90 p-8 rounded-xl shadow-xl flex-1 min-w-0 max-w-md mx-auto lg:mx-0 border border-teal-600"
            aria-labelledby="demo-accounts-heading"
          >
            <h2 id="demo-accounts-heading" className="text-lg font-semibold text-teal-100">
              Demo student accounts
            </h2>
            <p className="text-sm text-teal-100/90 leading-relaxed">
              Use these mock profiles to explore the app. The password for every demo student is{' '}
              <span className="font-mono font-semibold text-white">{MOCK_STUDENT_PASSWORD}</span>.
            </p>
            <ul className="flex flex-col gap-4 text-sm">
              {MOCK_STUDENT_DEMOS.map((demo) => (
                <li
                  key={demo.email}
                  className="rounded-lg border border-teal-600/80 bg-teal-900/40 p-3 text-teal-50/95"
                >
                  <div className="font-medium text-white">{demo.name}</div>
                  <div className="text-teal-200/90 text-xs font-mono mt-0.5 break-all">{demo.email}</div>
                  <p className="mt-2 text-teal-100/90 leading-snug">{demo.description}</p>
                  <button
                    type="button"
                    onClick={() => applyMockStudent(demo.email)}
                    className="mt-3 w-full text-center text-xs font-semibold uppercase tracking-wide bg-teal-700 hover:bg-teal-600 text-white py-2 rounded border border-teal-500/50 transition"
                  >
                    Fill login form
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DegreeHomePage session={session} onSignOut={onSignOut} />} />
        <Route path="/schedule" element={<SchedulePage session={session} onSignOut={onSignOut} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}