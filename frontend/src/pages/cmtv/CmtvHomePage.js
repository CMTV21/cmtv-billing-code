// CMTV local addition 2026-09-25: the CMTV storefront (homepage). Replaces the developer's HomePage on "/" (see App.js);
// his HomePage.js is left untouched, so his updates to it can't clash with this design.
// Reuses the same data and flows: products + product groups from the API, the cart store, login redirect, checkout.
import React, { useMemo, useState } from 'react';
import { Link, useSearchParams, useLocation } from 'react-router-dom';
import SiteNav from '../../components/cmtv/SiteNav'; // 2026-10-01: site menu
import { rememberPlan, pendingPlan, pendingCredits, pendingExtra, forgetPlan } from '../../components/cmtv/pendingPlan'; // 2026-09-28
import ResellerCredits, { creditPrice } from '../../components/cmtv/ResellerCredits'; // 2026-09-28: any credit amount
import { LINEUPS, lineupName } from '../../components/cmtv/lineups'; // 2026-09-29: Imperium channel line-ups
import ChannelPicker, { customName } from '../../components/cmtv/ChannelPicker'; // 2026-09-30: pick your own channel groups
import api from '../../api/api';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { ShoppingCart, X, Info, Package } from 'lucide-react';
import { productsAPI } from '../../api/api';
import { useAuthStore, useCartStore } from '../../store/store';
import { useBrandingStore } from '../../store/branding';
import { useCurrencyStore } from '../../store/currency';
import CurrencySwitcher from '../../components/CurrencySwitcher';
import FormattedText from '../../components/cmtv/FormattedText';
import ServiceComparison from '../../components/cmtv/ServiceComparison';
import { BRAND, lookup, familyOf, bundlePartsFor } from '../../components/cmtv/brand';
import '../../components/cmtv/cmtv-theme.css';

const API_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
const TABS = [
  { key: 'all', label: 'All' },
  { key: 'cctv', label: 'CCTV' },
  { key: 'imperium', label: 'Imperium' },
  { key: 'addons', label: 'Add-ons' },
  { key: 'resellers', label: 'Resellers' },
];

const firstPrice = (p) => {
  const [term, price] = Object.entries(p?.prices || {})[0] || ['1', 0];
  return { term: parseInt(term, 10) || 1, price: parseFloat(price) || 0 };
};

// "1 month", "12 months", "24 hours" (trials), or the product name (reseller credit packs)
function termLabel(p) {
  if (p.is_trial) {
    let n = Number(p.trial_duration || p.duration || 0);
    let unit = String(p.trial_duration_unit || p.duration_unit || 'days').toLowerCase();
    if (unit.startsWith('day') && n > 0 && n <= 2) { n *= 24; unit = 'hours'; }
    if (n > 0 && unit.startsWith('hour')) return `${n} hours`;
    if (n > 0 && unit.startsWith('day')) return `${n} days`;
    return 'Free trial';
  }
  if (p.account_type === 'reseller') return p.name;
  const { term } = firstPrice(p);
  return term === 1 ? '1 month' : `${term} months`;
}

// First paragraph of a description (always shown) and the rest (behind "What's included")
function splitDescription(text) {
  const lines = String(text || '').replace(/\r/g, '').split('\n');
  const first = [];
  let i = 0;
  while (i < lines.length && lines[i].trim() === '') i += 1;
  for (; i < lines.length; i += 1) {
    const l = lines[i].trim();
    if (l === '' || /^[-•*]\s+/.test(l)) break;
    first.push(l);
  }
  return { intro: first.join('\n'), rest: lines.slice(i).join('\n').trim() };
}

function titleCase(name) {
  const s = String(name || '').trim();
  return s === s.toUpperCase() ? s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bCctv\b/g, 'CCTV') : s;
}

// 2026-10-02 (the owner): overall rating from the customer survey (GET /api/cmtv/survey/score, average stars of completed
// answers; hidden until 5+). Worded as a survey result, without the number of answers.
function SurveyScore() {
  const [stars, setStars] = React.useState(null);
  React.useEffect(() => { api.get('/api/cmtv/survey/score').then((r) => setStars(r.data.stars)).catch(() => {}); }, []);
  if (!stars) return null;
  return (
    <div style={{ margin: '-8px auto 20px', fontSize: 15, color: 'var(--muted)' }} aria-label={`Rated ${stars} out of 5 based on our customer survey`}>
      <span style={{ color: '#facc15', letterSpacing: 2 }} aria-hidden="true">★★★★★</span>{' '}
      <b style={{ color: 'var(--text, #e9edf8)' }}>{stars.toFixed(1)} out of 5</b> based on our customer survey
    </div>
  );
}

export default function CmtvHomePage() {
  const { user } = useAuthStore();
  const { items, addItem } = useCartStore();
  const { branding, fetchBranding } = useBrandingStore();
  // 2026-09-28: links from cmtv.info: ?tab=cctv|imperium|addons|resellers opens that tab, ?tab=trials scrolls to the
  // free trials, ?add=<product id> puts that plan in the cart and opens checkout (after sign-in if needed)
  const [params] = useSearchParams();
  const [tab, setTab] = useState(() => (['cctv', 'imperium', 'addons', 'resellers'].includes(params.get('tab')) ? params.get('tab') : 'all'));

  React.useEffect(() => { fetchBranding(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const { data: products, isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: async () => (await productsAPI.getAll()).data,
  });
  const { data: productGroups } = useQuery({
    queryKey: ['product-groups-public'],
    queryFn: async () => (await axios.get(`${API_URL}/api/product-groups`)).data,
  });

  // 2026-10-01: reseller credits only for existing / approved resellers (the server refuses everyone else too)
  const { data: resellerAccess } = useQuery({
    queryKey: ['reseller-access', user?.id || user?.email || ''], enabled: !!user, staleTime: 60000,
    queryFn: async () => (await api.get('/api/cmtv/reseller/access')).data,
  });
  // the store shows admins what customers see: the slider only for real resellers (existing panel or approved)
  const canResell = !!(resellerAccess?.existing || resellerAccess?.approved);

  // Groups in the admin's order, each with its cards (one per sub-group, or one per product)
  const groups = useMemo(() => {
    if (!products) return [];
    const list = products.filter((p) => canResell || p.account_type !== 'reseller');
    const byOrder = (a, b) => (a.display_order || 0) - (b.display_order || 0);
    const grps = [...(productGroups || [])].map((g, i) => ({ ...g, _i: i }))
      .sort((a, b) => (a.display_order ?? a._i) - (b.display_order ?? b._i) || a._i - b._i);
    const known = new Set(grps.map((g) => g.id));
    const out = [];
    grps.forEach((g) => {
      const prods = list.filter((p) => p.group_id === g.id).sort(byOrder);
      if (!prods.length) return;
      const subs = g.subgroups || [];
      let cards;
      if (subs.length) {
        cards = subs.map((sg) => ({ id: sg.id, name: sg.name, products: prods.filter((p) => p.subgroup_id === sg.id) }))
          .filter((c) => c.products.length);
        const subIds = new Set(subs.map((s) => s.id));
        prods.filter((p) => !subIds.has(p.subgroup_id)).forEach((p) => cards.push({ id: p.id, name: p.name, products: [p] }));
      } else {
        cards = prods.map((p) => ({ id: p.id, name: p.name, products: [p] }));
      }
      out.push({ id: g.id, name: g.name, family: familyOf(g.name), hasSubgroups: subs.length > 0, cards });
    });
    const rest = list.filter((p) => !p.group_id || !known.has(p.group_id)).sort(byOrder);
    if (rest.length) out.push({ id: 'other', name: '', family: 'other', hasSubgroups: false, cards: rest.map((p) => ({ id: p.id, name: p.name, products: [p] })) });
    return out;
  }, [products, productGroups, canResell]);

  // a plan chosen on cmtv.info (?add=) or picked here while signed out: cart + checkout once signed in
  const [focusPlan, setFocusPlan] = useState(null);   // 2026-09-30: plan opened from a cmtv.info link (highlighted)
  const addDone = React.useRef(false);
  React.useEffect(() => {
    if (!products || addDone.current) return;
    const id = params.get('add') || pendingPlan();
    if (!id) return;
    addDone.current = true;
    const credits = Number(params.get('credits')) || pendingCredits();   // a chosen reseller credit amount
    const extra = params.get('add') ? null : pendingExtra();   // choices made on a card before signing in (2026-09-30)
    const p = products.find((x) => x.id === id);
    if (!p) { forgetPlan(); return; }
    // 2026-09-30: a cmtv.info price link to an Imperium plan opens its card (line-up + channel choice) instead of checkout
    if (params.get('add') && p.panel_type === 'aether' && p.account_type === 'subscriber' && !p.is_trial) {
      setTab('imperium'); setFocusPlan(p.id); return;
    }
    if (!user) { rememberPlan(id, credits); window.location.href = '/login?redirect=/'; return; }
    forgetPlan();
    (async () => {
      if (credits && p.account_type === 'reseller') {
        // same price the server will charge (it recalculates at checkout)
        const pr = (await api.get('/api/cmtv/reseller/pricing')).data;
        const s = Object.values(pr.servers || {}).find((x) => x.product_id === p.id);
        const q = s ? creditPrice(s.tiers, credits) : null;
        if (s && q) {
          addItem({ product_id: p.id, product_name: `${s.label} Reseller Credits - ${credits} credits`, term_months: 1,
            price: q.total, account_type: 'reseller', credits });
          window.location.href = '/checkout';
          return;
        }
      }
      const { term, price } = firstPrice(p);
      addItem({ product_id: p.id, product_name: extra?.product_name || p.name, term_months: term, price, account_type: p.account_type,
                ...(extra?.lineup ? { lineup: extra.lineup } : {}), ...(extra?.bouquets ? { bouquets: extra.bouquets } : {}) });
      window.location.href = '/checkout';
    })();
  }, [products, user]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2026-10-01: the site menu (SiteNav) links here with ?tab= and &go=; follow them on every click (location.key),
  // also when already on the store: switch the tab, then scroll to the plans / trials / comparison / resellers
  const location = useLocation();
  const tabParam = params.get('tab');
  const goParam = params.get('go');
  React.useEffect(() => {
    if (['all', 'cctv', 'imperium', 'addons', 'resellers'].includes(tabParam)) setTab(tabParam);
    else if (tabParam === 'trials') setTab('all');
  }, [location.key]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    if (!groups.length || params.get('add')) return;
    const target = goParam || (tabParam === 'trials' ? 'trials' : tabParam ? 'plans' : null);
    const id = { trials: 'group-trials', compare: 'compare', resellers: 'group-resellers', plans: 'plans' }[target];
    if (!id) return;
    const t = setTimeout(() => { const el = document.getElementById(id); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 80);
    return () => clearTimeout(t);
  }, [groups.length, location.key]); // eslint-disable-line react-hooks/exhaustive-deps

  const tabs = TABS.filter((t) => t.key === 'all' || groups.some((g) => g.family === t.key));

  // What the selected tab shows. Trials follow their service (a CCTV trial shows under CCTV).
  const visible = groups.map((g) => {
    if (tab === 'all') return g;
    if (g.family === 'trials' && (tab === 'cctv' || tab === 'imperium' || tab === 'addons')) {
      // CMTV local change 2026-09-25: add-on trials (Stremio, CMTVpn, Audiobooks) show under Add-ons
      const cards = g.cards.filter((c) => new RegExp(tab === 'addons' ? 'stremio|nuvio|vpn|audiobook' : tab, 'i').test(c.name));
      return cards.length ? { ...g, cards } : null;
    }
    return g.family === tab ? g : null;
  }).filter(Boolean);
  const compareAt = (tab === 'all' || tab === 'cctv' || tab === 'imperium')
    ? visible.findIndex((g) => g.family === 'cctv' || g.family === 'imperium') : -1;

  const [lead, ...restTitle] = String(branding.hero_title || 'Premium streaming. Instant setup.').split('. ');
  const titleTail = restTitle.join('. ');

  return (
    <div className="cmtv">
      <header>
        <div className="wrap bar">
          <Link className="brand" to="/" aria-label={`${branding.site_name || 'CMTV'} home`}>
            <img src={BRAND.siteLogo} alt="" />
            <span>{branding.site_name || 'CMTV'}</span>
          </Link>
          <SiteNav />{/* 2026-10-01: site menu */}
          <span className="hide-sm"><CurrencySwitcher /></span>
          {user ? (
            <>
              <Link className="cart" to="/checkout" aria-label="Cart">
                <ShoppingCart className="w-5 h-5" />
                {items.length > 0 && <b>{items.length}</b>}
              </Link>
              <Link className="btn btn-glow" to="/dashboard">Dashboard</Link>
            </>
          ) : (
            <>
              <Link className="btn btn-ghost" to="/login">Sign in</Link>
              <Link className="btn btn-glow" to="/register">Sign up</Link>
            </>
          )}
        </div>
      </header>

      <div className="hero">
        <div className="wrap inner">
          <div className="eyebrow">Canadian streaming, set up in minutes</div>
          <h1>{titleTail ? <>{lead}. <em>{titleTail}</em></> : lead}</h1>
          <p>{branding.hero_description || 'Thousands of channels, movies, and series on every device.'}</p>
          <SurveyScore />{/* 2026-10-02 */}
          <a className="btn btn-glow" href="#plans" style={{ padding: '12px 26px', fontSize: 15 }}>View plans</a>
        </div>
      </div>

      <div className="wrap">
        <div className="features">
          {[1, 2, 3].map((n) => branding[`feature_${n}_title`] && (
            <div className="feature" key={n}>
              <h3>{branding[`feature_${n}_title`]}</h3>
              <p>{branding[`feature_${n}_description`]}</p>
            </div>
          ))}
        </div>
      </div>

      <section className="plans" id="plans">
        <div className="wrap">
          <h2>Choose your plan</h2>
          <p className="sub">Two services, one account. Pay once, get your login right away.</p>
          {tabs.length > 2 && (
            <div className="tabs" role="group" aria-label="Show plans for">
              {tabs.map((t) => (
                <button key={t.key} type="button" className="tab" aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
              ))}
            </div>
          )}

          {isLoading ? <div className="spinner" aria-label="Loading plans" /> : visible.length === 0 ? (
            tab === 'resellers' && !canResell ? null : <p className="empty">No plans to show here right now.</p>
          ) : visible.map((g, gi) => (
            <div key={g.id} id={`group-${g.family}`} style={{ scrollMarginTop: 80 }}>
              {gi === compareAt && <div id="compare" style={{ margin: '28px 0 8px', scrollMarginTop: 80 }}><ServiceComparison /></div>}
              {g.name && <div className={`family fam-${g.family}`}><span>{g.name}</span></div>}
              {g.hasSubgroups && (() => {
                const { intro } = splitDescription(g.cards[0]?.products[0]?.description);
                return intro ? <div className="family-desc"><FormattedText text={intro} /></div> : null;
              })()}
              {/* 2026-09-28: resellers get the credit slider only (the fixed packs stay in billing: the slider orders through them) */}
              {g.family === 'resellers' ? (
                <>{/* 2026-09-28: new resellers -> the Partner Program page on cmtv.info */}
                  <ResellerCredits />
                  <p style={{ margin: '4px 0 0', fontSize: 14, color: 'var(--muted)' }}>New to reselling?{' '}
                    <a href="https://cmtv.info/partners/" style={{ color: 'var(--cyan)', fontWeight: 700 }}>See what's included and our partner services &rarr;</a></p>
                </>
              ) : (
                <div className={g.family === 'trials' || g.family === 'addons' ? 'trial-grid' : 'stack'}>{/* 2026-10-01: trials + add-ons as tiles */}
                  {g.cards.map((c) => <PlanCard key={c.id} card={c} family={g.family} grouped={g.hasSubgroups} allProducts={products} focus={focusPlan} />)}
                </div>
              )}
            </div>
          ))}
          {/* 2026-10-01: reseller credits are for approved resellers only: everyone else gets the application link */}
          {!isLoading && !canResell && (tab === 'all' || tab === 'resellers') && (
            <div id="group-resellers" style={{ scrollMarginTop: 80 }}>
              <div className="family fam-resellers"><span>Resellers</span></div>
              <div className="trial-tile" style={{ alignItems: 'center', textAlign: 'center', borderTopColor: 'var(--violet)', maxWidth: 560, margin: '0 auto' }}>
                <p style={{ margin: 0, color: 'var(--muted)', fontSize: 14.5 }}>
                  Run your own customers with CMTV: wholesale credits, your own reseller panel and branded setup guides.
                  Reseller credits are for approved resellers.
                </p>
                <a className="btn btn-glow" href="https://cmtv.info/partners/" style={{ padding: '10px 22px' }}>Apply to be a reseller</a>
              </div>
            </div>
          )}
        </div>
      </section>

      <footer>{branding.footer_text || 'CMTV'} · <Link to="/terms" style={{ color: 'inherit' }}>Terms and Conditions</Link> · <Link to="/privacy" style={{ color: 'inherit' }}>Privacy Policy</Link></footer>{/* CMTV 2026-09-27: terms + privacy links */}
    </div>
  );
}

function PlanCard({ card, family, grouped, allProducts, focus }) {
  const { user } = useAuthStore();
  const { addItem } = useCartStore();
  const { symbol, convertPrice } = useCurrencyStore();
  const [open, setOpen] = useState(false);
  const [channels, setChannels] = useState(null);
  const [lineup, setLineup] = useState('full');   // 2026-09-29: Imperium channel line-up (same price)
  const [bouquets, setBouquets] = useState(null);   // 2026-09-30: the customer's own channel groups (null = the line-up's)
  const [vodApp, setVodApp] = useState('nuvio');   // 2026-09-30: CMTV+ movies & series app (Nuvio, or Stremio on request)
  const [more, setMore] = useState(false);   // 2026-10-01: "What's included" on an add-on tile
  const products = card.products;
  // 2026-09-30: line-up / channel choices by panel, so the trial cards (Trials group) get them too
  const impLine = products[0]?.panel_type === 'aether' && products[0]?.account_type === 'subscriber';
  const cctvLine = products[0]?.panel_type === 'xtream' && products[0]?.account_type === 'subscriber';
  // a paid plan starts from the line-up / channels the customer used on their trial
  const { data: myServices } = useQuery({
    queryKey: ['services'], enabled: !!user && (impLine || cctvLine) && !products[0]?.is_trial, staleTime: 60000,
    queryFn: async () => (await api.get('/api/services')).data || [],
  });
  const fromTrial = useMemo(() => {
    if (!Array.isArray(myServices)) return null;
    const panel = impLine ? 'aether' : 'xtream';
    return myServices.find((s) => s.panel_type === panel && s.is_trial && (s.cmtv_lineup || (s.cmtv_bouquets || []).length)) || null;
  }, [myServices, impLine]);
  const [trialApplied, setTrialApplied] = useState(false);
  const trialDone = React.useRef(false);
  React.useEffect(() => {   // line-up first; the picker then resets its groups, and this effect (parent, runs after it) sets them
    if (!fromTrial || trialDone.current) return;
    if (impLine && fromTrial.cmtv_lineup && fromTrial.cmtv_lineup !== lineup) { setLineup(fromTrial.cmtv_lineup); return; }
    trialDone.current = true;
    if ((fromTrial.cmtv_bouquets || []).length) setBouquets(fromTrial.cmtv_bouquets);
    setTrialApplied(true);
  }, [fromTrial, lineup, impLine]);
  const first = products[0];
  const money = (v) => `${symbol}${convertPrice(v).toFixed(2)}`;

  const monthly1 = products.map(firstPrice).find((fp) => fp.term === 1 && fp.price > 0)?.price;
  // 2026-09-30: parts as on sale now (Stremio stands in for Nuvio until Nuvio is switched on)
  const bundleOf = lookup(BRAND.bundles, first?.name) ? bundlePartsFor(first?.name, (allProducts || []).map((p) => p.name)) : null;
  const vodChoice = !!bundleOf && bundleOf.includes('Nuvio');
  const bundleTotal = bundleOf
    ? bundleOf.map((n) => allProducts?.find((p) => p.name.trim().toLowerCase() === n.toLowerCase())).filter(Boolean)
        .reduce((sum, p) => sum + firstPrice(p).price, 0)
    : 0;

  const { intro, rest } = splitDescription(first?.description);
  const showIntro = !grouped && intro;
  const details = grouped ? first?.description : rest;
  const conns = first?.max_connections || 1;
  const logo = family === 'addons' ? lookup(BRAND.logos, first?.name) : null;

  const cardRef = React.useRef(null);
  const focused = !!focus && products.some((p) => p.id === focus);
  React.useEffect(() => {   // 2026-09-30: opened from a cmtv.info price link
    if (focused && cardRef.current) setTimeout(() => cardRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' }), 150);
  }, [focused]);

  const buy = (p) => {
    const { term, price } = firstPrice(p);
    const withLineup = p.panel_type === 'aether' && p.account_type === 'subscriber';   // 2026-09-30: trials too
    const withGroups = p.panel_type === 'xtream' && p.account_type === 'subscriber';   // 2026-09-30: CCTV channel groups, trials too
    const withStremio = vodChoice && vodApp === 'stremio';   // 2026-09-30: shows on the order as "CMTV+ (with Stremio)"
    const name = withLineup ? customName(lineupName(p.name, lineup), bouquets) : withGroups ? customName(p.name, bouquets)
      : withStremio ? `${p.name} (with Stremio)` : p.name;
    const choices = withLineup ? { lineup, ...(bouquets ? { bouquets } : {}) } : withGroups && bouquets ? { bouquets } : {};
    // 2026-09-28: remember the plan through sign-in (it used to be forgotten); 2026-09-30: with its line-up/channel choices
    if (!user) { rememberPlan(p.id, null, { ...choices, product_name: name }); window.location.href = '/login?redirect=/'; return; }
    addItem({ product_id: p.id, product_name: name, term_months: term, price, account_type: p.account_type, ...choices });
    window.location.href = '/checkout';
  };
  const showChannels = async () => {
    setChannels('loading');
    try { setChannels((await axios.get(`${API_URL}/api/products/${first.id}/channels`)).data.channels || []); }
    catch { setChannels([]); }
  };

  // 2026-10-01: free trials and add-ons as compact tiles (the owner found the full cards too bulky); same buy() and choices
  if ((family === 'trials' || family === 'addons') && products.length === 1) {
    const isAddon = family === 'addons';
    const paidOf = (allProducts || []).find((p) => p.id === first.cmtv_trial_of);
    const service = isAddon ? first.name : impLine ? 'Imperium' : cctvLine ? 'CCTV'
      : (paidOf?.name || String(first.name).replace(/\s*\d+[- ]?(day|hour)s?\s*trial$/i, '').trim());
    const tlogo = impLine ? BRAND.imperiumLogo : cctvLine ? BRAND.cctvLogo : lookup(BRAND.logos, service);
    const summary = String(intro || first.description || '').split('\n')[0].replace(/^\*\*[^*]+\*\*:\s*/, '').replace(/\*\*/g, '');
    const hasOptions = impLine || cctvLine || vodChoice;
    const { term, price } = firstPrice(first);
    const free = first.is_trial && price === 0;
    const tagline = isAddon ? lookup(BRAND.taglines, first.name) : null;
    const meta = isAddon ? (tagline || termLabel(first))
      : `${termLabel(first)}${first.panel_type !== 'manual' ? ` · ${conns} connection${conns !== 1 ? 's' : ''}` : ''}`;
    return (
      <div className={`trial-tile${impLine ? ' t-imperium' : cctvLine ? ' t-cctv' : isAddon ? ' t-addon' : ''}`} ref={cardRef}
        style={focused ? { boxShadow: '0 0 0 2px var(--gold, #d8b35a)' } : undefined}>
        <div className="t-head">
          {tlogo ? <img src={tlogo} alt="" /> : <div className="play-tile" aria-hidden="true" />}
          <div>
            <h4>{service}</h4>
            <div className="t-meta">{meta}</div>
          </div>
          {free ? <span className="t-free">FREE</span> : (
            <span className="t-price">{money(price)}<small>/{term === 12 ? 'year' : term === 1 ? 'month' : `${term} mo`}</small></span>
          )}
        </div>
        {summary && <p className="t-sum">{summary.charAt(0).toUpperCase() + summary.slice(1)}</p>}
        {bundleTotal > price && (
          <p className="t-bundle">{money(bundleTotal)} if bought separately · <b>save {Math.round((1 - price / bundleTotal) * 100)}%</b></p>
        )}
        {(hasOptions || (isAddon && details)) && (
          <div className="t-links">
            {hasOptions && (
              <button type="button" className="t-opts-btn" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
                {open ? 'Hide options' : impLine ? 'Options: line-up & channels' : cctvLine ? 'Options: pick your channels' : 'Options: movies & series app'}
                {bouquets && !open ? ' · customised' : impLine && lineup !== 'full' && !open ? ' · changed' : vodChoice && vodApp !== 'nuvio' && !open ? ' · Stremio' : ''}
              </button>
            )}
            {isAddon && details && (
              <button type="button" className="t-link" aria-expanded={more} onClick={() => setMore((v) => !v)}>
                <Package className="w-3.5 h-3.5" /> {more ? 'Hide details' : "What's included"}
              </button>
            )}
          </div>
        )}
        {more && details && <div className="t-details"><FormattedText text={details} /></div>}
        {vodChoice && open && (
          <div className="t-opts">
            <label className="lineup" style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 13, color: 'var(--muted)' }}>
              <span style={{ fontWeight: 700, color: 'var(--text)' }}>Movies &amp; series app</span>
              <select value={vodApp} onChange={(e) => setVodApp(e.target.value)} aria-label="Movies and series app"
                style={{ background: 'var(--deep, #0a1020)', color: 'var(--text, #e9edf8)', border: '1px solid var(--cyan, #22e6f2)', borderRadius: 10, padding: '7px 9px', fontSize: 14 }}>
                <option value="nuvio">Nuvio (recommended)</option>
                <option value="stremio">Stremio</option>
              </select>
              <small>{vodApp === 'nuvio' ? 'Profiles, cloud sync, made for TV.' : 'The classic Stremio app.'} Same price.</small>
            </label>
          </div>
        )}
        {(impLine || cctvLine) && open && (
          <div className="t-opts">
            {impLine && (
              <label className="lineup" style={{ display: 'flex', flexDirection: 'column', gap: 5, margin: '0 0 8px', fontSize: 13, color: 'var(--muted)' }}>
                <span style={{ fontWeight: 700, color: 'var(--text)' }}>Channel line-up</span>
                <select value={lineup} onChange={(e) => setLineup(e.target.value)} aria-label="Channel line-up"
                  style={{ background: 'var(--deep, #0a1020)', color: 'var(--text, #e9edf8)', border: '1px solid var(--gold, #d8b35a)', borderRadius: 10, padding: '7px 9px', fontSize: 14 }}>
                  {LINEUPS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
                </select>
                <small>{LINEUPS.find((l) => l.key === lineup)?.note}</small>
              </label>
            )}
            {impLine && <ChannelPicker productId={first.id} lineup={lineup} value={bouquets} onChange={setBouquets} />}
            {cctvLine && <ChannelPicker source="cctv" productId={first.id} value={bouquets} onChange={setBouquets} />}
            {first.show_channels !== false && (
              <button type="button" className="t-link" onClick={showChannels}><Info className="w-3.5 h-3.5" /> View channels</button>
            )}
          </div>
        )}
        <button type="button" className="btn btn-glow t-go" onClick={() => buy(first)}>{free ? 'Start free trial' : `Get ${service}`}</button>
        {channels !== null && (
          <div className="modal-bg" onClick={() => setChannels(null)}>
            <div className="modal" role="dialog" aria-label={`${service} channels`} onClick={(e) => e.stopPropagation()}>
              <header><h3>{service} channels</h3><button type="button" aria-label="Close" onClick={() => setChannels(null)}><X className="w-5 h-5" /></button></header>
              {channels === 'loading' ? <div className="spinner" /> : channels.length ? (
                <div className="list">{channels.map((ch) => <div key={ch.id}>{ch.name}</div>)}</div>
              ) : <p className="empty">Channel list not available.</p>}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`card card-${family}`} ref={cardRef} style={focused ? { boxShadow: '0 0 0 2px var(--gold, #d8b35a)' } : undefined}>
      <div className="side">
        {family === 'cctv' && <img src={BRAND.cctvLogo} alt="CCTV" />}
        {family === 'imperium' && <img src={BRAND.imperiumLogo} alt="Imperium" />}
        {family === 'imperium' && <span className="badge">Premium</span>}
        {family === 'trials' && <span className="badge">Trial</span>}
        {family === 'addons' && (logo ? <img src={logo} alt={first.name} /> : <div className="play-tile" aria-hidden="true" />)}
        {!(family === 'addons' && logo) && <h4 style={family === 'imperium' ? { marginTop: 8 } : undefined}>{titleCase(card.name)}</h4>}
        {family === 'addons' && lookup(BRAND.taglines, first?.name) && <div className="tag">{lookup(BRAND.taglines, first.name)}</div>}
        {products.length > 1 && <small>{products.length} plans available</small>}
        {(family === 'cctv' || family === 'trials' || family === 'other') && first?.account_type !== 'reseller' && first?.panel_type !== 'manual' && (
          <div className="conn">{conns} connection{conns !== 1 ? 's' : ''}</div>
        )}
        {family === 'resellers' && first?.reseller_credits > 0 && <div className="conn">{first.reseller_credits} credits</div>}
      </div>
      <div className="rows">
        {showIntro && <div className="desc"><FormattedText text={intro} /></div>}
        {focused && <p style={{ margin: '0 0 10px', fontSize: 13, color: 'var(--gold, #d8b35a)', fontWeight: 700 }}>Choose your channel line-up, then tap your plan below.</p>}
        {trialApplied && <p style={{ margin: '0 0 8px', fontSize: 12.5, color: 'var(--muted)' }}>Set to match your trial. Change it if you like.</p>}
        {impLine && (
          <label className="lineup" style={{ display: 'flex', flexDirection: 'column', gap: 5, margin: '0 0 10px', fontSize: 13, color: 'var(--muted)' }}>
            <span style={{ fontWeight: 700, color: 'var(--text)' }}>Channel line-up</span>
            <select value={lineup} onChange={(e) => setLineup(e.target.value)} aria-label="Channel line-up"
              style={{ background: 'var(--deep, #0a1020)', color: 'var(--text, #e9edf8)', border: '1px solid var(--gold, #d8b35a)', borderRadius: 10, padding: '8px 10px', fontSize: 14 }}>
              {LINEUPS.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
            </select>
            <small>{LINEUPS.find((l) => l.key === lineup)?.note} Same price.</small>
          </label>
        )}
        {impLine && (
          <ChannelPicker productId={first.id} lineup={lineup} value={bouquets} onChange={setBouquets} />
        )}
        {cctvLine && (
          <ChannelPicker source="cctv" productId={first.id} value={bouquets} onChange={setBouquets} />
        )}
        {vodChoice && (
          <label className="lineup" style={{ display: 'flex', flexDirection: 'column', gap: 5, margin: '0 0 10px', fontSize: 13, color: 'var(--muted)' }}>
            <span style={{ fontWeight: 700, color: 'var(--text)' }}>Movies &amp; series app</span>
            <select value={vodApp} onChange={(e) => setVodApp(e.target.value)} aria-label="Movies and series app"
              style={{ background: 'var(--deep, #0a1020)', color: 'var(--text, #e9edf8)', border: '1px solid var(--cyan, #22e6f2)', borderRadius: 10, padding: '8px 10px', fontSize: 14 }}>
              <option value="nuvio">Nuvio (recommended)</option>
              <option value="stremio">Stremio</option>
            </select>
            <small>{vodApp === 'nuvio' ? 'Profiles, cloud sync, made for TV.' : 'The classic Stremio app.'} Same price.</small>
          </label>
        )}
        {products.map((p) => {
          const { term, price } = firstPrice(p);
          const perMonth = term > 1 && price > 0 ? price / term : null;
          const save = perMonth && monthly1 ? Math.round((1 - perMonth / monthly1) * 100) : null;
          return (
            <button key={p.id} type="button" className="row" onClick={() => buy(p)}
              style={focus === p.id ? { outline: '2px solid var(--gold, #d8b35a)', outlineOffset: -2 } : undefined}>
              <span className="term">{termLabel(p)}</span>
              <span className="right">
                {perMonth && p.account_type !== 'reseller' && (
                  <span className="permo">{money(perMonth)}/mo{save > 0 && <> · <b>save {save}%</b></>}</span>
                )}
                <span className="price">{p.is_trial && price === 0 ? 'FREE' : money(price)}</span>
              </span>
            </button>
          );
        })}
        {bundleTotal > firstPrice(first).price && (
          <div className="bundle">
            {bundleOf.join(', ').replace(/, ([^,]*)$/, ' and $1')} together: {money(bundleTotal)} if bought separately,
            {' '}<b style={{ color: '#86efac' }}>save {Math.round((1 - firstPrice(first).price / bundleTotal) * 100)}%</b>.
          </div>
        )}
        {open && details && <div className="details"><FormattedText text={details} /></div>}
        <div className="more">
          {details && (
            <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
              <Package className="w-3.5 h-3.5" /> {open ? 'Hide details' : "What's included"}
            </button>
          )}
          {first?.account_type === 'subscriber' && first?.show_channels !== false && family !== 'addons' && (
            <button type="button" onClick={showChannels}><Info className="w-3.5 h-3.5" /> View channels</button>
          )}
        </div>
      </div>

      {channels !== null && (
        <div className="modal-bg" onClick={() => setChannels(null)}>
          <div className="modal" role="dialog" aria-label={`${card.name} channels`} onClick={(e) => e.stopPropagation()}>
            <header><h3>{titleCase(card.name)} channels</h3><button type="button" aria-label="Close" onClick={() => setChannels(null)}><X className="w-5 h-5" /></button></header>
            {channels === 'loading' ? <div className="spinner" /> : channels.length ? (
              <div className="list">{channels.map((ch) => <div key={ch.id}>{ch.name}</div>)}</div>
            ) : <p className="empty">Channel list not available.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
