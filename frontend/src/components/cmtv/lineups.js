// CMTV local addition 2026-09-29: Imperium channel line-ups (same keys as backend/cmtv_lineups.py). Same price for all.
export const LINEUPS = [
  { key: 'full', label: 'Full: all countries', short: null,
    note: 'Everything: USA, UK, Canada, PPV, 4K, 24/7, about 55 countries, and adult channels.' },
  { key: 'no_adult', label: 'Full: no adult channels', short: 'no adult',
    note: 'Everything in Full except the adult channels.' },
  { key: 'na', label: 'North America: US, UK, Canada + PPV', short: 'North America',
    note: 'USA, UK, Canada, Australia/NZ, PPV, 24/7 and 4K. Fewer channels to scroll, no adult, no international.' },
];
export const lineupName = (name, key) => {
  const l = LINEUPS.find((x) => x.key === key);
  return l && l.short ? `${name} (${l.short})` : name;
};
