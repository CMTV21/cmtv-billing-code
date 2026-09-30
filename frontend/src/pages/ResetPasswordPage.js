import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { LockKeyhole, AlertCircle, CheckCircle2, Eye, EyeOff, Loader2 } from 'lucide-react';
import { authAPI } from '../api/api';
import { AuthShell, authInputCls, formatApiError } from '../components/AuthShell';

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') || '';
  const [tokenState, setTokenState] = useState({ checking: true, valid: false, emailHint: '' });
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) { setTokenState({ checking: false, valid: false, emailHint: '' }); return; }
    authAPI.validateResetToken(token)
      .then((res) => setTokenState({ checking: false, valid: !!res.data.valid, emailHint: res.data.email_hint || '' }))
      .catch(() => setTokenState({ checking: false, valid: false, emailHint: '' }));
  }, [token]);

  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => navigate('/login?message=password_reset'), 3000);
    return () => clearTimeout(t);
  }, [done, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (password.length < 6) { setError('Password must be at least 6 characters.'); return; }
    if (password !== confirm) { setError('Passwords do not match.'); return; }
    setLoading(true);
    try {
      await authAPI.resetPassword({ token, new_password: password });
      setDone(true);
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail, 'Could not reset password. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  const invalidView = (
    <div className="space-y-6" data-testid="reset-password-invalid">
      <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
        <p className="text-sm text-red-800 dark:text-red-300">This password reset link is invalid or has expired. Reset links are valid for 60 minutes and can only be used once.</p>
      </div>
      <Link to="/forgot-password" className="block w-full text-center bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 transition" data-testid="request-new-link-btn">
        Request a new link
      </Link>
    </div>
  );

  const successView = (
    <div className="space-y-6" data-testid="reset-password-success">
      <div className="p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg flex items-start gap-3">
        <CheckCircle2 className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
        <p className="text-sm text-green-800 dark:text-green-300">Your password has been reset. Redirecting you to sign in…</p>
      </div>
      <Link to="/login" className="block w-full text-center bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 transition" data-testid="go-to-login-btn">
        Sign in now
      </Link>
    </div>
  );

  const formView = (
    <form onSubmit={handleSubmit} className="space-y-6" data-testid="reset-password-form">
      {tokenState.emailHint && (
        <p className="text-sm text-gray-600 dark:text-gray-400 text-center -mt-4">Resetting password for <span className="font-semibold">{tokenState.emailHint}</span></p>
      )}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3" data-testid="reset-password-error">
          <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
        </div>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">New Password</label>
        <div className="relative">
          <input type={show ? 'text' : 'password'} required minLength={6} autoFocus value={password} onChange={(e) => setPassword(e.target.value)}
            className={`${authInputCls} pr-12`} placeholder="At least 6 characters" data-testid="reset-password-new" />
          <button type="button" onClick={() => setShow(!show)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600" data-testid="toggle-password-visibility" aria-label="Toggle password visibility">
            {show ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
          </button>
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Confirm New Password</label>
        <input type={show ? 'text' : 'password'} required minLength={6} value={confirm} onChange={(e) => setConfirm(e.target.value)}
          className={authInputCls} placeholder="Repeat your new password" data-testid="reset-password-confirm" />
      </div>
      <button type="submit" disabled={loading}
        className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        data-testid="reset-password-submit">
        {loading ? 'Updating…' : 'Set New Password'}
      </button>
    </form>
  );

  return (
    <AuthShell icon={LockKeyhole} title="Reset Password" subtitle={tokenState.valid && !done ? 'Choose a new password for your account' : ''}>
      {tokenState.checking ? (
        <div className="flex justify-center py-6" data-testid="reset-password-checking"><Loader2 className="w-8 h-8 text-blue-600 animate-spin" /></div>
      ) : done ? successView : tokenState.valid ? formView : invalidView}
      {!done && (
        <div className="mt-6 text-center">
          <Link to="/login" className="text-blue-600 hover:text-blue-700 font-semibold text-sm" data-testid="reset-back-to-login-link">Back to sign in</Link>
        </div>
      )}
    </AuthShell>
  );
}
