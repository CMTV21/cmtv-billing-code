import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowLeft, TrendingUp, TrendingDown, DollarSign, ShoppingBag, Users, Activity, BarChart3, PieChart } from 'lucide-react';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart as RePie, Pie, Cell } from 'recharts';
import { useCurrencyStore } from '../store/currency';
import api from '../api/api';

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];

export default function AnalyticsDashboard() {
  const [period, setPeriod] = useState('30d');
  const { symbol } = useCurrencyStore();

  const { data, isLoading } = useQuery({
    queryKey: ['analytics', period],
    queryFn: async () => { const r = await api.get(`/api/admin/analytics?period=${period}`); return r.data; },
  });

  const StatCard = ({ title, value, change, prefix, icon: Icon, color }) => (
    <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500 dark:text-gray-400">{title}</span>
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${color}`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
      </div>
      <div className="text-2xl font-bold text-gray-900 dark:text-white">{prefix}{value}</div>
      {change !== undefined && (
        <div className={`flex items-center gap-1 mt-1 text-sm ${change >= 0 ? 'text-green-600' : 'text-red-500'}`}>
          {change >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          {Math.abs(change)}% vs prev period
        </div>
      )}
    </div>
  );

  if (isLoading) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
      <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
    </div>
  );

  const d = data || {};

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800 p-4 lg:p-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <Link to="/admin" className="text-gray-500 hover:text-blue-600"><ArrowLeft className="w-5 h-5" /></Link>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Revenue Analytics</h1>
              <p className="text-sm text-gray-500 dark:text-gray-400">Track performance and revenue trends</p>
            </div>
          </div>
          <div className="flex gap-1 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 p-1">
            {[{k:'7d',l:'7D'},{k:'30d',l:'30D'},{k:'90d',l:'90D'},{k:'1y',l:'1Y'}].map(p => (
              <button key={p.k} onClick={() => setPeriod(p.k)}
                className={`px-3 py-1.5 rounded text-sm font-medium ${period === p.k ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}`}>
                {p.l}
              </button>
            ))}
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatCard title="Revenue" value={d.revenue?.current?.toFixed(2)} change={d.revenue?.change} prefix={symbol} icon={DollarSign} color="bg-blue-600" />
          <StatCard title="Orders" value={d.orders?.current} change={d.orders?.change} prefix="" icon={ShoppingBag} color="bg-green-600" />
          <StatCard title="New Customers" value={d.customers?.current} change={d.customers?.change} prefix="" icon={Users} color="bg-purple-600" />
          <StatCard title="Avg Order Value" value={(d.avg_order_value || 0).toFixed(2)} prefix={symbol} icon={BarChart3} color="bg-amber-600" />
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
            <span className="text-sm text-gray-500 dark:text-gray-400">Est. MRR</span>
            <div className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{symbol}{(d.mrr || 0).toFixed(2)}</div>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
            <span className="text-sm text-gray-500 dark:text-gray-400">Churn Rate</span>
            <div className={`text-2xl font-bold mt-1 ${(d.churn_rate || 0) > 10 ? 'text-red-500' : (d.churn_rate || 0) > 5 ? 'text-amber-500' : 'text-green-600'}`}>{d.churn_rate || 0}%</div>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
            <span className="text-sm text-gray-500 dark:text-gray-400">Active Services</span>
            <div className="text-2xl font-bold text-green-600 mt-1">{d.active_services || 0}</div>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
            <span className="text-sm text-gray-500 dark:text-gray-400">Expired / Churned</span>
            <div className="text-2xl font-bold text-red-500 mt-1">{d.expired_services || 0}</div>
          </div>
        </div>

        {/* Revenue Chart */}
        <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 mb-6">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-4">Revenue Over Time</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={d.chart_data || d.chart || []}>{/* CMTV local change 2026-09-26: the API returns "chart", so this chart was always empty */}
              <defs>
                <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="date" tick={{fontSize: 12}} stroke="#9ca3af" />
              <YAxis tick={{fontSize: 12}} stroke="#9ca3af" tickFormatter={(v) => `${symbol}${v}`} />
              <Tooltip formatter={(v) => [`${symbol}${v}`, 'Revenue']} contentStyle={{borderRadius: '8px', border: '1px solid #e5e7eb'}} />
              <Area type="monotone" dataKey="revenue" stroke="#3b82f6" strokeWidth={2} fill="url(#revGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="grid lg:grid-cols-2 gap-6 mb-6">
          {/* Payment Methods */}
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
            <h3 className="font-semibold text-gray-900 dark:text-white mb-4">Revenue by Payment Method</h3>
            {(d.by_method || []).length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <RePie>
                    <Pie data={d.by_method} dataKey="revenue" nameKey="method" cx="50%" cy="50%" outerRadius={80} label={({method, percent}) => `${method} ${(percent*100).toFixed(0)}%`}>
                      {(d.by_method || []).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                    </Pie>
                    <Tooltip formatter={(v) => `${symbol}${v}`} />
                  </RePie>
                </ResponsiveContainer>
                <div className="space-y-2 mt-2">
                  {(d.by_method || []).map((m, i) => (
                    <div key={m.method} className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full" style={{background: COLORS[i % COLORS.length]}} />
                        <span className="text-gray-700 dark:text-gray-300 capitalize">{m.method}</span>
                      </div>
                      <span className="font-medium text-gray-900 dark:text-white">{symbol}{m.revenue} ({m.orders} orders)</span>
                    </div>
                  ))}
                </div>
              </>
            ) : <p className="text-gray-500 text-sm">No payment data for this period</p>}
          </div>

          {/* Top Products */}
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
            <h3 className="font-semibold text-gray-900 dark:text-white mb-4">Top Products</h3>
            {(d.by_product || []).length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={(d.by_product || []).slice(0, 6)} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis type="number" tick={{fontSize: 11}} stroke="#9ca3af" tickFormatter={(v) => `${symbol}${v}`} />
                    <YAxis dataKey="name" type="category" tick={{fontSize: 11}} stroke="#9ca3af" width={120} />
                    <Tooltip formatter={(v) => `${symbol}${v}`} />
                    <Bar dataKey="revenue" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
                <div className="space-y-2 mt-4">
                  {(d.by_product || []).map((p, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="text-gray-700 dark:text-gray-300 truncate flex-1">{p.name}</span>
                      <span className="font-medium text-gray-900 dark:text-white ml-2">{symbol}{p.revenue} ({p.sold} sold)</span>
                    </div>
                  ))}
                </div>
              </>
            ) : <p className="text-gray-500 text-sm">No product data for this period</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
