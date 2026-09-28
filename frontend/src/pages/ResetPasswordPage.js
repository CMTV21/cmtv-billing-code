import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { authAPI } from '../api/api';
import { AlertCircle } from 'lucide-react';
import { AuthShell, Note, PasswordInput } from '../components/cmtv/AuthShell';

// CMTV local change 2026-09-24: landing page for the link in the password reset email
// CMTV local change 2026-09-26: CMTV look (AuthShell), same logic
export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // CMTV local change 2026-09-28: new emails put the token after "#" (kept out of server logs); older links use ?token=
  const token = searchParams.get('token') || new URLSearchParams(window.location.hash.slice(1)).get('token') || '';
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

  return (
    <AuthShell variant="signin">
      <h2>Choose a new password</h2>
      <p className="sub">At least 6 characters. You'll use it to sign in to this website.</p>

      {account && (
        <div className="ab-account">
          <p>You're resetting the password for:</p>
          {account.username && <p><b>Username:</b> {account.username}</p>}
          <p><b>Email:</b> {account.email}</p>
          <small>This changes your sign-in for this website only. Your TV line / app login stays the same. Not your account? Don't continue; close this page.</small>
        </div>
      )}

      {error && (
        <Note kind="err"><AlertCircle size={18} />
          <span>
            {error}{' '}
            {(error.includes('expired') || error.includes('missing')) && <Link to="/forgot-password">Request a new link</Link>}
          </span>
        </Note>
      )}

      <form onSubmit={handleSubmit}>
        <div className="ab-field">
          <label htmlFor="rp-new">New password</label>
          <PasswordInput id="rp-new" required minLength={6} autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} placeholder="At least 6 characters" />
        </div>
        <div className="ab-field">
          <label htmlFor="rp-confirm">Confirm new password</label>
          <PasswordInput id="rp-confirm" required minLength={6} autoComplete="new-password" value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Type it again" />
        </div>
        <button type="submit" className="ab-btn" disabled={saving || !account}>{saving ? 'Saving…' : 'Save new password'}</button>
      </form>

      <p className="ab-alt"><Link to="/login">Back to sign in</Link></p>
    </AuthShell>
  );
}
