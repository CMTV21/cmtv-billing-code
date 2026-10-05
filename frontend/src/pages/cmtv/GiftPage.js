// CMTV local addition 2026-10-05: /gift "Give CMTV" gift cards (backend cmtv_gifts.py). Pick an amount, who it's for,
// a message and when it arrives; it goes through the normal checkout as the hidden gift card product. Hidden from
// customers until Admin > Gift cards switches it on (admins can always use it to test).
import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import { useAuthStore, useCartStore } from '../../store/store';
import { usePageMeta } from '../../components/cmtv/CmtvSEO';
import '../../components/cmtv/cmtv-kb.css';
import '../../components/cmtv/gift.css';

const DRAFT = 'cmtv-gift-draft';
const readDraft = () => { try { return JSON.parse(sessionStorage.getItem(DRAFT) || 'null'); } catch { return null; } };
const saveDraft = (d) => { try { sessionStorage.setItem(DRAFT, JSON.stringify(d)); } catch { /* private mode */ } };
const dropDraft = () => { try { sessionStorage.removeItem(DRAFT); } catch { /* ignore */ } };
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const niceDay = (s) => (s ? new Date(`${s}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' }) : '');

export function GiftCardArt({ amount, to, from, small }) {
  return (
    <div className={`gf-card${small ? ' small' : ''}`}>
      <div className="gf-card-top"><span>CMTV gift card</span><span>🎁</span></div>
      <div className="gf-card-amt">${amount || 0}</div>
      <div className="gf-card-to">{to ? `For ${to}` : ' '}</div>
      <div className="gf-card-from">{from ? `From ${from}` : ' '}</div>
    </div>
  );
}

function Status({ g }) {
  if (g.status === 'redeemed') return <span className="gf-pill ok">Redeemed</span>;
  if (g.status === 'void') return <span className="gf-pill off">Cancelled</span>;
  if (g.status === 'scheduled') return <span className="gf-pill wait">Arrives {niceDay(g.deliver_on)}</span>;
  if (g.status === 'sent') return <span className="gf-pill">Emailed</span>;
  return <span className="gf-pill">Ready to give</span>;
}

function MyGifts() {
  const { data } = useQuery({ queryKey: ['cmtv-gifts-mine'], queryFn: async () => (await api.get('/api/cmtv/gifts/mine')).data });
  if (!data?.bought?.length) return null;
  const copy = (c) => { try { navigator.clipboard.writeText(c); toast.success('Code copied'); } catch { /* ignore */ } };
  return (
    <section className="gf-mine">
      <h2>Gift cards you've bought</h2>
      {data.bought.map((g) => (
        <div key={g.id} className="gf-row">
          <b>${g.amount}</b>
          <span className="gf-row-to">{g.to_name || g.to_email || 'To give yourself'}</span>
          <Status g={g} />
          {g.status !== 'redeemed' && g.status !== 'void' && (
            <button type="button" className="gf-code" onClick={() => copy(g.code)} title="Copy code">{g.code}</button>
          )}
        </div>
      ))}
    </section>
  );
}

export default function GiftPage() {
  usePageMeta({ title: 'Gift cards | CMTV', description: 'Give CMTV: a gift card for any amount, delivered by email now or on the day you choose. Never expires.' });
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const { items, addItem, clearCart } = useCartStore();
  const { data: cfg, isLoading } = useQuery({ queryKey: ['cmtv-gifts-config'], queryFn: async () => (await api.get('/api/cmtv/gifts/config')).data });
  const d0 = readDraft() || {};
  const [pick, setPick] = useState(d0.pick ?? 50);
  const [custom, setCustom] = useState(d0.custom ?? '');
  const [toName, setToName] = useState(d0.toName ?? '');
  const [toEmail, setToEmail] = useState(d0.toEmail ?? '');
  const [self, setSelf] = useState(d0.self ?? false);
  const [fromName, setFromName] = useState(d0.fromName ?? (user?.name || ''));
  const [message, setMessage] = useState(d0.message ?? '');
  const [when, setWhen] = useState(d0.when ?? 'now');
  const [day, setDay] = useState(d0.day ?? '');
  useEffect(() => { if (!fromName && user?.name) setFromName(user.name); }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  const isAdmin = user?.role === 'admin';
  const min = cfg?.min || 10;
  const max = cfg?.max || 500;
  const amount = pick === 'custom' ? Number(custom) : pick;
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
  const lastDay = new Date(); lastDay.setDate(lastDay.getDate() + 365);
  const emailOk = /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(toEmail.trim());

  const problem = (() => {
    if (!Number.isInteger(amount) || amount < min || amount > max) return `Pick an amount from $${min} to $${max} (whole dollars).`;
    if (!self && !emailOk) return "Add the recipient's email, or choose to give it yourself.";
    if (!fromName.trim()) return 'Add who it’s from.';
    if (!self && when === 'date' && !day) return 'Pick the day it should arrive.';
    return '';
  })();

  const go = () => {
    if (problem) { toast.error(problem); return; }
    const draft = { pick, custom, toName, toEmail, self, fromName, message, when, day };
    if (!user) { saveDraft(draft); navigate('/login?redirect=/gift'); return; }
    const others = items.filter((i) => !i.gift);
    if (others.length && !window.confirm(`Gift cards are checked out on their own. Remove the ${others.length} other item${others.length === 1 ? '' : 's'} from your cart?`)) return;
    if (others.length) clearCart();
    addItem({
      product_id: cfg.product_id, product_name: `CMTV Gift Card $${amount}${toName.trim() ? ` for ${toName.trim()}` : ''}`,
      term_months: 0, price: amount, account_type: 'manual',
      gift: { amount, to_name: toName.trim(), to_email: self ? '' : toEmail.trim(), from_name: fromName.trim(), message: message.trim(),
        deliver_on: !self && when === 'date' ? day : null },
    });
    dropDraft();
    navigate('/checkout');
  };

  if (isLoading) return <div className="cmtv-kb gf"><article className="kb-article" style={{ marginTop: 12 }}><p className="kb-lede">Loading…</p></article></div>;
  if (!cfg?.enabled && !isAdmin) {
    return (
      <div className="cmtv-kb gf">
        <article className="kb-article" style={{ marginTop: 12, textAlign: 'center' }}>
          <h1>CMTV gift cards</h1>
          <p className="kb-lede">Gift cards are coming soon. Check back for the holidays!</p>
          <p><Link className="kb-btn" to="/redeem">Got a gift card? Redeem it</Link></p>
        </article>
      </div>
    );
  }

  const bonus = cfg?.give_get ? (amount >= 100 ? 20 : amount >= 50 ? 10 : 0) : 0;
  return (
    <div className="cmtv-kb gf">
      <article className="kb-article" style={{ marginTop: 12 }}>
        {!cfg?.enabled && <p className="gf-admin">👀 Only admins can see this page. Switch gift cards on in Admin &gt; Gift cards when you're ready.</p>}
        <h1>Give CMTV 🎁</h1>
        <p className="kb-lede">A gift card they can spend on any plan or add-on. Sent by email now or on the day you pick, and it never expires.</p>
        <div className="gf-grid">
          <div className="gf-form">
            <label className="gf-label">Amount</label>
            <div className="gf-amts">
              {(cfg?.amounts || [25, 50, 100]).map((a) => (
                <button key={a} type="button" className={pick === a ? 'on' : ''} onClick={() => setPick(a)}>${a}</button>
              ))}
              <button type="button" className={pick === 'custom' ? 'on' : ''} onClick={() => setPick('custom')}>Other</button>
            </div>
            {pick === 'custom' && (
              <input className="gf-input" type="number" inputMode="numeric" min={min} max={max} step="1" value={custom}
                onChange={(e) => setCustom(e.target.value)} placeholder={`$${min} to $${max}`} autoFocus />
            )}
            {bonus > 0 && <p className="gf-bonus">🎉 Holiday give-and-get: you'll also get <b>${bonus}</b> credit for yourself.</p>}

            <label className="gf-label">Who's it for?</label>
            <input className="gf-input" value={toName} maxLength={60} onChange={(e) => setToName(e.target.value)} placeholder="Their name (optional)" />
            {!self && <input className="gf-input" type="email" value={toEmail} maxLength={120} onChange={(e) => setToEmail(e.target.value)} placeholder="Their email" />}
            <label className="gf-check"><input type="checkbox" checked={self} onChange={(e) => setSelf(e.target.checked)} /> I'll give it to them myself (we email the code to you)</label>

            <label className="gf-label">From</label>
            <input className="gf-input" value={fromName} maxLength={60} onChange={(e) => setFromName(e.target.value)} placeholder="Your name" />

            <label className="gf-label">Message <small>(optional)</small></label>
            <textarea className="gf-input" rows={3} value={message} maxLength={300} onChange={(e) => setMessage(e.target.value)} placeholder="Happy holidays! Enjoy the hockey." />

            {!self && (
              <>
                <label className="gf-label">When should it arrive?</label>
                <div className="gf-amts two">
                  <button type="button" className={when === 'now' ? 'on' : ''} onClick={() => setWhen('now')}>Right after I pay</button>
                  <button type="button" className={when === 'date' ? 'on' : ''} onClick={() => setWhen('date')}>On a date</button>
                </div>
                {when === 'date' && (
                  <>
                    <input className="gf-input" type="date" value={day} min={isoDay(tomorrow)} max={isoDay(lastDay)} onChange={(e) => setDay(e.target.value)} />
                    {day && <p className="gf-small">Arrives {niceDay(day)} at about 8 am Eastern.</p>}
                  </>
                )}
              </>
            )}
          </div>
          <div className="gf-side">
            <GiftCardArt amount={Number.isFinite(amount) ? amount : 0} to={toName.trim()} from={fromName.trim()} />
            {message.trim() && <p className="gf-msg">“{message.trim()}”</p>}
            <button type="button" className="kb-btn glow gf-go" onClick={go}>
              {user ? `Continue to checkout · $${Number.isFinite(amount) ? amount : 0}` : 'Sign in to continue'}
            </button>
            {problem && <p className="gf-small">{problem}</p>}
            <p className="gf-small">Pay by PayPal or e-Transfer as usual. The code works once and goes on the account of whoever redeems it.</p>
          </div>
        </div>
        {user && <MyGifts />}
        <p className="gf-small" style={{ marginTop: 18 }}>Got a gift card? <Link to="/redeem">Redeem it here</Link>.</p>
      </article>
    </div>
  );
}
