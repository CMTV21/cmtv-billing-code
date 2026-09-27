// CMTV local addition 2026-09-27: public /privacy page. Text in cmtv_config {_id: "privacy_policy"} (GET /api/cmtv/seo/privacy),
// written by scripts/2026-09-27-privacy (privacy_content.py + apply_privacy.py). Same look as the Terms page.
import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import api from '../../api/api';
import '../../components/cmtv/cmtv-kb.css';

export default function PrivacyPage() {
  const { data, isLoading } = useQuery({ queryKey: ['privacy'], queryFn: async () => (await api.get('/api/cmtv/seo/privacy')).data });
  return (
    <div className="cmtv-kb">
      <article className="kb-article" style={{ marginTop: 12 }}>
        <h1>{data?.title || 'Privacy Policy'}</h1>
        {isLoading ? <p className="kb-lede">Loading…</p>
          : data?.enabled && data?.content
            ? <div className="kb-body" dangerouslySetInnerHTML={{ __html: data.content }} />   // our own text, set by script
            : <p className="kb-lede">Our privacy policy is being updated. Questions? Email <a href="mailto:cmtv@pm.me">cmtv@pm.me</a>.</p>}
      </article>
      <div className="kb-help">
        <div><b>Privacy questions or requests?</b><span>Email cmtv@pm.me and we'll answer within 30 days.</span></div>
        <Link className="kb-btn" to="/terms">Terms and Conditions</Link>
        <Link className="kb-btn" to="/">Back to the store</Link>
      </div>
    </div>
  );
}
