import React from 'react';
import { Check, Minus } from 'lucide-react';

// CMTV local addition 2026-09-24: CCTV vs Imperium feature matrix shown above those plans on the homepage.
// To change a row, edit ROWS below (a value of null shows a dash).
const ROWS = [
  ['Live channels', '11,000', '30,000'],
  ['Movie library', '20,000', '35,000'],
  ['Series library', '6,000', '8,000'],
  ['Canadian & US live TV', true, true],
  ['Sports & PPV', true, true],
  ['Multi-lingual channels', 'Limited', 'Extensive'],
  ['Channel catch-up', null, true],
  ['Sports replay', null, true],
  ['24/7 themed channels', 'Some', 'Extensive'],
  ['Connection options', '1 / 2 / 4 / 6', '2 / 4 / 5'],
  ['Works with all CMTV apps', true, true],
];

function Cell({ value, accent }) {
  if (value === true) return <Check className={`w-5 h-5 ${accent}`} aria-label="Yes" />;
  if (value === null || value === false) return <Minus className="w-4 h-4 text-gray-500" aria-label="Not included" />;
  return <span className="text-gray-100">{value}</span>;
}

export default function ServiceComparison() {
  return (
    <section className="rounded-xl border border-gray-700 bg-gray-900 text-white p-5 sm:p-8 shadow-sm" aria-labelledby="cmtv-compare-title">
      <h3 id="cmtv-compare-title" className="text-xl sm:text-2xl font-extrabold uppercase tracking-wide">CCTV vs Imperium</h3>
      <p className="text-sm text-gray-400 mt-1 mb-5">A side-by-side look at what separates the two.</p>
      <div className="overflow-x-auto -mx-2 px-2">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="border-b border-gray-700">
              <th scope="col" className="text-left font-semibold uppercase tracking-wider text-gray-400 py-3 pr-4">Feature</th>
              <th scope="col" className="text-left font-bold uppercase tracking-widest text-cyan-400 py-3 pr-4">CCTV</th>
              <th scope="col" className="text-left font-bold uppercase tracking-widest text-amber-400 py-3">Imperium</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([feature, cctv, imperium]) => (
              <tr key={feature} className="border-b border-gray-800 last:border-0">
                <th scope="row" className="text-left font-normal text-gray-400 py-3 pr-4">{feature}</th>
                <td className="py-3 pr-4"><Cell value={cctv} accent="text-cyan-400" /></td>
                <td className="py-3"><Cell value={imperium} accent="text-amber-400" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
