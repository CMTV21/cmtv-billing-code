import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import { ArrowLeft, Mail, Eye, Send, Save, AlertCircle, CheckCircle, History, RotateCcw } from 'lucide-react';
import RichTextEditor from '../components/RichTextEditor';
import EmailPreview from '../components/EmailPreview';
import { toast } from 'sonner';

export default function AdminEmailTemplates() {
  const queryClient = useQueryClient();
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [testEmail, setTestEmail] = useState('');
  const [showPreview, setShowPreview] = useState(false);
  const [previewHtml, setPreviewHtml] = useState('');

  const { data: templates, isLoading } = useQuery({
    queryKey: ['email-templates'],
    queryFn: async () => {
      const response = await adminAPI.getEmailTemplates();
      return response.data;
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ templateId, data }) => {
      return await adminAPI.updateEmailTemplate(templateId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['email-templates']);
      setIsEditing(false);
      toast.success('Template updated successfully!');
    },
  });

  const testEmailMutation = useMutation({
    mutationFn: async ({ templateId, data }) => {
      return await adminAPI.testEmailTemplate(templateId, data);
    },
    onSuccess: () => {
      toast.success('Test email sent successfully!');
      setTestEmail('');
    },
    onError: (error) => {
      toast.error('Failed to send test email: ' + error.response?.data?.detail);
    },
  });

  const previewMutation = useMutation({
    mutationFn: async ({ templateId, data }) => {
      const response = await adminAPI.previewEmailTemplate(templateId, data);
      return response.data;
    },
    onSuccess: (data) => {
      setPreviewHtml(data.html_content);
      setShowPreview(true);
    },
  });

  const handleSaveTemplate = () => {
    if (!selectedTemplate) return;
    
    updateMutation.mutate({
      templateId: selectedTemplate.id,
      data: {
        name: selectedTemplate.name,
        subject: selectedTemplate.subject,
        html_content: selectedTemplate.html_content,
        text_content: selectedTemplate.text_content,
        is_active: selectedTemplate.is_active,
      },
    });
  };

  const handleTestEmail = () => {
    if (!testEmail || !selectedTemplate) return;
    
    // Create sample data for variables
    const sampleData = {
      test_email: testEmail,
      customer_name: 'John Doe',
      order_id: '12345678',
      amount: '15.00',
      product_name: 'IPTV Subscription',
      duration: '1',
      service_name: 'IPTV Service',
      username: 'user12345',
      password: 'pass67890',
      streaming_url: 'http://streaming.example.com:8000',
      max_connections: '2',
      expiry_date: '2024-12-31',
      ghostapk_code: '482913',
      ghostapk_section: '<p style="margin: 0 0 8px; font-size: 14px;"><strong>GhostAPK Login Pin:</strong> <span style="font-family: monospace; font-size: 16px; letter-spacing: 2px;">482913</span></p>',
      days_remaining: '7',
      ticket_id: 'TKT-001',
      ticket_subject: 'Service Issue',
      reply_message: 'This is a sample reply message',
      company_name: 'Digital Services',
      payment_method: 'Credit Card',
      payment_date: new Date().toLocaleDateString(),
      renewal_link: window.location.origin + '/products',
      ticket_link: window.location.origin + '/tickets',
      dashboard_link: window.location.origin + '/dashboard',
    };
    
    testEmailMutation.mutate({
      templateId: selectedTemplate.id,
      data: sampleData,
    });
  };

  const handlePreview = () => {
    if (!selectedTemplate) return;
    
    const sampleData = {
      customer_name: 'John Doe',
      order_id: '12345678',
      amount: '15.00',
      product_name: 'IPTV Subscription',
      duration: '1',
      service_name: 'IPTV Service',
      username: 'user12345',
      password: 'pass67890',
      streaming_url: 'http://streaming.example.com:8000',
      max_connections: '2',
      expiry_date: '2024-12-31',
      ghostapk_code: '482913',
      ghostapk_section: '<p style="margin: 0 0 8px; font-size: 14px;"><strong>GhostAPK Login Pin:</strong> <span style="font-family: monospace; font-size: 16px; letter-spacing: 2px;">482913</span></p>',
      days_remaining: '7',
      ticket_id: 'TKT-001',
      ticket_subject: 'Service Issue',
      reply_message: 'This is a sample reply message',
      company_name: 'Digital Services',
      payment_method: 'Credit Card',
      payment_date: new Date().toLocaleDateString(),
      renewal_link: '#',
      ticket_link: '#',
      dashboard_link: '#',
    };
    
    previewMutation.mutate({
      templateId: selectedTemplate.id,
      data: sampleData,
    });
  };

  if (isLoading) {
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
          <Link to="/admin" className="flex items-center gap-2 text-gray-600 dark:text-gray-300 hover:text-blue-600">
            <ArrowLeft className="w-5 h-5" />
            Back to Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">Email Templates</h1>
            <p className="text-gray-600 dark:text-gray-400">Customize email templates sent to customers</p>
          </div>
          <button
            onClick={async () => {
              if (!window.confirm('Reset all templates to spam-filter-friendly defaults? Your custom changes will be overwritten.')) return;
              try {
                const res = await adminAPI.resetEmailTemplates();
                toast.success(res.data.message);
                queryClient.invalidateQueries(['email-templates']);
              } catch (err) {
                toast.error(err.response?.data?.detail || 'Failed to reset templates');
              }
            }}
            className="px-4 py-2 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition"
            data-testid="reset-templates-btn"
          >
            Reset to Defaults
          </button>
        </div>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Template List */}
          <div className="lg:col-span-1">
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow">
              <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Templates</h2>
              </div>
              <div className="divide-y divide-gray-200 dark:divide-gray-700">
                {templates?.map((template) => (
                  <button
                    key={template.id}
                    onClick={() => {
                      setSelectedTemplate(template);
                      setIsEditing(false);
                      setShowPreview(false);
                    }}
                    className={`w-full text-left p-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition ${
                      selectedTemplate?.id === template.id ? 'bg-blue-50 dark:bg-blue-900/20 border-l-4 border-blue-600' : ''
                    }`}
                    data-testid={`template-${template.template_type}`}
                  >
                    <div className="flex items-start gap-3">
                      <Mail className={`w-5 h-5 mt-0.5 ${template.is_active ? 'text-blue-600' : 'text-gray-400'}`} />
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-gray-900 dark:text-white truncate">{template.name}</h3>
                        <p className="text-sm text-gray-600 dark:text-gray-400 truncate">{template.description}</p>
                        <div className="mt-1">
                          {template.is_active ? (
                            <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                              <CheckCircle className="w-3 h-3" />
                              Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                              <AlertCircle className="w-3 h-3" />
                              Inactive
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Template Editor */}
          <div className="lg:col-span-2">
            {selectedTemplate ? (
              <div className="bg-white dark:bg-gray-900 rounded-lg shadow">
                <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-xl font-bold text-gray-900 dark:text-white">{selectedTemplate.name}</h2>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <span className="text-sm text-gray-600 dark:text-gray-400">Active</span>
                      <input
                        type="checkbox"
                        checked={selectedTemplate.is_active}
                        onChange={(e) => {
                          setSelectedTemplate({ ...selectedTemplate, is_active: e.target.checked });
                          setIsEditing(true);
                        }}
                        className="w-4 h-4"
                        data-testid="template-active-toggle"
                      />
                    </label>
                  </div>
                  
                  <div className="flex flex-wrap gap-2 mb-4">
                    <button
                      onClick={() => setIsEditing(!isEditing)}
                      className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                      data-testid="edit-template-btn"
                    >
                      {isEditing ? 'Cancel Edit' : 'Edit Template'}
                    </button>
                    {isEditing && (
                      <button
                        onClick={handleSaveTemplate}
                        className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
                        data-testid="save-template-btn"
                      >
                        <Save className="w-4 h-4" />
                        Save Changes
                      </button>
                    )}
                    <button
                      onClick={handlePreview}
                      className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700"
                      data-testid="preview-template-btn"
                    >
                      <Eye className="w-4 h-4" />
                      Preview
                    </button>
                  </div>

                  <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
                    <p className="text-sm text-blue-800 dark:text-blue-300 mb-2"><strong>Available Variables:</strong></p>
                    <div className="flex flex-wrap gap-2">
                      {selectedTemplate.available_variables?.map((variable) => (
                        <code
                          key={variable}
                          className="px-2 py-1 bg-white dark:bg-gray-800 text-blue-600 dark:text-blue-400 rounded text-xs font-mono"
                        >
                          {`{{${variable}}}`}
                        </code>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="p-6 space-y-6">
                  {/* Subject */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Email Subject
                    </label>
                    <input
                      type="text"
                      value={selectedTemplate.subject}
                      onChange={(e) => {
                        setSelectedTemplate({ ...selectedTemplate, subject: e.target.value });
                        setIsEditing(true);
                      }}
                      className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                      placeholder="Email subject line..."
                      disabled={!isEditing}
                      data-testid="template-subject-input"
                    />
                  </div>

                  {/* HTML Content */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      HTML Content
                    </label>
                    {isEditing ? (
                      <RichTextEditor
                        value={selectedTemplate.html_content}
                        onChange={(value) => {
                          setSelectedTemplate({ ...selectedTemplate, html_content: value });
                        }}
                        height="500px"
                      />
                    ) : (
                      <div className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-800 max-h-96 overflow-auto">
                        <div dangerouslySetInnerHTML={{ __html: selectedTemplate.html_content }} />
                      </div>
                    )}
                  </div>

                  {/* Test Email */}
                  <div className="pt-6 border-t border-gray-200 dark:border-gray-700">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Send Test Email
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="email"
                        value={testEmail}
                        onChange={(e) => setTestEmail(e.target.value)}
                        className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                        placeholder="test@example.com"
                        data-testid="test-email-input"
                      />
                      <button
                        onClick={handleTestEmail}
                        disabled={!testEmail}
                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                        data-testid="send-test-email-btn"
                      >
                        <Send className="w-4 h-4" />
                        Send Test
                      </button>
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                      Test email will use sample data for all variables
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
                <Mail className="w-16 h-16 text-gray-400 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">Select a Template</h3>
                <p className="text-gray-600 dark:text-gray-400">Choose a template from the list to view and edit</p>
              </div>
            )}
          </div>
        </div>

        {/* Preview Modal */}
        {showPreview && (
          <EmailPreview
            htmlContent={previewHtml}
            onClose={() => setShowPreview(false)}
          />
        )}
      </main>
    </div>
  );
}
