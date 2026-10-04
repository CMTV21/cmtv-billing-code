// CMTV local addition 2026-09-27: page titles, descriptions, link previews and search-engine rules for every page.
// Replaces the developer's SEOHead (still in the code, unused), which gave every page the same title and pointed every
// page's canonical/og:url at cmtv.info (the separate marketing site), where those paths don't exist.
// Home uses Admin > Settings > SEO (meta_title / meta_description / og_image, GA id, JSON-LD); other public pages use
// PAGES below; everything else (account, admin, checkout) is marked noindex. A page can set its own title/description
// with usePageMeta (the guides do, per article). public/index.html carries the same defaults for crawlers without JS.
import { useEffect, useReducer } from 'react';
import { useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';

const FALLBACK_IMAGE = '/cmtv/og-image.png';
const PAGES = {
  '/register': ['Create your account | CMTV', 'Create your CMTV account to start a free trial or order a plan. Canadian & US channels, add-ons and real support.'],
  '/login': ['Sign in | CMTV', 'Sign in to your CMTV account to manage your services, renew and get help.'],
  '/terms': ['Terms and Conditions | CMTV', 'The terms for using CMTV services: plans, renewals, trials, refunds and referrals.'],
  '/privacy': ['Privacy Policy | CMTV', 'What personal information CMTV collects, how it is used and shared, and your privacy choices.'],
  '/devices': ['Devices & apps | CMTV', 'Which app to use on your TV, phone or computer, and the streaming devices we recommend.'],   // 2026-10-04
  '/status': ['Service status | CMTV', 'Live status of every CMTV service, uptime for the last 30 days and recent incidents.'],   // 2026-10-02
  '/knowledge-base': ['Setup Guides & Help | CMTV', 'Step-by-step setup guides for Firestick, Android TV, Google TV, iPhone, iPad and PC, plus fixes for buffering and common problems.'],
};
const PRIVATE_TITLES = [
  ['/admin', 'Admin'], ['/dashboard', 'My account'], ['/services', 'My services'], ['/orders', 'Orders'], ['/invoices', 'Invoices'],
  ['/tickets', 'Support'], ['/referrals', 'Referrals'], ['/downloads', 'Downloads'], ['/checkout', 'Checkout'],
  ['/forgot-password', 'Reset your password'], ['/reset-password', 'Reset your password'],
];

let pageMeta = null;
const listeners = new Set();
const announce = () => listeners.forEach((f) => f());

export function usePageMeta(meta) {
  const key = meta ? JSON.stringify(meta) : '';
  useEffect(() => {
    if (!key) return undefined;
    pageMeta = JSON.parse(key);
    announce();
    return () => { pageMeta = null; announce(); };
  }, [key]);
}

function setMeta(attr, key, content) {
  let el = document.querySelector(`meta[${attr}="${key}"]`);
  if (!content) { if (el) el.remove(); return; }
  if (!el) { el = document.createElement('meta'); el.setAttribute(attr, key); document.head.appendChild(el); }
  el.setAttribute('content', content);
}

function setLink(rel, href) {
  let el = document.querySelector(`link[rel="${rel}"]`);
  if (!el) { el = document.createElement('link'); el.rel = rel; document.head.appendChild(el); }
  el.href = href;
}

const absolute = (url) => (/^https?:\/\//.test(url) ? url : window.location.origin + url);

export default function CmtvSEO() {
  const { pathname } = useLocation();
  const [, bump] = useReducer((x) => x + 1, 0);
  useEffect(() => { listeners.add(bump); return () => listeners.delete(bump); }, []);
  const { data: seo } = useQuery({
    queryKey: ['seo-settings'],
    queryFn: async () => (await api.get('/api/seo')).data,
    staleTime: 300000,
  });

  useEffect(() => {
    const s = seo || {};
    const path = pathname.replace(/\/+$/, '') || '/';
    let title; let desc; let index = true;
    if (path === '/') {
      title = s.meta_title; desc = s.meta_description;
    } else if (PAGES[path]) {
      [title, desc] = PAGES[path];
    } else if (path.startsWith('/knowledge-base/')) {
      [title, desc] = PAGES['/knowledge-base'];
    } else {
      index = false;
      const hit = PRIVATE_TITLES.find(([p]) => path === p || path.startsWith(`${p}/`));
      title = `${hit ? hit[1] : 'CMTV'} | CMTV`;
    }
    if (pageMeta) { title = pageMeta.title || title; desc = pageMeta.description || desc; }
    title = title || 'CMTV'; desc = desc || s.meta_description || '';
    const url = window.location.origin + (path === '/' ? '/' : path);
    const image = absolute(s.og_image || FALLBACK_IMAGE);

    document.title = title;
    setMeta('name', 'description', desc);
    setMeta('name', 'robots', index ? 'index, follow' : 'noindex, nofollow');
    setMeta('name', 'keywords', path === '/' ? s.meta_keywords : '');
    setMeta('property', 'og:title', path === '/' ? (s.og_title || title) : title);
    setMeta('property', 'og:description', path === '/' ? (s.og_description || desc) : desc);
    setMeta('property', 'og:image', image);
    setMeta('property', 'og:site_name', 'CMTV');
    setMeta('property', 'og:type', 'website');
    setMeta('property', 'og:url', url);
    setMeta('name', 'twitter:card', 'summary_large_image');
    setMeta('name', 'twitter:title', path === '/' ? (s.og_title || title) : title);
    setMeta('name', 'twitter:description', path === '/' ? (s.og_description || desc) : desc);
    setMeta('name', 'twitter:image', image);
    setLink('canonical', url);
    if (s.favicon_url) setLink('icon', s.favicon_url);

    if (s.schema_name && !document.querySelector('script[data-seo-schema]')) {
      const el = document.createElement('script');
      el.type = 'application/ld+json';
      el.setAttribute('data-seo-schema', 'true');
      const data = { '@context': 'https://schema.org', '@type': s.schema_type || 'Organization', name: s.schema_name,
        description: s.schema_description || '', url: s.schema_url || window.location.origin };
      if (s.schema_logo) data.logo = s.schema_logo;
      if (s.schema_email) data.email = s.schema_email;
      if (s.schema_phone) data.telephone = s.schema_phone;
      el.textContent = JSON.stringify(data);
      document.head.appendChild(el);
    }

    const ga = s.google_analytics_id;
    if (ga && /^[A-Z0-9-]+$/i.test(ga) && !document.querySelector(`script[src*="${ga}"]`)) {
      const tag = document.createElement('script');
      tag.async = true;
      tag.src = `https://www.googletagmanager.com/gtag/js?id=${ga}`;
      document.head.appendChild(tag);
      window.dataLayer = window.dataLayer || [];
      window.gtag = function gtag() { window.dataLayer.push(arguments); }; // eslint-disable-line prefer-rest-params
      window.gtag('js', new Date());
      window.gtag('config', ga);
    }
  });

  return null;
}
