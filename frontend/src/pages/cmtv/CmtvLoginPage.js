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

// 2026-10-01: "Remember this device" for the admin 2FA step (backend: cmtv_trusted_devices.py). The key stays in this browser.
const DEVICE_KEY = 'cmtv_2fa_device';
const deviceKey = () => { try { return localStorage.getItem(DEVICE_KEY) || ''; } catch { return ''; } };
const saveDeviceKey = (v) => { try { if (v) localStorage.setItem(DEVICE_KEY, v); else localStorage.removeItem(DEVICE_KEY); } catch { /* private mode */ } };
const deviceLabel = () => {
  const ua = navigator.userAgent || '';
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
  const os = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iPhone/iPad' : /Mac OS X/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : '';
  return os ? `${browser} on ${os}` : browser;
};

export default function CmtvLoginPage() {
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [requires2FA, setRequires2FA] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [rememberDevice, setRememberDevice] = useState(false);   // 2026-10-01: skip the 2FA code on this browser for 30 days
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
        if (deviceKey()) saveDeviceKey(null);   // the remembered device key no longer works (expired or removed)
        setRequires2FA(true);
        setError('');
      } else {
        if (response.data.device_token) saveDeviceKey(response.data.device_token);
        setAuth(response.data.user, response.data.access_token);
        const params = new URLSearchParams(window.location.search);
        const redirectTo = params.get('redirect');
        // CMTV 2026-09-28: signed in with a TV line login -> finish the account first (then back to where they were going)
        if (response.data.needs_email_link && response.data.user.role !== 'admin' && redirectTo !== '/link-email') {
          navigate(`/link-email${redirectTo ? `?redirect=${encodeURIComponent(redirectTo)}` : ''}`);
        } else if (redirectTo) {
          navigate(redirectTo);
        } else if (response.data.user.role === 'admin') {
          navigate('/admin');
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
    if (deviceKey()) loginData.device_token = deviceKey();
    if (requires2FA) {
      loginData.totp_code = totpCode;
      if (rememberDevice) { loginData.remember_device = true; loginData.device_label = deviceLabel(); }
    }
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
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 13.5, cursor: 'pointer' }}>
              <input type="checkbox" checked={rememberDevice} onChange={(e) => setRememberDevice(e.target.checked)} />
              Remember this device for 30 days
            </label>
            <p style={{ margin: '4px 0 0', fontSize: 12, opacity: 0.75 }}>Only on your own device. You'll still need your password.</p>
          </div>
        )}

        <button type="submit" className="ab-btn" disabled={loginMutation.isPending}>
          {loginMutation.isPending ? 'Signing in…' : requires2FA ? 'Verify and sign in' : 'Sign in'}
        </button>
      </form>

      {/* CMTV 2026-09-28: customers set up by hand can sign in with their TV login, then finish their account */}
      <p className="ab-alt">Already a customer but never used this website? Sign in with your TV app's <b>username</b> and <b>password</b>.</p>
      <p className="ab-alt">New to CMTV? <Link to="/register">Create an account</Link></p>
      <RecaptchaLegal enabled={recaptchaConfig?.enabled} />
    </AuthShell>
  );
}
