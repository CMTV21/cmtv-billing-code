// CMTV local addition 2026-10-01: the CMTV Web Player (webplayer.cmtv.info) from the customer area.
// webPlayerLink(service) = a one-tap sign-in link for that TV line: /login#cmtv=<base64url JSON {u, p, s}>. The part after
// "#" is never sent to a server (not in any log); the web player reads it, removes it from the address bar and signs in.
// No link for Imperium (its video doesn't play in browsers yet: the provider's CDN has no CORS headers), add-ons or resellers.
export const WEBPLAYER = 'https://webplayer.cmtv.info';

const b64url = (text) => btoa(unescape(encodeURIComponent(text))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

// the web player's server names (its Admin > servers list); same rules as GuideLogin's serverOf
export function webPlayerServer(s) {
  if (!s || s.cockpit_module || s.panel_type === 'manual' || s.account_type === 'reseller') return null;
  const name = String(s.product_name || '').toLowerCase();
  if (['aether', 'nxtdash'].includes(s.panel_type) || name.includes('imperium')) return null;
  if (name.includes('amethyst')) return 'Amethyst';
  if (s.panel_type === 'onestream' || name.includes('extreme')) return 'Extreme';
  return 'CCTV';
}

export function webPlayerLink(s) {
  const server = webPlayerServer(s);
  const u = s && (s.xtream_username || s.username);
  const p = s && (s.xtream_password || s.password);
  if (!server || !u || !p) return null;
  return `${WEBPLAYER}/login#cmtv=${b64url(JSON.stringify({ u, p, s: server }))}`;
}
