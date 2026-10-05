// CMTV local addition 2026-10-04: "Test my line" on a TV service card (backend cmtv_linecheck.py). One tap checks the
// plan, the line on the server, the server's status and the devices in use right now, and answers in plain words with
// the next step (renew, add devices, status page, quick fixes, support).
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/api';

const ICON = { true: '✅', false: '❌', null: '⚠️' };

export default function LineCheck({ service, onRenew }) {
  const [state, setState] = useState(null);   // null | 'loading' | {error} | result
  const run = async () => {
    setState('loading');
    try { setState((await api.get(`/api/cmtv/linecheck/${service.id}`)).data); }
    catch (e) { setState({ error: e?.response?.data?.detail || 'The check couldn\'t run right now. Please try again in a minute.' }); }
  };
  const r = state && state !== 'loading' && !state.error ? state : null;
  return (
    <>
      <button type="button" className="ca-btn ca-ghost" onClick={state ? () => setState(null) : run}>
        {state === 'loading' ? 'Checking…' : state ? 'Hide check' : 'Test my line'}
      </button>
      {state && state !== 'loading' && (
        <div className="ca-setup" style={{ flexBasis: '100%', width: '100%' }}>
          {state.error ? <p>{state.error}</p> : (
            <>
              <p style={{ margin: '0 0 8px', fontWeight: 700 }}>{r.ok ? '✅ ' : '⚠️ '}{r.verdict}</p>
              {r.checks.map((c, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, margin: '6px 0' }}>
                  <span aria-hidden="true">{ICON[String(c.ok)]}</span>
                  <div><b>{c.title}</b>{c.detail && <div style={{ fontSize: 13.5, color: 'var(--muted, #9aa6c6)' }}>{c.detail}</div>}</div>
                </div>
              ))}
              <div className="ca-help" style={{ marginTop: 10 }}>
                {r.actions.includes('renew') && onRenew && <button type="button" className="ca-btn ca-glow" onClick={onRenew}>Renew now</button>}
                {r.actions.includes('devices') && <span style={{ fontSize: 13 }}>Use <b>Add devices</b> on this card to watch on more screens at once.</span>}
                {r.actions.includes('status') && <Link className="ca-btn ca-ghost" to="/status">Service status</Link>}
                {r.actions.includes('fixes') && <Link className="ca-btn ca-ghost" to="/knowledge-base/cmtv-buffering">Quick fixes</Link>}
                <a className="ca-btn ca-ghost" href="https://t.me/Cmtv_support_bot" target="_blank" rel="noopener noreferrer">Still stuck? Message support</a>
              </div>
              <button type="button" className="ca-link" onClick={run} style={{ marginTop: 6, background: 'none', border: 0, color: 'var(--cyan, #22e6f2)', cursor: 'pointer', padding: 0, textDecoration: 'underline', fontSize: 13 }}>Check again</button>
            </>
          )}
        </div>
      )}
    </>
  );
}
