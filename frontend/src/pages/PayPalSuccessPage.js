import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

export default function PayPalSuccessPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [status, setStatus] = React.useState('processing');

  useEffect(() => {
    const processPayment = async () => {
      const paymentId = searchParams.get('paymentId');
      const payerId = searchParams.get('PayerID');
      const orderId = searchParams.get('order_id');
      // CMTV local change 2026-10-11: the same-tab PayPal / card flow (Orders v2) returns ?token=<PayPal order>: capture it
      const ppToken = searchParams.get('token');
      if (ppToken && orderId && !paymentId) {
        try {
          const auth = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
          await axios.post(`${API_URL}/api/orders/paypal/capture`, { order_id: orderId, paypal_order_id: ppToken },
            { headers: { Authorization: `Bearer ${auth}` } });
          setStatus('success');
          setTimeout(() => navigate(`/pay/${orderId}`), 1500);
        } catch (error) {
          console.error('PayPal capture error:', error);
          setStatus('error');
        }
        return;
      }

      if (!paymentId || !payerId) {
        setStatus('error');
        return;
      }

      try {
        // Call backend to execute payment
        const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
        await axios.get(
          `${API_URL}/api/orders/${orderId}/pay/paypal/success?paymentId=${paymentId}&PayerID=${payerId}`,
          { headers: { Authorization: `Bearer ${token}` }}
        );
        
        setStatus('success');
        setTimeout(() => navigate('/orders'), 2000);
      } catch (error) {
        console.error('Payment execution error:', error);
        setStatus('error');
      }
    };

    processPayment();
  }, [searchParams, navigate]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl p-12 max-w-md text-center">
        {status === 'processing' && (
          <>
            <div className="animate-spin rounded-full h-16 w-16 border-b-4 border-blue-600 mx-auto mb-4"></div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Processing Payment...</h2>
            <p className="text-gray-600 dark:text-gray-400">Please wait while we confirm your PayPal payment</p>
          </>
        )}
        
        {status === 'success' && (
          <>
            <div className="w-16 h-16 bg-green-100 dark:bg-green-900 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-10 h-10 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Payment Successful!</h2>
            <p className="text-gray-600 dark:text-gray-400">Your services are being provisioned...</p>
          </>
        )}
        
        {status === 'error' && (
          <>
            <div className="w-16 h-16 bg-red-100 dark:bg-red-900 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-10 h-10 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Payment Failed</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4">There was an error processing your payment</p>
            <button
              onClick={() => navigate(searchParams.get('order_id') ? `/pay/${searchParams.get('order_id')}` : '/checkout')}   /* CMTV 2026-10-11 */
              className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700"
            >
              Back to Checkout
            </button>
          </>
        )}
      </div>
    </div>
  );
}
