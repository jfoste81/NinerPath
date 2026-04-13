import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { supabase } from './supabaseClient';
import DegreeHomePage from './pages/DegreeHomePage';
import SchedulePage from './pages/SchedulePage';

export default function App() {
  const [session, setSession] = useState(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session: s } }) => setSession(s));
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      if (event === 'SIGNED_OUT') {
        setEmail('');
        setPassword('');
      }
    });
    return () => subscription.unsubscribe();
  }, []);

  const handleLogin = async (e) => {
    e?.preventDefault?.();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) alert(error.message);
  };

  const handleSignUp = async (e) => {
    e.preventDefault();
    const { error } = await supabase.auth.signUp({ email, password });
    if (error) alert(error.message);
    else alert('Success! Check your email to confirm your account.');
  };

  const onSignOut = () => supabase.auth.signOut();

  if (!session) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-teal-900 text-white font-sans">
        <div className="flex items-center gap-4 mb-8">
          <img src="/ninerpath-logo.png" alt="NinerPath Logo" className="h-16 w-auto" />
          <h1 className="text-5xl font-extrabold tracking-tight">NinerPath</h1>
        </div>

        <form
          className="flex flex-col gap-5 bg-teal-800 p-10 rounded-xl shadow-2xl w-96 border border-teal-700"
          onSubmit={handleLogin}
        >
          <h2 className="text-xl font-semibold text-center mb-2">Student Portal Login</h2>
          <input
            type="email"
            placeholder="Email (e.g., john@charlotte.edu)"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="p-3 text-black rounded shadow-inner focus:outline-none focus:ring-2 focus:ring-teal-500"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="p-3 text-black rounded shadow-inner focus:outline-none focus:ring-2 focus:ring-teal-500"
          />
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