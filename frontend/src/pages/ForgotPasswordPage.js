import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { authAPI } from '../api/api';
import { useBrandingStore } from '../store/branding';
import { KeyRound, Server, AlertCircle } from 'lucide-react';
import { useGoogleReCaptcha } from 'react-google-recaptcha-v3';
import api from '../api/api';

// CMTV local change 2026-09-24: "Forgot password" - asks the backend to email a reset link
export default function ForgotPasswordPage() {
  const { branding } = useBrandingStore();
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [sending, setSending] = useState(false);
  const { executeRecaptcha } = useGoogleReCaptcha();

  const { data: recaptchaConfig } = useQuery({
    queryKey: ['recaptcha-config'],
    queryFn: async () => {
      const response = await api.get('/api/recaptcha/sitekey');
      return response.data;
    },
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');

    let recaptchaToken = '';
    if (recaptchaConfig?.enabled && executeRecaptcha) {
      try {
        recaptchaToken = await executeRecaptcha('forgot_password');
      } catch (err) {
        setError('reCAPTCHA verification failed. Please refresh and try again.');
        return;
      }
    }

    setSending(true);
    try {
      const response = await authAPI.forgotPassword({ email, recaptcha_token: recaptchaToken });
      setSuccessMessage(response.data.message);
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    }
    setSending(false);
  };

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
              <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">Forgot Password</h2>
              <p className="text-gray-600 mt-2">Enter your email or username and we'll email you a link to reset your password.</p>
            </div>

            {successMessage && (
              <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3">
                <svg className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <p className="text-sm text-green-800">{successMessage} Don't forget to check your spam folder.</p>
              </div>
            )}

            {error && (
              <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Email Address or Username
                </label>
                <input
                  type="text"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                  placeholder="you@example.com or username"
                />
              </div>

              <button
                type="submit"
                disabled={sending}
                className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                {sending ? 'Sending...' : 'Send Reset Link'}
              </button>
            </form>

            {recaptchaConfig?.enabled && (
              <p className="mt-4 text-xs text-gray-500 text-center">
                Protected by reCAPTCHA v3. Google{' '}
                <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer" className="underline">Privacy Policy</a> and{' '}
                <a href="https://policies.google.com/terms" target="_blank" rel="noopener noreferrer" className="underline">Terms</a> apply.
              </p>
            )}

            <div className="mt-6 text-center">
              <p className="text-gray-600 dark:text-gray-400">
                Remembered it?{' '}
                <Link to="/login" className="text-blue-600 hover:text-blue-700 font-semibold">
                  Back to sign in
                </Link>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
