import React from 'react';
import { Link } from 'react-router-dom';
import { Server } from 'lucide-react';
import { useBrandingStore } from '../store/branding';

export function AuthShell({ icon: Icon, title, subtitle, children }) {
  const { branding } = useBrandingStore();
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800 flex flex-col">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/" className="flex items-center gap-2">
            {branding.logo_url ? (
              <img src={branding.logo_url} alt={branding.site_name} className="h-8" />
            ) : (
              <Server className="w-8 h-8" style={{ color: branding.primary_color }} />
            )}
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{branding.site_name}</h1>
          </Link>
        </div>
      </header>
      <div className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="max-w-md w-full">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl p-8">
            <div className="text-center mb-8">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-full mb-4">
                <Icon className="w-8 h-8 text-blue-600" />
              </div>
              <h2 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white">{title}</h2>
              {subtitle && <p className="text-gray-600 dark:text-gray-400 mt-2">{subtitle}</p>}
            </div>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

export const authInputCls = 'w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500';

export const formatApiError = (detail, fallback) => {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((e) => e?.msg || JSON.stringify(e)).join(' ');
  return detail.msg || fallback;
};
