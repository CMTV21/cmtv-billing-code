// CMTV local addition 2026-09-26: CMTV-styled sign in page on /login. The logic is the developer's LoginPage.js,
// unchanged (reCAPTCHA v3, admin 2FA step, redirects, resend verification); LoginPage.js is still there, unused.
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AlertCircle, CheckCircle2, Mail, Shield } from 'lucide-react';
import { useGoogleReCaptcha } from 'react-google-recaptcha-v3';
import api, { authAPI } from '../../api/api';
import { useAuthStore } from '../../store/store';
import { AuthShell, Note, PasswordInput, RecaptchaLegal } from '../../components/cmtv/AuthShell';

export default function CmtvLoginPage() {
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [requires2FA, setRequires2FA] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [showResendVerification, setShowResendVerification] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [resending, setResending] = useState(false);
  const { executeRecaptcha } = useGoogleReCaptcha();

  const { data: recaptchaConfig } = useQuery({
    queryKey: ['recaptcha-config'],
    queryFn: async () => (await api.get('/api/recaptcha/sitekey')).data,
  });

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('message') === 'email_verified') {
      setSuccessMessage('Email verified. You can sign in now.');
    } else if (params.get('registered') === 'true') {
      setSuccessMessage('Account created. Check your email (and spam folder) for the link to verify it, then sign in.');
    } else if (params.get('message') === 'password_reset') {
      setSuccessMessage('Password changed. Sign in with your new password.');
    } else if (params.get('error') === 'invalid_token') {
      setError('That verification link is invalid or has expired. Sign in below to get a new one.');
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
    onError: (err) => {
      const status = err.response?.status;
      const detail = err.response?.data?.detail || 'Sign in failed';
      setError(detail);
      if (status === 403 && String(detail).toLowerCase().includes('not verified')) {
        setShowResendVerification(true);
      }
    },
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    let recaptchaToken = '';
    if (recaptchaConfig?.enabled && executeRecaptcha) {
      try {
        recaptchaToken = await executeRecaptcha('login');
      } catch (err) {
        setError('reCAPTCHA check failed. Please refresh the page and try again.');
        return;
      }
    }
    const loginData = { ...formData, recaptcha_token: recaptchaToken };
    if (requires2FA) loginData.totp_code = totpCode;
    loginMutation.mutate(loginData);
  };

  const handleResendVerification = async () => {
    setResending(true);
    setError('');
    try {
      const response = await api.post('/api/auth/resend-verification', {
        email: formData.email, password: formData.password, new_email: newEmail || null,
      });
      setSuccessMessage(response.data.message);
      setShowResendVerification(false);
      setNewEmail('');
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't resend the verification email");
    }
    setResending(false);
  };

  return (
    <AuthShell variant="signin">
      <h2>Sign in</h2>
      <p className="sub">Good to see you again.</p>

      {successMessage && <Note kind="ok"><CheckCircle2 size={18} /><span>{successMessage}</span></Note>}
      {error && <Note kind="err"><AlertCircle size={18} /><span>{error}</span></Note>}

      {showResendVerification && (
        <div className="ab-note warn">
          <h4><Mail size={16} /> Didn't get the verification email?</h4>
          <p>We can send it again. If you signed up with the wrong address, enter the right one here first.</p>
          <input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)}
            placeholder={formData.email || 'New email address (optional)'} aria-label="New email address (optional)" />
          <button type="button" className="ab-btn" onClick={handleResendVerification} disabled={resending}>
            {resending ? 'Sending…' : 'Send it again'}
          </button>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="ab-field">
          <label htmlFor="login-email">Email or username</label>
          <input id="login-email" type="text" required autoComplete="username" value={formData.email}
            onChange={(e) => setFormData({ ...formData, email: e.target.value })} placeholder="you@example.com" />
        </div>
        <div className="ab-field">
          <div className="ab-labelrow"><label htmlFor="login-password" style={{ margin: 0 }}>Password</label><Link to="/forgot-password">Forgot password?</Link></div>
          <PasswordInput id="login-password" required autoComplete="current-password" value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })} placeholder="Your password" />
        </div>

        {requires2FA && (
          <div className="ab-2fa">
            <h3><Shield size={16} /> Two-step code</h3>
            <p>Enter the 6-digit code from your authenticator app.</p>
            <input type="text" inputMode="numeric" autoComplete="one-time-code" maxLength="6" value={totpCode}
              onChange={(e) => setTotpCode(e.target.value.replace(/[^0-9]/g, ''))} placeholder="000000" aria-label="6-digit code" autoFocus />
          </div>
        )}

        <button type="submit" className="ab-btn" disabled={loginMutation.isPending}>
          {loginMutation.isPending ? 'Signing in…' : requires2FA ? 'Verify and sign in' : 'Sign in'}
        </button>
      </form>

      <p className="ab-alt">New to CMTV? <Link to="/register">Create an account</Link></p>
      <RecaptchaLegal enabled={recaptchaConfig?.enabled} />
    </AuthShell>
  );
}
