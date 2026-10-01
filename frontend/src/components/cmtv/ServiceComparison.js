import React, { useState } from 'react';
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

// 2026-10-01: compact (the owner: it took up a lot of space): the first SHOWN rows always, the rest behind a toggle
const SHOWN = 3;

export default function ServiceComparison() {
  const [all, setAll] = useState(false);
  const rows = all ? ROWS : ROWS.slice(0, SHOWN);
  return (
    <section className="rounded-xl px-5 py-4 sm:px-6" style={{ background: '#141d33', border: '1px solid #27345a', color: '#e9edf8' }} aria-labelledby="cmtv-compare-title">
      <div className="overflow-x-auto -mx-2 px-2">
        <table className="w-full min-w-[360px] text-sm" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #27345a' }}>
              <th scope="col" id="cmtv-compare-title" className="text-left uppercase py-2 pr-4" style={{ font: 'italic 800 17px "Exo 2", system-ui, sans-serif', letterSpacing: '.04em', color: '#e9edf8' }}>CCTV vs Imperium</th>
              <th scope="col" className="text-left font-bold uppercase tracking-widest py-2 pr-4" style={{ color: CYAN, fontSize: 12 }}>CCTV</th>
              <th scope="col" className="text-left font-bold uppercase tracking-widest py-2" style={{ color: GOLD, fontSize: 12 }}>Imperium</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([feature, cctv, imperium], i) => (
              <tr key={feature} style={i < rows.length - 1 ? { borderBottom: '1px solid #202b4a' } : undefined}>
                <th scope="row" className="text-left font-normal py-1.5 pr-4" style={{ color: '#9aa6c6' }}>{feature}</th>
                <td className="py-1.5 pr-4" style={{ fontVariantNumeric: 'tabular-nums' }}><Cell value={cctv} color={CYAN} /></td>
                <td className="py-1.5" style={{ fontVariantNumeric: 'tabular-nums' }}><Cell value={imperium} color={GOLD} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ROWS.length > SHOWN && (
        <button type="button" aria-expanded={all} onClick={() => setAll((v) => !v)}
          style={{ marginTop: 8, background: 'none', border: 0, padding: 0, cursor: 'pointer', color: CYAN, font: '600 13px Figtree, system-ui, sans-serif' }}>
          {all ? 'Show less' : `Compare all ${ROWS.length} features`}
        </button>
      )}
    </section>
  );
}
