import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token to requests
api.interceptors.request.use((config) => {
  const authData = localStorage.getItem('auth-storage');
  if (authData) {
    try {
      const { state } = JSON.parse(authData);
      if (state?.token) {
        config.headers.Authorization = `Bearer ${state.token}`;
      }
    } catch (e) {
      console.error('Error parsing auth data:', e);
    }
  }
  return config;
});

// Handle 401 responses - redirect to login on expired session
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/api/auth/login')) {
      // Clear auth state and redirect to login
      try {
        localStorage.removeItem('auth-storage');
      } catch (e) {}
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authAPI = {
  register: (data) => api.post('/api/auth/register', data),
  login: (data) => api.post('/api/auth/login', data),
  forgotPassword: (data) => api.post('/api/auth/forgot-password', data),
  resetPassword: (data) => api.post('/api/auth/reset-password', data),
  checkResetToken: (token) => api.post('/api/auth/reset-password/check', { token }), // CMTV 2026-09-28: POST, keeps the token out of logs
  getMe: () => api.get('/api/auth/me'),
};

// Products API
export const productsAPI = {
  getAll: () => api.get('/api/products'),
  getOne: (id) => api.get(`/api/products/${id}`),
};

// Orders API
export const ordersAPI = {
  create: (data) => api.post('/api/orders', data),
  getAll: () => api.get('/api/orders'),
  getOne: (id) => api.get(`/api/orders/${id}`),
  checkGhostPay: (id) => api.post(`/api/orders/${id}/ghostpay/check`),
};

// Physical items & shipping
export const physicalItemsAPI = {
  getAll: () => api.get('/api/physical-items'),
  getOne: (id) => api.get(`/api/physical-items/${id}`),
  adminList: () => api.get('/api/admin/physical-items'),
  adminCreate: (data) => api.post('/api/admin/physical-items', data),
  adminUpdate: (id, data) => api.put(`/api/admin/physical-items/${id}`, data),
  adminDelete: (id) => api.delete(`/api/admin/physical-items/${id}`),
};

export const shippingAPI = {
  config: () => api.get('/api/shipping/config'),
  rates: (data) => api.post('/api/shipping/rates', data),
  myShipments: () => api.get('/api/shipments'),
  adminSettings: () => api.get('/api/admin/shipping/settings'),
  adminSaveSettings: (data) => api.put('/api/admin/shipping/settings', data),
  adminTestRates: (data) => api.post('/api/admin/shipping/test-rates', data),
  adminShipments: (status) => api.get('/api/admin/shipments', { params: status ? { status } : {} }),
  adminUpdateShipment: (id, data) => api.put(`/api/admin/shipments/${id}`, data),
  shippoTest: () => api.post('/api/admin/shipping/shippo/test'),
  shippoRegisterWebhook: () => api.post('/api/admin/shipping/shippo/register-webhook'),
  shipmentShippoRates: (id) => api.post(`/api/admin/shipments/${id}/shippo-rates`, null, { timeout: 60000 }),
  shipmentBuyLabel: (id, rate_id) => api.post(`/api/admin/shipments/${id}/buy-label`, { rate_id }, { timeout: 90000 }),
  shipmentLabel: (id) => api.get(`/api/admin/shipments/${id}/label`, { responseType: 'blob' }),
};

// Services API
export const servicesAPI = {
  getAll: () => api.get('/api/services'),
  getOne: (id) => api.get(`/api/services/${id}`),
  requestRefund: (orderId, amount, reason) => api.post('/api/refund/request', {
    order_id: orderId,
    amount: amount,
    reason: reason,
    refund_type: 'full',
    method: 'credit'
  }),
};

// Invoices API
export const invoicesAPI = {
  getAll: () => api.get('/api/invoices'),
  downloadPDF: (id) => api.get(`/api/invoices/${id}/pdf`, { responseType: 'blob' }),
};

// Branding API (public)
export const brandingAPI = {
  get: () => api.get('/api/branding'),
};

// Panels API (public)
export const panelsAPI = {
  getNames: () => api.get('/api/panels/names'),
};

// Admin API
export const adminAPI = {
  getStats: () => api.get('/api/admin/stats'),
  getCustomers: () => api.get('/api/admin/customers'),
  getCustomerDetails: (id) => api.get(`/api/admin/customers/${id}`),
  updateCustomer: (id, data) => api.put(`/api/admin/customers/${id}`, data),
  deleteCustomer: (id) => api.delete(`/api/admin/customers/${id}`),
  changeCustomerPassword: (id, newPassword) => api.post(`/api/admin/customers/${id}/change-password`, null, {
    params: { new_password: newPassword }
  }),
  getOrders: () => api.get('/api/admin/orders'),
  markOrderPaid: (id) => api.post(`/api/admin/orders/${id}/mark-paid`),
  cancelOrder: (id) => api.post(`/api/admin/orders/${id}/cancel`),
  getProducts: () => api.get('/api/admin/products'),
  createProduct: (data) => api.post('/api/admin/products', data),
  updateProduct: (id, data) => api.put(`/api/admin/products/${id}`, data),
  deleteProduct: (id) => api.delete(`/api/admin/products/${id}`),
  reorderProduct: (id, direction) => api.post(`/api/admin/products/${id}/reorder?direction=${direction}`),
  getProductGroups: () => api.get('/api/admin/product-groups'),
  saveProductGroups: (groups) => api.put('/api/admin/product-groups', { groups }),
  setProductGroup: (id, groupId, subgroupId) => api.post(`/api/admin/products/${id}/set-group`, { group_id: groupId, subgroup_id: subgroupId }),
  fixProductDisplayOrder: () => api.post('/api/admin/products/fix-display-order'),
  suspendService: (id) => api.post(`/api/admin/services/${id}/suspend`),
  unsuspendService: (id) => api.post(`/api/admin/services/${id}/unsuspend`),
  refreshGhostApkCode: (id) => api.post(`/api/admin/services/${id}/ghostapk-refresh`),
  xtreamGhostApkStatus: (panelIndex) => api.get(`/api/admin/xtream/${panelIndex}/ghostapk-status`),
  xtreamGhostApkSyncAll: (panelIndex) => api.post(`/api/admin/xtream/${panelIndex}/ghostapk-sync-all`),
  xtreamGhostApkSyncStatus: (panelIndex) => api.get(`/api/admin/xtream/${panelIndex}/ghostapk-sync-status`),
  cancelService: (id) => api.post(`/api/admin/services/${id}/cancel`),
  createManualService: (data) => api.post('/api/admin/services/create-manual', data),
  getSettings: () => api.get('/api/admin/settings'),
  updateSettings: (data) => api.put('/api/admin/settings', data),
  // Email endpoints
  sendTestEmail: (email) => api.post('/api/admin/email/test', { email }),
  getEmailProvider: () => api.get('/api/admin/email-provider'),
  updateEmailProvider: (data) => api.put('/api/admin/email-provider', data),
  testEmailProvider: (data) => api.post('/api/admin/email-provider/test', data),
  sendMassEmail: (subject, content, recipientFilter) => api.post('/api/admin/email/mass', { subject, content, recipient_filter: recipientFilter }),
  getEmailLogs: () => api.get('/api/admin/email/logs'),
  // Email template endpoints
  getEmailTemplates: () => api.get('/api/admin/email/templates'),
  getEmailTemplate: (id) => api.get(`/api/admin/email/templates/${id}`),
  updateEmailTemplate: (id, data) => api.put(`/api/admin/email/templates/${id}`, data),
  previewEmailTemplate: (id, sampleData) => api.post(`/api/admin/email/templates/${id}/preview`, sampleData),
  testEmailTemplate: (id, testData) => api.post(`/api/admin/email/templates/${id}/test`, testData),
  resetEmailTemplates: () => api.post('/api/admin/email/templates/reset-defaults'),
  // Advanced email endpoints
  getAllEmailLogs: (params) => api.get('/api/admin/email/logs/all', { params }),
  getEmailLogDetail: (id) => api.get(`/api/admin/email/logs/${id}`),
  resendEmail: (id) => api.post(`/api/admin/email/logs/${id}/resend`),
  getEmailStatistics: (days = 30) => api.get(`/api/admin/email/statistics?days=${days}`),
  getUnsubscribes: (params) => api.get('/api/admin/unsubscribes', { params }),
  removeUnsubscribe: (email) => api.delete(`/api/admin/unsubscribes/${email}`),
  scheduleEmail: (subject, content, recipientFilter, scheduledFor) => api.post('/api/admin/email/schedule', { subject, content, recipient_filter: recipientFilter, scheduled_for: scheduledFor }),
  getScheduledEmails: () => api.get('/api/admin/email/scheduled'),
  cancelScheduledEmail: (id) => api.delete(`/api/admin/email/scheduled/${id}`),
  sendScheduledEmailNow: (id) => api.post(`/api/admin/email/scheduled/${id}/send-now`),
  getTemplateVersions: (id) => api.get(`/api/admin/email/templates/${id}/versions`),
  restoreTemplateVersion: (templateId, versionId) => api.post(`/api/admin/email/templates/${templateId}/restore/${versionId}`),
  uploadAttachment: (formData) => api.post('/api/admin/upload/attachment', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }),
  deleteAttachment: (filename) => api.delete(`/api/admin/upload/attachment/${filename}`),
  uploadHeroImage: (formData) => api.post('/api/admin/upload/hero-image', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }),
  getBouquets: (panelIndex = 0, panelType = 'xtream') => api.get(`/api/admin/bouquets?panel_id=${panelIndex}&panel_type=${panelType}`),
  syncBouquetsFromPanel: (panelIndex = 0) => api.get(`/api/admin/bouquets/sync?panel_index=${panelIndex}`),
  syncPackagesFromPanel: (panelIndex = 0) => api.get(`/api/admin/packages/sync?panel_index=${panelIndex}`),
  syncUsersFromPanel: (panelIndex = 0) => api.post(`/api/admin/xtream/sync-users?panel_index=${panelIndex}`),
  getImportedUsers: (panelIndex) => api.get(`/api/admin/imported-users${panelIndex !== undefined ? `?panel_index=${panelIndex}` : ''}`),
  suspendImportedUser: (id) => api.post(`/api/admin/imported-users/${id}/suspend`),
  activateImportedUser: (id) => api.post(`/api/admin/imported-users/${id}/activate`),
  deleteImportedUser: (id) => api.delete(`/api/admin/imported-users/${id}`),
  createImportedUser: (data) => api.post('/api/admin/imported-users/create', data),
  extendImportedUser: (id, data) => api.post(`/api/admin/imported-users/${id}/extend`, data),
  syncAllUsers: (config) => api.post('/api/admin/sync-all-users', null, { timeout: 120000, ...config }),
  resyncServicesExpiry: () => api.post('/api/admin/services/resync-expiry', null, { timeout: 120000 }),
  // Customer creation
  createCustomer: (data) => api.post('/api/admin/customers/create', data),

  // XuiOne Panel endpoints
  testXuiOne: (panelIndex = 0) => api.post(`/api/admin/xuione/test?panel_index=${panelIndex}`),
  syncXuiOnePackages: (panelIndex = 0) => api.get(`/api/admin/xuione/sync-packages?panel_index=${panelIndex}`),
  syncXuiOneBouquets: (panelIndex = 0) => api.get(`/api/admin/xuione/sync-bouquets?panel_index=${panelIndex}`),
  syncXuiOneUsers: (panelIndex = 0) => api.post(`/api/admin/xuione/sync-users?panel_index=${panelIndex}`),

  // Notification settings
  getNotificationSettings: () => api.get('/api/admin/notifications/settings'),
  updateTelegramSettings: (data) => api.put('/api/admin/notifications/telegram', data),
  testTelegramNotification: (data) => api.post('/api/admin/notifications/telegram/test', data),
  updateEmailNotificationSettings: (data) => api.put('/api/admin/notifications/email', data),
  testEmailNotification: (data) => api.post('/api/admin/notifications/email/test', data),
  updateSmsNotificationSettings: (data) => api.put('/api/admin/notifications/sms', data),
  testSmsNotification: (data) => api.post('/api/admin/notifications/sms/test', data),

  syncTrialPackagesFromPanel: (panelIndex = 0) => api.get(`/api/admin/packages/sync-trial?panel_index=${panelIndex}`),
  updateBouquets: (data) => api.put('/api/admin/bouquets', data),
  getPackages: () => api.get('/api/admin/packages'),
  testXtreamUI: (panelIndex = 0) => api.post(`/api/admin/xtreamui/test?panel_index=${panelIndex}`),
  getTickets: () => api.get('/api/admin/tickets'),
  replyToTicket: (id, data) => api.post(`/api/admin/tickets/${id}/reply`, data),
  updateTicketStatus: (id, data) => api.put(`/api/admin/tickets/${id}/status`, data),
  // Coupon endpoints
  getCoupons: () => api.get('/api/admin/coupons'),
  createCoupon: (data) => api.post('/api/admin/coupons', data),
  deleteCoupon: (id) => api.delete(`/api/admin/coupons/${id}`),
  // Refund endpoints
  getPendingRefunds: () => api.get('/api/admin/refunds/pending'),
  approveRefund: (id, notes) => api.post(`/api/admin/refunds/${id}/approve`, { notes }),
  rejectRefund: (id, notes) => api.post(`/api/admin/refunds/${id}/reject`, { notes }),
  // Credit management
  addCredits: (userId, amount, description) => api.post('/api/admin/credits/add', { user_id: userId, amount, description }),
  deductCredits: (userId, amount, description) => api.post('/api/admin/credits/deduct', { user_id: userId, amount, description }),
  // Downloads
  getDownloads: () => api.get('/api/admin/downloads'),
  createDownload: (data) => api.post('/api/admin/downloads', data),
  deleteDownload: (id) => api.delete(`/api/admin/downloads/${id}`),
  // Licenses
  getLicenses: () => api.get('/api/admin/licenses'),
  createLicense: (data) => api.post('/api/admin/licenses', data),
  revokeLicense: (key, reason) => api.post(`/api/admin/licenses/${key}/revoke`, { reason }),
  activateLicense: (key) => api.post(`/api/admin/licenses/${key}/activate`),
  // User Guide
  downloadUserGuide: () => api.get('/api/admin/user-guide', { responseType: 'blob' }),
  // Imported User Credits
  addCreditsToImportedUser: (userId, credits) => api.post(`/api/admin/imported-users/${userId}/add-credits`, { credits }),
  // 1-Stream
  testOneStream: (panelIndex = 0) => api.post(`/api/admin/onestream/test?panel_index=${panelIndex}`),
  syncOneStreamPackages: (panelIndex = 0) => api.get(`/api/admin/onestream/packages?panel_index=${panelIndex}`),
  syncOneStreamBouquets: (panelIndex = 0) => api.get(`/api/admin/onestream/bouquets?panel_index=${panelIndex}`),
  syncOneStreamUsers: (panelIndex = 0) => api.post(`/api/admin/onestream/sync-users?panel_index=${panelIndex}`),
  // NXT Dash
  testNxtDash: (panelIndex = 0) => api.post(`/api/admin/nxtdash/test?panel_index=${panelIndex}`),
  getNxtDashPackages: (panelIndex = 0) => api.get(`/api/admin/nxtdash/packages?panel_index=${panelIndex}`),
  getNxtDashBouquets: (panelIndex = 0) => api.get(`/api/admin/nxtdash/bouquets?panel_index=${panelIndex}`),
  updateNxtDashBouquetNames: (bouquets, panelIndex = 0) => api.put(`/api/admin/nxtdash/bouquets?panel_index=${panelIndex}`, { bouquets }),
  syncNxtDashUsers: (panelIndex = 0) => api.post(`/api/admin/nxtdash/sync-users?panel_index=${panelIndex}`),
  // Aether
  testAether: (panelIndex = 0) => api.post(`/api/admin/aether/test?panel_index=${panelIndex}`),
  getAetherPackages: (panelIndex = 0) => api.get(`/api/admin/aether/packages?panel_index=${panelIndex}`),
  getAetherBouquets: (panelIndex = 0) => api.get(`/api/admin/aether/bouquets?panel_index=${panelIndex}`),
  getAetherPackageBouquets: (packageId, panelIndex = 0) => api.get(`/api/admin/aether/packages/${packageId}/bouquets?panel_index=${panelIndex}`),
  syncAetherUsers: (panelIndex = 0) => api.post(`/api/admin/aether/sync-users?panel_index=${panelIndex}`),
  testGold: (panelIndex = 0) => api.post(`/api/admin/gold/test?panel_index=${panelIndex}`),
  getGoldPackages: (panelIndex = 0) => api.get(`/api/admin/gold/packages?panel_index=${panelIndex}`),
  refreshGoldUsers: (panelIndex = 0) => api.post(`/api/admin/gold/refresh-users?panel_index=${panelIndex}`, null, { timeout: 120000 }),
  // Maintenance
  deduplicateImportedUsers: () => api.post('/api/admin/imported-users/deduplicate'),
  // Staff management
  getStaff: () => api.get('/api/admin/staff'),
  createStaff: (data) => api.post('/api/admin/staff', data),
  updateStaff: (id, data) => api.put(`/api/admin/staff/${id}`, data),
  deleteStaff: (id) => api.delete(`/api/admin/staff/${id}`),
  createAccountsForImportedUsers: () => api.post('/api/admin/imported-users/create-accounts'),
  cleanupOrphanedUsers: (deleteCustomers = false) => api.post('/api/admin/imported-users/cleanup-orphans', { delete_customers: deleteCustomers }),
  bulkActionImportedUsers: (action, userIds) => api.post('/api/admin/imported-users/bulk-action', { action, user_ids: userIds }),
  // Knowledge Base
  getKBArticles: () => api.get('/api/admin/kb'),
  createKBArticle: (data) => api.post('/api/admin/kb', data),
  updateKBArticle: (id, data) => api.put(`/api/admin/kb/${id}`, data),
  deleteKBArticle: (id) => api.delete(`/api/admin/kb/${id}`),
};

export default api;
