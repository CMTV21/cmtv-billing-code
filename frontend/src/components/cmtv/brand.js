// CMTV local addition 2026-09-25: brand settings for the CMTV storefront (pages/cmtv/CmtvHomePage.js).
// Images live in frontend/public/cmtv/. Product names are matched case-insensitively.

export const BRAND = {
  siteLogo: '/cmtv/cmtv-logo.png',
  imperiumLogo: '/cmtv/imperium.png',
  cctvLogo: '/cmtv/cctv.png',
  // Logo shown on an add-on's card (product name -> image). Products without one get a gradient play tile.
  logos: {
    'CMTV+': '/cmtv/cmtv-plus.png',
    'CMTVpn': '/cmtv/cmtvpn.png',
    'CMTV Audiobooks': '/cmtv/cmtv-audiobooks.png',
    'Nuvio': '/cmtv/nuvio.png', // 2026-09-30
  },
  // Short line under the logo on an add-on card
  taglines: {
    'CMTV+': 'Stream, secure, listen',
    'CMTVpn': 'Private, secure, connected',
    'CMTV Audiobooks': 'Any device, requests welcome',
    'Nuvio': 'Profiles, cloud sync, made for TV', // 2026-09-30
    'Stremio': 'The classic Stremio app',
  },
  // Add-ons offered at checkout ("Complete your setup", components/cmtv/CheckoutAddons.js), bundle first
  addons: ['CMTV+', 'Nuvio', 'Stremio', 'CMTVpn', 'CMTV Audiobooks'],
  // Bundles: the card shows the saving against buying these products separately
  bundles: {
    'CMTV+': ['Nuvio', 'CMTVpn', 'CMTV Audiobooks'],
  },
  // 2026-09-30: while a product named Nuvio isn't on sale (hidden until launch), Stremio stands in for it in the
  // bundle's parts; once Nuvio is on sale the checkout offer shows Nuvio instead of Stremio (Stremio stays in the store)
  standIns: { 'Nuvio': 'Stremio' },
};

const norm = (s) => String(s || '').trim().toLowerCase();
export const lookup = (map, name) => {
  const key = Object.keys(map).find((k) => norm(k) === norm(name));
  return key ? map[key] : undefined;
};

// Which look a product group gets, from its name
export function familyOf(groupName) {
  const n = norm(groupName);
  if (/trial/.test(n)) return 'trials';
  if (/resell/.test(n)) return 'resellers';
  if (/imperium/.test(n)) return 'imperium';
  if (/cctv/.test(n)) return 'cctv';
  if (/add-?on/.test(n)) return 'addons';
  return 'other';
}

// 2026-09-30: a bundle's parts, given the add-on names on sale (a hidden part is replaced by its stand-in)
export function bundlePartsFor(bundleName, onSale) {
  const sale = new Set([...(onSale || [])].map(norm));
  return (lookup(BRAND.bundles || {}, bundleName) || []).map((n) => {
    if (sale.has(norm(n))) return n;
    const alt = lookup(BRAND.standIns || {}, n);
    return alt && sale.has(norm(alt)) ? alt : n;
  });
}
// Add-ons not offered at checkout because the one they stand in for is on sale (Stremio once Nuvio is)
export function replacedBy(onSale) {
  const sale = new Set([...(onSale || [])].map(norm));
  return Object.entries(BRAND.standIns || {}).filter(([n]) => sale.has(norm(n))).map(([, alt]) => norm(alt));
}
// "Nuvio, CMTVpn and Audiobooks"
export const partsText = (names) => names.map((n) => n.replace(/^CMTV (?=Audiobooks)/, ''))
  .join(', ').replace(/, ([^,]*)$/, ' and $1');
