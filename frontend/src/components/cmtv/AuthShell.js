// CMTV local addition 2026-09-26: the frame for sign in / sign up / forgot / reset password: CMTV brand panel + form.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Eye, EyeOff } from 'lucide-react';
import { BRAND } from './brand';
import './cmtv-auth.css';

const PERKS = {
  signin: [
    ['Everything in one place', 'Your services, logins, renewals and orders.'],
    ['Renew in a few taps', 'Or switch on auto-renew with PayPal and forget about it.'],
    ['Help when you need it', 'Open a ticket here or message @Cmtv_support_bot on Telegram.'],
  ],
  signup: [
    ['Try before you pay', 'Free trials: CCTV 24 hours, Imperium 48 hours, add-ons 7 days.'],
    ['Add what you like', 'Stremio, CMTVpn and Audiobooks, or all three with CMTV+.'],
    ['Refer friends, save more', '5 referrals = 10% off your plans. 10 = 20% off, plus free add-ons.'],
  ],
};
const HEAD = {
  signin: <>Welcome <em>back</em></>,
  signup: <>Your TV, <em>your way</em></>,
};
const PITCH = {
  signin: 'Sign in to manage your CMTV services.',
  signup: 'Create a free account to start a trial or pick a plan. It takes a minute.',
};

export function AuthShell({ variant = 'signin', children }) {
  return (
    <div className="cmtv-auth">
      <aside className="ab-brand">
        <Link to="/" className="ab-logo" aria-label="CMTV home"><img src={BRAND.siteLogo} alt="" /><span>CMTV</span></Link>
        <div className="ab-pitch">
          <h1>{HEAD[variant] || HEAD.signin}</h1>
          <p>{PITCH[variant] || PITCH.signin}</p>
        </div>
        <ul className="ab-perks">
          {(PERKS[variant] || PERKS.signin).map(([b, s]) => (
            <li key={b}><span className="tick" aria-hidden="true">✓</span><span><b>{b}</b><small>{s}</small></span></li>
          ))}
        </ul>
        <div className="ab-logos" aria-hidden="true">
          {['/cmtv/cctv.png', '/cmtv/imperium.png', '/cmtv/cmtv-plus.png', '/cmtv/cmtvpn.png', '/cmtv/cmtv-audiobooks.png'].map((src) => (
            <img key={src} src={src} alt="" onError={(e) => { e.currentTarget.style.display = 'none'; }} />
          ))}
        </div>
      </aside>
      <main className="ab-main"><div className="ab-card">{children}</div></main>
    </div>
  );
}

export function PasswordInput({ value, onChange, ...rest }) {
  const [show, setShow] = useState(false);
  return (
    <div className="ab-input">
      <input type={show ? 'text' : 'password'} value={value} onChange={onChange} {...rest} />
      <button type="button" className="ab-eye" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'}>
        {show ? <EyeOff size={18} /> : <Eye size={18} />}
      </button>
    </div>
  );
}

export function Note({ kind = 'info', children }) {
  return <div className={`ab-note ${kind}`} role={kind === 'err' ? 'alert' : 'status'}>{children}</div>;
}

// 2026-10-08 (owner): a blocked reCAPTCHA check (usually an ad blocker or privacy browser) said "refresh and try again",
// which doesn't help. One clear message + a way to reach us without signing in (the support bot opens tickets).
export const HUMAN_MSG = "Couldn't verify you're human. Turn off your ad blocker or try another browser, or open a ticket.";
export const isHumanCheck = (msg) => /verify you're human|security check failed|security verification required|recaptcha check failed/i.test(String(msg || ''));
export const humanOr = (msg) => (isHumanCheck(msg) ? HUMAN_MSG : msg);
export function HumanCheckHelp({ error }) {
  if (!isHumanCheck(error)) return null;
  return (
    <span className="ab-human"> <a href="https://t.me/Cmtv_support_bot" target="_blank" rel="noopener noreferrer">Open a ticket with our Telegram support bot</a>{' '}
      or email <a href="mailto:cmtv@pm.me">cmtv@pm.me</a>.</span>
  );
}

export function RecaptchaLegal({ enabled }) {
  if (!enabled) return null;
  return (
    <p className="ab-legal">
      Protected by reCAPTCHA. Google <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a> and{' '}
      <a href="https://policies.google.com/terms" target="_blank" rel="noopener noreferrer">Terms</a> apply.
    </p>
  );
}
