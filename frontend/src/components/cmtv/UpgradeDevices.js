// CMTV local addition 2026-10-04: "Add devices" on a running CCTV / Imperium line (backend cmtv_upgrades.py). Shows each
// option with the price worked out step by step (the owner: "show the math to the customer"):
// (12-month price for the new number of devices - for the current number) x days left / 365, rounded up, minimum $5.
// Picking one puts an "upgrade" item in the cart (server re-prices it) and opens checkout.
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../api/api';
import { useCartStore } from '../../store/store';

const usd = (v) => `$${Number(v).toFixed(Number(v) % 1 ? 2 : 0)}`;
const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');
const dev = (n) => `${n} device${n === 1 ? '' : 's'}`;

export default function UpgradeDevices({ service }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);   // null = not loaded, {error}, or the options
  const { addRenewalItem } = useCartStore();
  const navigate = useNavigate();

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !data) {
      try { setData((await api.get(`/api/cmtv/upgrades/options/${service.id}`)).data); }
      catch (e) { setData({ error: e?.response?.data?.detail || 'Upgrade options can\'t be loaded right now.' }); }
    }
  };
  const choose = (o) => {
    addRenewalItem({
      product_id: o.product_id, product_name: `Add devices: ${data.login} to ${dev(o.connections)}`,
      term_months: 1, price: o.price, account_type: 'subscriber',
      term_label: `Device upgrade · rest of your plan${o.bonus_month ? ' + 1 bonus month' : ''}`,
    }, service.id, 'upgrade');
    navigate('/checkout');
  };

  return (
    <>
      <button type="button" className="ca-btn ca-ghost" onClick={toggle} aria-expanded={open}>{open ? 'Hide' : 'Add devices'}</button>
      {open && (
        <div className="ca-setup" style={{ flexBasis: '100%', width: '100%' }}>
          {!data ? <p>Checking your line…</p> : data.error ? <p>{data.error}</p> : (
            <>
              <p style={{ margin: '0 0 8px' }}>
                Your {data.panel} line <b>{data.login}</b> has <b>{dev(data.current)}</b>
                {data.ends ? <> and runs until <b>{day(data.ends)}</b> ({data.days_left} days left)</> : null}.
                Add devices for the rest of your plan: you only pay for the time left.
              </p>
              {data.reason && !data.options.length ? <p>{data.reason}</p> : data.options.map((o) => {
                const m = o.math;
                return (
                  <div key={o.connections} style={{ border: '1px solid var(--line, #27345a)', borderRadius: 12, padding: '10px 12px', margin: '8px 0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                      <b style={{ fontSize: 16 }}>{dev(o.connections)}</b>
                      <b style={{ fontSize: 18 }}>{usd(o.price)}</b>
                    </div>
                    <div style={{ fontSize: 13.5, lineHeight: 1.6, margin: '6px 0 8px', color: 'var(--muted, #9aa6c6)' }}>
                      <div>{dev(o.connections)} for a year: {usd(m.new_year)} &nbsp;−&nbsp; {dev(data.current)} for a year: {usd(m.cur_year)} = <b>{usd(m.diff_year)} a year</b></div>
                      <div>{usd(m.diff_year)} × {m.days_left} days left ÷ 365 days = {usd(m.raw)}</div>
                      <div>{m.minimum_applied ? <>Minimum charge: <b>{usd(m.price)}</b></> : <>Rounded up to the dollar: <b>{usd(m.price)}</b></>}</div>
                      {o.bonus_month
                        ? <div>Bonus: we add <b>1 extra month</b>, so your plan runs until <b>{day(o.new_end)}</b>.</div>
                        : <div>Your end date stays <b>{day(o.new_end)}</b>.</div>}
                    </div>
                    <button type="button" className="ca-btn ca-glow" onClick={() => choose(o)}>Upgrade to {dev(o.connections)} for {usd(o.price)}</button>
                  </div>
                );
              })}
              <p style={{ fontSize: 12.5, margin: '6px 0 0', color: 'var(--muted, #9aa6c6)' }}>
                Your username and password stay the same: just sign in on the extra devices. Your channels stay as they are.
              </p>
            </>
          )}
        </div>
      )}
    </>
  );
}
