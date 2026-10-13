// CMTV local addition 2026-10-13 (owner approved the mock-up): the simplified customer dashboard.
// Same data and features as CmtvDashboardPage (whose helpers it imports), reorganised:
//  - one "needs attention" list, then Your TV (CCTV/Imperium lines), CMTV+ (one card for its parts), Add-ons (rows),
//    ended services folded away, and three tiles (Help / Orders / Refer a friend)
//  - each card: name, devices, status, end date, login + two buttons: Renew (the renew panel for TV lines) and Details
//    (everything else: password, server, app codes, setup, test my line, watch in browser, add devices, auto-renew,
//    listed first, "try the other server")
// Served at /dashboard after the owner's OK; the previous dashboard stays at /dashboard/classic for a week.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api, { ordersAPI, productsAPI, servicesAPI } from '../../api/api';
import { useAuthStore, useCartStore } from '../../store/store';
import { AccountHeader } from '../../components/cmtv/AccountShell';
import TelegramAlerts from '../../components/cmtv/TelegramAlerts';
import NuvioDevices from '../../components/cmtv/NuvioDevices';
import { webPlayerLink } from '../../components/cmtv/webPlayer';
import ResellerPanels from '../../components/cmtv/ResellerPanels';
import CmtvUpdates from '../../components/cmtv/CmtvUpdates';
import SpellOut from '../../components/cmtv/SpellOut';
import UpgradeDevices from '../../components/cmtv/UpgradeDevices';
import FeedbackBox from '../../components/cmtv/FeedbackBox';
import LineCheck from '../../components/cmtv/LineCheck';
import SwitchTrialOffer from '../../components/cmtv/SwitchTrialOffer';
import { ListedFirstControl } from '../../components/cmtv/ListedFirst';
import FormattedText from '../../components/cmtv/FormattedText';
import { paymentLabel } from '../../components/cmtv/paymentMethod';
import RenewPanel, { renewOptions } from '../../components/cmtv/RenewPanel';
import { pendingPlan } from '../../components/cmtv/pendingPlan';
import { describe, AutoRenewSwitch, fmtDate, copy, termText, SOON, DAY } from './CmtvDashboardPage';

const useQ = (key, fn, extra = {}) => useQuery({ queryKey: key, queryFn: fn, staleTime: 30000, ...extra });

function pillOf(d) {
  const warn = !d.ended && d.daysLeft !== null && d.daysLeft <= SOON;
  return d.ended ? (d.isTrial ? ['crit', 'Trial ended'] : d.s.status === 'suspended' ? ['crit', 'Suspended'] : ['crit', 'Expired'])
    : warn ? ['warn', `${d.daysLeft} day${d.daysLeft === 1 ? '' : 's'} left`] : ['good', d.isTrial ? 'Trial' : 'Active'];
}

// Everything that used to sit on the card, now behind "Details"
function Details({ d, autoRenewEnabled, onRenew }) {
  const [showPass, setShowPass] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const { s } = d;
  const tv = ['xtream', 'aether'].includes(s.panel_type) && s.account_type !== 'reseller';
  return (
    <div className="ca-details">
      {!d.ended && (d.username || d.server) && (
        <div className="ca-login">
          {d.username && <div className="ca-field"><label>Username</label><div className="val"><code>{d.username}</code>
            <button type="button" className="ca-icon" onClick={() => copy(d.username, 'Username')}>Copy</button></div><SpellOut value={d.username} label="username" /></div>}
          {d.password && <div className="ca-field"><label>Password</label><div className="val"><code>{showPass ? d.password : '••••••••'}</code>
            <button type="button" className="ca-icon" onClick={() => setShowPass(!showPass)}>{showPass ? 'Hide' : 'Show'}</button>
            <button type="button" className="ca-icon" onClick={() => copy(d.password, 'Password')}>Copy</button></div>{showPass && <SpellOut value={d.password} />}</div>}
          {d.server && <div className="ca-field"><label>Server</label><div className="val"><code>{d.server}</code>
            <button type="button" className="ca-icon" onClick={() => copy(d.server, 'Server')}>Copy</button></div></div>}
          {s.ghostapk_code && <div className="ca-field ca-ghost"><label>CMTVGhost code</label><div className="val"><code>{s.ghostapk_code}</code>
            <button type="button" className="ca-icon" onClick={() => copy(s.ghostapk_code, 'CMTVGhost code')}>Copy</button></div>
            <small className="ca-fieldnote">Open CMTVGhost and enter this code instead of your username and password.</small></div>}
          {s.cmtv_tivimate?.code && <div className="ca-field ca-ghost"><label>CMTivi code</label><div className="val"><code>{s.cmtv_tivimate.code}</code>
            <button type="button" className="ca-icon" onClick={() => copy(s.cmtv_tivimate.code, 'CMTivi code')}>Copy</button></div>
            <small className="ca-fieldnote">Enter this code when the CMTivi app asks for an activation code.</small></div>}
          {s.cockpit_module === 'nuviocloud' && d.username && <NuvioDevices username={d.username} />}
          {s.panel_type === 'aether' && s.account_type !== 'reseller' && <ListedFirstControl service={s} />}
        </div>
      )}
      <div className="ca-actions">
        {!d.ended && (d.setup ? (
          <button type="button" className="ca-btn ca-ghost" onClick={() => setShowSetup(!showSetup)}>{showSetup ? 'Hide setup' : 'Set up a device'}</button>
        ) : <Link className="ca-btn ca-ghost" to="/knowledge-base">Setup guides</Link>)}
        {!d.ended && webPlayerLink(s) && (
          <a className="ca-btn ca-ghost" href={webPlayerLink(s)} target="_blank" rel="noopener noreferrer">Watch in browser</a>
        )}
        {tv && <LineCheck service={s} onRenew={d.canRenew ? () => onRenew(d) : null} />}
        {!d.ended && !d.isTrial && tv && s.status === 'active' && <UpgradeDevices service={s} />}
        <AutoRenewSwitch d={d} enabled={autoRenewEnabled} />
      </div>
      {!d.ended && !d.isTrial && tv && s.status === 'active' && <SwitchTrialOffer service={s} />}
      {showSetup && d.setup && <div className="ca-setup"><FormattedText text={d.setup} /></div>}
    </div>
  );
}

function Card({ d, products, autoRenewEnabled, onRenew, compact, startRenewing }) {
  const [open, setOpen] = useState(false);
  const [renewing, setRenewing] = useState(!!startRenewing);
  useEffect(() => { if (startRenewing) setRenewing(true); }, [startRenewing]);
  const { s } = d;
  const pill = pillOf(d);
  const hasPanel = renewOptions(d, products).length > 0;
  const devices = s.max_connections || d.product?.max_connections;
  const title = d.family === 'cctv' ? `CCTV${devices ? ` · ${devices} device${Number(devices) === 1 ? '' : 's'}` : ''}`
    : d.family === 'imperium' ? `Imperium${devices ? ` · ${devices} device${Number(devices) === 1 ? '' : 's'}` : ''}` : (d.addonName || s.product_name);
  const renewLabel = d.isTrial ? `Keep it · $${d.rp.price.toFixed(0)}/${termText(d.rp.term)}` : 'Renew';
  const renew = () => (hasPanel ? setRenewing(!renewing) : onRenew(d));
  return (
    <article className={`ca-card ${d.family}${compact ? ' compact' : ''}${d.ended ? ' dim' : ''}`}>
      <div className="ca-card-top">
        {d.logo ? <img className="ca-card-logo" src={d.logo} alt="" /> : <span className="ca-card-logo ca-tile-sm" aria-hidden="true">{title.slice(0, 1)}</span>}
        <div className="ca-card-title">
          <b>{title}</b>
          <small>{d.expiry ? `${d.ended ? 'Ended' : (s.auto_renew || {}).status === 'ACTIVE' ? 'Renews' : 'Ends'} ${fmtDate(d.expiry)}` : s.product_name}
            {!d.ended && d.username && !compact ? ` · login ${d.username}` : ''}</small>
        </div>
        <span className={`ca-pill ${pill[0]}`}>{pill[1]}</span>
      </div>
      <div className="ca-card-btns">
        {d.canRenew && <button type="button" className={`ca-btn ${pill[0] !== 'good' ? 'ca-glow' : 'ca-ghost'}`} onClick={renew} aria-expanded={hasPanel ? renewing : undefined}>{renewLabel}</button>}
        {!d.canRenew && d.isTrial && !d.ended && ['cctv', 'imperium'].includes(d.family) && (
          <Link className="ca-btn ca-glow" to={`/?tab=${d.family}`}>Keep it · choose a plan</Link>
        )}
        {!d.canRenew && d.ended && <Link className="ca-btn ca-ghost" to="/">See plans</Link>}
        {!d.canRenew && !d.ended && s.account_type === 'reseller' && <Link className="ca-btn ca-ghost" to="/services">Manage</Link>}
        <button type="button" className="ca-btn ca-ghost" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide details' : 'Details'}</button>
      </div>
      {renewing && <RenewPanel d={d} products={products} onClose={() => setRenewing(false)} />}
      {open && <Details d={d} autoRenewEnabled={autoRenewEnabled} onRenew={onRenew} />}
    </article>
  );
}

// CMTV+ = one card for its parts (Audiobooks, CMTVpn, Nuvio), one renewal
function PlusCard({ parts, autoRenewEnabled, onRenew }) {
  const [open, setOpen] = useState(null);
  const first = parts[0];
  const end = parts.map((d) => d.expiry).filter(Boolean).sort((a, b) => a - b)[0];
  return (
    <article className="ca-card addons">
      <div className="ca-card-top">
        <span className="ca-card-logo ca-tile-sm" aria-hidden="true">+</span>
        <div className="ca-card-title"><b>CMTV+</b><small>{parts.map((d) => d.addonName).join(' · ')}{end ? ` · ends ${fmtDate(end)}` : ''}</small></div>
        <span className={`ca-pill ${pillOf(first)[0]}`}>{pillOf(first)[1]}</span>
      </div>
      <div className="ca-card-btns">
        {first.canRenew && <button type="button" className="ca-btn ca-ghost" onClick={() => onRenew(first)}>Renew CMTV+ · ${first.rp.price.toFixed(0)}/{termText(first.rp.term)}</button>}
      </div>
      <div className="ca-plus-parts">
        {parts.map((d) => (
          <div key={d.s.id}>
            <button type="button" className="ca-plus-row" aria-expanded={open === d.s.id} onClick={() => setOpen(open === d.s.id ? null : d.s.id)}>
              <span>{d.addonName}</span><span className="ca-linkish">{open === d.s.id ? 'Hide' : 'Details'}</span>
            </button>
            {open === d.s.id && <Details d={d} autoRenewEnabled={autoRenewEnabled} onRenew={onRenew} />}
          </div>
        ))}
      </div>
    </article>
  );
}

export default function CmtvDashboardV2() {
  const { user } = useAuthStore();
  const { addRenewalItem } = useCartStore();
  const navigate = useNavigate();
  const now = useMemo(() => new Date(), []);
  const services = useQ(['services'], async () => (await servicesAPI.getAll()).data || []);
  const products = useQ(['products'], async () => (await productsAPI.getAll()).data || [], { staleTime: 300000 });
  const groups = useQ(['product-groups-public'], async () => (await api.get('/api/product-groups')).data || [], { staleTime: 300000 });
  const orders = useQ(['orders'], async () => (await ordersAPI.getAll()).data || []);
  const tickets = useQ(['my-tickets'], async () => (await api.get('/api/tickets')).data || []);
  const tier = useQ(['cmtv-tier-me'], async () => (await api.get('/api/cmtv/referral/me')).data);
  const arCfg = useQ(['autorenew-config'], async () => (await api.get('/api/cmtv/autorenew/config')).data, { staleTime: 300000 });
  const [help, setHelp] = useState(false);
  // a plan picked on cmtv.info / the storefront before signing in: finish it (the storefront adds it and opens checkout)
  useEffect(() => { if (pendingPlan()) navigate('/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // the Telegram reminder's "Renew now" opens /dashboard?renew=<service id>: open that line's renew panel
  const [params, setParams] = useSearchParams();
  const renewId = params.get('renew');

  const cards = useMemo(() => {
    const byId = Object.fromEntries((products.data || []).map((p) => [p.id, p]));
    const groupsById = Object.fromEntries((groups.data || []).map((g) => [g.id, g.name]));
    return (services.data || []).filter((s) => !s.is_credit_addon && s.status !== 'failed' && s.status !== 'cancelled')
      .map((s) => describe(s, byId, groupsById, now))
      .sort((a, b) => ((a.daysLeft ?? 99999) - (b.daysLeft ?? 99999)));
  }, [services.data, products.data, groups.data, now]);
  const live = cards.filter((d) => !d.ended);
  const tv = live.filter((d) => ['cctv', 'imperium'].includes(d.family));
  const plus = live.filter((d) => d.s.cmtv_plus);
  const addons = live.filter((d) => !tv.includes(d) && !d.s.cmtv_plus);
  const ended = cards.filter((d) => d.ended && (!d.expiry || now - d.expiry < 60 * DAY));
  const autoRenew = !!arCfg.data?.enabled;
  const prods = products.data || [];

  const renew = (d) => {   // add-ons + CMTV+ (no length choice): the same plan, as before
    const p = d.renewWith;
    addRenewalItem({ product_id: p.id, product_name: p.name, term_months: d.rp.term, price: d.rp.price,
                     account_type: p.account_type || d.s.account_type }, d.s.id, 'extend');
    toast.success(`${p.name} added. It extends your current login.`);
    navigate('/checkout');
  };

  const alerts = [];
  live.filter((d) => d.daysLeft !== null && d.daysLeft <= SOON && (d.s.auto_renew || {}).status !== 'ACTIVE')
    .forEach((d) => alerts.push({ key: `soon-${d.s.id}`, kind: 'warn', title: `${d.family === 'addons' ? d.addonName : d.s.product_name} ends in ${d.daysLeft} day${d.daysLeft === 1 ? '' : 's'}`,
      action: ['Renew', () => (renewOptions(d, prods).length ? setParams({ renew: d.s.id }, { replace: true }) : renew(d))] }));
  (orders.data || []).filter((o) => o.status === 'pending' && Number(o.total) > 0).slice(0, 2)
    .forEach((o) => alerts.push({ key: `order-${o.id}`, kind: 'crit', title: `Order waiting for payment: $${Number(o.total).toFixed(2)}`,
      action: ['Pay now', () => navigate(`/pay/${o.id}`)] }));
  (tickets.data || []).filter((t) => t.status !== 'closed' && (t.messages || []).length && t.messages[t.messages.length - 1].is_admin)
    .slice(0, 2).forEach((t) => alerts.push({ key: `t-${t.id}`, kind: 'info', title: `Support replied to “${t.subject}”`, action: ['View reply', () => navigate('/tickets')] }));

  const firstName = (user?.name || '').trim().split(/\s+/)[0];
  const loading = services.isLoading || products.isLoading;
  const t = tier.data;
  const renewDone = useRef(false);
  useEffect(() => {
    if (!renewId || renewDone.current || loading) return;
    renewDone.current = true;
    const d = cards.find((c) => c.s.id === renewId);
    if (!d || !d.canRenew) { setParams({}, { replace: true }); toast.info("That service can't be renewed online. Pick a plan or contact us."); return; }
    if (!renewOptions(d, prods).length) renew(d);   // add-ons / CMTV+: straight to checkout as before
    else setTimeout(() => document.getElementById(`card-${d.s.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 300);
  }, [renewId, cards, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="cmtv-acct">
      <AccountHeader />
      <main className="ca-page ca-v2">
        <h1>{firstName ? `Hi ${firstName}` : 'Welcome back'}</h1>
        <p className="ca-sub">{loading ? 'Loading your services…' : live.length ? `${live.length} active service${live.length === 1 ? '' : 's'}` : ''}</p>
        <CmtvUpdates variant="dashboard" />
        <ResellerPanels />
        {alerts.length > 0 && (
          <section className="ca-attention" aria-label="Needs attention">
            {alerts.map((a) => (
              <div key={a.key} className={`ca-alert${a.kind === 'info' ? ' info' : a.kind === 'crit' ? ' crit' : ''}`}>
                <div className="msg"><b>{a.title}</b></div>
                <button type="button" className={`ca-btn ${a.kind === 'warn' ? 'ca-glow' : 'ca-ghost'}`} onClick={a.action[1]}>{a.action[0]}</button>
              </div>
            ))}
          </section>
        )}
        <TelegramAlerts variant="nudge" show={live.length > 0} />

        {!loading && cards.length === 0 ? (
          <div className="ca-empty">
            <h3>No services yet</h3>
            <p className="ca-note">Start with a free trial, or pick a plan. Your login arrives by email straight away.</p>
            <Link className="ca-btn ca-glow" to="/">Browse plans and free trials</Link>
          </div>
        ) : (<>
          {tv.length > 0 && <section aria-label="Your TV"><h2 className="ca-h2">Your TV</h2>
            <div className="ca-stack">{tv.map((d) => <div id={`card-${d.s.id}`} key={d.s.id}><Card d={d} products={prods} autoRenewEnabled={autoRenew} onRenew={renew} startRenewing={renewId === d.s.id} /></div>)}</div></section>}
          {plus.length > 0 && <section aria-label="CMTV+"><h2 className="ca-h2">CMTV+</h2>
            <div id={`card-${plus[0].s.id}`}><PlusCard parts={plus} autoRenewEnabled={autoRenew} onRenew={renew} /></div></section>}
          {addons.length > 0 && <section aria-label="Add-ons"><h2 className="ca-h2">Add-ons</h2>
            <div className="ca-stack">{addons.map((d) => <div id={`card-${d.s.id}`} key={d.s.id}><Card d={d} compact products={prods} autoRenewEnabled={autoRenew} onRenew={renew} /></div>)}</div></section>}
          {ended.length > 0 && (
            <details className="ca-ended"><summary>{ended.length} ended service{ended.length === 1 ? '' : 's'}</summary>
              <div className="ca-stack">{ended.map((d) => <Card key={d.s.id} d={d} compact products={prods} autoRenewEnabled={autoRenew} onRenew={renew} />)}</div>
              <Link className="ca-more" to="/services">All services →</Link>
            </details>
          )}
        </>)}

        <div className="ca-tiles">
          <button type="button" className="ca-tilebtn" aria-expanded={help} onClick={() => setHelp(!help)}><span aria-hidden="true">?</span>Help</button>
          <Link className="ca-tilebtn" to="/orders"><span aria-hidden="true">$</span>Orders</Link>
          <Link className="ca-tilebtn" to="/referrals"><span aria-hidden="true">+</span>{t && t.enabled !== false ? 'Refer, earn $15' : 'Referrals'}</Link>
        </div>
        {help && (
          <div className="ca-panel ca-helpbox">
            <p>Most answers are in <b>Details → Set up a device</b> on each service. For anything else:</p>
            <div className="ca-help">
              <a className="ca-btn ca-ghost" href="https://t.me/Cmtv_support_bot" target="_blank" rel="noopener noreferrer">Chat with our support bot</a>
              <Link className="ca-btn ca-ghost" to="/tickets">Open a ticket</Link>
            </div>
            <p style={{ marginTop: 10 }}><Link to="/knowledge-base/cmtv-buffering">Buffering? Quick fixes</Link> · <Link to="/status">Service status</Link>
              {' · '}<a href="https://www.youtube.com/@cmtvinfo" target="_blank" rel="noopener noreferrer">Video guides</a>
              {' · '}<Link to="/devices#picks">Recommended devices</Link> · <Link to="/gift">Gift cards</Link></p>
            <div style={{ marginTop: 12 }}><FeedbackBox /></div>
          </div>
        )}
        {(orders.data || []).length > 0 && <p className="ca-note ca-lastorder">Last order: {(orders.data[0].items || []).map((i) => i.product_name).join(', ')}
          {' · '}{fmtDate(orders.data[0].paid_at || orders.data[0].created_at)} · {paymentLabel(orders.data[0])}</p>}
      </main>
    </div>
  );
}
