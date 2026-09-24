import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { authAPI } from '../api/api';
import { useBrandingStore } from '../store/branding';
import { KeyRound, Server, AlertCircle } from 'lucide-react';

// CMTV local change 2026-09-24: landing page for the link in the password reset email
export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const { branding } = useBrandingStore();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState(token ? '' : 'This reset link is missing its token. Please use the link from your email, or request a new one.');
  const [saving, setSaving] = useState(false);
  const [account, setAccount] = useState(null); // { email: 'jo***@gmail.com', username } once the link is checked

  // Check the link first and show which account it's for, so the customer knows they're resetting the right one
  useEffect(() => {
    if (!token) return;
    authAPI.checkResetToken(token)
      .then((response) => setAccount(response.data))
      .catch((err) => setError(err.response?.data?.detail || 'This reset link is invalid or has expired. Please request a new one.'));
  }, [token]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setSaving(true);
    try {
      await authAPI.resetPassword({ token, new_password: password });
      navigate('/login?message=password_reset');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to reset password. Please try again.');
    }
    setSaving(false);
  };

  const inputClass = "w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500";

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800 flex flex-col">
      {/* Header */}
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/" className="flex items-center gap-2">
            {branding.logo_url ? (
              <img src={branding.logo_url} alt={branding.site_name} className="h-8" />
            ) : (
              <Server className="w-8 h-8" style={{ color: branding.primary_color }} />
            )}
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{branding.site_name}</h1>
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="max-w-md w-full">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl p-8">
            <div className="text-center mb-8">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-full mb-4">
                <KeyRound className="w-8 h-8 text-blue-600" />
              </div>
              <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">Choose a New Password</h2>
              <p className="text-gray-600 mt-2">Enter a new password for your account.</p>
            </div>

            {account && (
              <div className="mb-6 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg text-sm text-blue-900 dark:text-blue-200">
                <p className="mb-1">You're resetting the password for:</p>
                {account.username && <p><span className="font-semibold">Username:</span> {account.username}</p>}
                <p><span className="font-semibold">Email:</span> {account.email}</p>
                <p className="mt-2 text-xs text-blue-800 dark:text-blue-300">
                  This changes your sign-in for this website only. Your TV line / app login stays the same.
                  Not your account? Don't continue; close this page.
                </p>
              </div>
            )}

            {error && (
              <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-800 dark:text-red-300">
                  {error}{' '}
                  {(error.includes('expired') || error.includes('missing')) && (
                    <Link to="/forgot-password" className="underline font-semibold">Request a new link</Link>
                  )}
                </p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  New Password
                </label>
                <input
                  type="password"
                  required
                  minLength={6}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={inputClass}
                  placeholder="••••••••"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Confirm New Password
                </label>
                <input
                  type="password"
                  required
                  minLength={6}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className={inputClass}
                  placeholder="••••••••"
                />
              </div>

              <button
                type="submit"
                disabled={saving || !account}
                className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                {saving ? 'Saving...' : 'Reset Password'}
              </button>
            </form>

            <div className="mt-6 text-center">
              <Link to="/login" className="text-blue-600 hover:text-blue-700 font-semibold">
                Back to sign in
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
