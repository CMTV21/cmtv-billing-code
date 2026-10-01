import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Shield, Copy, Check, X, Download } from 'lucide-react';
import api from '../api/api';
import { toast } from 'sonner';
import RememberedDevices from './cmtv/RememberedDevices'; // CMTV local change 2026-10-01

export default function TwoFactorSetup() {
  const [step, setStep] = useState('initial'); // initial, setup, verify, complete
  const [qrCode, setQrCode] = useState('');
  const [secret, setSecret] = useState('');
  const [verifyCode, setVerifyCode] = useState('');
  const [backupCodes, setBackupCodes] = useState([]);
  const [copied, setCopied] = useState(false);

  // Get 2FA status
  const { data: status, refetch } = useQuery({
    queryKey: ['2fa-status'],
    queryFn: async () => {
      const response = await api.get('/api/auth/2fa/status');
      return response.data;
    },
  });

  // Setup 2FA mutation
  const setupMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/api/auth/2fa/setup');
      return response.data;
    },
    onSuccess: (data) => {
      setQrCode(data.qr_code);
      setSecret(data.secret);
      setStep('setup');
    },
    onError: (error) => {
      toast.error('Failed to setup 2FA: ' + (error.response?.data?.detail || error.message));
    },
  });

  // Verify setup mutation
  const verifyMutation = useMutation({
    mutationFn: async (code) => {
      const response = await api.post('/api/auth/2fa/verify-setup', null, {
        params: { totp_code: code }
      });
      return response.data;
    },
    onSuccess: (data) => {
      setBackupCodes(data.backup_codes);
      setStep('complete');
      refetch();
    },
    onError: (error) => {
      toast.error('Invalid code. Please try again.');
    },
  });

  // Disable 2FA mutation
  const disableMutation = useMutation({
    mutationFn: async (password) => {
      const response = await api.post('/api/auth/2fa/disable', null, {
        params: { password }
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('2FA disabled successfully');
      setStep('initial');
      refetch();
    },
    onError: (error) => {
      toast.error('Failed to disable 2FA: ' + (error.response?.data?.detail || error.message));
    },
  });

  const handleVerify = () => {
    if (verifyCode.length === 6) {
      verifyMutation.mutate(verifyCode);
    }
  };

  const handleDisable = () => {
    const password = prompt('Enter your password to disable 2FA:');
    if (password) {
      disableMutation.mutate(password);
    }
  };

  const copySecret = () => {
    navigator.clipboard.writeText(secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadBackupCodes = () => {
    const text = backupCodes.join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = '2fa-backup-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (status?.enabled && step === 'initial') {
    return (
      <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Shield className="w-6 h-6 text-green-600 dark:text-green-400" />
            <div>
              <h4 className="font-semibold text-green-900 dark:text-green-100">2FA Enabled</h4>
              <p className="text-sm text-green-700 dark:text-green-300">Your account is protected with two-factor authentication</p>
            </div>
          </div>
          <button
            onClick={handleDisable}
            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm"
          >
            Disable 2FA
          </button>
        </div>
        <RememberedDevices />{/* CMTV local change 2026-10-01: remembered devices for 2FA */}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-600" />
          Two-Factor Authentication
        </h3>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Add an extra layer of security to your admin account
        </p>
      </div>

      {step === 'initial' && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
          <p className="text-sm text-blue-900 dark:text-blue-100 mb-4">
            Enable 2FA to protect your admin account with Google Authenticator.
          </p>
          <button
            onClick={() => setupMutation.mutate()}
            disabled={setupMutation.isLoading}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
          >
            {setupMutation.isLoading ? 'Setting up...' : 'Enable 2FA'}
          </button>
        </div>
      )}

      {step === 'setup' && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
          <h4 className="font-semibold text-gray-900 dark:text-white mb-4">Step 1: Scan QR Code</h4>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            Scan this QR code with Google Authenticator app:
          </p>
          
          <div className="flex justify-center mb-6">
            <img src={qrCode} alt="2FA QR Code" className="w-64 h-64 border border-gray-300 rounded-lg" />
          </div>

          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4 mb-4">
            <p className="text-xs text-gray-600 dark:text-gray-400 mb-2">Manual entry key:</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-sm font-mono bg-white dark:bg-gray-800 px-3 py-2 rounded border">
                {secret}
              </code>
              <button
                onClick={copySecret}
                className="p-2 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
                title="Copy secret"
              >
                {copied ? <Check className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <button
            onClick={() => setStep('verify')}
            className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
          >
            Next: Verify Code
          </button>
        </div>
      )}

      {step === 'verify' && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
          <h4 className="font-semibold text-gray-900 dark:text-white mb-4">Step 2: Verify</h4>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            Enter the 6-digit code from Google Authenticator:
          </p>
          
          <input
            type="text"
            maxLength="6"
            value={verifyCode}
            onChange={(e) => setVerifyCode(e.target.value.replace(/[^0-9]/g, ''))}
            placeholder="000000"
            className="w-full text-center text-3xl font-mono tracking-widest px-4 py-4 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white mb-4"
          />

          <div className="flex gap-3">
            <button
              onClick={() => setStep('setup')}
              className="flex-1 px-6 py-3 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              Back
            </button>
            <button
              onClick={handleVerify}
              disabled={verifyCode.length !== 6 || verifyMutation.isLoading}
              className="flex-1 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium disabled:opacity-50"
            >
              {verifyMutation.isLoading ? 'Verifying...' : 'Verify & Enable'}
            </button>
          </div>
        </div>
      )}

      {step === 'complete' && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
          <div className="text-center mb-6">
            <div className="w-16 h-16 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
              <Shield className="w-8 h-8 text-green-600 dark:text-green-400" />
            </div>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-2">2FA Enabled Successfully!</h4>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Your account is now protected with two-factor authentication
            </p>
          </div>

          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 mb-4">
            <h5 className="font-semibold text-yellow-900 dark:text-yellow-100 mb-2">Save Your Backup Codes</h5>
            <p className="text-sm text-yellow-800 dark:text-yellow-200 mb-3">
              Store these codes safely. Each code can be used once if you lose access to your authenticator app.
            </p>
            
            <div className="grid grid-cols-2 gap-2 mb-4">
              {backupCodes.map((code, idx) => (
                <div key={idx} className="bg-white dark:bg-gray-800 px-3 py-2 rounded border font-mono text-sm text-center">
                  {code}
                </div>
              ))}
            </div>

            <button
              onClick={downloadBackupCodes}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700"
            >
              <Download className="w-4 h-4" />
              Download Backup Codes
            </button>
          </div>

          <button
            onClick={() => setStep('initial')}
            className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
          >
            Done
          </button>
        </div>
      )}
    </div>
  );
}
