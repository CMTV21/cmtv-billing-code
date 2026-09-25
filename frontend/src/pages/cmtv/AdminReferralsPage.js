// CMTV local addition 2026-09-25: Admin > Customers > Referrals (backend: cmtv_referral.py).
// Everyone with referrals, their lifetime count and tier; search any customer to add past referrals or credit.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Award, Search } from 'lucide-react';
import api from '../../api/api';
import { AdminCustomerReferrals } from '../../components/cmtv/ReferralTier';

const tierClass = {
  Ambassador: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
  Advocate: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200',
  Member: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
};

export default function AdminReferralsPage() {
  const [q, setQ] = useState('');
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(null);
  const { data, isLoading } = useQuery({
    queryKey: ['cmtv-ref-overview', search],
    queryFn: async () => (await api.get('/api/cmtv/referral/admin/overview', { params: { q: search } })).data,
  });
  const rows = data?.rows || [];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center gap-4">
          <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600">
            <ArrowLeft className="w-5 h-5" /> Admin
          </Link>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2"><Award className="w-5 h-5" /> Referrals</h1>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6 space-y-4">
        <div className="flex flex-wrap gap-3 items-center justify-between">
          <form className="flex gap-2 flex-1 min-w-[240px]" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); setOpen(null); }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find any customer (name, email, username, code)"
              className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm" />
            <button className="flex items-center gap-1 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"><Search className="w-4 h-4" /> Search</button>
            {search && <button type="button" onClick={() => { setQ(''); setSearch(''); setOpen(null); }}
              className="px-3 py-2 text-sm text-gray-600 dark:text-gray-300">Show all referrers</button>}
          </form>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {(data?.tiers || []).filter((t) => t.min > 0).map((t) => `${t.name} at ${t.min}: ${t.pct}% off${t.free_cmtv_plus ? ' + CMTV+ free' : ''}`).join(' · ')}
          </p>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">
          {isLoading ? <p className="p-6 text-sm text-gray-500">Loading…</p> : rows.length === 0 ? (
            <p className="p-6 text-sm text-gray-500 dark:text-gray-400">{search ? 'No customers match.' : 'Nobody has referrals yet.'}</p>
          ) : (
            <ul className="divide-y divide-gray-200 dark:divide-gray-700">
              {rows.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => setOpen(open === r.id ? null : r.id)}
                    className="w-full text-left px-4 py-3 flex flex-wrap items-center gap-3 hover:bg-gray-50 dark:hover:bg-gray-800">
                    <span className="text-2xl font-bold w-10 text-gray-900 dark:text-white">{r.count}</span>
                    <span className="flex-1 min-w-[180px]">
                      <span className="font-semibold text-gray-900 dark:text-white">{r.name}</span>
                      <span className="block text-xs text-gray-500 dark:text-gray-400">{r.email}</span>
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">{r.billing_count} in billing · {r.past_count} past</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400 w-24 text-right">credit ${r.credit_balance.toFixed(2)}</span>
                    <span className={`px-2 py-1 rounded-full text-xs font-semibold ${tierClass[r.tier] || tierClass.Member}`}>{r.tier}</span>
                  </button>
                  {open === r.id && <div className="px-4 pb-4"><AdminCustomerReferrals customerId={r.id} /></div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  );
}
