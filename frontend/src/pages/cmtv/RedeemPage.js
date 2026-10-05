// CMTV local addition 2026-10-05: /redeem "Redeem a gift card" (backend cmtv_gifts.py). Signed in: enter the code and the
// amount goes on the account as credit (used at checkout). Works whether or not gift cards are on sale yet.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import api from '../../api/api';
import { useAuthStore } from '../../store/store';
import { usePageMeta } from '../../components/cmtv/CmtvSEO';
import { GiftCardArt } from './GiftPage';
import '../../components/cmtv/cmtv-kb.css';
import '../../components/cmtv/gift.css';

export default function RedeemPage() {
  usePageMeta({ title: 'Redeem a gift card | CMTV', description: 'Got a CMTV gift card? Enter the code to add it to your account.' });
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const start = new URLSearchParams(window.location.search).get('code') || '';
  const [code, setCode] = useState(start);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [done, setDone] = useState(null);
  const back = `/redeem${start ? `?code=${encodeURIComponent(start)}` : ''}`;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const r = (await api.post('/api/cmtv/gifts/redeem', { code })).data;
      setDone(r);
      qc.invalidateQueries();
    } catch (x) { setErr(x?.response?.data?.detail || 'Something went wrong. Please try again.'); }
    setBusy(false);
  };

  return (
    <div className="cmtv-kb gf">
      <article className="kb-article gf-redeem" style={{ marginTop: 12 }}>
        <h1>Redeem a gift card 🎁</h1>
        {done ? (
          <div className="gf-done">
            <GiftCardArt amount={done.amount} from={done.from_name} small />
            <h2>${done.amount.toFixed(2)} added to your account!</h2>
            <p>Your credit balance is now <b>${Number(done.balance).toFixed(2)}</b>. Choose to use your credit at checkout on any plan or add-on.</p>
            <p className="gf-actions">
              <Link className="kb-btn glow" to="/">Browse plans</Link>
              <Link className="kb-btn" to="/dashboard">Renew my plan</Link>
            </p>
          </div>
        ) : !user ? (
          <>
            <p className="kb-lede">Sign in to add your gift card to your account. New to CMTV? Create a free account first, then sign in and come back here.</p>
            <p className="gf-actions">
              <Link className="kb-btn glow" to={`/login?redirect=${encodeURIComponent(back)}`}>Sign in</Link>
              <Link className="kb-btn" to="/register">Create an account</Link>
            </p>
          </>
        ) : (
          <form onSubmit={submit}>
            <p className="kb-lede">Enter the code from your gift card email. The amount goes on your account as credit.</p>
            <input className="gf-input gf-codein" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="CMTV-ABCD-EFGH-JKMN"
              autoCapitalize="characters" autoComplete="off" spellCheck={false} maxLength={24} />
            {err && <p className="gf-err">{err}</p>}
            <button type="submit" className="kb-btn glow gf-go" disabled={busy || code.replace(/[^a-z0-9]/gi, '').length < 12}>
              {busy ? 'Checking…' : 'Redeem'}
            </button>
            <p className="gf-small">Codes never contain the letters I, L or O or the numbers 0 or 1, so there's no mixing them up.</p>
          </form>
        )}
      </article>
    </div>
  );
}
