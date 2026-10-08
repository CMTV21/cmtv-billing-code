import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { authAPI } from '../api/api';
import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { useGoogleReCaptcha } from 'react-google-recaptcha-v3';
import api from '../api/api';
import { AuthShell, Note, RecaptchaLegal, HUMAN_MSG, HumanCheckHelp, humanOr } from '../components/cmtv/AuthShell';

// CMTV local change 2026-09-24: "Forgot password" - asks the backend to email a reset link
// CMTV local change 2026-09-26: CMTV look (AuthShell), same logic
export default function ForgotPasswordPage() {
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
        setError(HUMAN_MSG); // CMTV 2026-10-08: clear message when reCAPTCHA is blocked
        return;
      }
    }

    setSending(true);
    try {
      const response = await authAPI.forgotPassword({ email, recaptcha_token: recaptchaToken });
      setSuccessMessage(response.data.message);
    } catch (err) {
      setError(humanOr(err.response?.data?.detail) || 'Something went wrong. Please try again.');   // CMTV 2026-10-08
    }
    setSending(false);
  };

  return (
    <AuthShell variant="signin">
      <h2>Forgot your password?</h2>
      <p className="sub">Enter your email or username and we'll email you a link to choose a new one.</p>

      {successMessage && <Note kind="ok"><CheckCircle2 size={18} /><span>{successMessage} Don't forget to check your spam folder.</span></Note>}
      {error && <Note kind="err"><AlertCircle size={18} /><span>{error}<HumanCheckHelp error={error} /></span></Note>}

      <form onSubmit={handleSubmit}>
        <div className="ab-field">
          <label htmlFor="fp-email">Email or username</label>
          <input id="fp-email" type="text" required autoComplete="username" value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <button type="submit" className="ab-btn" disabled={sending}>{sending ? 'Sending…' : 'Send reset link'}</button>
      </form>

      <p className="ab-alt">Remembered it? <Link to="/login">Back to sign in</Link></p>
      <RecaptchaLegal enabled={recaptchaConfig?.enabled} />
    </AuthShell>
  );
}
