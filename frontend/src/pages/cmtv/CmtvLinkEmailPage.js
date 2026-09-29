// CMTV local addition 2026-09-28: /link-email for customers who signed in with their TV line login (panel-only accounts).
// They add their email + a website password; if the email already has a CMTV account, they confirm that account's
// password and the two are joined. Backend: POST /api/cmtv/claim/link (cmtv_claim.py). Replaces the developer's
// LinkEmailPage (still in the code, unused).
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertCircle, CheckCircle2 } from 'lucide-react';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import { AuthShell, Note, PasswordInput } from '../../components/cmtv/AuthShell';

export default function CmtvLinkEmailPage() {
  const navigate = useNavigate();
  const { user, setAuth } = useAuthStore();
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '', existing: '' });
  const [needsExisting, setNeedsExisting] = useState(null); // masked email of the account it will join
  const [error, setError] = useState('');
  const [done, setDone] = useState(null); // 'linked' | 'joined'
  const [busy, setBusy] = useState(false);
  const next = new URLSearchParams(window.location.search).get('redirect') || '/dashboard';
  const set = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setError(''); };

  if (!user) {
    return (
      <AuthShell variant="signin">
        <h2>Finish setting up your account</h2>
        <p className="sub">First sign in with the username and password of your TV line (the ones you use in your app).</p>
        <Link className="ab-btn" to="/login?redirect=/link-email" style={{ display: 'block', textAlign: 'center' }}>Sign in</Link>
      </AuthShell>
    );
  }
  if (!user.needs_email_link && !done) {
    return (
      <AuthShell variant="signin">
        <h2>You're all set</h2>
        <p className="sub">Your account already has an email address.</p>
        <Link className="ab-btn" to="/dashboard" style={{ display: 'block', textAlign: 'center' }}>Go to your dashboard</Link>
      </AuthShell>
    );
  }

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!needsExisting) {
      if (form.password.length < 6) { setError('Choose a website password of at least 6 characters.'); return; }
      if (form.password !== form.confirm) { setError('The two passwords don\'t match.'); return; }
    }
    setBusy(true);
    try {
      const { data } = await api.post('/api/cmtv/claim/link', {
        email: form.email, name: form.name, new_password: form.password,
        existing_password: needsExisting ? form.existing : undefined,
      });
      if (data.needs_existing_password) {
        setNeedsExisting(data.email);
      } else {
        setAuth(data.user, data.access_token);
        setDone(data.joined ? 'joined' : 'linked');
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    }
    setBusy(false);
  };

  if (done) {
    return (
      <AuthShell variant="signin">
        <h2>{done === 'joined' ? 'Accounts joined' : 'Your account is ready'}</h2>
        <Note kind="ok"><CheckCircle2 size={18} /><span>
          {done === 'joined'
            ? 'Your TV line is now on your existing account. From now on, sign in with that email and its password.'
            : `We've sent a link to ${form.email} to confirm it's yours. From now on, sign in with your email and the password you just chose.`}
        </span></Note>
        <button type="button" className="ab-btn" onClick={() => navigate(next)}>Continue</button>
      </AuthShell>
    );
  }

  return (
    <AuthShell variant="signin">
      <h2>Finish setting up your account</h2>
      <p className="sub">
        Welcome{user.panel_username ? `, ${user.panel_username}` : ''}! Add your email so you get renewal reminders and can reset your
        password, and choose a password for this website. Your TV app login doesn't change.
      </p>
      {error && <Note kind="err"><AlertCircle size={18} /><span>{error}</span></Note>}
      <form onSubmit={submit}>
        {!needsExisting ? (
          <>
            <div className="ab-field">
              <label htmlFor="le-name">Your name</label>
              <input id="le-name" type="text" autoComplete="name" maxLength={80} value={form.name} onChange={set('name')} placeholder="First and last name" />
            </div>
            <div className="ab-field">
              <label htmlFor="le-email">Email</label>
              <input id="le-email" type="email" required autoComplete="email" value={form.email} onChange={set('email')} placeholder="you@example.com" />
            </div>
            <div className="ab-field">
              <label htmlFor="le-pw">Website password</label>
              <PasswordInput id="le-pw" required minLength={6} autoComplete="new-password" value={form.password} onChange={set('password')} placeholder="At least 6 characters" />
            </div>
            <div className="ab-field">
              <label htmlFor="le-pw2">Confirm password</label>
              <PasswordInput id="le-pw2" required minLength={6} autoComplete="new-password" value={form.confirm} onChange={set('confirm')} placeholder="Type it again" />
            </div>
          </>
        ) : (
          <>
            <Note kind="ok"><CheckCircle2 size={18} /><span>
              {needsExisting} already has a CMTV account. Enter that account's password and we'll put this TV line on it, so everything is in one place.
            </span></Note>
            <div className="ab-field">
              <label htmlFor="le-existing">Password for {needsExisting}</label>
              <PasswordInput id="le-existing" required autoComplete="current-password" value={form.existing} onChange={set('existing')} placeholder="That account's password" />
            </div>
            <p className="ab-alt" style={{ marginTop: 0 }}>
              Forgot it? <Link to="/forgot-password">Reset that account's password</Link>, then come back here.{' '}
              <button type="button" style={{ background: 'none', border: 0, padding: 0, color: 'inherit', textDecoration: 'underline', cursor: 'pointer', font: 'inherit' }} onClick={() => { setNeedsExisting(null); setForm({ ...form, existing: '' }); }}>Use a different email</button>
            </p>
          </>
        )}
        <button type="submit" className="ab-btn" disabled={busy}>{busy ? 'Saving…' : needsExisting ? 'Join my accounts' : 'Save and continue'}</button>
      </form>
      <p className="ab-alt"><Link to={next}>Skip for now</Link></p>
    </AuthShell>
  );
}
