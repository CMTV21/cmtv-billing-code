// CMTV local addition 2026-10-04: customers mixed up capital i (I) and small L (l) in their passwords. SpellOut shows a
// login one character per box and names the look-alikes underneath ("small L", "capital i", "zero"...). Renders nothing
// when the value has no look-alike characters. Used on the dashboard service cards and the guides' "Your details" box.
// Folded behind a small "See it letter by letter" link (the owner, same day: the open boxes took over the card on phones).
import React, { useState } from 'react';
import './spell-out.css';

const NAMES = { I: 'capital i', l: 'small L', 1: 'one', O: 'capital O', 0: 'zero', o: 'small o', i: 'small i', L: 'capital L' };
const RISKY = /[Il1O0]/;

export const hasLookAlikes = (v) => RISKY.test(String(v || ''));

export default function SpellOut({ value, label = 'password' }) {
  const [open, setOpen] = useState(false);
  const v = String(value || '');
  if (!hasLookAlikes(v)) return null;
  return (
    <div className="spell-out" aria-label={`Your ${label}, letter by letter`}>
      <button type="button" className="spell-out-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? 'Hide letter by letter' : 'Has look-alike letters: see it letter by letter'}
      </button>
      {open && (
        <div className="spell-out-row">
          {[...v].map((ch, i) => (
            // look-alikes get their name; other capitals get "CAP" so case is never a guess
            <span key={i} className={`spell-out-ch${NAMES[ch] ? ' risky' : ''}`}>
              <b>{ch}</b>
              <small>{NAMES[ch] || (/[A-Z]/.test(ch) ? 'CAP' : '')}</small>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
