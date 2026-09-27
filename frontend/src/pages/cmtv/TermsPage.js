// CMTV local addition 2026-09-27: public /terms page (same text as the checkout "I agree" pop-up: settings.terms via
// GET /api/terms, edited in Admin > Settings). Shown in the customer area's navy frame.
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import '../../components/cmtv/cmtv-kb.css';

export default function TermsPage() {
  const { data, isLoading } = useQuery({ queryKey: ['terms'], queryFn: async () => (await api.get('/api/terms')).data });
  return (
    <div className="cmtv-kb">
      <article className="kb-article" style={{ marginTop: 12 }}>
        <h1>{data?.title || 'Terms and Conditions'}</h1>
        {isLoading ? <p className="kb-lede">Loading…</p>
          : data?.enabled && data?.content
            ? <div className="kb-body" dangerouslySetInnerHTML={{ __html: data.content }} />   // admin-set text from Settings
            : <p className="kb-lede">Our terms are being updated. Questions? Email <a href="mailto:cmtv@pm.me">cmtv@pm.me</a>.</p>}
      </article>
      <div className="kb-help">
        <div><b>Questions about these terms?</b><span>Message us on Telegram or email cmtv@pm.me.</span></div>
        <Link className="kb-btn" to="/privacy">Privacy Policy</Link>
        <Link className="kb-btn" to="/">Back to the store</Link>
      </div>
    </div>
  );
}
