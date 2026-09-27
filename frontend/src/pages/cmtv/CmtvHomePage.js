// CMTV local addition 2026-09-25: the CMTV storefront (homepage). Replaces the developer's HomePage on "/" (see App.js);
// his HomePage.js is left untouched, so his updates to it can't clash with this design.
// Reuses the same data and flows: products + product groups from the API, the cart store, login redirect, checkout.
import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
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
import { BRAND, lookup, familyOf } from '../../components/cmtv/brand';
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

export default function CmtvHomePage() {
  const { user } = useAuthStore();
  const { items } = useCartStore();
  const { branding, fetchBranding } = useBrandingStore();
  const [tab, setTab] = useState('all');

  React.useEffect(() => { fetchBranding(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const { data: products, isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: async () => (await productsAPI.getAll()).data,
  });
  const { data: productGroups } = useQuery({
    queryKey: ['product-groups-public'],
    queryFn: async () => (await axios.get(`${API_URL}/api/product-groups`)).data,
  });

  // Groups in the admin's order, each with its cards (one per sub-group, or one per product)
  const groups = useMemo(() => {
    if (!products) return [];
    const list = [...products];
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
  }, [products, productGroups]);

  const tabs = TABS.filter((t) => t.key === 'all' || groups.some((g) => g.family === t.key));

  // What the selected tab shows. Trials follow their service (a CCTV trial shows under CCTV).
  const visible = groups.map((g) => {
    if (tab === 'all') return g;
    if (g.family === 'trials' && (tab === 'cctv' || tab === 'imperium' || tab === 'addons')) {
      // CMTV local change 2026-09-25: add-on trials (Stremio, CMTVpn, Audiobooks) show under Add-ons
      const cards = g.cards.filter((c) => new RegExp(tab === 'addons' ? 'stremio|vpn|audiobook' : tab, 'i').test(c.name));
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
            <p className="empty">No plans to show here right now.</p>
          ) : visible.map((g, gi) => (
            <div key={g.id}>
              {gi === compareAt && <div style={{ margin: '28px 0 8px' }}><ServiceComparison /></div>}
              {g.name && <div className={`family fam-${g.family}`}><span>{g.name}</span></div>}
              {g.hasSubgroups && (() => {
                const { intro } = splitDescription(g.cards[0]?.products[0]?.description);
                return intro ? <div className="family-desc"><FormattedText text={intro} /></div> : null;
              })()}
              <div className="stack">
                {g.cards.map((c) => <PlanCard key={c.id} card={c} family={g.family} grouped={g.hasSubgroups} allProducts={products} />)}
              </div>
            </div>
          ))}
        </div>
      </section>

      <footer>{branding.footer_text || 'CMTV'} · <Link to="/terms" style={{ color: 'inherit' }}>Terms and Conditions</Link></footer>{/* CMTV 2026-09-27: terms link */}
    </div>
  );
}

function PlanCard({ card, family, grouped, allProducts }) {
  const { user } = useAuthStore();
  const { addItem } = useCartStore();
  const { symbol, convertPrice } = useCurrencyStore();
  const [open, setOpen] = useState(false);
  const [channels, setChannels] = useState(null);
  const products = card.products;
  const first = products[0];
  const money = (v) => `${symbol}${convertPrice(v).toFixed(2)}`;

  const monthly1 = products.map(firstPrice).find((fp) => fp.term === 1 && fp.price > 0)?.price;
  const bundleOf = lookup(BRAND.bundles, first?.name);
  const bundleTotal = bundleOf
    ? bundleOf.map((n) => allProducts?.find((p) => p.name.trim().toLowerCase() === n.toLowerCase())).filter(Boolean)
        .reduce((sum, p) => sum + firstPrice(p).price, 0)
    : 0;

  const { intro, rest } = splitDescription(first?.description);
  const showIntro = !grouped && intro;
  const details = grouped ? first?.description : rest;
  const conns = first?.max_connections || 1;
  const logo = family === 'addons' ? lookup(BRAND.logos, first?.name) : null;

  const buy = (p) => {
    if (!user) { window.location.href = '/login'; return; }
    const { term, price } = firstPrice(p);
    addItem({ product_id: p.id, product_name: p.name, term_months: term, price, account_type: p.account_type });
    window.location.href = '/checkout';
  };
  const showChannels = async () => {
    setChannels('loading');
    try { setChannels((await axios.get(`${API_URL}/api/products/${first.id}/channels`)).data.channels || []); }
    catch { setChannels([]); }
  };

  return (
    <div className={`card card-${family}`}>
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
        {products.map((p) => {
          const { term, price } = firstPrice(p);
          const perMonth = term > 1 && price > 0 ? price / term : null;
          const save = perMonth && monthly1 ? Math.round((1 - perMonth / monthly1) * 100) : null;
          return (
            <button key={p.id} type="button" className="row" onClick={() => buy(p)}>
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
