import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { KeyRound, AlertCircle, CheckCircle2, ArrowLeft } from 'lucide-react';
import { useGoogleReCaptcha } from 'react-google-recaptcha-v3';
import { authAPI } from '../api/api';
import { AuthShell, authInputCls, formatApiError } from '../components/AuthShell';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const { executeRecaptcha } = useGoogleReCaptcha();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      let recaptcha_token = '';
      if (executeRecaptcha) {
        try { recaptcha_token = await executeRecaptcha('forgot_password'); } catch (_) { /* recaptcha optional */ }
      }
      await authAPI.forgotPassword({ email: email.trim(), recaptcha_token });
      setSent(true);
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail, 'Something went wrong. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell icon={KeyRound} title="Forgot Password" subtitle="Enter your email or username and we'll send you a reset link">
      {sent ? (
        <div className="space-y-6" data-testid="forgot-password-success">
          <div className="p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-green-800 dark:text-green-300">
              If an account exists for <span className="font-semibold">{email}</span>, a password reset link is on its way. Check your inbox and spam folder — the link expires in 60 minutes.
            </p>
          </div>
          <button type="button" onClick={() => { setSent(false); setError(''); }} className="w-full text-sm text-blue-600 hover:text-blue-700 font-semibold" data-testid="forgot-password-try-again">
            Didn't get it? Send again
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-6" data-testid="forgot-password-form">
          {error && (
            <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3" data-testid="forgot-password-error">
              <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Email Address or Username</label>
            <input type="text" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} className={authInputCls}
              placeholder="you@example.com or username" data-testid="forgot-password-email" />
          </div>
          <button type="submit" disabled={loading}
            className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
            data-testid="forgot-password-submit">
            {loading ? 'Sending…' : 'Send Reset Link'}
          </button>
        </form>
      )}
      <div className="mt-6 text-center">
        <Link to="/login" className="inline-flex items-center gap-1.5 text-blue-600 hover:text-blue-700 font-semibold text-sm" data-testid="back-to-login-link">
          <ArrowLeft className="w-4 h-4" /> Back to sign in
        </Link>
      </div>
    </AuthShell>
  );
}
