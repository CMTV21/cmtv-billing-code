// CMTV local addition 2026-09-26: CMTV-styled sign up page on /register. The logic is the developer's RegisterPage.js,
// unchanged (reCAPTCHA v3, ?ref= referral code, verification email, then /login?registered=true after 5 s).
import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AlertCircle, Gift } from 'lucide-react';
import { useGoogleReCaptcha } from 'react-google-recaptcha-v3';
import api, { authAPI } from '../../api/api';
import { AuthShell, Note, PasswordInput, RecaptchaLegal } from '../../components/cmtv/AuthShell';

export default function CmtvRegisterPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const referralCode = searchParams.get('ref') || '';
  const [formData, setFormData] = useState({ name: '', email: '', password: '', referral_code: referralCode });
  const [error, setError] = useState('');
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const { executeRecaptcha } = useGoogleReCaptcha();

  const { data: recaptchaConfig } = useQuery({
    queryKey: ['recaptcha-config'],
    queryFn: async () => (await api.get('/api/recaptcha/sitekey')).data,
  });

  const registerMutation = useMutation({
    mutationFn: (data) => authAPI.register(data),
    onSuccess: () => {
      setShowSuccessModal(true);
      setTimeout(() => navigate('/login?registered=true'), 5000);
    },
    onError: (err) => setError(err.response?.data?.detail || "Couldn't create the account"),
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    let recaptchaToken = '';
    if (recaptchaConfig?.enabled && executeRecaptcha) {
      try {
        recaptchaToken = await executeRecaptcha('register');
      } catch (err) {
        setError('reCAPTCHA check failed. Please refresh the page and try again.');
        return;
      }
    }
    registerMutation.mutate({ ...formData, recaptcha_token: recaptchaToken });
  };

  return (
    <AuthShell variant="signup">
      <h2>Create your account</h2>
      <p className="sub">Free to join. You only pay when you pick a plan.</p>

      {referralCode && (
        <Note kind="info"><Gift size={18} /><span>A friend invited you. Their referral code <b>{referralCode}</b> is already filled in below.</span></Note>
      )}
      {error && <Note kind="err"><AlertCircle size={18} /><span>{error}</span></Note>}

      <form onSubmit={handleSubmit}>
        <div className="ab-field">
          <label htmlFor="reg-name">Full name</label>
          <input id="reg-name" type="text" required autoComplete="name" value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })} placeholder="Jane Smith" />
        </div>
        <div className="ab-field">
          <label htmlFor="reg-email">Email</label>
          <input id="reg-email" type="email" required autoComplete="email" value={formData.email}
            onChange={(e) => setFormData({ ...formData, email: e.target.value })} placeholder="you@example.com" />
          <p className="hint">We'll send a link here to confirm it's you.</p>
        </div>
        <div className="ab-field">
          <label htmlFor="reg-password">Password</label>
          <PasswordInput id="reg-password" required minLength={6} autoComplete="new-password" value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })} placeholder="At least 6 characters" />
        </div>
        <div className="ab-field">
          <label htmlFor="reg-ref">Referral code <span style={{ fontWeight: 400, color: 'var(--faint)' }}>(optional)</span></label>
          <input id="reg-ref" type="text" value={formData.referral_code}
            onChange={(e) => setFormData({ ...formData, referral_code: e.target.value.toUpperCase() })} placeholder="From a friend" />
        </div>
        <button type="submit" className="ab-btn" disabled={registerMutation.isPending}>
          {registerMutation.isPending ? 'Creating your account…' : 'Create account'}
        </button>
      </form>

      <p className="ab-alt">Already with us? <Link to="/login">Sign in</Link></p>
      <RecaptchaLegal enabled={recaptchaConfig?.enabled} />

      {showSuccessModal && (
        <div className="ab-modal" role="dialog" aria-modal="true" aria-labelledby="reg-done">
          <div>
            <div className="big-tick" aria-hidden="true">✓</div>
            <h3 id="reg-done">Check your email</h3>
            <p>We sent a verification link to</p>
            <p className="email">{formData.email}</p>
            <p>Click it to activate your account, then sign in. It can take a minute, and sometimes lands in spam.</p>
            <p style={{ fontSize: 13, color: 'var(--faint)', marginTop: 14 }}>Taking you to sign in…</p>
          </div>
        </div>
      )}
    </AuthShell>
  );
}
