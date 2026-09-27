import React, { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GoogleReCaptchaProvider } from 'react-google-recaptcha-v3';
import { useAuthStore } from './store/store';
import { useBrandingStore } from './store/branding';
import { useCurrencyStore } from './store/currency';
import api from './api/api';
import { Toaster } from 'sonner';

// Pages
import HomePage from './pages/HomePage';
import CmtvHomePage from './pages/cmtv/CmtvHomePage'; // CMTV local change 2026-09-25: CMTV storefront on "/"
import FinancesPage from './pages/cmtv/FinancesPage'; // CMTV local change 2026-09-25: Admin > Finances
import AdminReferralsPage from './pages/cmtv/AdminReferralsPage'; // CMTV local change 2026-09-25: Admin > Referrals
import AdminAudiobooksPage from './pages/cmtv/AdminAudiobooksPage'; // CMTV local change 2026-09-25: Admin > Audiobooks
import AdminCustomerPage from './pages/cmtv/AdminCustomerPage'; // CMTV local change 2026-09-27: customer profile page
import AdminAddonsPage from './pages/cmtv/AdminAddonsPage'; // CMTV local change 2026-09-26: Admin > Add-ons (Cockpit: Stremio, CMTVpn)
import LoginPage from './pages/LoginPage'; // eslint-disable-line no-unused-vars -- CMTV 2026-09-26: replaced by CmtvLoginPage
import RegisterPage from './pages/RegisterPage'; // eslint-disable-line no-unused-vars -- CMTV 2026-09-26: replaced by CmtvRegisterPage
import CmtvLoginPage from './pages/cmtv/CmtvLoginPage'; // CMTV local change 2026-09-26: CMTV sign in page
import CmtvRegisterPage from './pages/cmtv/CmtvRegisterPage'; // CMTV local change 2026-09-26: CMTV sign up page
import LinkEmailPage from './pages/LinkEmailPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import ProductsPage from './pages/ProductsPage';
import OrderProductPage from './pages/OrderProductPage';
import CheckoutPage from './pages/CheckoutPage';
import DashboardPage from './pages/DashboardPage'; // eslint-disable-line no-unused-vars -- CMTV 2026-09-26: replaced by CmtvDashboardPage
import CmtvDashboardPage from './pages/cmtv/CmtvDashboardPage'; // CMTV local change 2026-09-26: new customer dashboard
import { CmtvAccountFrame } from './components/cmtv/AccountShell'; // CMTV local change 2026-09-26: navy frame for customer pages
import ServicesPage from './pages/ServicesPage';
import OrdersPage from './pages/OrdersPage';
import InvoicesPage from './pages/InvoicesPage';
import ReferralDashboard from './pages/ReferralDashboard';
import LicenseActivationRequired from './pages/LicenseActivationRequired';
import EmailVerificationPage from './pages/EmailVerificationPage';
import AdminDashboard from './pages/AdminDashboard'; // eslint-disable-line no-unused-vars -- CMTV 2026-09-26: shown to staff by AdminHomePage
import AdminHomePage from './pages/cmtv/AdminHomePage'; // CMTV local change 2026-09-26: admin home "command centre"
import { CmtvAdminFrame } from './components/cmtv/AdminShell'; // CMTV local change 2026-09-26: navy frame + sidebar around every admin tab
import AdminCustomers from './pages/AdminCustomers';
import AdminOrders from './pages/AdminOrders';
import AdminInvoices from './pages/AdminInvoices';
import AdminProducts from './pages/AdminProducts';
import AdminSettings from './pages/AdminSettings';
import StaffManagement from './pages/StaffManagement';
import AdminTickets from './pages/AdminTickets';
import AdminMassEmail from './pages/AdminMassEmail';
import AdminEmailTemplates from './pages/AdminEmailTemplates';
import AdminCoupons from './pages/AdminCoupons';
import AdminRefunds from './pages/AdminRefunds';
import AdminDownloads from './pages/AdminDownloads';
import AdminKnowledgeBase from './pages/AdminKnowledgeBase';
import KnowledgeBasePage from './pages/KnowledgeBasePage';
import SEOHead from './components/SEOHead';
import ChatbotWidget from './components/ChatbotWidget';
import { useTimezone } from './utils/timezone';
import AnalyticsDashboard from './pages/AnalyticsDashboard';
import AdminImportedUsers from './pages/AdminImportedUsers';
import TicketsPage from './pages/TicketsPage';
import DownloadsPage from './pages/DownloadsPage';
import PayPalSuccessPage from './pages/PayPalSuccessPage';
import LauncherPayPage from './pages/LauncherPayPage';
import LauncherDashboard from './pages/LauncherDashboard';
import LauncherManagePage from './pages/LauncherManagePage';

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Protected Route Component
function ProtectedRoute({ children }) {
  const { token } = useAuthStore();
  return token ? children : <Navigate to="/login" />;
}

// Admin Route Component
function AdminRoute({ children }) {
  const { isAdmin, user } = useAuthStore();
  const isStaff = user?.role === 'staff';
  return (isAdmin() || isStaff) ? children : <Navigate to="/dashboard" />;
}

// License Check Component
function LicenseCheck({ children }) {
  const [licensed, setLicensed] = React.useState(null);

  React.useEffect(() => {
    const checkLicense = async () => {
      try {
        const response = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/license/status`);
        const data = await response.json();
        
        if (!data.licensed && licensed === true) {
          // License became invalid, force reload to show lock screen
          window.location.reload();
        }
        
        setLicensed(data.licensed);
      } catch (error) {
        setLicensed(false);
      }
    };
    
    checkLicense();
    
    // Check license every 30 seconds
    const interval = setInterval(checkLicense, 30000);
    
    return () => clearInterval(interval);
  }, [licensed]);

  if (licensed === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900">
        <div>
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-white text-center">Checking license...</p>
        </div>
      </div>
    );
  }

  if (!licensed) {
    return <LicenseActivationRequired />;
  }

  return children;
}

function TimezoneLoader() {
  useTimezone();
  return null;
}

function App() {
  const { fetchBranding } = useBrandingStore();
  const { fetchCurrency } = useCurrencyStore();
  const { token, logout } = useAuthStore();
  const [recaptchaSiteKey, setRecaptchaSiteKey] = useState('');
  const [isReady, setIsReady] = useState(false);

  // Auto-logout after 15 minutes of inactivity
  useEffect(() => {
    if (!token) return;
    
    const TIMEOUT = 15 * 60 * 1000; // 15 minutes
    let timer;

    const resetTimer = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        logout();
        window.location.href = '/login';
      }, TIMEOUT);
    };

    const events = ['mousedown', 'keydown', 'scroll', 'touchstart'];
    events.forEach(e => window.addEventListener(e, resetTimer));
    resetTimer();

    return () => {
      clearTimeout(timer);
      events.forEach(e => window.removeEventListener(e, resetTimer));
    };
  }, [token, logout]);

  React.useEffect(() => {
    const loadBranding = async () => {
      await fetchBranding();
      await fetchCurrency();
    };
    loadBranding();
    
    // Fetch reCAPTCHA site key
    const fetchRecaptchaKey = async () => {
      try {
        const response = await api.get('/api/recaptcha/sitekey');
        if (response.data.site_key) {
          setRecaptchaSiteKey(response.data.site_key);
        }
      } catch (err) {
        console.log('Using default reCAPTCHA key');
      }
      setIsReady(true);
    };
    fetchRecaptchaKey();
  }, [fetchBranding]);

  if (!isReady) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <GoogleReCaptchaProvider reCaptchaKey={recaptchaSiteKey}>
        <LicenseCheck>
          <Router>
            <div className="min-h-screen bg-gray-50">
          <Routes>
            {/* Public routes */}
            <Route path="/" element={<CmtvHomePage />} />
            <Route path="/classic" element={<HomePage />} />
            <Route path="/login" element={<CmtvLoginPage />} />
            <Route path="/register" element={<CmtvRegisterPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/link-email" element={<LinkEmailPage />} />
            <Route path="/verify-email" element={<EmailVerificationPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/order/:productId" element={<OrderProductPage />} />
            <Route path="/launcher/pay/:orderId" element={<LauncherPayPage />} />
            <Route path="/launcher/manage/:deviceToken" element={<LauncherManagePage />} />
            
            {/* Protected routes */}
            <Route
              path="/checkout"
              element={
                <ProtectedRoute>
                  <CheckoutPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <CmtvDashboardPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/services"
              element={
                <ProtectedRoute>
                  <CmtvAccountFrame><ServicesPage /></CmtvAccountFrame>
                </ProtectedRoute>
              }
            />
            <Route
              path="/orders"
              element={
                <ProtectedRoute>
                  <CmtvAccountFrame><OrdersPage /></CmtvAccountFrame>
                </ProtectedRoute>
              }
            />
            <Route
              path="/invoices"
              element={
                <ProtectedRoute>
                  <CmtvAccountFrame><InvoicesPage /></CmtvAccountFrame>
                </ProtectedRoute>
              }
            />
            <Route
              path="/tickets"
              element={
                <ProtectedRoute>
                  <CmtvAccountFrame><TicketsPage /></CmtvAccountFrame>
                </ProtectedRoute>
              }
            />
            <Route
              path="/referrals"
              element={
                <ProtectedRoute>
                  <CmtvAccountFrame><ReferralDashboard /></CmtvAccountFrame>
                </ProtectedRoute>
              }
            />
            <Route
              path="/downloads"
              element={
                <ProtectedRoute>
                  <CmtvAccountFrame><DownloadsPage /></CmtvAccountFrame>
                </ProtectedRoute>
              }
            />
            
            {/* Admin routes */}
            <Route
              path="/admin"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <AdminHomePage />
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route path="/admin/imported-users" element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AdminImportedUsers /></CmtvAdminFrame></AdminRoute></ProtectedRoute>} />
            <Route path="/admin/launcher" element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><LauncherDashboard /></CmtvAdminFrame></AdminRoute></ProtectedRoute>} />

            <Route
              path="/admin/customers"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminCustomers /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/orders"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminOrders /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/invoices"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminInvoices /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/products"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminProducts /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/settings"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminSettings /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/tickets"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminTickets /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/mass-email"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminMassEmail /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/email-templates"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminEmailTemplates /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/coupons"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminCoupons /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/refunds"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminRefunds /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/downloads"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminDownloads /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/knowledge-base"
              element={
                <ProtectedRoute>
                  <AdminRoute>
                    <CmtvAdminFrame><AdminKnowledgeBase /></CmtvAdminFrame>
                  </AdminRoute>
                </ProtectedRoute>
              }
            />
            <Route
              path="/knowledge-base"
              element={
                <ProtectedRoute>
                  <CmtvAccountFrame><KnowledgeBasePage /></CmtvAccountFrame>
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/staff"
              element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><StaffManagement /></CmtvAdminFrame></AdminRoute></ProtectedRoute>}
            />
            <Route
              path="/admin/analytics"
              element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AnalyticsDashboard /></CmtvAdminFrame></AdminRoute></ProtectedRoute>}
            />
            <Route
              path="/admin/finances"
              element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><FinancesPage /></CmtvAdminFrame></AdminRoute></ProtectedRoute>}
            />
            <Route
              path="/admin/referrals"
              element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AdminReferralsPage /></CmtvAdminFrame></AdminRoute></ProtectedRoute>}
            />
            <Route path="/admin/customer" element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AdminCustomerPage /></CmtvAdminFrame></AdminRoute></ProtectedRoute>} />
            <Route path="/admin/customer/:id" element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AdminCustomerPage /></CmtvAdminFrame></AdminRoute></ProtectedRoute>} />
            <Route
              path="/admin/stremio"
              element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AdminAddonsPage key="nuvio" module="nuvio" /></CmtvAdminFrame></AdminRoute></ProtectedRoute>}
            />
            <Route
              path="/admin/cmtvpn"
              element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AdminAddonsPage key="vpn" module="vpn" /></CmtvAdminFrame></AdminRoute></ProtectedRoute>}
            />
            <Route path="/admin/addons" element={<Navigate to="/admin/stremio" replace />} />
            <Route
              path="/admin/audiobooks"
              element={<ProtectedRoute><AdminRoute><CmtvAdminFrame><AdminAudiobooksPage /></CmtvAdminFrame></AdminRoute></ProtectedRoute>}
            />
          </Routes>
        </div>
      </Router>
      <SEOHead />
      <ChatbotWidget />
      <TimezoneLoader />
      <Toaster position="top-center" richColors closeButton duration={4000} />
      </LicenseCheck>
      </GoogleReCaptchaProvider>
    </QueryClientProvider>
  );
}

export default App;
