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
  },
  // Short line under the logo on an add-on card
  taglines: {
    'CMTV+': 'Stream, secure, listen',
    'CMTVpn': 'Private, secure, connected',
    'CMTV Audiobooks': 'Any device, requests welcome',
    'Stremio': 'Works with the Nuvio app',
  },
  // Bundles: the card shows the saving against buying these products separately
  bundles: {
    'CMTV+': ['Stremio', 'CMTVpn', 'CMTV Audiobooks'],
  },
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
