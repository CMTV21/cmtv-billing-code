import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ordersAPI, servicesAPI } from '../api/api';
import { useCartStore, useAuthStore } from '../store/store';
import { ArrowLeft, ShoppingCart, Trash2, AlertCircle, CreditCard, Bitcoin, Copy, CheckCircle, Loader2, RefreshCw, Plus, DollarSign } from 'lucide-react';
import { PayPalScriptProvider, PayPalButtons } from "@paypal/react-paypal-js";
import { CheckoutAutoRenew } from './../components/cmtv/AutoRenew'; // CMTV local change 2026-09-25
import { useTierQuote } from '../components/cmtv/ReferralTier'; // CMTV local change 2026-09-25: referral tiers
import CheckoutAddons, { useAddonProducts, extendChoices } from '../components/cmtv/CheckoutAddons'; // CMTV 2026-09-25: add-on offer
import SquarePaymentForm from '../components/SquarePaymentForm';
import CheckoutCouponCredits from '../components/CheckoutCouponCredits';
import { QRCodeSVG } from 'qrcode.react';
import axios from 'axios';
import { toast } from 'sonner';
import { useCurrencyStore } from '../store/currency';
import CurrencySwitcher from '../components/CurrencySwitcher';

const API_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

export default function CheckoutPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const { items, addItem, removeItem, clearCart, getTotal, updateItemAction } = useCartStore();
  // CMTV local change 2026-09-25: add-ons only offer to extend the same add-on; TV plans never offer to extend an add-on
  const addonIds = new Set(useAddonProducts().map((p) => p.id));
  const { symbol: currencySymbol, convertPrice, code: currencyCode } = useCurrencyStore();
  const [error, setError] = React.useState('');
  const [paymentMethod, setPaymentMethod] = useState('');
  const [currentOrderId, setCurrentOrderId] = useState(null);
  const [pollingSessionId, setPollingSessionId] = useState(null);
  
  // Coupon and Credits state
  const [discountAmount, setDiscountAmount] = useState(0);
  const [appliedCouponCode, setAppliedCouponCode] = useState(null);
  const [creditsUsed, setCreditsUsed] = useState(0);

  // CMTV local change 2026-09-25: referral tier discount. Same rule as the server: the bigger of the tier discount
  // and the coupon applies, never both. The server works it out again when the order is created.
  const tierQuote = useTierQuote(items);
  const tierWins = tierQuote.amount > discountAmount + 0.009;
  const effectiveDiscount = tierWins ? tierQuote.amount : discountAmount;
  const creditsApplied = Math.min(creditsUsed, Math.max(0, getTotal() - effectiveDiscount));
  const payTotal = Math.max(0, Math.round((getTotal() - effectiveDiscount - creditsApplied) * 100) / 100);

  // Reseller credentials state
  const [resellerUsername, setResellerUsername] = useState('');
  const [resellerPassword, setResellerPassword] = useState('');
  const [resellerUsernameExists, setResellerUsernameExists] = useState(false);
  const [resellerAddCredits, setResellerAddCredits] = useState(false);
  const [checkingUsername, setCheckingUsername] = useState(false);
  
  // Blockonomics Bitcoin payment state
  const [btcPaymentData, setBtcPaymentData] = useState(null);
  const [btcPaymentStatus, setBtcPaymentStatus] = useState(null);
  const [btcPolling, setBtcPolling] = useState(false);
  const [copiedAddress, setCopiedAddress] = useState(false);

  // Terms and conditions state
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [showTermsModal, setShowTermsModal] = useState(false);

  const { data: termsData } = useQuery({
    queryKey: ['terms'],
    queryFn: async () => {
      const resp = await axios.get(`${API_URL}/api/terms`);
      return resp.data;
    },
  });

  // GhostPay state
  const [ghostpayLoading, setGhostpayLoading] = useState(false);

  // Helcim payment state
  const [helcimLoading, setHelcimLoading] = useState(false);

  // Check if cart has reseller products that need new credentials
  const hasNewResellerProduct = items.some(item => 
    item.account_type === 'reseller' && item.action_type !== 'extend'
  );
  
  // Check if cart has subscriber products (for extend/create option)
  const hasSubscriberProduct = items.some(item => item.account_type === 'subscriber');

  // Fetch user's existing services to show extend option
  const { data: userServices } = useQuery({
    queryKey: ['user-services'],
    queryFn: async () => {
      const response = await servicesAPI.getAll();
      return response.data?.filter(s => s.account_type === 'subscriber' && !s.is_credit_addon) || [];
    },
    enabled: hasSubscriberProduct, // Only fetch if cart has subscriber products
  });

  // Fetch payment config (public endpoint)
  const { data: settings, isLoading: settingsLoading, error: settingsError } = useQuery({
    queryKey: ['payment-config'],
    queryFn: async () => {
      try {
        const response = await axios.get(`${API_URL}/api/payment/config`);
        console.log('Payment config loaded:', response.data);
        return response.data;
      } catch (error) {
        console.error('Payment config fetch error:', error);
        throw error;
      }
    },
  });

  console.log('Payment config:', settings);

  // Auto-select first enabled payment method
  React.useEffect(() => {
    if (!settings || paymentMethod) return;
    const order = settings.payment_method_order || ['manual', 'emt', 'zelle', 'cashapp', 'venmo', 'wise', 'stripe', 'paypal', 'square', 'blockonomics', 'ghostpay'];
    const enabledCheck = {
      manual: settings.manual?.enabled !== false,
      stripe: settings.stripe?.enabled,
      paypal: settings.paypal?.enabled,
      square: settings.square?.enabled,
      helcim: settings.helcim?.enabled,
      blockonomics: settings.blockonomics?.enabled,
      ghostpay: settings.ghostpay?.enabled,
      tagadapay: settings.tagadapay?.enabled,
      emt: settings.emt?.enabled,
      zelle: settings.zelle?.enabled,
      cashapp: settings.cashapp?.enabled,
      venmo: settings.venmo?.enabled,
      wise: settings.wise?.enabled,
    };
    const first = order.find(m => enabledCheck[m]);
    if (first) setPaymentMethod(first);
  }, [settings, paymentMethod]);

  const createOrderMutation = useMutation({
    mutationFn: (data) => ordersAPI.create(data),
    onSuccess: (response) => {
      const orderId = response.data.order_id;
      setCurrentOrderId(orderId);
      
      if (['manual', 'emt', 'zelle', 'cashapp', 'venmo', 'wise'].includes(paymentMethod) && Number(response.data.total) > 0) { // CMTV 2026-09-25: not for $0 orders
        clearCart();
        navigate('/orders');
        toast.success(paymentMethod === 'manual' ? 'Order placed! Please wait for admin to confirm payment.' : `Order placed! Please send your ${paymentMethod.toUpperCase()} payment now. Include your Order ID.`);
      }
      
      // Free trial / fully paid with credits
      const finalTotal = Number(response.data.total ?? payTotal); // CMTV local change 2026-09-25: the server's total
      if (finalTotal === 0) {
        clearCart();
        toast.success('Order placed! Your service is being provisioned.');
        navigate('/orders');
      }
      // For PayPal, buttons will handle the flow
    },
    onError: (error) => {
      const msg = error.response?.data?.detail || 'Failed to create order';
      setError(msg);
      toast.error(msg);
    },
  });

  const handleCheckout = () => {
    if (items.length === 0) {
      setError('Cart is empty');
      return;
    }

    if (!paymentMethod) {
      setError('Please select a payment method');
      return;
    }

    if (termsData?.enabled && !termsAccepted) {
      setError('You must agree to the Terms and Conditions to continue');
      return;
    }

    setError('');
    
    // Validate reseller credentials if needed
    if (hasNewResellerProduct && (!resellerUsername || !resellerPassword)) {
      setError('Please set username and password for your reseller panel');
      return;
    }
    
    if (hasNewResellerProduct && resellerUsernameExists && !resellerAddCredits) {
      setError('Please confirm whether to add credits to the existing username or choose a different one');
      return;
    }
    
    createOrderMutation.mutate({
      items: items,
      total: getTotal(),
      coupon_code: appliedCouponCode,
      use_credits: creditsApplied,
      reseller_credentials: hasNewResellerProduct ? {
        username: resellerUsername,
        password: resellerPassword,
        add_credits_to_existing: resellerAddCredits
      } : null
    });
  };

  const createPayPalOrder = async () => {
    try {
      if (!currentOrderId) {
        const orderData = {
          items: items.map(i => ({
            product_id: i.product_id, product_name: i.product_name,
            term_months: i.term_months, price: i.price, account_type: i.account_type,
            action_type: i.action_type, renewal_service_id: i.renewal_service_id
          })),
          total: getTotal(),
          coupon_code: appliedCouponCode,
          use_credits: creditsApplied,
          reseller_credentials: hasNewResellerProduct ? {
            username: resellerUsername, password: resellerPassword,
            add_credits_to_existing: resellerAddCredits
          } : null
        };
        const orderResponse = await ordersAPI.create(orderData);
        const orderId = orderResponse.data.order_id || orderResponse.data.id;
        setCurrentOrderId(orderId);
        
        const authToken = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
        const paypalResponse = await axios.post(
          `${API_URL}/api/orders/${orderId}/pay/paypal`,
          { origin: window.location.origin },
          { headers: { Authorization: `Bearer ${authToken}` }}
        );
        
        return paypalResponse.data.order_id;
      }
    } catch (error) {
      setError(`PayPal error: ${error.response?.data?.detail || error.message}`);
      throw error;
    }
  };

  const onPayPalApprove = async (data) => {
    try {
      console.log('PayPal approved:', data);
      console.log('Order ID:', currentOrderId);
      console.log('PayPal Order ID:', data.orderID);
      
      if (!currentOrderId) {
        throw new Error('No order ID found');
      }
      
      // Capture the order via backend
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      const response = await axios.post(
        `${API_URL}/api/orders/paypal/capture`,
        { 
          order_id: currentOrderId,
          paypal_order_id: data.orderID 
        },
        { headers: { Authorization: `Bearer ${token}` }}
      );
      
      console.log('Capture response:', response.data);
      
      clearCart();
      toast.success('Payment successful! Your services are being provisioned.');
      navigate('/orders');
      return response.data;
    } catch (error) {
      console.error('PayPal approval error:', error);
      setError(`Payment processing failed: ${error.response?.data?.detail || error.message}`);
      throw error;
    }
  };

  const handleStripePay = async () => {
    try {
      const orderData = {
        items: items.map(i => ({
          product_id: i.product_id, product_name: i.product_name,
          term_months: i.term_months, price: i.price, account_type: i.account_type,
          action_type: i.action_type, renewal_service_id: i.renewal_service_id
        })),
        total: getTotal(),
        coupon_code: appliedCouponCode,
        use_credits: creditsApplied,
        reseller_credentials: hasNewResellerProduct ? {
          username: resellerUsername, password: resellerPassword,
          add_credits_to_existing: resellerAddCredits
        } : null
      };
      const orderResponse = await ordersAPI.create(orderData);
      const orderId = orderResponse.data.order_id || orderResponse.data.id;
      setCurrentOrderId(orderId);
      
      // Create Stripe session
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      console.log('Creating Stripe session...');
      
      const stripeResponse = await axios.post(
        `${API_URL}/api/orders/${orderId}/pay/stripe`,
        { origin: window.location.origin },
        { headers: { Authorization: `Bearer ${token}` }}
      );
      
      console.log('Stripe response:', stripeResponse.data);
      
      if (stripeResponse.data.success && stripeResponse.data.checkout_url) {
        // Redirect to Stripe checkout
        window.location.href = stripeResponse.data.checkout_url;
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (error) {
      console.error('Stripe payment error:', error);
      setError(`Stripe payment failed: ${error.response?.data?.detail || error.message}`);
    }
  };

  const handleSquarePay = () => {
    // Square form will handle payment
    if (!currentOrderId) {
      // Create order first
      const orderData = { items: items, total: getTotal() };
      createOrderMutation.mutate(orderData);
    }
  };

  const handleSquareSuccess = (paymentId) => {
    console.log('Square payment successful:', paymentId);
    clearCart();
    toast.success('Payment successful! Your services are being provisioned.');
    navigate('/orders');
  };

  const handleSquareError = (error) => {
    console.error('Square payment error:', error);
    setError(`Square payment failed: ${error}`);
  };

  // Blockonomics Bitcoin Payment Handlers
  const handleBlockonomicsPay = async () => {
    try {
      setError('');
      console.log('Starting Blockonomics Bitcoin payment...');
      
      // Create order first
      const orderData = { items: items, total: getTotal() };
      const orderResponse = await ordersAPI.create(orderData);
      const orderId = orderResponse.data.order_id;
      setCurrentOrderId(orderId);
      console.log('Order created:', orderId);
      
      // Create Blockonomics payment
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      const btcResponse = await axios.post(
        `${API_URL}/api/orders/${orderId}/pay/blockonomics`,
        {},
        { headers: { Authorization: `Bearer ${token}` }}
      );
      
      console.log('Blockonomics response:', btcResponse.data);
      
      if (btcResponse.data.success) {
        setBtcPaymentData(btcResponse.data);
        setBtcPolling(true);
        // Start polling for payment status
        pollBlockonomicsStatus(orderId);
      } else {
        throw new Error(btcResponse.data.error || 'Failed to create Bitcoin payment');
      }
    } catch (error) {
      console.error('Blockonomics payment error:', error);
      setError(`Bitcoin payment failed: ${error.response?.data?.detail || error.message}`);
    }
  };

  const pollBlockonomicsStatus = async (orderId, attempt = 0) => {
    if (attempt >= 60) { // Poll for up to 10 minutes (60 attempts * 10 seconds)
      console.log('Bitcoin payment polling timeout');
      setBtcPolling(false);
      return;
    }
    
    try {
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      const response = await axios.get(
        `${API_URL}/api/payments/blockonomics/status/${orderId}`,
        { headers: { Authorization: `Bearer ${token}` }}
      );
      
      console.log('BTC payment status:', response.data);
      setBtcPaymentStatus(response.data);
      
      if (response.data.payment_status === 'confirmed') {
        setBtcPolling(false);
        clearCart();
        toast.info('Bitcoin payment confirmed! Your services are being provisioned.');
        navigate('/orders');
      } else if (response.data.payment_status === 'unconfirmed') {
        // Payment received but waiting for confirmations
        setTimeout(() => pollBlockonomicsStatus(orderId, attempt + 1), 10000);
      } else {
        // Still pending
        setTimeout(() => pollBlockonomicsStatus(orderId, attempt + 1), 10000);
      }
    } catch (error) {
      console.error('BTC status check error:', error);
      setTimeout(() => pollBlockonomicsStatus(orderId, attempt + 1), 10000);
    }
  };

  const copyBtcAddress = () => {
    if (btcPaymentData?.btc_address) {
      navigator.clipboard.writeText(btcPaymentData.btc_address);
      setCopiedAddress(true);
      setTimeout(() => setCopiedAddress(false), 2000);
    }
  };

  // ===== HELCIM PAYMENT =====
  const handleHelcimPay = async () => {
    try {
      setError('');
      setHelcimLoading(true);

      const orderData = {
        items: items.map(i => ({
          product_id: i.product_id, product_name: i.product_name,
          term_months: i.term_months, price: i.price, account_type: i.account_type,
          action_type: i.action_type, renewal_service_id: i.renewal_service_id
        })),
        total: getTotal(),
        coupon_code: appliedCouponCode,
        use_credits: creditsApplied,
        reseller_credentials: hasNewResellerProduct ? {
          username: resellerUsername, password: resellerPassword,
          add_credits_to_existing: resellerAddCredits
        } : null
      };

      const orderResponse = await ordersAPI.create(orderData);
      const orderId = orderResponse.data.order_id || orderResponse.data.id;
      setCurrentOrderId(orderId);

      // Initialize Helcim checkout
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      const helcimResponse = await axios.post(
        `${API_URL}/api/orders/${orderId}/pay/helcim`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );

      if (!helcimResponse.data.success || !helcimResponse.data.checkoutToken) {
        throw new Error('Failed to initialize Helcim checkout');
      }

      const checkoutToken = helcimResponse.data.checkoutToken;

      // Load HelcimPay.js script if not already loaded
      if (!document.querySelector('script[src*="helcim-pay"]')) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = 'https://secure.helcim.app/helcim-pay/services/start.js';
          script.type = 'text/javascript';
          script.async = true;
          script.onload = resolve;
          script.onerror = () => reject(new Error('Failed to load HelcimPay.js'));
          document.head.appendChild(script);
        });
      }

      // Listen for iFrame events
      const messageHandler = async (event) => {
        const key = 'helcim-pay-js-' + checkoutToken;
        if (event.data.eventName !== key) return;

        window.removeEventListener('message', messageHandler);

        if (event.data.eventStatus === 'SUCCESS') {
          try {
            const txnData = typeof event.data.eventMessage === 'string'
              ? JSON.parse(event.data.eventMessage)
              : event.data.eventMessage;
            const txn = txnData?.data || txnData;

            // Verify payment on backend
            await axios.post(
              `${API_URL}/api/orders/${orderId}/helcim/verify`,
              { transactionId: txn.transactionId || '', cardToken: txn.cardToken || '' },
              { headers: { Authorization: `Bearer ${token}` } }
            );

            clearCart();
            toast.success('Payment successful! Your services are being provisioned.');
            navigate('/orders');
          } catch (verifyErr) {
            console.error('Helcim verify error:', verifyErr);
            setError('Payment completed but verification failed. Please contact support.');
          }
        } else if (event.data.eventStatus === 'ABORTED') {
          setError('Payment was declined. Please try again.');
        }
        // HIDE = user closed modal, do nothing special
        setHelcimLoading(false);
      };

      window.addEventListener('message', messageHandler);

      // Open the HelcimPay.js modal
      if (typeof window.appendHelcimPayIframe === 'function') {
        window.appendHelcimPayIframe(checkoutToken);
      } else {
        throw new Error('HelcimPay.js not loaded');
      }

      setHelcimLoading(false);
    } catch (err) {
      console.error('Helcim payment error:', err);
      setError(`Helcim payment failed: ${err.response?.data?.detail || err.message}`);
      setHelcimLoading(false);
    }
  };

  // Detect if returning from payment gateway
  const urlParams = new URLSearchParams(window.location.search);
  const isPaymentReturn = urlParams.get('payment') === 'success' && urlParams.get('session_id');

  // Poll for payment status if returning from Stripe
  React.useEffect(() => {
    const sessionId = urlParams.get('session_id');
    const orderId = urlParams.get('order_id');
    const paymentStatus = urlParams.get('payment');
    
    if (paymentStatus === 'success' && sessionId && !pollingSessionId) {
      setPollingSessionId(sessionId);
      if (orderId) {
        setCurrentOrderId(orderId);
      }
      pollPaymentStatus(sessionId, orderId);
    }
  }, [pollingSessionId]);

  const pollPaymentStatus = async (sessionId, orderId, attempt = 0) => {
    if (attempt >= 8) {
      clearCart();
      toast.success('Payment received! Your services are being set up.');
      navigate('/orders');
      return;
    }
    
    try {
      const token = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
      const response = await axios.get(
        `${API_URL}/api/payments/stripe/status/${sessionId}`,
        { headers: { Authorization: `Bearer ${token}` }}
      );
      
      if (response.data.success && response.data.payment_status === 'paid') {
        clearCart();
        toast.success('Payment successful! Your services are being provisioned.');
        navigate('/orders');
      } else if (attempt < 7) {
        setTimeout(() => pollPaymentStatus(sessionId, orderId, attempt + 1), 2000);
      } else {
        clearCart();
        toast.success('Payment received! Check your orders page.');
        navigate('/orders');
      }
    } catch (error) {
      if (attempt < 7) {
        setTimeout(() => pollPaymentStatus(sessionId, orderId, attempt + 1), 2000);
      } else {
        clearCart();
        toast.success('Payment received! Check your orders page.');
        navigate('/orders');
      }
    }
  };

  // Show loading state when returning from payment gateway
  if (isPaymentReturn) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Verifying Payment</h2>
          <p className="text-gray-600 dark:text-gray-400">Please wait while we confirm your payment...</p>
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
        <header className="bg-white dark:bg-gray-900 shadow-sm">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
            <Link to="/" className="flex items-center gap-2 text-gray-600 hover:text-blue-600">
              <ArrowLeft className="w-5 h-5" />
              Continue Shopping
            </Link>
          </div>
        </header>

        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
            <ShoppingCart className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Your cart is empty</h3>
            <p className="text-gray-600 mb-6">Add some products to get started</p>
            <Link to="/" className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700">
              Browse Products
            </Link>
          </div>
        </main>
      </div>
    );
  }

  if (settingsLoading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-800">
      <header className="bg-white dark:bg-gray-900 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <Link to="/" className="flex items-center gap-2 text-gray-600 hover:text-blue-600">
            <ArrowLeft className="w-5 h-5" />
            Continue Shopping
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 dark:text-white mb-6 sm:mb-8">Checkout</h1>

        <div className="grid lg:grid-cols-3 gap-8">
          {/* Cart Items */}
          <div className="lg:col-span-2">
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow">
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Order Items</h2>
              </div>
              <div className="divide-y divide-gray-200">
                {items.map((item, index) => (
                  <div key={index} className="p-6">
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <h3 className="font-semibold text-gray-900 dark:text-white">{item.product_name}</h3>
                        <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                          {item.term_months} {item.term_months === 1 ? 'Month' : 'Months'}
                        </p>
                        <p className="text-sm text-gray-600 dark:text-gray-300">
                          {item.account_type === 'subscriber' ? 'Subscriber' : 'Reseller'}
                        </p>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="text-xl font-bold text-gray-900 dark:text-white">{currencySymbol}{convertPrice(item.price).toFixed(2)}</span>
                        <button
                          onClick={() => removeItem(item.product_id, item.term_months)}
                          className="text-red-600 hover:text-red-700"
                          data-testid={`remove-item-${index}`}
                        >
                          <Trash2 className="w-5 h-5" />
                        </button>
                      </div>
                    </div>
                    
                    {/* Extend/Create Option for Subscriber Products */}
                    {item.account_type === 'subscriber' && extendChoices(item, userServices, addonIds).length > 0 && (
                      <div className="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-700">
                        <p className="text-sm font-medium text-blue-800 dark:text-blue-200 mb-3">
                          What would you like to do?
                        </p>
                        <div className="space-y-2">
                          {/* Option to create new line */}
                          <label className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 border-2 border-transparent has-[:checked]:border-blue-500">
                            <input
                              type="radio"
                              name={`action-${index}`}
                              checked={!item.action_type || item.action_type === 'create_new'}
                              onChange={() => updateItemAction(item.product_id, item.term_months, 'create_new', null)}
                              className="w-4 h-4 text-blue-600"
                              data-testid={`create-new-${index}`}
                            />
                            <Plus className="w-5 h-5 text-green-600" />
                            <div>
                              <span className="font-medium text-gray-900 dark:text-white">Create New Line</span>
                              <p className="text-xs text-gray-500 dark:text-gray-400">Get a new subscriber account</p>
                            </div>
                          </label>
                          
                          <p className="text-xs text-blue-700 dark:text-blue-300 px-2">Or extend one of your existing services:</p>
                          
                          {extendChoices(item, userServices, addonIds).map((service) => (
                            <label 
                              key={service.id} 
                              className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 border-2 border-transparent has-[:checked]:border-blue-500"
                            >
                              <input
                                type="radio"
                                name={`action-${index}`}
                                checked={item.action_type === 'extend' && item.renewal_service_id === service.id}
                                onChange={() => updateItemAction(item.product_id, item.term_months, 'extend', service.id)}
                                className="w-4 h-4 text-blue-600"
                                data-testid={`extend-${service.id}-${index}`}
                              />
                              <RefreshCw className="w-5 h-5 text-blue-600" />
                              <div className="flex-1">
                                <span className="font-medium text-gray-900 dark:text-white">Extend: {service.xtream_username}</span>
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  Expires: {service.expiry_date ? new Date(service.expiry_date).toLocaleDateString() : 'N/A'}
                                </p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* CMTV local change 2026-09-25: "Complete your setup" add-on offer */}
            <CheckoutAddons items={items} addItem={addItem} removeItem={removeItem}
              currencySymbol={currencySymbol} convertPrice={convertPrice} />
          </div>

          {/* Order Summary */}
          <div>
            {/* Coupon & Credits Section */}
            <div className="mb-6">
              <CheckoutCouponCredits
                subtotal={getTotal()}
                onDiscountChange={(discount, code) => {
                  setDiscountAmount(discount);
                  setAppliedCouponCode(code);
                }}
                onCreditsChange={(amount) => {
                  setCreditsUsed(amount);
                }}
              />
            </div>

            {/* Reseller Panel Credentials */}
            {hasNewResellerProduct && (
              <div className="mb-6 bg-purple-50 dark:bg-purple-900/20 border-2 border-purple-200 dark:border-purple-700 rounded-lg p-6">
                <div className="flex items-center gap-2 mb-4">
                  <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                  </svg>
                  <h3 className="font-bold text-purple-900 dark:text-purple-200 text-lg">
                    Reseller Panel Credentials
                  </h3>
                </div>
                
                <p className="text-sm text-purple-800 dark:text-purple-300 mb-4">
                  Enter the username and password for your reseller panel. If the username already exists, credits will be added to that account.
                </p>
                
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-purple-900 dark:text-purple-200 mb-2">
                      Username *
                    </label>
                    <input
                      type="text"
                      required={hasNewResellerProduct}
                      value={resellerUsername}
                      onChange={(e) => {
                        const val = e.target.value;
                        setResellerUsername(val);
                        setResellerUsernameExists(false);
                        setResellerAddCredits(false);
                        // Debounce username check
                        if (val.length >= 3) {
                          setCheckingUsername(true);
                          clearTimeout(window._resellerCheckTimeout);
                          window._resellerCheckTimeout = setTimeout(async () => {
                            try {
                              const authToken = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
                              const res = await axios.get(`${API_URL}/api/reseller/check-username/${val}`, {
                                headers: { Authorization: `Bearer ${authToken}` }
                              });
                              if (res.data.exists) {
                                setResellerUsernameExists(true);
                              }
                            } catch(e) {}
                            setCheckingUsername(false);
                          }, 500);
                        }
                      }}
                      className={`w-full px-4 py-2 border-2 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white ${resellerUsernameExists ? 'border-yellow-400' : 'border-purple-300 dark:border-purple-600'} focus:border-purple-500`}
                      placeholder="Enter reseller username"
                      data-testid="reseller-username"
                    />
                    {checkingUsername && (
                      <p className="text-xs text-purple-500 mt-1">Checking username...</p>
                    )}
                    {resellerUsernameExists && !resellerAddCredits && (
                      <div className="mt-2 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-lg">
                        <p className="text-sm text-yellow-800 dark:text-yellow-200 font-medium">
                          Username "{resellerUsername}" already exists on the panel.
                        </p>
                        <p className="text-xs text-yellow-700 dark:text-yellow-300 mt-1">
                          Would you like to add credits to this existing account?
                        </p>
                        <div className="flex gap-2 mt-2">
                          <button type="button" onClick={() => setResellerAddCredits(true)}
                            className="px-3 py-1 bg-yellow-600 text-white text-xs rounded hover:bg-yellow-700" data-testid="reseller-add-credits-yes">
                            Yes, add credits
                          </button>
                          <button type="button" onClick={() => { setResellerUsername(''); setResellerUsernameExists(false); }}
                            className="px-3 py-1 bg-gray-300 dark:bg-gray-600 text-gray-800 dark:text-white text-xs rounded hover:bg-gray-400" data-testid="reseller-add-credits-no">
                            No, choose different username
                          </button>
                        </div>
                      </div>
                    )}
                    {resellerAddCredits && (
                      <p className="text-xs text-green-600 mt-1 font-medium">Credits will be added to existing account "{resellerUsername}"</p>
                    )}
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-purple-900 dark:text-purple-200 mb-2">
                      Password *
                    </label>
                    <input
                      type="password"
                      required={hasNewResellerProduct}
                      value={resellerPassword}
                      onChange={(e) => setResellerPassword(e.target.value)}
                      className="w-full px-4 py-2 border-2 border-purple-300 dark:border-purple-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:border-purple-500"
                      placeholder="Choose a password"
                    />
                  </div>
                </div>
              </div>
            )}

            <div className="bg-white dark:bg-gray-900 rounded-lg shadow sticky top-4">
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Order Summary</h2>
              </div>
              <div className="p-6 space-y-4">
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-300">Subtotal</span>
                  <span className="font-semibold text-gray-900 dark:text-white">{currencySymbol}{convertPrice(getTotal()).toFixed(2)}</span>
                </div>
                
                {discountAmount > 0 && !tierWins && (
                  <div className="flex justify-between text-green-600">
                    <span>Discount ({appliedCouponCode})</span>
                    <span>-${discountAmount.toFixed(2)}</span>
                  </div>
                )}

                {/* CMTV local change 2026-09-25: referral tier discount */}
                {tierWins && (
                  <div className="flex justify-between text-green-600" data-testid="tier-discount-row">
                    <span>{tierQuote.tier} discount{tierQuote.lines.some((l) => l.free) ? ' (includes free CMTV+)' : ` (${tierQuote.pct}%)`}</span>
                    <span>-${tierQuote.amount.toFixed(2)}</span>
                  </div>
                )}
                {tierWins && appliedCouponCode && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Your {tierQuote.tier} discount is bigger than coupon {appliedCouponCode}, so it's used instead (they don't combine).
                  </p>
                )}

                {creditsApplied > 0 && (
                  <div className="flex justify-between text-green-600">
                    <span>Credits Applied</span>
                    <span>-${creditsApplied.toFixed(2)}</span>
                  </div>
                )}

                <div className="flex justify-between text-lg font-bold border-t pt-4">
                  <span className="text-gray-900 dark:text-white">Total</span>
                  <span className="text-blue-600">{currencySymbol}{convertPrice(payTotal).toFixed(2)}</span>
                </div>
              </div>

              {error && (
                <div className="px-6 pb-4">
                  <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg flex items-start gap-2">
                    <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
                  </div>
                </div>
              )}

              {/* Terms and Conditions */}
              {termsData?.enabled && (
                <div className="px-6 pb-4">
                  <div className="flex items-start gap-3 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    <input
                      type="checkbox"
                      id="terms-checkbox"
                      checked={termsAccepted}
                      onChange={(e) => setTermsAccepted(e.target.checked)}
                      className="w-5 h-5 mt-0.5 text-blue-600 border-gray-300 rounded focus:ring-blue-500 cursor-pointer shrink-0"
                      data-testid="terms-checkbox"
                    />
                    <label htmlFor="terms-checkbox" className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                      I agree to the{' '}
                      <button
                        type="button"
                        onClick={() => setShowTermsModal(true)}
                        className="text-blue-600 hover:text-blue-700 underline font-medium"
                        data-testid="view-terms-link"
                      >
                        {termsData.title || 'Terms and Conditions'}
                      </button>
                    </label>
                  </div>
                </div>
              )}

              {/* Terms Modal */}
              {showTermsModal && termsData && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                  <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
                    <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between shrink-0">
                      <h3 className="text-lg font-bold text-gray-900 dark:text-white">{termsData.title}</h3>
                      <button onClick={() => setShowTermsModal(false)} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
                    </div>
                    <div className="p-6 overflow-y-auto flex-1 prose dark:prose-invert max-w-none text-sm"
                      dangerouslySetInnerHTML={{ __html: termsData.content }}
                    />
                    <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex gap-3 shrink-0">
                      <button onClick={() => { setTermsAccepted(true); setShowTermsModal(false); }}
                        className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
                        data-testid="accept-terms-btn">
                        I Agree
                      </button>
                      <button onClick={() => setShowTermsModal(false)}
                        className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700">
                        Close
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Payment Method Selection */}
              <div className="px-6 pb-6">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Payment Method</h3>
                
                <div className="space-y-3 mb-6">
                  {/* Render payment methods in order from settings */}
                  {(settings?.payment_method_order || ['manual', 'emt', 'zelle', 'cashapp', 'venmo', 'wise', 'stripe', 'paypal', 'square', 'blockonomics', 'ghostpay', 'tagadapay']).map((method) => {
                    // Manual Payment
                    if (method === 'manual' && settings?.manual?.enabled !== false) {
                      return (
                        <label key="manual" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-blue-500 transition bg-white dark:bg-gray-800">
                          <input
                            type="radio"
                            name="payment"
                            value="manual"
                            checked={paymentMethod === 'manual'}
                            onChange={(e) => setPaymentMethod(e.target.value)}
                            className="w-4 h-4 text-blue-600"
                          />
                          <div className="ml-3">
                            <p className="font-semibold text-gray-900 dark:text-white">Manual Payment</p>
                            <p className="text-sm text-gray-600 dark:text-gray-400">Admin will confirm your payment</p>
                          </div>
                        </label>
                      );
                    }
                    
                    // Stripe
                    if (method === 'stripe' && settings?.stripe?.enabled) {
                      return (
                        <label key="stripe" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-purple-500 transition bg-white dark:bg-gray-800">
                          <input
                            type="radio"
                            name="payment"
                            value="stripe"
                            checked={paymentMethod === 'stripe'}
                            onChange={(e) => setPaymentMethod(e.target.value)}
                            className="w-4 h-4 text-purple-600"
                          />
                          <div className="ml-3 flex items-center gap-2">
                            <CreditCard className="w-5 h-5 text-purple-600" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Stripe</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">
                                {settings?.stripe?.crypto_enabled ? 'Cards, Bitcoin, USDC, ETH' : 'Pay with card'}
                              </p>
                            </div>
                          </div>
                        </label>
                      );
                    }
                    
                    // PayPal
                    if (method === 'paypal' && settings?.paypal?.enabled) {
                      return (
                        <label key="paypal" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-blue-500 transition bg-white dark:bg-gray-800">
                          <input
                            type="radio"
                            name="payment"
                            value="paypal"
                            checked={paymentMethod === 'paypal'}
                            onChange={(e) => setPaymentMethod(e.target.value)}
                            className="w-4 h-4 text-blue-600"
                          />
                          <div className="ml-3 flex items-center gap-2">
                            <CreditCard className="w-5 h-5 text-blue-600" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">PayPal</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay securely with PayPal</p>
                            </div>
                          </div>
                        </label>
                      );
                    }
                    
                    // Square
                    if (method === 'square' && settings?.square?.enabled) {
                      return (
                        <label key="square" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-indigo-500 transition bg-white dark:bg-gray-800">
                          <input
                            type="radio"
                            name="payment"
                            value="square"
                            checked={paymentMethod === 'square'}
                            onChange={(e) => setPaymentMethod(e.target.value)}
                            className="w-4 h-4 text-indigo-600"
                          />
                          <div className="ml-3 flex items-center gap-2">
                            <CreditCard className="w-5 h-5 text-indigo-600" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Square</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay with card, Apple Pay, Google Pay</p>
                            </div>
                          </div>
                        </label>
                      );
                    }
                    
                    // Blockonomics (Bitcoin)
                    if (method === 'blockonomics' && settings?.blockonomics?.enabled) {
                      return (
                        <label key="blockonomics" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-orange-500 transition bg-white dark:bg-gray-800">
                          <input
                            type="radio"
                            name="payment"
                            value="blockonomics"
                            checked={paymentMethod === 'blockonomics'}
                            onChange={(e) => setPaymentMethod(e.target.value)}
                            className="w-4 h-4 text-orange-500"
                          />
                          <div className="ml-3 flex items-center gap-2">
                            <Bitcoin className="w-5 h-5 text-orange-500" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Bitcoin</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay directly with Bitcoin (BTC)</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    if (method === 'ghostpay' && settings?.ghostpay?.enabled) {
                      return (
                        <label key="ghostpay" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-purple-500 transition bg-white dark:bg-gray-800" data-testid="payment-ghostpay">
                          <input type="radio" name="payment" value="ghostpay"
                            checked={paymentMethod === 'ghostpay'}
                            onChange={(e) => setPaymentMethod(e.target.value)}
                            className="w-4 h-4 text-purple-500" />
                          <div className="ml-3 flex items-center gap-2">
                            <Bitcoin className="w-5 h-5 text-purple-500" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Crypto (GhostPay)</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay with BTC, ETH, LTC, USDT and more</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    // Interac e-Transfer (EMT)
                    if (method === 'emt' && settings?.emt?.enabled) {
                      return (
                        <label key="emt" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-emerald-500 transition bg-white dark:bg-gray-800">
                          <input type="radio" name="payment" value="emt" checked={paymentMethod === 'emt'} onChange={(e) => setPaymentMethod(e.target.value)} className="w-4 h-4 text-emerald-600" />
                          <div className="ml-3 flex items-center gap-2">
                            <DollarSign className="w-5 h-5 text-emerald-600" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Interac e-Transfer</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay via EMT (Canadian banks)</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    // Zelle
                    if (method === 'zelle' && settings?.zelle?.enabled) {
                      return (
                        <label key="zelle" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-purple-500 transition bg-white dark:bg-gray-800">
                          <input type="radio" name="payment" value="zelle" checked={paymentMethod === 'zelle'} onChange={(e) => setPaymentMethod(e.target.value)} className="w-4 h-4 text-purple-600" />
                          <div className="ml-3 flex items-center gap-2">
                            <DollarSign className="w-5 h-5 text-purple-600" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Zelle</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay via Zelle bank transfer</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    // Cash App
                    if (method === 'cashapp' && settings?.cashapp?.enabled) {
                      return (
                        <label key="cashapp" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-green-500 transition bg-white dark:bg-gray-800">
                          <input type="radio" name="payment" value="cashapp" checked={paymentMethod === 'cashapp'} onChange={(e) => setPaymentMethod(e.target.value)} className="w-4 h-4 text-green-500" />
                          <div className="ml-3 flex items-center gap-2">
                            <DollarSign className="w-5 h-5 text-green-500" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Cash App</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay via Cash App</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    // Venmo
                    if (method === 'venmo' && settings?.venmo?.enabled) {
                      return (
                        <label key="venmo" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-blue-500 transition bg-white dark:bg-gray-800">
                          <input type="radio" name="payment" value="venmo" checked={paymentMethod === 'venmo'} onChange={(e) => setPaymentMethod(e.target.value)} className="w-4 h-4 text-blue-500" />
                          <div className="ml-3 flex items-center gap-2">
                            <DollarSign className="w-5 h-5 text-blue-500" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Venmo</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay via Venmo</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    // Wise
                    if (method === 'wise' && settings?.wise?.enabled) {
                      return (
                        <label key="wise" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-green-600 transition bg-white dark:bg-gray-800">
                          <input type="radio" name="payment" value="wise" checked={paymentMethod === 'wise'} onChange={(e) => setPaymentMethod(e.target.value)} className="w-4 h-4 text-green-600" />
                          <div className="ml-3 flex items-center gap-2">
                            <DollarSign className="w-5 h-5 text-green-600" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Wise</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">International bank transfer via Wise</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    // Helcim
                    if (method === 'tagadapay' && settings?.tagadapay?.enabled) {
                      return (
                        <label key="tagadapay" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-teal-500 transition bg-white dark:bg-gray-800" data-testid="payment-tagadapay">
                          <input type="radio" name="payment" value="tagadapay" checked={paymentMethod === 'tagadapay'}
                            onChange={(e) => setPaymentMethod(e.target.value)} className="w-4 h-4 text-teal-500" />
                          <div className="ml-3 flex items-center gap-2">
                            <CreditCard className="w-5 h-5 text-teal-500" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">TagadaPay</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Cards, SEPA, iDEAL, Bancontact and more</p>
                            </div>
                          </div>
                        </label>
                      );
                    }

                    if (method === 'helcim' && settings?.helcim?.enabled) {
                      return (
                        <label key="helcim" className="flex items-center p-4 border-2 border-gray-200 dark:border-gray-700 rounded-lg cursor-pointer hover:border-teal-500 transition bg-white dark:bg-gray-800" data-testid="helcim-payment-option">
                          <input type="radio" name="payment" value="helcim" checked={paymentMethod === 'helcim'} onChange={(e) => setPaymentMethod(e.target.value)} className="w-4 h-4 text-teal-600" />
                          <div className="ml-3 flex items-center gap-2">
                            <CreditCard className="w-5 h-5 text-teal-600" />
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white">Helcim</p>
                              <p className="text-sm text-gray-600 dark:text-gray-400">Pay with credit/debit card or ACH</p>
                            </div>
                          </div>
                        </label>
                      );
                    }
                    
                    return null;
                  })}
                </div>

                {/* Payment Button/PayPal/Stripe/Square/EMT */}
                {/* CMTV local change 2026-09-25: nothing to pay (a member's free CMTV+, or credits cover it): one button, no payment */}
                {tierWins && payTotal === 0 ? (
                  <div>
                    <button
                      onClick={handleCheckout}
                      disabled={createOrderMutation.isPending}
                      className="w-full bg-green-600 text-white py-3 rounded-lg font-semibold hover:bg-green-700 disabled:opacity-50"
                      data-testid="free-order-btn"
                    >
                      {createOrderMutation.isPending ? 'Processing...' : 'Complete order ($0.00)'}
                    </button>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-3 text-center">
                      Covered by your {tierQuote.tier} benefits. Nothing to pay.
                    </p>
                  </div>
                ) : paymentMethod === 'manual' ? (
                  <div>
                    <button
                      onClick={handleCheckout}
                      disabled={createOrderMutation.isPending}
                      className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50"
                    >
                      {createOrderMutation.isPending ? 'Processing...' : 'Place Order'}
                    </button>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-3 text-center">
                      Your order will be pending until payment is confirmed by admin
                    </p>
                  </div>
                ) : paymentMethod === 'emt' ? (
                  <div>
                    <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-5 mb-4">
                      <h4 className="font-semibold text-emerald-900 dark:text-emerald-200 mb-3 flex items-center gap-2">
                        <DollarSign className="w-5 h-5" />
                        Interac e-Transfer Instructions
                      </h4>
                      <div className="text-sm text-emerald-800 dark:text-emerald-300 whitespace-pre-line">
                        {settings?.emt?.instructions || 'Please contact support for e-Transfer payment details.'}
                      </div>
                      <div className="mt-3 pt-3 border-t border-emerald-200 dark:border-emerald-700">
                        <p className="text-sm font-medium text-emerald-900 dark:text-emerald-200">
                          Amount: <span className="font-bold">{currencySymbol}{convertPrice(payTotal).toFixed(2)} {currencyCode}</span>
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={handleCheckout}
                      disabled={createOrderMutation.isPending}
                      className="w-full bg-emerald-600 text-white py-3 rounded-lg font-semibold hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {createOrderMutation.isPending ? 'Processing...' : 'Place Order (EMT)'}
                    </button>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-3 text-center">
                      Send your e-Transfer after placing the order. Include your Order ID in the message.
                    </p>
                  </div>
                                ) : paymentMethod === 'zelle' ? (
                  <div>
                    <div className="bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 rounded-lg p-5 mb-4">
                      <h4 className="font-semibold text-purple-900 dark:text-purple-200 mb-3 flex items-center gap-2">
                        <DollarSign className="w-5 h-5" />
                        Zelle Payment Instructions
                      </h4>
                      <div className="text-sm text-purple-800 dark:text-purple-300 whitespace-pre-line">
                        {settings?.zelle?.instructions || 'Please contact support for Zelle payment details.'}
                      </div>
                      <div className="mt-3 pt-3 border-t border-purple-200 dark:border-purple-700">
                        <p className="text-sm font-medium text-purple-900 dark:text-purple-200">
                          Amount: <span className="font-bold">{currencySymbol}{convertPrice(payTotal).toFixed(2)} {currencyCode}</span>
                        </p>
                      </div>
                    </div>
                    <button onClick={handleCheckout} disabled={createOrderMutation.isPending}
                      className="w-full bg-purple-600 text-white py-3 rounded-lg font-semibold hover:bg-purple-700 disabled:opacity-50">
                      {createOrderMutation.isPending ? 'Processing...' : 'Place Order (Zelle)'}
                    </button>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-3 text-center">
                      Send your Zelle payment after placing the order. Include your Order ID.
                    </p>
                  </div>
                                ) : paymentMethod === 'cashapp' ? (
                  <div>
                    <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-5 mb-4">
                      <h4 className="font-semibold text-green-900 dark:text-green-200 mb-3 flex items-center gap-2">
                        <DollarSign className="w-5 h-5" />
                        Cash App Payment Instructions
                      </h4>
                      <div className="text-sm text-green-800 dark:text-green-300 whitespace-pre-line">
                        {settings?.cashapp?.instructions || 'Please contact support for Cash App payment details.'}
                      </div>
                      <div className="mt-3 pt-3 border-t border-green-200 dark:border-green-700">
                        <p className="text-sm font-medium text-green-900 dark:text-green-200">
                          Amount: <span className="font-bold">{currencySymbol}{convertPrice(payTotal).toFixed(2)} {currencyCode}</span>
                        </p>
                      </div>
                    </div>
                    <button onClick={handleCheckout} disabled={createOrderMutation.isPending}
                      className="w-full bg-green-600 text-white py-3 rounded-lg font-semibold hover:bg-green-700 disabled:opacity-50">
                      {createOrderMutation.isPending ? 'Processing...' : 'Place Order (Cash App)'}
                    </button>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-3 text-center">
                      Send your Cash App payment after placing the order. Include your Order ID.
                    </p>
                  </div>
                                ) : paymentMethod === 'venmo' ? (
                  <div>
                    <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-5 mb-4">
                      <h4 className="font-semibold text-blue-900 dark:text-blue-200 mb-3 flex items-center gap-2">
                        <DollarSign className="w-5 h-5" />
                        Venmo Payment Instructions
                      </h4>
                      <div className="text-sm text-blue-800 dark:text-blue-300 whitespace-pre-line">
                        {settings?.venmo?.instructions || 'Please contact support for Venmo payment details.'}
                      </div>
                      <div className="mt-3 pt-3 border-t border-blue-200 dark:border-blue-700">
                        <p className="text-sm font-medium text-blue-900 dark:text-blue-200">
                          Amount: <span className="font-bold">{currencySymbol}{convertPrice(payTotal).toFixed(2)} {currencyCode}</span>
                        </p>
                      </div>
                    </div>
                    <button onClick={handleCheckout} disabled={createOrderMutation.isPending}
                      className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50">
                      {createOrderMutation.isPending ? 'Processing...' : 'Place Order (Venmo)'}
                    </button>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-3 text-center">
                      Send your Venmo payment after placing the order. Include your Order ID.
                    </p>
                  </div>
                                ) : paymentMethod === 'wise' ? (
                  <div>
                    <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-5 mb-4">
                      <h4 className="font-semibold text-green-900 dark:text-green-200 mb-3 flex items-center gap-2">
                        <DollarSign className="w-5 h-5" />
                        Wise Payment Instructions
                      </h4>
                      <div className="text-sm text-green-800 dark:text-green-300 whitespace-pre-line">
                        {settings?.wise?.instructions || 'Please contact support for Wise payment details.'}
                      </div>
                      <div className="mt-3 pt-3 border-t border-green-200 dark:border-green-700">
                        <p className="text-sm font-medium text-green-900 dark:text-green-200">
                          Amount: <span className="font-bold">{currencySymbol}{convertPrice(payTotal).toFixed(2)} {currencyCode}</span>
                        </p>
                      </div>
                    </div>
                    <button onClick={handleCheckout} disabled={createOrderMutation.isPending}
                      className="w-full bg-green-600 text-white py-3 rounded-lg font-semibold hover:bg-green-700 disabled:opacity-50">
                      {createOrderMutation.isPending ? 'Processing...' : 'Place Order (Wise)'}
                    </button>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-3 text-center">
                      Send your Wise payment after placing the order. Include your Order ID.
                    </p>
                  </div>
                ) : paymentMethod === 'helcim' && settings?.helcim?.enabled ? (
                  <button
                    onClick={handleHelcimPay}
                    disabled={helcimLoading}
                    data-testid="helcim-pay-button"
                    className="w-full bg-teal-600 text-white py-4 rounded-lg font-semibold text-lg hover:bg-teal-700 flex items-center justify-center gap-2 disabled:opacity-50"
                  >
                    {helcimLoading ? (
                      <><Loader2 className="w-5 h-5 animate-spin" /> Initializing...</>
                    ) : (
                      <><CreditCard className="w-6 h-6" /> Pay with Helcim</>
                    )}
                  </button>
                ) : paymentMethod === 'paypal' && settings?.paypal?.client_id ? (
                  /* CMTV local change 2026-09-25: optional "Renew automatically" (PayPal subscription) around the normal buttons */
                  <CheckoutAutoRenew items={items} total={getTotal()} discounted={(!!appliedCouponCode && !tierWins) || creditsApplied > 0}
                    memberPrice={tierWins ? payTotal : null}
                    clientId={settings.paypal.client_id} onDone={() => { clearCart(); navigate('/orders'); }} onError={setError}>
                  <PayPalScriptProvider options={{ "client-id": settings.paypal.client_id, currency: settings?.currency?.code || "USD" }}>
                    <PayPalButtons
                      style={{ layout: "vertical", color: "blue" }}
                      createOrder={createPayPalOrder}
                      onApprove={onPayPalApprove}
                      onError={(err) => setError('PayPal payment failed')}
                    />
                  </PayPalScriptProvider>
                  </CheckoutAutoRenew>
                ) : paymentMethod === 'stripe' && settings?.stripe?.enabled ? (
                  <button
                    onClick={handleStripePay}
                    className="w-full bg-purple-600 text-white py-4 rounded-lg font-semibold text-lg hover:bg-purple-700 flex items-center justify-center gap-2"
                  >
                    <CreditCard className="w-6 h-6" />
                    Pay with Bitcoin/Crypto/Card
                  </button>
                ) : paymentMethod === 'square' && settings?.square?.enabled ? (
                  currentOrderId ? (
                    <SquarePaymentForm
                      amount={getTotal()}
                      orderId={currentOrderId}
                      settings={settings.square}
                      onSuccess={handleSquareSuccess}
                      onError={handleSquareError}
                    />
                  ) : (
                    <button
                      onClick={handleSquarePay}
                      className="w-full bg-indigo-600 text-white py-4 rounded-lg font-semibold text-lg hover:bg-indigo-700"
                    >
                      Continue with Square
                    </button>
                  )
                ) : paymentMethod === 'blockonomics' && settings?.blockonomics?.enabled ? (
                  btcPaymentData ? (
                    <div className="space-y-4">
                      {/* Bitcoin Payment Details */}
                      <div className="bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-700 rounded-lg p-4">
                        <div className="flex items-center gap-2 mb-3">
                          <Bitcoin className="w-5 h-5 text-orange-500" />
                          <span className="font-semibold text-orange-800 dark:text-orange-200">
                            Send Bitcoin to complete payment
                          </span>
                        </div>
                        
                        {/* QR Code */}
                        <div className="flex justify-center mb-4 p-4 bg-white rounded-lg">
                          <QRCodeSVG 
                            value={btcPaymentData.qr_data} 
                            size={180}
                            level="H"
                            includeMargin={true}
                          />
                        </div>
                        
                        {/* Amount */}
                        <div className="mb-4 text-center">
                          <p className="text-2xl font-bold text-orange-600 dark:text-orange-400">
                            {btcPaymentData.amount_btc?.toFixed(8)} BTC
                          </p>
                          <p className="text-sm text-gray-600 dark:text-gray-400">
                            ≈ ${btcPaymentData.amount_usd?.toFixed(2)} USD @ ${btcPaymentData.btc_price?.toLocaleString()}/BTC
                          </p>
                        </div>
                        
                        {/* Address */}
                        <div className="mb-4">
                          <label className="text-xs text-gray-600 dark:text-gray-400 mb-1 block">Bitcoin Address</label>
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={btcPaymentData.btc_address}
                              readOnly
                              className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm font-mono"
                            />
                            <button
                              onClick={copyBtcAddress}
                              className="px-3 py-2 bg-gray-200 dark:bg-gray-700 rounded hover:bg-gray-300 dark:hover:bg-gray-600"
                            >
                              {copiedAddress ? <CheckCircle className="w-5 h-5 text-green-500" /> : <Copy className="w-5 h-5 text-gray-600 dark:text-gray-300" />}
                            </button>
                          </div>
                        </div>
                        
                        {/* Payment Status */}
                        {btcPaymentStatus && (
                          <div className="mb-4 p-3 bg-white dark:bg-gray-800 rounded-lg">
                            <div className="flex items-center justify-between text-sm">
                              <span className="text-gray-600 dark:text-gray-400">Status:</span>
                              <span className={`font-semibold ${
                                btcPaymentStatus.payment_status === 'confirmed' ? 'text-green-600' :
                                btcPaymentStatus.payment_status === 'unconfirmed' ? 'text-yellow-600' :
                                'text-gray-600'
                              }`}>
                                {btcPaymentStatus.payment_status === 'confirmed' ? 'Confirmed!' :
                                 btcPaymentStatus.payment_status === 'unconfirmed' ? 'Received - Confirming...' :
                                 'Waiting for payment...'}
                              </span>
                            </div>
                            {btcPaymentStatus.confirmations > 0 && (
                              <div className="flex items-center justify-between text-sm mt-1">
                                <span className="text-gray-600 dark:text-gray-400">Confirmations:</span>
                                <span className="font-semibold text-gray-900 dark:text-white">
                                  {btcPaymentStatus.confirmations}/{btcPaymentStatus.confirmations_required}
                                </span>
                              </div>
                            )}
                            {btcPaymentStatus.amount_received_btc > 0 && (
                              <div className="flex items-center justify-between text-sm mt-1">
                                <span className="text-gray-600 dark:text-gray-400">Received:</span>
                                <span className="font-semibold text-green-600">
                                  {btcPaymentStatus.amount_received_btc?.toFixed(8)} BTC
                                </span>
                              </div>
                            )}
                          </div>
                        )}
                        
                        {/* Polling indicator */}
                        {btcPolling && (
                          <div className="flex items-center justify-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            <span>Monitoring for payment...</span>
                          </div>
                        )}
                      </div>
                      
                      <p className="text-xs text-gray-500 dark:text-gray-400 text-center">
                        Payment expires in {btcPaymentData.expires_in_minutes} minutes. Send exact amount to avoid delays.
                      </p>
                    </div>
                  ) : (
                    <button
                      onClick={handleBlockonomicsPay}
                      className="w-full bg-orange-500 text-white py-4 rounded-lg font-semibold text-lg hover:bg-orange-600 flex items-center justify-center gap-2"
                    >
                      <Bitcoin className="w-6 h-6" />
                      Pay with Bitcoin
                    </button>
                  )
                ) : paymentMethod === 'ghostpay' && settings?.ghostpay?.enabled ? (
                  <div className="space-y-3">
                    <button
                      onClick={async () => {
                        try {
                          setError('');
                          setGhostpayLoading(true);
                          const authToken = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
                          // Create order first
                          const orderRes = await axios.post(`${API_URL}/api/orders`, {
                            items: items.map(i => ({ product_id: i.product_id, product_name: i.product_name, term_months: i.term_months, price: i.price, account_type: i.account_type, action_type: i.action_type, renewal_service_id: i.renewal_service_id })),
                            total: getTotal(), coupon_code: appliedCouponCode, use_credits: creditsApplied
                          }, { headers: { Authorization: `Bearer ${authToken}` }});
                          const orderId = orderRes.data.order_id || orderRes.data.id;
                          // Redirect to GhostPay hosted checkout
                          const gpApiKey = settings?.ghostpay?.api_key || '';
                          const amount = getTotal().toFixed(2);
                          const siteUrl = window.location.origin;
                          const fiat = typeof settings?.currency === 'string' ? settings.currency : settings?.currency?.code || 'USD';
                          const callbackUrl = encodeURIComponent(`${API_URL}/api/webhooks/ghostpay`);
                          const returnUrl = encodeURIComponent(`${siteUrl}/orders?payment=success&order_id=${orderId}`);
                          clearCart();
                          window.location.href = `https://gateway.ghostpay.cash/checkout?amount=${amount}&fiat=${fiat}&orderId=${orderId}&apiKey=${gpApiKey}&callbackUrl=${callbackUrl}&returnUrl=${returnUrl}`;
                        } catch (err) {
                          setError(err.response?.data?.detail || 'Failed to create order');
                          setGhostpayLoading(false);
                        }
                      }}
                      disabled={ghostpayLoading}
                      className="w-full bg-purple-600 text-white py-3 rounded-lg font-bold hover:bg-purple-700 flex items-center justify-center gap-2 disabled:opacity-50"
                      data-testid="ghostpay-pay-btn"
                    >
                      <Bitcoin className="w-5 h-5" />
                      {ghostpayLoading ? 'Redirecting to GhostPay...' : 'Pay with Crypto (GhostPay)'}
                    </button>
                    <p className="text-xs text-center text-gray-500 dark:text-gray-400">You will be redirected to GhostPay to select your cryptocurrency and complete payment</p>
                  </div>
                ) : paymentMethod === 'tagadapay' && settings?.tagadapay?.enabled ? (
                  <div className="space-y-3">
                    <div className="space-y-3">
                      <input type="text" placeholder="Card Number" id="tagada-card" className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white" />
                      <div className="grid grid-cols-2 gap-3">
                        <input type="text" placeholder="MM/YY" id="tagada-expiry" className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white" />
                        <input type="text" placeholder="CVC" id="tagada-cvc" className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white" />
                      </div>
                      <input type="text" placeholder="Cardholder Name" id="tagada-name" className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white" />
                    </div>
                    <button
                      onClick={async () => {
                        try {
                          setError('');
                          setGhostpayLoading(true);
                          
                          const cardNumber = document.getElementById('tagada-card').value.replace(/\s/g, '');
                          const expiry = document.getElementById('tagada-expiry').value;
                          const cvc = document.getElementById('tagada-cvc').value;
                          const cardName = document.getElementById('tagada-name').value;
                          
                          if (!cardNumber || !expiry || !cvc) { setError('Please fill in all card fields'); setGhostpayLoading(false); return; }
                          
                          // Send card data to backend for server-side tokenization & payment
                          const authToken = JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token;
                          const orderRes = await axios.post(`${API_URL}/api/orders`, {
                            items: items.map(i => ({ product_id: i.product_id, product_name: i.product_name, term_months: i.term_months, price: i.price, account_type: i.account_type, action_type: i.action_type, renewal_service_id: i.renewal_service_id })),
                            total: getTotal(), coupon_code: appliedCouponCode, use_credits: creditsApplied,
                            reseller_credentials: hasNewResellerProduct ? { username: resellerUsername, password: resellerPassword, add_credits_to_existing: resellerAddCredits } : null
                          }, { headers: { Authorization: `Bearer ${authToken}` }});
                          const orderId = orderRes.data.order_id || orderRes.data.id;
                          
                          const payRes = await axios.post(`${API_URL}/api/orders/${orderId}/pay/tagadapay`, {
                            card_number: cardNumber, expiry, cvc, cardholder_name: cardName
                          }, { headers: { Authorization: `Bearer ${authToken}` }});
                          
                          if (payRes.data.requires_redirect) {
                            window.location.href = payRes.data.redirect_url;
                          } else if (payRes.data.success) {
                            clearCart();
                            toast.success('Payment successful!');
                            navigate('/orders');
                          }
                        } catch (err) {
                          setError(err.response?.data?.detail || err.message || 'Payment failed');
                        } finally {
                          setGhostpayLoading(false);
                        }
                      }}
                      disabled={ghostpayLoading}
                      className="w-full bg-teal-600 text-white py-3 rounded-lg font-bold hover:bg-teal-700 flex items-center justify-center gap-2 disabled:opacity-50"
                      data-testid="tagadapay-pay-btn"
                    >
                      <CreditCard className="w-5 h-5" />
                      {ghostpayLoading ? 'Processing...' : `Pay $${getTotal().toFixed(2)}`}
                    </button>
                  </div>
                ) : (
                  <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-600 rounded-lg p-4">
                    <p className="text-sm text-yellow-800 dark:text-yellow-200">Selected payment method is not configured.</p>
                  </div>
                )}
              </div>
            </div>

            {/* Customer Info */}
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow mt-6 p-6">
              <h3 className="font-semibold text-gray-900 dark:text-white mb-3">Customer Information</h3>
              <div className="space-y-2 text-sm">
                <p className="text-gray-600 dark:text-gray-300">Name: <span className="text-gray-900 dark:text-white font-medium">{user?.name}</span></p>
                <p className="text-gray-600 dark:text-gray-300">Email: <span className="text-gray-900 dark:text-white font-medium">{user?.email}</span></p>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
