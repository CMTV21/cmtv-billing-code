// CMTV local addition 2026-09-26: the customer dashboard (/dashboard), replacing the developer's DashboardPage
// (still in the code, unused). Mockup agreed with the user 2026-09-26.
// Fixes vs the old page: Renew really extends the service (addRenewalItem with the service id) at the product's real
// price and length (the old button put a $0, 1-month item in the cart as a NEW line); the "days left" bar uses the
// service's own term instead of assuming 30 days.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ReferralOfferLine, ReferralShare } from '../../components/cmtv/ReferralShare'; // 2026-10-05: referral offer + share
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import TelegramAlerts from '../../components/cmtv/TelegramAlerts'; // 2026-09-28: Telegram alerts panel
import NuvioDevices from '../../components/cmtv/NuvioDevices'; // 2026-09-29: devices on a Nuvio service card
import { webPlayerLink } from '../../components/cmtv/webPlayer'; // 2026-10-01: "Watch in browser"
import ResellerPanels from '../../components/cmtv/ResellerPanels'; // 2026-09-28: reseller login, balance, top-up slider
import CmtvUpdates from '../../components/cmtv/CmtvUpdates'; // 2026-09-28: latest CMTV Updates post
import SpellOut from '../../components/cmtv/SpellOut'; // 2026-10-04: I / l look-alikes spelled out
import UpgradeDevices from '../../components/cmtv/UpgradeDevices'; // 2026-10-04: add devices, prorated
import FeedbackBox from '../../components/cmtv/FeedbackBox'; // 2026-10-04: suggestions + leave a review
import LineCheck from '../../components/cmtv/LineCheck'; // 2026-10-04: Test my line
import { pendingPlan } from '../../components/cmtv/pendingPlan'; // 2026-09-28: plan picked before signing in
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import api, { ordersAPI, productsAPI, servicesAPI } from '../../api/api';
import { useAuthStore, useCartStore } from '../../store/store';
import { AccountHeader } from '../../components/cmtv/AccountShell';
import { BRAND, familyOf, lookup } from '../../components/cmtv/brand';
import FormattedText from '../../components/cmtv/FormattedText';
import { paymentLabel } from '../../components/cmtv/paymentMethod';

const DAY = 86400000;
const SOON = 7;
const MODULE_PRODUCT = { nuvio: 'Stremio', vpn: 'CMTVpn', audiobooks: 'CMTV Audiobooks', nuviocloud: 'Nuvio' };
const errText = (e, fb) => e?.response?.data?.detail || fb;
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '');
const termText = (m) => (m === 12 ? 'yr' : m === 1 ? 'mo' : `${m} mo`);
const firstPrice = (p) => {
  const [term, price] = Object.entries(p?.prices || {})[0] || ['1', 0];
  return { term: parseInt(term, 10) || 1, price: parseFloat(price) || 0 };
};
const copy = (text, label) => {
  const done = () => toast.success(`${label} copied`);
  try { navigator.clipboard.writeText(text).then(done, () => toast(text)); } catch (e) { toast(text); }
};

// Everything the card needs about one service, worked out once
function describe(s, productsById, groupsById, now) {
  const product = productsById[s.product_id];
  const paid = product?.cmtv_trial_of ? productsById[product.cmtv_trial_of] : null;   // a trial's paid product
  const groupName = groupsById[product?.group_id] || '';
  let family = familyOf(groupName);
  if (family === 'trials' || family === 'other') {
    if (s.cockpit_module || /stremio|vpn|audiobook|cmtv\+/i.test(s.product_name || '')) family = 'addons';
    else if (s.panel_type === 'aether' || /imperium/i.test(s.product_name || '')) family = 'imperium';
    else if (['xtream', 'xuione', 'nxtdash', 'onestream'].includes(s.panel_type) || /cctv|connection/i.test(s.product_name || '')) family = 'cctv';
  }
  const addonName = (paid || product)?.name || MODULE_PRODUCT[s.cockpit_module] || s.product_name;
  const logo = family === 'cctv' ? BRAND.cctvLogo : family === 'imperium' ? BRAND.imperiumLogo
    : family === 'addons' ? lookup(BRAND.logos, addonName) : null;
  const expiry = s.expiry_date ? new Date(s.expiry_date) : null;
  const start = s.start_date || s.created_at ? new Date(s.start_date || s.created_at) : null;
  const totalDays = start && expiry && expiry > start ? Math.max(1, Math.round((expiry - start) / DAY))
    : Math.round((s.term_months || firstPrice(product).term || 1) * 30.44);
  const daysLeft = expiry ? Math.ceil((expiry - now) / DAY) : null;
  const ended = s.status !== 'active' || (daysLeft !== null && daysLeft <= 0);
  const isTrial = !!(s.is_trial || product?.is_trial);
  // What "Renew" adds to the cart: the service's own product, or for a trial its paid product (same login)
  // 2026-10-05: a part of CMTV+ renews as CMTV+ (all three, one price), never on its own
  const plusProduct = s.cmtv_plus ? Object.values(productsById).find((p) => p.cmtv_plus) : null;
  const renewWith = plusProduct || (!isTrial ? product : paid);
  const rp = firstPrice(renewWith);
  const canRenew = !!renewWith && rp.price > 0 && s.account_type !== 'reseller' && !renewWith.is_bundle;
  // 2026-10-04: "Renew for a year and save" (same server + devices, 12-month price vs 12 months of the current plan)
  let yearly = null;
  if (canRenew && rp.term < 12 && renewWith.account_type === 'subscriber') {
    const y = Object.values(productsById).find((p) => p.panel_type === renewWith.panel_type && p.account_type === 'subscriber'
      && !p.is_trial && Number(p.max_connections) === Number(renewWith.max_connections) && firstPrice(p).term === 12 && firstPrice(p).price > 0);
    if (y) {
      const save = Math.round((rp.price / rp.term) * 12 - firstPrice(y).price);
      if (save > 0) yearly = { product: y, price: firstPrice(y).price, save, monthlyEquivalent: (firstPrice(y).price / 12) };
    }
  }
  const username = s.xtream_username || s.username || s.vpn_username;
  const password = s.xtream_password || s.password || s.vpn_password;
  const server = s.panel_type !== 'manual' ? s.streaming_url : null;
  const conns = s.max_connections || product?.max_connections;
  const subtitle = family === 'addons' ? (s.cmtv_plus ? ['Part of CMTV+', lookup(BRAND.taglines, addonName)].filter(Boolean).join(' · ') : (lookup(BRAND.taglines, addonName) || ''))
    : conns ? `${conns} device${conns === 1 ? '' : 's'} at once` : '';
  return { s, product, family, logo, addonName, expiry, daysLeft, totalDays, ended, isTrial, renewWith, rp, canRenew, yearly,
           username, password, server, subtitle, setup: s.setup_instructions || product?.setup_instructions || renewWith?.setup_instructions };
}

function AutoRenewSwitch({ d, enabled }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const ar = d.s.auto_renew || {};
  const on = ar.status === 'ACTIVE';
  const eligible = enabled && d.renewWith && !d.isTrial && d.rp.price > 0 && d.s.account_type !== 'reseller' && !d.s.cmtv_plus /* 2026-10-05 */
    && ['active', 'expired', 'suspended'].includes(d.s.status);
  if (!on && !eligible) return null;
  const start = async () => {
    setBusy(true);
    try {
      const { data } = await api.post('/api/cmtv/autorenew/start', { service_id: d.s.id, origin: window.location.origin });
      window.location.href = data.approve_url;
    } catch (e) { toast.error(errText(e, "Couldn't start auto-renew. Please try again.")); setBusy(false); }
  };
  const stop = async () => {
    setBusy(true);
    try {
      await api.post('/api/cmtv/autorenew/cancel', { service_id: d.s.id });
      toast.success("Auto-renew is off. We'll email you before it ends.");
      qc.invalidateQueries({ queryKey: ['services'] });
    } catch (e) { toast.error(errText(e, "Couldn't turn off auto-renew. Please try again.")); }
    setBusy(false); setConfirmOff(false);
  };
  if (confirmOff) {
    return (
      <span className="ca-confirm">Turn off auto-renew?
        <button type="button" className="ca-btn ca-danger" disabled={busy} onClick={stop}>Turn off</button>
        <button type="button" className="ca-btn ca-ghost" onClick={() => setConfirmOff(false)}>Keep on</button>
      </span>
    );
  }
  return (
    <button type="button" className="ca-toggle" aria-pressed={on} disabled={busy}
      title={on ? 'Renews automatically with PayPal the day before it ends'
        : 'Renew automatically with PayPal and pay 10% less (you approve it in PayPal; a lower member price wins)'}
      onClick={() => (on ? setConfirmOff(true) : start())}>
      {/* 2026-09-28: auto-renew is 10% off */}
      <span className="ca-switch" />{busy ? 'Opening PayPal…' : on ? 'Auto-renew' : 'Auto-renew · save 10%'}
    </button>
  );
}

function ServiceCard({ d, autoRenewEnabled, onRenew }) {
  const [showPass, setShowPass] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const { s } = d;
  const warn = !d.ended && d.daysLeft !== null && d.daysLeft <= SOON;
  const pill = d.ended ? (d.isTrial ? ['crit', 'Trial ended'] : s.status === 'suspended' ? ['crit', 'Suspended'] : ['crit', 'Expired'])
    : warn ? ['warn', `${d.daysLeft} day${d.daysLeft === 1 ? '' : 's'} left`] : ['good', d.isTrial ? 'Trial' : 'Active'];
  const pct = d.daysLeft === null ? 100 : Math.max(2, Math.min(100, (d.daysLeft / d.totalDays) * 100));
  const renewLabel = s.cmtv_plus ? `Renew CMTV+ · $${d.rp.price.toFixed(0)}/${termText(d.rp.term)}` /* 2026-10-05 */ : d.isTrial ? `Keep it · $${d.rp.price.toFixed(0)}/${termText(d.rp.term)}` : `Renew · $${d.rp.price.toFixed(d.rp.price % 1 ? 2 : 0)}/${termText(d.rp.term)}`;
  return (
    <article className={`ca-svc ${d.family}${d.ended ? ' dim' : ''}`}>
      <div className="ca-side">
        {d.logo ? <img src={d.logo} alt={d.family === 'addons' ? d.addonName : d.family.toUpperCase()} />
          : <div className="ca-tile" aria-hidden="true">{(d.addonName || s.product_name || '?').slice(0, 1)}</div>}
        <span className="ca-kind" style={d.family === 'imperium' ? { color: 'var(--gold)' } : undefined}>
          {d.family === 'cctv' ? 'CMTV Core' : d.family === 'imperium' ? 'Premium' : d.family === 'addons' ? 'Add-on' : 'Service'}
        </span>
      </div>
      <div className="ca-main">
        <div className="ca-top">
          <h3>{s.product_name}{d.subtitle && <small>{d.subtitle}</small>}</h3>
          <span className={`ca-pill ${pill[0]}`}>{pill[1]}</span>
        </div>
        {d.expiry && (
          <div className="ca-term">
            <div className="row">
              <span>{d.ended ? `Ended ${fmtDate(d.expiry)}` : `${(s.auto_renew || {}).status === 'ACTIVE' ? 'Renews' : 'Ends'} ${fmtDate(d.expiry)}`}</span>
              {!d.ended && <span>{d.daysLeft} of {d.totalDays} days left</span>}
            </div>
            {!d.ended && <div className={`ca-track${warn ? ' warn' : ''}`}><i style={{ width: `${pct}%` }} /></div>}
          </div>
        )}
        {!d.ended && (d.username || d.server) && (
          <div className="ca-login">
            {d.username && <div className="ca-field"><label>Username</label><div className="val"><code>{d.username}</code>
              <button type="button" className="ca-icon" onClick={() => copy(d.username, 'Username')}>Copy</button></div><SpellOut value={d.username} label="username" /></div>}
            {d.password && <div className="ca-field"><label>Password</label><div className="val"><code>{showPass ? d.password : '••••••••'}</code>
              <button type="button" className="ca-icon" onClick={() => setShowPass(!showPass)}>{showPass ? 'Hide' : 'Show'}</button>
              <button type="button" className="ca-icon" onClick={() => copy(d.password, 'Password')}>Copy</button></div>{showPass && <SpellOut value={d.password} />}</div>}
            {d.server && <div className="ca-field"><label>Server</label><div className="val"><code>{d.server}</code>
              <button type="button" className="ca-icon" onClick={() => copy(d.server, 'Server')}>Copy</button></div></div>}
            {/* 2026-09-29: the CMTVGhost app's login code (GhostAPK pin from the CCTV panel; cmtv_ghostapk.py fills older lines) */}
            {d.s.ghostapk_code && <div className="ca-field ca-ghost"><label>CMTVGhost code</label><div className="val"><code>{d.s.ghostapk_code}</code>
              <button type="button" className="ca-icon" onClick={() => copy(d.s.ghostapk_code, 'CMTVGhost code')}>Copy</button></div>
              <small style={{ display: 'block', color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>Open CMTVGhost and enter this code instead of your username and password.</small></div>}
            {/* 2026-10-02: activation code for CMTivi, CMTV's own TiviMate app (codes from its panel export, service.cmtv_tivimate) */}
            {d.s.cmtv_tivimate?.code && <div className="ca-field ca-ghost"><label>CMTivi code</label><div className="val"><code>{d.s.cmtv_tivimate.code}</code>
              <button type="button" className="ca-icon" onClick={() => copy(d.s.cmtv_tivimate.code, 'CMTivi code')}>Copy</button></div>
              <small style={{ display: 'block', color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>Enter this code when the CMTivi app asks for an activation code.</small></div>}
            {s.cockpit_module === 'nuviocloud' && d.username && <NuvioDevices username={d.username} />}
          </div>
        )}
        {d.ended && d.isTrial && !d.canRenew && (
          <p className="ca-note">{d.family === 'imperium' ? 'Liked it? Imperium adds catch-up, sports replay and 30,000 channels.' : 'Liked it? Pick a plan to keep watching.'}</p>
        )}
        <div className="ca-actions">
          {d.canRenew && (
            <button type="button" className={`ca-btn ${warn || d.ended ? 'ca-glow' : 'ca-ghost'}`} onClick={() => onRenew(d)}>{renewLabel}</button>
          )}
          {d.yearly && (
            <button type="button" className="ca-btn ca-glow" onClick={() => onRenew(d, d.yearly)}
              title={`$${d.yearly.monthlyEquivalent.toFixed(2)} a month instead of $${(d.rp.price / d.rp.term).toFixed(2)}`}>
              Renew for a year · ${d.yearly.price.toFixed(0)} (save ${d.yearly.save})
            </button>
          )}
          {!d.canRenew && d.ended && (
            <Link className={`ca-btn ${d.family === 'imperium' ? 'ca-gold' : 'ca-glow'}`} to="/">See plans</Link>
          )}
          {!d.canRenew && !d.ended && s.account_type === 'reseller' && <Link className="ca-btn ca-ghost" to="/services">Manage</Link>}
          {!d.ended && (d.setup ? (
            <button type="button" className="ca-btn ca-ghost" onClick={() => setShowSetup(!showSetup)}>{showSetup ? 'Hide setup' : 'Set up'}</button>
          ) : <Link className="ca-btn ca-ghost" to="/knowledge-base">Setup guides</Link>)}
          {/* 2026-10-01: one-tap sign-in to the CMTV Web Player (not Imperium yet: see webPlayer.js) */}
          {!d.ended && webPlayerLink(s) && (
            <a className="ca-btn ca-ghost" href={webPlayerLink(s)} target="_blank" rel="noopener noreferrer"
              title="Opens the CMTV Web Player, signed in with this line">Watch in browser</a>
          )}
          <AutoRenewSwitch d={d} enabled={autoRenewEnabled} />
          {['xtream', 'aether'].includes(s.panel_type) && s.account_type !== 'reseller'
            && <LineCheck service={s} onRenew={d.canRenew ? () => onRenew(d) : null} />}
          {!d.ended && !d.isTrial && ['xtream', 'aether'].includes(s.panel_type) && s.account_type !== 'reseller' && s.status === 'active'
            && <UpgradeDevices service={s} />}
        </div>
        {showSetup && d.setup && <div className="ca-setup"><FormattedText text={d.setup} /></div>}
      </div>
    </article>
  );
}

const useQ = (key, fn, extra = {}) => useQuery({ queryKey: key, queryFn: fn, staleTime: 30000, ...extra });

export default function CmtvDashboardPage() {
  const { user } = useAuthStore();
  const { addRenewalItem } = useCartStore();
  const navigate = useNavigate();
  const now = useMemo(() => new Date(), []);
  // a plan picked on cmtv.info / the storefront before signing in: finish it (the storefront adds it and opens checkout)
  useEffect(() => { if (pendingPlan()) navigate('/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const services = useQ(['services'], async () => (await servicesAPI.getAll()).data || []);
  const products = useQ(['products'], async () => (await productsAPI.getAll()).data || [], { staleTime: 300000 });
  const groups = useQ(['product-groups-public'], async () => (await api.get('/api/product-groups')).data || [], { staleTime: 300000 });
  const orders = useQ(['orders'], async () => (await ordersAPI.getAll()).data || []);
  const tickets = useQ(['my-tickets'], async () => (await api.get('/api/tickets')).data || []);
  const tier = useQ(['cmtv-tier-me'], async () => (await api.get('/api/cmtv/referral/me')).data);
  const refCode = useQ(['my-referral'], async () => (await api.get('/api/referral/my-code')).data);
  const arCfg = useQ(['autorenew-config'], async () => (await api.get('/api/cmtv/autorenew/config')).data, { staleTime: 300000 });

  const cards = useMemo(() => {
    const byId = Object.fromEntries((products.data || []).map((p) => [p.id, p]));
    const groupsById = Object.fromEntries((groups.data || []).map((g) => [g.id, g.name]));
    return (services.data || []).filter((s) => !s.is_credit_addon && s.status !== 'failed')
      .map((s) => describe(s, byId, groupsById, now))
      .sort((a, b) => (a.ended - b.ended) || ((a.daysLeft ?? 99999) - (b.daysLeft ?? 99999)));
  }, [services.data, products.data, groups.data, now]);
  const active = cards.filter((d) => !d.ended);
  // Ended services worth showing: anything from the last 60 days (older ones live on the Services page)
  const ended = cards.filter((d) => d.ended && (!d.expiry || now - d.expiry < 60 * DAY));

  const renew = (d, yearly = null) => {
    const p = yearly ? yearly.product : d.renewWith;   // 2026-10-04: "Renew for a year"
    addRenewalItem({ product_id: p.id, product_name: p.name, term_months: yearly ? 12 : d.rp.term, price: yearly ? yearly.price : d.rp.price,
                     account_type: p.account_type || d.s.account_type }, d.s.id, 'extend');
    toast.success(`${p.name} added. It extends your current login.`);
    navigate('/checkout');
  };

  // Needs attention
  const alerts = [];
  active.filter((d) => d.daysLeft !== null && d.daysLeft <= SOON && (d.s.auto_renew || {}).status !== 'ACTIVE')
    .forEach((d) => alerts.push({ kind: 'warn', key: `soon-${d.s.id}`, title: `${d.s.product_name} ends in ${d.daysLeft} day${d.daysLeft === 1 ? '' : 's'}`,
      note: 'Renew now and your login stays the same.', action: d.canRenew ? ['Renew', () => renew(d)] : ['See plans', () => navigate('/')] }));
  (orders.data || []).filter((o) => o.status === 'pending' && Number(o.total) > 0).slice(0, 2)
    .forEach((o) => alerts.push({ kind: 'crit', key: `order-${o.id}`, title: `Order waiting for payment: $${Number(o.total).toFixed(2)}`,
      note: `${(o.items || []).map((i) => i.product_name).join(', ')} · ${paymentLabel(o)}`, action: ['View order', () => navigate('/orders')] }));
  (tickets.data || []).filter((t) => t.status !== 'closed' && (t.messages || []).length && t.messages[t.messages.length - 1].is_admin)
    .slice(0, 2).forEach((t) => alerts.push({ kind: 'info', key: `t-${t.id}`, title: `Support replied to “${t.subject}”`,
      note: fmtDate(t.messages[t.messages.length - 1].created_at), action: ['View reply', () => navigate('/tickets')] }));

  const nextEnd = active.filter((d) => d.expiry && !d.isTrial).map((d) => d.expiry).sort((a, b) => a - b)[0];
  const firstName = (user?.name || '').trim().split(/\s+/)[0];
  const t = tier.data;
  const recent = (orders.data || []).filter((o) => o.status === 'paid' || o.status === 'pending').slice(0, 3);
  const loading = services.isLoading || products.isLoading;

  // 2026-09-28: the Telegram reminder's "Renew now" opens /dashboard?renew=<service id>: put that renewal in the cart
  const [params, setParams] = useSearchParams();
  const renewId = params.get('renew');
  const renewDone = useRef(false);
  useEffect(() => {
    if (!renewId || renewDone.current || loading) return;
    renewDone.current = true;
    const d = cards.find((c) => c.s.id === renewId);
    if (d && d.canRenew) renew(d);
    else { setParams({}, { replace: true }); toast.info('That service can\'t be renewed online. Pick a plan or contact us.'); }
  }, [renewId, cards, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="cmtv-acct">
      <AccountHeader />
      <main className="ca-page">
        <h1>{firstName ? `Welcome back, ${firstName}` : 'Welcome back'}</h1>
        <p className="ca-sub">
          {loading ? 'Loading your services…' : `${active.length} active service${active.length === 1 ? '' : 's'}`
            + (nextEnd ? ` · next renewal ${fmtDate(nextEnd)}` : '')}
        </p>

        <CmtvUpdates variant="dashboard" />
        <ResellerPanels />
        {alerts.length > 0 && (
          <section className="ca-attention" aria-label="Needs attention">
            {alerts.map((a) => (
              <div key={a.key} className={`ca-alert${a.kind === 'info' ? ' info' : a.kind === 'crit' ? ' crit' : ''}`}>
                <div className="msg"><b>{a.title}</b><small>{a.note}</small></div>
                <button type="button" className={`ca-btn ${a.kind === 'warn' ? 'ca-glow' : 'ca-ghost'}`} onClick={a.action[1]}>{a.action[0]}</button>
              </div>
            ))}
          </section>
        )}

        <div className="ca-layout">
          <section aria-label="Your services">
            <h2 className="ca-h2">Your services</h2>
            {!loading && cards.length === 0 ? (
              <div className="ca-empty">
                <h3>No services yet</h3>
                <p className="ca-note">Start with a free trial, or pick a plan. Your login arrives by email straight away.</p>
                <Link className="ca-btn ca-glow" to="/">Browse plans and free trials</Link>
              </div>
            ) : (
              <div className="ca-services">
                {[...active, ...ended].map((d) => (
                  <ServiceCard key={d.s.id} d={d} autoRenewEnabled={!!arCfg.data?.enabled} onRenew={renew} />
                ))}
              </div>
            )}
            {cards.length > active.length + ended.length && (
              <Link className="ca-more" to="/services">Older services →</Link>
            )}
          </section>

          <aside className="ca-rail" aria-label="Account summary">
            {t && t.enabled !== false && (
              <div className="ca-panel">
                <h2 className="ca-h2">Referrals</h2>
                <div className="ca-tier"><strong>{t.tier}</strong>
                  <span>{t.next ? `${t.count} of ${t.next.min} to ${t.next.name}` : `${t.count} referrals`}</span></div>
                <div className="ca-steps" aria-hidden="true">
                  {t.tiers.filter((x) => x.min > 0).map((x) => <div key={x.name} className={t.count >= x.min ? 'on' : ''} />)}
                </div>
                <p>{t.next ? <><b>{t.next.needs} more friend{t.next.needs === 1 ? '' : 's'}</b> and you get <b>{t.next.pct}% off everything</b>
                  {t.next.free_cmtv_plus ? ' plus CMTV+ free' : ''}. </> : <><b>{t.pct}% off everything</b>, applied automatically. </>}
                  <ReferralOfferLine /></p>{/* 2026-10-05 */}
                {refCode.data?.referral_code && (
                  <div className="ca-codebox"><code>{refCode.data.referral_code}</code>
                    <button type="button" className="ca-icon" onClick={() => copy(refCode.data.referral_link || refCode.data.referral_code, 'Referral link')}>Copy link</button></div>
                )}
                <ReferralShare link={refCode.data?.referral_link} />{/* 2026-10-05: share buttons */}
                <Link className="ca-more" to="/referrals">Your referrals →</Link>
              </div>
            )}
            {recent.length > 0 && (
              <div className="ca-panel">
                <h2 className="ca-h2">Recent orders</h2>
                <div className="ca-list">
                  {recent.map((o) => (
                    <div className="li" key={o.id}>
                      <span>{(o.items || []).map((i) => i.product_name).join(', ')}
                        <small>{fmtDate(o.paid_at || o.created_at)} · {o.status === 'pending' ? 'waiting for payment' : paymentLabel(o)}</small></span>
                      <span className="ca-amt">${Number(o.total || 0).toFixed(2)}</span>
                    </div>
                  ))}
                </div>
                <Link className="ca-more" to="/orders">All orders →</Link>
              </div>
            )}
            <TelegramAlerts />
            <FeedbackBox />
            <div className="ca-panel">
              <h2 className="ca-h2">Need help?</h2>
              <p>Most answers are in the setup steps on each service. For anything else:</p>
              <div className="ca-help">
                <a className="ca-btn ca-ghost" href="https://t.me/Cmtv_support_bot" target="_blank" rel="noopener noreferrer">Chat with our support bot</a>
                <Link className="ca-btn ca-ghost" to="/tickets">Open a ticket</Link>
              </div>
              {/* 2026-10-02 */}
              <p style={{ marginTop: 10 }}><Link to="/knowledge-base/cmtv-buffering">Buffering? Quick fixes</Link> · <Link to="/status">Service status</Link></p>
              {/* 2026-10-04: point people at the recommended devices before they buy (owner: no Firesticks) */}
              <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 12, border: '1px solid rgba(34,230,242,.35)', background: 'rgba(34,230,242,.07)' }}>
                <b>Thinking of buying a new device?</b>
                <p style={{ margin: '4px 0 8px', fontSize: 13.5 }}>We don't recommend buying a Firestick, especially the newest models.</p>
                <Link className="ca-btn ca-ghost" to="/devices#picks">See our recommended devices →</Link>
              </div>
              {/* 2026-10-05: gift cards */}
              <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 12, border: '1px solid rgba(139,92,246,.4)', background: 'rgba(139,92,246,.08)' }}>
                <b>Give CMTV 🎁</b>
                <p style={{ margin: '4px 0 8px', fontSize: 13.5 }}>Gift cards from $10, emailed now or on the day you pick. Got one? <Link to="/redeem">Redeem it</Link>.</p>
                <Link className="ca-btn ca-ghost" to="/gift">Send a gift card →</Link>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
