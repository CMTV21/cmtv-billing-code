import React from 'react';
import { Check, Minus } from 'lucide-react';

// CMTV local addition 2026-09-24 (restyled 2026-09-25): CCTV vs Imperium feature matrix on the storefront.
// CCTV is CMTV cyan, Imperium is its own gold. To change a row, edit ROWS below (a value of null shows a dash).
const ROWS = [
  ['Live channels', '11,000', '40,000'],
  ['Movie library', '20,000', '30,000'],
  ['Series library', '6,000', '8,000'],
  ['Canadian and US live TV', true, true],
  ['Sports and PPV', true, true],
  ['Multi-lingual channels', 'Limited', 'Extensive'],
  ['Channel catch-up', null, true],
  ['Sports replay', null, true],
  ['24/7 themed channels', 'Some', 'Extensive'],
  ['Connection options', '1 / 2 / 4 / 6', '2 / 4 / 5'],
  ['Works with all CMTV apps', true, true],
];
const CYAN = '#22e6f2';
const GOLD = '#d8b35a';

function Cell({ value, color }) {
  if (value === true) return <Check className="w-5 h-5" style={{ color }} aria-label="Yes" />;
  if (value === null || value === false) return <Minus className="w-4 h-4" style={{ color: '#6b7799' }} aria-label="Not included" />;
  return <span style={{ color: '#e9edf8' }}>{value}</span>;
}

export default function ServiceComparison() {
  return (
    <section className="rounded-xl p-5 sm:p-7" style={{ background: '#141d33', border: '1px solid #27345a', color: '#e9edf8' }} aria-labelledby="cmtv-compare-title">
      <h3 id="cmtv-compare-title" className="text-xl sm:text-2xl uppercase" style={{ font: 'italic 800 22px "Exo 2", system-ui, sans-serif', letterSpacing: '.04em', margin: 0 }}>CCTV vs Imperium</h3>
      <p className="text-sm mt-1 mb-4" style={{ color: '#9aa6c6' }}>A side-by-side look at what separates the two.</p>
      <div className="overflow-x-auto -mx-2 px-2">
        <table className="w-full min-w-[420px] text-sm" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #27345a' }}>
              <th scope="col" className="text-left font-semibold uppercase tracking-wider py-3 pr-4" style={{ color: '#6b7799', fontSize: 12 }}>Feature</th>
              <th scope="col" className="text-left font-bold uppercase tracking-widest py-3 pr-4" style={{ color: CYAN, fontSize: 12 }}>CCTV</th>
              <th scope="col" className="text-left font-bold uppercase tracking-widest py-3" style={{ color: GOLD, fontSize: 12 }}>Imperium</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([feature, cctv, imperium], i) => (
              <tr key={feature} style={i < ROWS.length - 1 ? { borderBottom: '1px solid #202b4a' } : undefined}>
                <th scope="row" className="text-left font-normal py-3 pr-4" style={{ color: '#9aa6c6' }}>{feature}</th>
                <td className="py-3 pr-4" style={{ fontVariantNumeric: 'tabular-nums' }}><Cell value={cctv} color={CYAN} /></td>
                <td className="py-3" style={{ fontVariantNumeric: 'tabular-nums' }}><Cell value={imperium} color={GOLD} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
