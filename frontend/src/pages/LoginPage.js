import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { authAPI } from '../api/api';
import { useAuthStore } from '../store/store';
import { useBrandingStore } from '../store/branding';
import { LogIn, Server, AlertCircle, Shield, Mail } from 'lucide-react';
import { useGoogleReCaptcha } from 'react-google-recaptcha-v3';
import Header from '../components/Header';
import PrimaryButton from '../components/PrimaryButton';
import api from '../api/api';

export default function LoginPage() {
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();
  const { branding } = useBrandingStore();
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [requires2FA, setRequires2FA] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [showResendVerification, setShowResendVerification] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [resending, setResending] = useState(false);
  const { executeRecaptcha } = useGoogleReCaptcha();

  // Fetch reCAPTCHA configuration
  const { data: recaptchaConfig } = useQuery({
    queryKey: ['recaptcha-config'],
    queryFn: async () => {
      const response = await api.get('/api/recaptcha/sitekey');
      return response.data;
    },
  });

  // Check URL parameters for messages
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('message') === 'email_verified') {
      setSuccessMessage('✅ Email verified successfully! You can now log in.');
    } else if (params.get('registered') === 'true') {
      setSuccessMessage('📧 Registration successful! Please check your email to verify your account.');
    } else if (params.get('message') === 'password_reset') {
      setSuccessMessage('✅ Password reset! You can now sign in with your new password.');
    } else if (params.get('error') === 'invalid_token') {
      setError('Invalid or expired verification link. Please request a new one.');
    }
  }, []);

  const loginMutation = useMutation({
    mutationFn: (data) => authAPI.login(data),
    onSuccess: (response) => {
      if (response.data.requires_2fa) {
        setRequires2FA(true);
        setError('');
      } else {
        setAuth(response.data.user, response.data.access_token);
        const params = new URLSearchParams(window.location.search);
        const redirectTo = params.get('redirect');
        if (redirectTo) {
          navigate(redirectTo);
        } else if (response.data.user.role === 'admin') {
          navigate('/admin');
        } else if (response.data.needs_email_link) {
          navigate('/link-email');
        } else {
          navigate('/dashboard');
        }
      }
    },
    onError: (error) => {
      const status = error.response?.status;
      const detail = error.response?.data?.detail || 'Login failed';
      setError(detail);
      if (status === 403 && detail.toLowerCase().includes('not verified')) {
        setShowResendVerification(true);
      }
    },
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    
    let recaptchaToken = '';
    
    // Execute reCAPTCHA v3 (invisible)
    if (recaptchaConfig?.enabled && executeRecaptcha) {
      try {
        recaptchaToken = await executeRecaptcha('login');
      } catch (err) {
        setError('reCAPTCHA verification failed. Please refresh and try again.');
        return;
      }
    }
    
    const loginData = {
      ...formData,
      recaptcha_token: recaptchaToken,
    };
    
    if (requires2FA) {
      loginData.totp_code = totpCode;
    }
    
    loginMutation.mutate(loginData);
  };

  const handleResendVerification = async () => {
    setResending(true);
    setError('');
    try {
      const response = await api.post('/api/auth/resend-verification', {
        email: formData.email,
        password: formData.password,
        new_email: newEmail || null
      });
      setSuccessMessage(response.data.message);
      setShowResendVerification(false);
      setNewEmail('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to resend verification email');
    }
    setResending(false);
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
                <LogIn className="w-8 h-8 text-blue-600" />
              </div>
              <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">Welcome Back</h2>
              <p className="text-gray-600 mt-2">Sign in to your account</p>
            </div>

            {successMessage && (
              <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3">
                <svg className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <p className="text-sm text-green-800">{successMessage}</p>
              </div>
            )}

            {error && (
              <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
              </div>
            )}

            {/* Resend Verification Email */}
            {showResendVerification && (
              <div className="mb-4 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
                <div className="flex items-center gap-2 mb-3">
                  <Mail className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                  <h4 className="font-semibold text-amber-900 dark:text-amber-200 text-sm">Resend Verification Email</h4>
                </div>
                <p className="text-sm text-amber-800 dark:text-amber-300 mb-3">
                  Didn't receive the email? You can resend it or update your email address below.
                </p>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-amber-800 dark:text-amber-300 mb-1">
                      Change email address (optional)
                    </label>
                    <input
                      type="email"
                      value={newEmail}
                      onChange={(e) => setNewEmail(e.target.value)}
                      placeholder={formData.email || 'Enter new email address'}
                      className="w-full px-3 py-2 text-sm border border-amber-300 dark:border-amber-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={handleResendVerification}
                    disabled={resending}
                    className="w-full flex items-center justify-center gap-2 bg-amber-600 text-white py-2 rounded-lg hover:bg-amber-700 text-sm font-semibold disabled:opacity-50"
                  >
                    <Mail className="w-4 h-4" />
                    {resending ? 'Sending...' : 'Resend Verification Email'}
                  </button>
                </div>
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
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                  placeholder="you@example.com or username"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Password
                  </label>
                  <Link to="/forgot-password" className="text-sm text-blue-600 hover:text-blue-700 font-medium">
                    Forgot password?
                  </Link>
                </div>
                <input
                  type="password"
                  required
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
                  placeholder="••••••••"
                />
              </div>

              {/* 2FA Code Input (if required) */}
              {requires2FA && (
                <div className="space-y-3 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
                  <div className="flex items-center gap-2">
                    <Shield className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                    <h3 className="font-semibold text-gray-900 dark:text-white">Two-Factor Authentication</h3>
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Enter the 6-digit code from Google Authenticator
                  </p>
                  <input
                    type="text"
                    maxLength="6"
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.replace(/[^0-9]/g, ''))}
                    placeholder="000000"
                    className="w-full text-center text-3xl font-mono tracking-widest px-4 py-4 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                    autoFocus
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={loginMutation.isPending}
                className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                {loginMutation.isPending ? 'Signing in...' : requires2FA ? 'Verify & Sign In' : 'Sign In'}
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
                Don't have an account?{' '}
                <Link to="/register" className="text-blue-600 hover:text-blue-700 font-semibold">
                  Sign up
                </Link>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
