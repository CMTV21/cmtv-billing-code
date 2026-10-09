// CMTV local addition 2026-10-09: /pay/:orderId "Pay for your order" (backend cmtv_pay.py). After choosing e-Transfer or Wise
// the customer lands here with every exact detail and a copy button for each (owner: "I get too many questions afterward").
import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { QRCodeSVG } from 'qrcode.react';   // 2026-10-09: QR of the owner's Wise "get paid" link
import api from '../../api/api';
import '../../components/cmtv/cmtv-kb.css';

const card = { background: '#141d33', border: '1px solid #27345a', borderRadius: 14, padding: '6px 16px', margin: '14px 0' };
const money = (v) => `$${Number(v || 0).toFixed(2)} CAD`;

function Row({ label, value, mono = false, copy = true, note }) {
  const [done, setDone] = useState(false);
  const doCopy = async () => {
    try { await navigator.clipboard.writeText(String(value)); setDone(true); setTimeout(() => setDone(false), 1500); }
    catch { toast.error('Copy didn\'t work: press and hold to copy instead'); }
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 0', borderBottom: '1px solid #27345a', flexWrap: 'wrap' }}>
      <div style={{ flex: '1 1 180px', minWidth: 0 }}>
        <div style={{ fontSize: 13, color: '#8391b5' }}>{label}</div>
        <div style={{ fontWeight: 800, fontSize: mono ? 17 : 16, wordBreak: 'break-all', letterSpacing: mono ? 1 : 0,
          fontFamily: mono ? 'Consolas, Menlo, monospace' : 'inherit' }}>{value}</div>
        {note && <div style={{ fontSize: 13, color: '#8391b5', marginTop: 2 }}>{note}</div>}
      </div>
      {copy && <button type="button" className="kb-btn" onClick={doCopy} style={{ flex: 'none', padding: '8px 14px' }}
        aria-label={`Copy ${label}`}>{done ? 'Copied ✓' : 'Copy'}</button>}
    </div>
  );
}

export default function PayPage() {
  const { orderId } = useParams();
  const { data: v, error, isLoading } = useQuery({
    queryKey: ['cmtv-pay', orderId],
    queryFn: async () => (await api.get(`/api/cmtv/pay/order/${orderId}`)).data,
    refetchInterval: (q) => (q.state.data?.status === 'pending' ? 30000 : false),   // shows "paid" by itself (Wise is automatic)
  });
  if (isLoading) return <div className="cmtv-kb"><article className="kb-article"><p className="kb-lede">Loading your order…</p></article></div>;
  if (error || !v) return <div className="cmtv-kb"><article className="kb-article"><p className="kb-lede">We couldn't find that order.</p>
    <Link className="kb-btn" to="/orders">My orders</Link></article></div>;
  const paid = v.status === 'paid';
  const h = v.hours;
  return (
    <div className="cmtv-kb">
      <article className="kb-article" style={{ marginTop: 12, maxWidth: 640 }}>
        <h1 style={{ marginBottom: 4 }}>{paid ? 'Payment received ✅' : 'Pay for your order'}</h1>
        <p className="kb-lede" style={{ marginBottom: 6 }}>{(v.items || []).join(', ')} · <b>{money(v.total)}</b></p>

        {paid ? (
          <>
            <p>Thanks! Your order is paid. Your login details are on your dashboard and in your email.</p>
            <Link className="kb-btn glow" to="/dashboard">Go to my dashboard</Link>
          </>
        ) : v.method === 'emt' && v.emt ? (
          <>
            <p>Send an <b>Interac e-Transfer</b> from your bank with exactly these details:</p>
            <div style={card}>
              <Row label="Send to" value={v.emt.send_to} />
              <Row label="Amount" value={v.emt.amount.toFixed(2)} note="Canadian dollars" />
              {/* 2026-10-09: Autodeposit (Wise): no security question */}
              <Row label="Message" value={v.emt.message} mono note="Your order number: so we can match your payment" />
            </div>
            <p style={{ fontSize: 14, color: '#8391b5' }}>
              {h ? (h.open_now
                ? `We're online now (${h.hours}): you'll be set up soon after your e-Transfer arrives.`
                : `We confirm e-Transfers ${h.hours}. We're offline right now, so you'll be set up by about ${h.next_open_text}.`)
                : 'You\'ll be set up soon after your e-Transfer arrives.'}
              {' '}We've also emailed you these details.
            </p>
          </>
        ) : v.method === 'wise' && v.wise ? (
          <>
            <p>Pay with <b>Wise</b> using exactly these details. Your order is set up <b>automatically</b> as soon as the payment reaches us.</p>
            <div style={card}>
              <Row label="Amount" value={v.wise.amount.toFixed(2)} note="Canadian dollars (or the same value in your currency)" />
              <Row label="Reference" value={v.wise.reference} mono note="Your order number: put it in the reference so we can match it" />
              {v.wise.tag && <Row label="Wise users: send to" value={v.wise.tag} />}
              {v.wise.email && <Row label="Or the Wise email" value={v.wise.email} />}
            </div>
            {v.wise.link && (
              <div style={{ ...card, display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', padding: 16 }}>
                <div style={{ background: '#fff', padding: 8, borderRadius: 10, flex: 'none' }}>
                  <QRCodeSVG value={v.wise.link} size={132} />
                </div>
                <div style={{ flex: '1 1 200px', minWidth: 0 }}>
                  <p style={{ margin: '0 0 10px' }}>Have Wise? Scan this with your phone, or tap the button, then enter the amount
                    <b> {v.wise.amount.toFixed(2)}</b> and the reference <b>{v.wise.reference}</b>.</p>
                  <a className="kb-btn glow" href={v.wise.link} target="_blank" rel="noopener noreferrer">Pay in the Wise app</a>
                </div>
              </div>
            )}
            {v.wise.invite && (   /* 2026-10-09: the owner's Wise invite link */
              <p style={{ fontSize: 14 }}>No Wise account? <a href={v.wise.invite} target="_blank" rel="noopener noreferrer"><b>Open one free
                with our link</b></a>, then come back to this page to pay.</p>
            )}
            {Object.keys(v.wise.bank || {}).length > 0 && (
              <>
                <h2 style={{ fontSize: 18, marginTop: 18 }}>No Wise account? Pay from your own bank</h2>
                <p style={{ fontSize: 14, color: '#8391b5' }}>Pick your currency and send a normal bank transfer with the same reference
                  <b> {v.wise.reference}</b>.</p>
                {Object.entries(v.wise.bank).map(([cur, txt]) => (
                  <div key={cur} style={card}>
                    <div style={{ fontWeight: 800, padding: '10px 0 4px' }}>{cur}</div>
                    {txt.split('\n').filter((l) => l.trim()).map((line, i) => {
                      const m = line.match(/^([^:]{2,40}):\s*(.+)$/);
                      return m ? <Row key={i} label={m[1]} value={m[2]} /> : <p key={i} style={{ margin: '6px 0' }}>{line}</p>;
                    })}
                  </div>
                ))}
              </>
            )}
            <p style={{ fontSize: 14, color: '#8391b5' }}>Wise transfers usually arrive in minutes
              {Object.keys(v.wise.bank || {}).length > 0 ? '; bank transfers can take 1-2 business days' : ''}.
              This page updates by itself when it's paid. We've also emailed you these details.</p>
          </>
        ) : (
          <p>This order is waiting for payment. If you're not sure how to pay, <Link to="/tickets">message us</Link>.</p>
        )}

        {/* 2026-10-09 (owner): the short order number, same as the reference/message above */}
        <p style={{ marginTop: 18, fontSize: 14 }}>Order number <code>{String(v.order_id).slice(0, 10).toUpperCase()}</code> · <Link to="/orders">My orders</Link>
          {' '}· Questions? <Link to="/tickets">Contact us</Link></p>
      </article>
    </div>
  );
}
