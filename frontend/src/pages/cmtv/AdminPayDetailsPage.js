// CMTV local addition 2026-10-09: Admin > Payment details (backend cmtv_pay.py). The exact details customers see on the
// "Pay for your order" page and in the order email: the e-Transfer address, and the Wise Wisetag / email / bank details.
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import api from '../../api/api';

const CUR = ['CAD', 'USD', 'EUR', 'GBP'];
const inputStyle = { width: '100%', minWidth: 0, padding: '8px 10px', borderRadius: 8, border: '1px solid rgba(255,255,255,.15)',
  background: 'transparent', color: 'inherit', font: 'inherit' };
const errText = (e, fb) => e?.response?.data?.detail || fb;

export default function AdminPayDetailsPage() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get('/api/cmtv/pay/admin/details').then((r) => setD(r.data)).catch((e) => toast.error(errText(e, "Couldn't load"))); }, []);
  if (!d) return <div className="adm-home"><p className="skeleton">Loading…</p></div>;
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  const setBank = (c) => (e) => setD({ ...d, wise_bank: { ...d.wise_bank, [c]: e.target.value } });
  const save = async () => {
    setBusy(true);
    try { setD((await api.post('/api/cmtv/pay/admin/details', d)).data); toast.success('Saved'); }
    catch (e) { toast.error(errText(e, "Couldn't save")); }
    setBusy(false);
  };
  return (
    <div className="adm-home">
      <h1>Payment details</h1>
      <p className="note" style={{ margin: '4px 0 16px' }}>What customers see on the "Pay for your order" page and in the order email after
        they choose e-Transfer or Wise. Switch the methods on or off in <Link className="link" to="/admin/settings">Settings &gt; Payment gateways</Link>.</p>

      <section className="card" style={{ marginBottom: 14 }}>
        <h2>Interac e-Transfer</h2>
        <label className="note" htmlFor="pd-emt">Customers send to</label>
        <input id="pd-emt" style={inputStyle} value={d.emt_email} onChange={set('emt_email')} />
        <p className="note" style={{ marginTop: 8 }}>They're also told: amount, security question "What is my CMTV order number?", answer and
          message = their order ID (the e-Transfer Telegram note shows it with tap-to-copy).</p>
      </section>

      <section className="card" style={{ marginBottom: 14 }}>
        <h2>Wise</h2>
        <div className="grid2">
          <div><label className="note" htmlFor="pd-tag">Wisetag (for Wise users)</label>
            <input id="pd-tag" style={inputStyle} placeholder="@cmtv" value={d.wise_tag} onChange={set('wise_tag')} /></div>
          <div><label className="note" htmlFor="pd-wemail">Wise email (optional)</label>
            <input id="pd-wemail" style={inputStyle} value={d.wise_email} onChange={set('wise_email')} /></div>
        </div>
        <p className="note" style={{ marginTop: 12 }}>Bank details for people without Wise: copy them from Wise (Home &gt; your CAD / USD / EUR /
          GBP balance &gt; Account details). One per line as <b>Label: value</b> so customers get a copy button for each, e.g.
          "Account holder: CMTV". Leave a currency empty to hide it.</p>
        {CUR.map((c) => (
          <div key={c} style={{ marginTop: 10 }}>
            <label className="note" htmlFor={`pd-${c}`}>{c}</label>
            <textarea id={`pd-${c}`} rows={4} style={inputStyle} value={d.wise_bank?.[c] || ''} onChange={setBank(c)}
              placeholder={c === 'EUR' ? 'Account holder: CMTV\nIBAN: ...\nSwift/BIC: ...' : 'Account holder: CMTV\nAccount number: ...'} />
          </div>
        ))}
        <p className="note" style={{ marginTop: 10 }}>Wise payments are matched automatically every 5 minutes (reference = the order's first 10
          characters, amount covers the order): the order is marked paid and set up. Anything unclear comes to Ops Billing.</p>
      </section>

      <button type="button" className="btn" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>
    </div>
  );
}
