import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../api/api';
import { Gift, Users, TrendingUp, Copy, Check, ArrowLeft } from 'lucide-react';
import { TierCard } from '../components/cmtv/ReferralTier'; // CMTV local change 2026-09-25: referral tiers

export default function ReferralDashboard() {
  const [copied, setCopied] = React.useState(false);

  const { data: referralData, isLoading } = useQuery({
    queryKey: ['my-referral'],
    queryFn: async () => {
      const response = await api.get('/api/referral/my-code');
      return response.data;
    },
  });

  const { data: leaderboard } = useQuery({
    queryKey: ['referral-leaderboard'],
    queryFn: async () => {
      const response = await api.get('/api/referral/leaderboard');
      return response.data;
    },
  });

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Get reward amounts from API response
  const referrerReward = referralData?.settings?.referrer_reward || 10;
  const referredReward = referralData?.settings?.referred_reward || 5;
  const isReferralEnabled = referralData?.settings?.enabled !== false;


  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  // If referral system is disabled
  if (!isReferralEnabled) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-800 p-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
            <Gift className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              Referral Program Not Available
            </h2>
            <p className="text-gray-600 dark:text-gray-400">
              The referral program is currently disabled. Please contact support for more information.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      {/* Header Navigation */}
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/dashboard" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600">
            <ArrowLeft className="w-5 h-5" />
            Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="space-y-6">
          {/* Hero Header */}
          <div className="bg-gradient-to-r from-purple-600 to-blue-600 rounded-lg p-8 text-white">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-3xl font-bold mb-2 flex items-center gap-2">
                  <Gift className="w-8 h-8" />
                  Refer & Earn
                </h2>
                <p className="text-purple-100 text-lg">
                  Earn ${referrerReward} credits for every friend who makes a purchase!
                </p>
              </div>
              <div className="text-right">
                <p className="text-purple-200 text-sm">Total Earned</p>
                <p className="text-4xl font-bold">${referralData?.total_earned || 0}</p>
            </div>
          </div>
        </div>

        <TierCard />

        {/* Stats Grid */}
        <div className="grid md:grid-cols-3 gap-6">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <Users className="w-6 h-6 text-blue-600" />
              </div>
              <div>
                <p className="text-sm text-gray-600 dark:text-gray-400">Total Referrals</p>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {referralData?.total_referrals || 0}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                <Check className="w-6 h-6 text-green-600" />
              </div>
              <div>
                <p className="text-sm text-gray-600 dark:text-gray-400">Completed</p>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {referralData?.completed_referrals || 0}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                <TrendingUp className="w-6 h-6 text-purple-600" />
              </div>
              <div>
                <p className="text-sm text-gray-600 dark:text-gray-400">Earnings</p>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  ${referralData?.total_earned || 0}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Referral Link */}
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4">Your Referral Link</h3>
          <div className="flex gap-3">
            <input
              type="text"
              value={referralData?.referral_link || ''}
              readOnly
              className="flex-1 px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white font-mono text-sm"
              data-testid="referral-link-input"
            />
            <button
              onClick={() => copyToClipboard(referralData?.referral_link)}
              className="flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              data-testid="copy-link-btn"
            >
              {copied ? (
                <>
                  <Check className="w-5 h-5" />
                  Copied!
                </>
              ) : (
                <>
                  <Copy className="w-5 h-5" />
                  Copy
                </>
              )}
            </button>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-3">
            Share this link with friends. You'll earn ${referrerReward} credits when they make their first purchase!
          </p>
        </div>

        {/* Referral Code */}
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4">Your Referral Code</h3>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="inline-block px-6 py-4 bg-gradient-to-r from-purple-100 to-blue-100 dark:from-purple-900 dark:to-blue-900 rounded-lg">
                <code className="text-3xl font-bold text-purple-600 dark:text-purple-300">
                  {referralData?.referral_code || 'LOADING'}
                </code>
              </div>
            </div>
            <button
              onClick={() => copyToClipboard(referralData?.referral_code)}
              className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              <Copy className="w-5 h-5" />
            </button>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-3">
            Friends can also use this code during signup to get ${referredReward} welcome credits!
          </p>
        </div>
        </div>
      </main>
    </div>
  );
}
