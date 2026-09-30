import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminAPI } from '../api/api';
import { Save, Palette, Type, Image as ImageIcon } from 'lucide-react';
import { toast } from 'sonner';

export default function BrandingSettings({ settings }) {
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState({
    site_name: settings?.branding?.site_name || 'IPTV Billing',
    logo_url: settings?.branding?.logo_url || '',
    theme: settings?.branding?.theme || 'light',
    primary_color: settings?.branding?.primary_color || '#2563eb',
    secondary_color: settings?.branding?.secondary_color || '#7c3aed',
    accent_color: settings?.branding?.accent_color || '#059669',
    product_card_color: settings?.branding?.product_card_color || '#2563eb',
    hero_background_image: settings?.branding?.hero_background_image || '',
    homepage_bg_color: settings?.branding?.homepage_bg_color || '',
    hero_title: settings?.branding?.hero_title || 'Premium IPTV Subscriptions',
    hero_description: settings?.branding?.hero_description || 'Access thousands of channels with our reliable IPTV service. Flexible plans, instant activation, 24/7 support.',
    footer_text: settings?.branding?.footer_text || 'Premium IPTV Services',
    provision_notes_template: settings?.branding?.provision_notes_template || '{{site_name}} | Order: {{order_id}}',
    feature_1_title: settings?.branding?.feature_1_title || 'Instant Activation',
    feature_1_description: settings?.branding?.feature_1_description || 'Get your credentials immediately after payment. Start watching within minutes.',
    feature_2_title: settings?.branding?.feature_2_title || 'Multiple Connections',
    feature_2_description: settings?.branding?.feature_2_description || 'Watch on multiple devices simultaneously. Perfect for families.',
    feature_3_title: settings?.branding?.feature_3_title || 'Flexible Plans',
    feature_3_description: settings?.branding?.feature_3_description || 'Choose from 1, 3, 6, or 12-month plans. Save more with longer subscriptions.'
  });
  
  const [heroImageFile, setHeroImageFile] = useState(null);

  const updateMutation = useMutation({
    mutationFn: (data) => {
      const settingsUpdate = {
        ...settings,
        branding: data
      };
      return adminAPI.updateSettings(settingsUpdate);
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-settings']);
      queryClient.invalidateQueries(['branding']);
      
      // Clear branding from localStorage to force fresh fetch
      localStorage.removeItem('app-branding');
      
      toast.success('Branding settings saved! Page will refresh to apply changes.');
      
      // Delay reload slightly to ensure cache is cleared
      setTimeout(() => {
        window.location.reload();
      }, 100);
    },
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    let updatedFormData = { ...formData };
    
    // Upload hero image if selected
    if (heroImageFile) {
      try {
        const imageFormData = new FormData();
        imageFormData.append('file', heroImageFile);
        
        const uploadResponse = await adminAPI.uploadHeroImage(imageFormData);
        updatedFormData.hero_background_image = uploadResponse.data.url;
      } catch (error) {
        console.error('Hero image upload error:', error);
        const errorMsg = error.response?.data?.detail || error.message || JSON.stringify(error);
        toast.error('Failed to upload hero image: ' + errorMsg);
        return;
      }
    }
    
    updateMutation.mutate(updatedFormData);
  };

  const presetThemes = {
    light: {
      name: 'Light (Default)',
      primary: '#2563eb',
      secondary: '#7c3aed',
      accent: '#059669',
    },
    dark: {
      name: 'Dark',
      primary: '#3b82f6',
      secondary: '#8b5cf6',
      accent: '#10b981',
    },
  };

  const applyPreset = (preset) => {
    setFormData(prev => ({
      ...prev,
      theme: preset,  // Set the theme name
      primary_color: presetThemes[preset].primary,
      secondary_color: presetThemes[preset].secondary,
      accent_color: presetThemes[preset].accent,
    }));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
          <Palette className="w-5 h-5 text-blue-600" />
          Branding & Appearance
        </h3>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
          Customize your billing system's look and feel. Changes apply after page refresh.
        </p>
      </div>

      {/* Site Name */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
          <Type className="w-4 h-4" />
          Site Name
        </label>
        <input
          type="text"
          value={formData.site_name}
          onChange={(e) => setFormData({ ...formData, site_name: e.target.value })}
          className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          placeholder="IPTV Billing"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          This appears in the header, footer, and page title
        </p>
      </div>

      {/* Logo URL */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
          <ImageIcon className="w-4 h-4" />
          Logo URL
        </label>
        <input
          type="url"
          value={formData.logo_url}
          onChange={(e) => setFormData({ ...formData, logo_url: e.target.value })}
          className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          placeholder="https://yoursite.com/logo.png"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          Full URL to your logo image (leave empty to use site name)
        </p>
      </div>

      {/* Homepage Content */}
      <div className="border-t border-gray-200 dark:border-gray-700 pt-6 space-y-4">
        <h4 className="text-md font-semibold text-gray-900 dark:text-white">Homepage Content</h4>
        
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Hero Title
          </label>
          <input
            type="text"
            value={formData.hero_title}
            onChange={(e) => setFormData({ ...formData, hero_title: e.target.value })}
            className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            placeholder="Premium IPTV Subscriptions"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Main headline on homepage</p>
        </div>
        
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Hero Description
          </label>
          <textarea
            rows={3}
            value={formData.hero_description}
            onChange={(e) => setFormData({ ...formData, hero_description: e.target.value })}
            className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            placeholder="Access thousands of channels with our reliable IPTV service. Flexible plans, instant activation, 24/7 support."
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Subtitle text below hero title</p>
        </div>
        
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Footer Text
          </label>
          <input
            type="text"
            value={formData.footer_text}
            onChange={(e) => setFormData({ ...formData, footer_text: e.target.value })}
            className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            placeholder="Premium IPTV Services"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Text in footer section</p>
        </div>

        {/* Provisioning Notes Template */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Provisioning Notes Template
          </label>
          <input
            type="text"
            value={formData.provision_notes_template}
            onChange={(e) => setFormData({ ...formData, provision_notes_template: e.target.value })}
            className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono text-sm"
            placeholder="{{site_name}} | Order: {{order_id}}"
            data-testid="provision-notes-template-input"
          />
          <p className="text-xs text-gray-500 mt-1">Written into the "notes" field on the IPTV panel for every line created through billing. Use <code>{'{{site_name}}'}</code> so your panel name shows instead of the customer's.</p>
          <div className="mt-2 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Available variables:</p>
            <div className="flex flex-wrap gap-1.5">
              {['{{site_name}}', '{{order_id}}', '{{product_name}}', '{{username}}', '{{customer_name}}', '{{email}}'].map(v => (
                <button key={v} type="button" onClick={() => setFormData({ ...formData, provision_notes_template: (formData.provision_notes_template || '') + ' ' + v })}
                  className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs rounded font-mono hover:bg-blue-200">
                  {v}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Preview: <span className="font-mono text-gray-700 dark:text-gray-300" data-testid="provision-notes-preview">
                {(formData.provision_notes_template || '').replace(/\{\{site_name\}\}/g, formData.site_name || 'IPTV Billing').replace(/\{\{customer_name\}\}/g, 'John Doe').replace(/\{\{email\}\}/g, 'john@example.com').replace(/\{\{order_id\}\}/g, 'abc123').replace(/\{\{username\}\}/g, 'johndoe99').replace(/\{\{product_name\}\}/g, '1 Month Plan')}
              </span>
            </p>
          </div>
        </div>
        
      </div>

      {/* Feature Sections */}
      <div className="border-t border-gray-200 dark:border-gray-700 pt-6 space-y-6">
        <h4 className="text-md font-semibold text-gray-900 dark:text-white">Feature Cards (3 sections below hero)</h4>
        
        {/* Feature 1 */}
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-gray-50 dark:bg-gray-800">
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3">Feature 1: Instant Activation</p>
          <div className="space-y-3">
            <input
              type="text"
              value={formData.feature_1_title}
              onChange={(e) => setFormData({ ...formData, feature_1_title: e.target.value })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Instant Activation"
            />
            <textarea
              rows={2}
              value={formData.feature_1_description}
              onChange={(e) => setFormData({ ...formData, feature_1_description: e.target.value })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Get your credentials immediately..."
            />
          </div>
        </div>
        
        {/* Feature 2 */}
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-gray-50 dark:bg-gray-800">
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3">Feature 2: Multiple Connections</p>
          <div className="space-y-3">
            <input
              type="text"
              value={formData.feature_2_title}
              onChange={(e) => setFormData({ ...formData, feature_2_title: e.target.value })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Multiple Connections"
            />
            <textarea
              rows={2}
              value={formData.feature_2_description}
              onChange={(e) => setFormData({ ...formData, feature_2_description: e.target.value })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Watch on multiple devices..."
            />
          </div>
        </div>
        
        {/* Feature 3 */}
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-gray-50 dark:bg-gray-800">
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3">Feature 3: Flexible Plans</p>
          <div className="space-y-3">
            <input
              type="text"
              value={formData.feature_3_title}
              onChange={(e) => setFormData({ ...formData, feature_3_title: e.target.value })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Flexible Plans"
            />
            <textarea
              rows={2}
              value={formData.feature_3_description}
              onChange={(e) => setFormData({ ...formData, feature_3_description: e.target.value })}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              placeholder="Choose from 1, 3, 6, or 12-month plans..."
            />
          </div>
        </div>
      </div>

      {/* Theme Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-3">
          Theme Presets
        </label>
        <div className="grid grid-cols-2 gap-3 mb-3">
          {Object.entries(presetThemes).map(([key, theme]) => (
            <button
              key={key}
              type="button"
              onClick={() => applyPreset(key)}
              className={`p-4 border-2 rounded-lg transition text-center ${
                formData.theme === key 
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 dark:border-blue-400' 
                  : 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:border-blue-400'
              }`}
            >
              <div className="font-semibold text-gray-900 dark:text-white mb-2">{theme.name}</div>
              <div className="flex gap-1 justify-center">
                <div className="w-6 h-6 rounded" style={{ backgroundColor: theme.primary }}></div>
                <div className="w-6 h-6 rounded" style={{ backgroundColor: theme.secondary }}></div>
                <div className="w-6 h-6 rounded" style={{ backgroundColor: theme.accent }}></div>
              </div>
              {formData.theme === key && (
                <div className="text-xs text-blue-600 dark:text-blue-300 mt-2 font-semibold">✓ Selected</div>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Color Pickers */}
      <div className="grid md:grid-cols-3 gap-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Primary Color
          </label>
          <div className="flex gap-2">
            <input
              type="color"
              value={formData.primary_color}
              onChange={(e) => setFormData({ ...formData, primary_color: e.target.value })}
              className="w-16 h-12 border border-gray-300 rounded cursor-pointer"
            />
            <input
              type="text"
              value={formData.primary_color}
              onChange={(e) => setFormData({ ...formData, primary_color: e.target.value })}
              className="flex-1 px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono"
              placeholder="#2563eb"
            />
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Buttons, links, main elements</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Secondary Color
          </label>
          <div className="flex gap-2">
            <input
              type="color"
              value={formData.secondary_color}
              onChange={(e) => setFormData({ ...formData, secondary_color: e.target.value })}
              className="w-16 h-12 border border-gray-300 rounded cursor-pointer"
            />
            <input
              type="text"
              value={formData.secondary_color}
              onChange={(e) => setFormData({ ...formData, secondary_color: e.target.value })}
              className="flex-1 px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono"
              placeholder="#7c3aed"
            />
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Accent elements, badges</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Accent Color
          </label>
          <div className="flex gap-2">
            <input
              type="color"
              value={formData.accent_color}
              onChange={(e) => setFormData({ ...formData, accent_color: e.target.value })}
              className="w-16 h-12 border border-gray-300 rounded cursor-pointer"
            />
            <input
              type="text"
              value={formData.accent_color}
              onChange={(e) => setFormData({ ...formData, accent_color: e.target.value })}
              className="flex-1 px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono"
              placeholder="#059669"
            />
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Success states, highlights</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Product Card Color
          </label>
          <div className="flex gap-2">
            <input
              type="color"
              value={formData.product_card_color}
              onChange={(e) => setFormData({ ...formData, product_card_color: e.target.value })}
              className="w-16 h-12 border border-gray-300 rounded cursor-pointer"
            />
            <input
              type="text"
              value={formData.product_card_color}
              onChange={(e) => setFormData({ ...formData, product_card_color: e.target.value })}
              className="flex-1 px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono"
              placeholder="#2563eb"
            />
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Color for product card gradients on homepage</p>
        </div>
      </div>

      {/* Hero Section */}
      <div>
        <h4 className="text-md font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
          <ImageIcon className="w-5 h-5 text-blue-600" />
          Hero Section
        </h4>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Hero Background Image
            </label>
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setHeroImageFile(e.target.files[0])}
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            />
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Recommended: 1920x600px (16:9 aspect ratio) • Max 5MB • JPG, PNG, WebP
            </p>
            {formData.hero_background_image && (
              <div className="mt-2">
                <img 
                  src={formData.hero_background_image} 
                  alt="Hero preview" 
                  className="w-full h-32 object-cover rounded-lg border border-gray-300"
                />
                <button
                  type="button"
                  onClick={() => setFormData({ ...formData, hero_background_image: '' })}
                  className="text-xs text-red-600 hover:text-red-700 mt-1"
                >
                  Remove image
                </button>
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Homepage Background Color
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Used when no background image is set, or as an overlay tint</p>
            <div className="flex items-center gap-3">
              <input
                type="color"
                value={formData.homepage_bg_color || '#1e3a5f'}
                onChange={(e) => setFormData({ ...formData, homepage_bg_color: e.target.value })}
                className="w-12 h-12 rounded-lg border border-gray-300 dark:border-gray-600 cursor-pointer"
              />
              <input
                type="text"
                value={formData.homepage_bg_color}
                onChange={(e) => setFormData({ ...formData, homepage_bg_color: e.target.value })}
                placeholder="#1e3a5f"
                className="w-32 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm"
              />
              <div className="h-12 flex-1 rounded-lg border border-gray-300" style={{ background: formData.homepage_bg_color || '#1e3a5f' }}></div>
              {formData.homepage_bg_color && (
                <button type="button" onClick={() => setFormData({ ...formData, homepage_bg_color: '' })} className="text-xs text-red-600 hover:text-red-700">
                  Clear
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Preview */}
      <div className="border-t border-gray-200 dark:border-gray-700 pt-6">
        <label className="block text-sm font-medium text-gray-700 mb-3">
          Preview
        </label>
        <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 rounded-lg p-6">
          <div className="flex items-center gap-3 mb-4">
            {formData.logo_url ? (
              <img src={formData.logo_url} alt="Logo" className="h-8" />
            ) : (
              <div className="w-8 h-8 bg-gray-300 rounded"></div>
            )}
            <span className="text-2xl font-bold">{formData.site_name}</span>
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              className="px-4 py-2 rounded-lg text-white"
              style={{ backgroundColor: formData.primary_color }}
            >
              Primary Button
            </button>
            <button
              type="button"
              className="px-4 py-2 rounded-lg text-white"
              style={{ backgroundColor: formData.secondary_color }}
            >
              Secondary
            </button>
            <button
              type="button"
              className="px-4 py-2 rounded-lg text-white"
              style={{ backgroundColor: formData.accent_color }}
            >
              Accent
            </button>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="pt-6 border-t">
        <button
          type="submit"
          disabled={updateMutation.isPending}
          className="flex items-center gap-2 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 font-semibold"
        >
          <Save className="w-5 h-5" />
          {updateMutation.isPending ? 'Saving...' : 'Save Branding'}
        </button>
        <p className="text-sm text-gray-600 mt-2">
          Note: Page will refresh to apply branding changes
        </p>
      </div>
    </form>
  );
}
