// CMTV local addition 2026-10-16: plain names for order items on My Orders (pages/OrdersPage.js), e.g.
// "1 Connection 1 Month" -> "CCTV · 1 month · 1 connection", "Imperium 3 months 2 connections (North America)" ->
// "Imperium · 3 months · 2 connections · North America", "24 HOUR CCTV TRIAL" -> "CCTV · 24-hour free trial".
// Only the wording changes; anything it doesn't recognise is shown as before.
const SERVERS = { xtream: 'CCTV', aether: 'Imperium' };
const plural = (n, word) => `${n} ${word}${Number(n) === 1 ? '' : 's'}`;
const termText = (m) => (Number(m) === 12 ? '1 year' : plural(m, 'month'));
// " (North America) · custom channels (14 groups)" -> " · North America · custom channels (14 groups)"
const extras = (rest) => {
  const r = String(rest || '').trim().replace(/^\(([^)]*)\)/, '$1').replace(/^·\s*/, '');
  return r ? ` · ${r}` : '';
};

export function plainItemName(item, productsById) {
  const name = String(item?.product_name || '').trim();
  const product = productsById?.[item?.product_id];
  let m = name.match(/^(\d+) Connections? (\d+) Months?\s*(.*)$/i);   // CCTV plans
  if (m && product && SERVERS[product.panel_type]) {
    return `${SERVERS[product.panel_type]} · ${termText(m[2])} · ${plural(m[1], 'connection')}${extras(m[3])}`;
  }
  m = name.match(/^Imperium (\d+) months? (\d+) connections?\s*(.*)$/i) || name.match(/^Imperium (\d+) Connections? - (\d+) Months?\s*(.*)$/i);
  if (m) {
    const [months, conns] = /^Imperium \d+ months?/i.test(name) ? [m[1], m[2]] : [m[2], m[1]];
    return `Imperium · ${termText(months)} · ${plural(conns, 'connection')}${extras(m[3])}`;
  }
  m = name.match(/^24 HOUR CCTV TRIAL\s*(.*)$/i);
  if (m) return `CCTV · 24-hour free trial${extras(m[1])}`;
  m = name.match(/^Imperium (\d+) hour Trial\s*(.*)$/i);
  if (m) return `Imperium · ${m[1]}-hour free trial${extras(m[2])}`;
  m = name.match(/^(.+?) 7-Day Trial$/i);
  if (m) return `${m[1]} · 7-day free trial`;
  // yearly add-ons and bundles (CMTV+, Nuvio, CMTVpn, Audiobooks)
  if (product && product.account_type === 'manual' && !/\d/.test(name) && Number(item?.term_months) === 12) return `${name} · 1 year`;
  return name;
}
