// CMTV local addition 2026-10-08: Admin > Growth > Campaigns. Write a branded email (blocks with personal fields), preview it
// at desktop and phone width, send a test to yourself, dry-run the audience, then schedule (Toronto time) or send now after
// typing the number of recipients. Sending is throttled, 10:00-20:00 Toronto, once per customer. Backend: cmtv_campaigns.py.
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import api from '../../api/api';
import '../../components/cmtv/cmtv-campaigns.css';

const BASE = '/api/cmtv/campaigns/admin';
const STATUS = { draft: 'Draft', scheduled: 'Scheduled', sending: 'Sending', paused: 'Paused', sent: 'Sent', cancelled: 'Cancelled' };
const BLOCKS = {
  p: { label: 'Paragraph', keys: ['text', 'fallback'] },
  card: { label: 'Offer card', keys: ['emoji', 'title', 'subtitle', 'text'] },
  heading: { label: 'Section title', keys: ['text'] },
  list: { label: 'Bullet list (one per line)', keys: ['text'] },
  button: { label: 'Button', keys: ['label', 'href'] },
  note: { label: 'Small print', keys: ['text'] },
  spacer: { label: 'Space', keys: [] },
};
const KEY_LABEL = { text: 'Text', fallback: 'If a field is missing, use this instead (empty = leave the block out)', emoji: 'Emoji',
  title: 'Title', subtitle: 'Grey note after the title', label: 'Button text', href: 'Link (https://... or {{dashboard_link}})' };
const err = (e, d) => e?.response?.data?.detail || d;

function Preview({ draft }) {
  const [width, setWidth] = useState(600);
  const [who, setWho] = useState('');
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setOut((await api.post(`${BASE}/preview`, { campaign: draft, user_id: who.trim() || undefined })).data); }
    catch (e) { toast.error(err(e, 'Preview failed')); }
    setBusy(false);
  };
  useEffect(() => { run(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="cmp-box">
      <div className="cmp-row">
        <b>Preview</b>
        <button type="button" className={`rv-btn ${width === 600 ? 'glow' : ''}`} onClick={() => setWidth(600)}>Desktop</button>
        <button type="button" className={`rv-btn ${width === 375 ? 'glow' : ''}`} onClick={() => setWidth(375)}>Phone</button>
        <input className="cmp-in sm" placeholder="Customer id (empty = sample Sam)" value={who} onChange={(e) => setWho(e.target.value)} />
        <button type="button" className="rv-btn" disabled={busy} onClick={run}>{busy ? 'Rendering…' : 'Refresh preview'}</button>
      </div>
      {out && <>
        <p className="cmp-sub">Subject: <b>{out.subject}</b> · for {out.for}{out.assumes_sale ? ' · dates count the holiday bonus as if the sale is running' : ''}</p>
        <div className="cmp-frame" style={{ width }}><iframe title="Email preview" srcDoc={out.html} sandbox="" /></div>
        <details><summary>Plain-text version</summary><pre className="cmp-pre">{out.text}</pre></details>
      </>}
    </div>
  );
}

function Editor({ camp, meta, onSaved, onClose }) {
  const [d, setD] = useState(() => ({ name: camp.name || '', subject: camp.subject || '', preheader: camp.preheader || '',
    heading: camp.heading || '', audience: camp.audience || 'active_paying', include_resellers: !!camp.include_resellers,
    include_unbilled: !!camp.include_unbilled,
    requires_promo: !!camp.requires_promo, notes: camp.notes || '', blocks: camp.blocks || [] }));
  const [showPrev, setShowPrev] = useState(0);
  const editable = camp.status === 'draft';
  const set = (k, v) => setD((x) => ({ ...x, [k]: v }));
  const setBlock = (i, k, v) => setD((x) => ({ ...x, blocks: x.blocks.map((b, j) => (j === i ? { ...b, [k]: v } : b)) }));
  const move = (i, by) => setD((x) => { const b = [...x.blocks]; const [it] = b.splice(i, 1); b.splice(Math.max(0, Math.min(b.length, i + by)), 0, it); return { ...x, blocks: b }; });
  const save = async () => {
    try { const r = (await api.put(`${BASE}/${camp.id}`, d)).data; toast.success('Saved'); onSaved(r); }
    catch (e) { toast.error(err(e, 'Could not save')); }
  };
  return (
    <div className="cmp-box">
      <div className="cmp-row"><b>{editable ? 'Edit' : 'View'}: {camp.name}</b><span className="cmp-sub">{editable ? '' : 'Only drafts can be edited.'}</span>
        <button type="button" className="rv-btn" style={{ marginLeft: 'auto' }} onClick={onClose}>Close</button></div>
      <fieldset disabled={!editable} className="cmp-fs">
        <label>Name (only you see it)<input className="cmp-in" value={d.name} onChange={(e) => set('name', e.target.value)} /></label>
        <label>Subject<input className="cmp-in" value={d.subject} onChange={(e) => set('subject', e.target.value)} /></label>
        <label>Preview line (shown after the subject in the inbox)<input className="cmp-in" value={d.preheader} onChange={(e) => set('preheader', e.target.value)} /></label>
        <label>Heading<input className="cmp-in" value={d.heading} onChange={(e) => set('heading', e.target.value)} /></label>
        <div className="cmp-row">
          <label>Audience <select className="cmp-in sm" value={d.audience} onChange={(e) => set('audience', e.target.value)}>
            {Object.entries(meta.audiences || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="cmp-check"><input type="checkbox" checked={d.include_resellers} onChange={(e) => set('include_resellers', e.target.checked)} /> Include resellers</label>
          <label className="cmp-check" title="Customers with a paid plan but no paid order in billing (mostly panel-only accounts you renew directly)"><input type="checkbox" checked={d.include_unbilled} onChange={(e) => set('include_unbilled', e.target.checked)} /> Include customers who pay outside billing</label>
          <label className="cmp-check"><input type="checkbox" checked={d.requires_promo} onChange={(e) => set('requires_promo', e.target.checked)} /> Only send while the holiday sale runs</label>
        </div>
        <p className="cmp-sub">Personal fields: {(meta.fields || []).map((f) => <code key={f}>{`{{${f}}}`}</code>)} · <code>**bold**</code>.
          If a customer has no value for a field, that block uses its fallback or is left out.</p>
        {d.blocks.map((b, i) => (
          <div className="cmp-block" key={i}>
            <div className="cmp-row"><b>{BLOCKS[b.type]?.label || b.type}</b>
              <span style={{ marginLeft: 'auto' }} />
              <button type="button" className="rv-btn" onClick={() => move(i, -1)} aria-label="Move up">↑</button>
              <button type="button" className="rv-btn" onClick={() => move(i, 1)} aria-label="Move down">↓</button>
              <button type="button" className="rv-btn" onClick={() => set('blocks', d.blocks.filter((_, j) => j !== i))}>Remove</button></div>
            {(BLOCKS[b.type]?.keys || []).map((k) => (
              <label key={k}>{KEY_LABEL[k]}{(k === 'text' || k === 'fallback')
                ? <textarea className="cmp-in" rows={b.type === 'list' ? 4 : 2} value={b[k] || ''} onChange={(e) => setBlock(i, k, e.target.value)} />
                : <input className="cmp-in" value={b[k] || ''} onChange={(e) => setBlock(i, k, e.target.value)} />}</label>
            ))}
          </div>
        ))}
        <div className="cmp-row"><span className="cmp-sub">Add:</span>
          {Object.entries(BLOCKS).map(([k, v]) => <button type="button" key={k} className="rv-btn" onClick={() => set('blocks', [...d.blocks, { type: k }])}>{v.label.split(' (')[0]}</button>)}</div>
        <label>Notes (only you see them)<textarea className="cmp-in" rows={2} value={d.notes} onChange={(e) => set('notes', e.target.value)} /></label>
      </fieldset>
      <div className="cmp-row">
        {editable && <button type="button" className="rv-btn glow" onClick={save}>Save</button>}
        <button type="button" className="rv-btn" onClick={() => setShowPrev((n) => n + 1)}>Preview</button>
      </div>
      {showPrev > 0 && <Preview key={showPrev} draft={d} />}
    </div>
  );
}

function SendPanel({ camp, meta, refetch }) {
  const [to, setTo] = useState(meta.me || '');
  const [dry, setDry] = useState(null);
  const [mode, setMode] = useState(null);   // 'schedule' | 'now'
  const [when, setWhen] = useState('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const act = async (fn, ok) => { setBusy(true); try { await fn(); if (ok) toast.success(ok); refetch(); } catch (e) { toast.error(err(e, 'Something went wrong')); } setBusy(false); };
  const test = () => act(async () => { const r = (await api.post(`${BASE}/${camp.id}/test`, { to })).data; toast.success(`Test sent to ${r.to}${r.assumes_sale ? ' (dates assume the sale is running)' : ''}`); });
  const dryRun = () => act(async () => setDry((await api.post(`${BASE}/${camp.id}/dry-run`)).data));
  const arm = () => act(async () => {
    if (mode === 'now') await api.post(`${BASE}/${camp.id}/send-now`, { confirm: typed });
    else await api.post(`${BASE}/${camp.id}/schedule`, { confirm: typed, send_at: when });
    setMode(null); setTyped('');
  }, mode === 'now' ? 'Sending has started' : 'Scheduled');
  const simple = (path, ok) => act(() => api.post(`${BASE}/${camp.id}/${path}`), ok);
  const st = camp.status;
  return (
    <div className="cmp-box">
      <div className="cmp-row"><b>Send</b><span className="cmp-sub">One email every {meta.throttle_seconds}s, {meta.window}, once per customer.</span></div>
      <div className="cmp-row">
        <input className="cmp-in sm" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Test address" />
        <button type="button" className="rv-btn" disabled={busy} onClick={test}>Send test to me</button>
        <button type="button" className="rv-btn" disabled={busy} onClick={dryRun}>Dry run</button>
      </div>
      {dry && (
        <div className="cmp-dry">
          <p><b>{dry.count}</b> would get it ({dry.audience}).{!dry.in_window && ` Outside send hours now: it would start at ${dry.next_window} Toronto.`}</p>
          {dry.first.length > 0 && <p className="cmp-sub">First {dry.first.length}: {dry.first.map((r) => `${r.name || '?'} <${r.email}>`).join(', ')}</p>}
          {dry.skipped.length > 0 && <details><summary>{dry.skipped.length} left out: {Object.entries(dry.skipped_by_reason).map(([k, v]) => `${k} ${v}`).join(' · ')}</summary>
            <table className="cmp-table"><tbody>{dry.skipped.map((s) => <tr key={s.user_id}><td>{s.name}</td><td>{s.email}</td><td>{s.reason}</td></tr>)}</tbody></table></details>}
        </div>
      )}
      {st === 'draft' && (
        <div className="cmp-row">
          <button type="button" className="rv-btn" onClick={() => { setMode('schedule'); setTyped(''); }}>Schedule…</button>
          <button type="button" className="rv-btn" onClick={() => { setMode('now'); setTyped(''); }}>Send now…</button>
        </div>
      )}
      {st === 'draft' && mode && (
        <div className="cmp-confirm">
          {mode === 'schedule' && <label>Send at (Toronto time) <input type="datetime-local" className="cmp-in sm" value={when} onChange={(e) => setWhen(e.target.value)} /></label>}
          <p>This emails real customers{dry ? ` (${dry.count} right now)` : ''}{camp.requires_promo ? ', only while the holiday sale runs' : ''}.
            Type the number of recipients to confirm (run the dry run first if you don't know it).</p>
          <div className="cmp-row">
            <input className="cmp-in sm" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Number of recipients" />
            <button type="button" className="rv-btn glow" disabled={busy || !typed || (mode === 'schedule' && !when)} onClick={arm}>{mode === 'now' ? 'Send now' : 'Schedule'}</button>
            <button type="button" className="rv-btn" onClick={() => setMode(null)}>Cancel</button>
          </div>
        </div>
      )}
      <div className="cmp-row">
        {st === 'scheduled' && <><span>Scheduled for {camp.send_at_local} Toronto.</span><button type="button" className="rv-btn" onClick={() => simple('unschedule', 'Back to draft')}>Unschedule</button></>}
        {st === 'sending' && <button type="button" className="rv-btn" onClick={() => simple('pause', 'Paused')}>Pause</button>}
        {st === 'paused' && <><span className="cmp-warn">Paused: {camp.pause_reason}</span><button type="button" className="rv-btn" onClick={() => simple('resume', 'Resumed')}>Resume</button></>}
        {['scheduled', 'sending', 'paused'].includes(st) && <button type="button" className="rv-btn" onClick={() => { if (window.confirm('Cancel this campaign? Nobody else gets it.')) simple('cancel', 'Cancelled'); }}>Cancel campaign</button>}
      </div>
    </div>
  );
}

function SendsLog({ camp }) {
  const { data } = useQuery({ queryKey: ['cmp-sends', camp.id], queryFn: async () => (await api.get(`${BASE}/${camp.id}/sends`)).data, refetchInterval: camp.status === 'sending' ? 10000 : false });
  if (!data || !data.sends.length) return null;
  return (
    <details className="cmp-box"><summary>Send log ({Object.entries(data.counts).filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(' · ')})</summary>
      <table className="cmp-table"><tbody>{data.sends.map((s, i) => <tr key={i}><td>{s.name}</td><td>{s.email}</td><td>{s.status}</td><td>{s.reason}</td><td>{s.done_at}</td></tr>)}</tbody></table>
    </details>
  );
}

export default function AdminCampaignsPage() {
  const [all, setAll] = useState(false);
  const { data, refetch } = useQuery({ queryKey: ['cmp-list', all], queryFn: async () => (await api.get(`${BASE}?all=${all ? 1 : 0}`)).data, refetchInterval: 30000 });
  const [openId, setOpenId] = useState(null);
  const [excl, setExcl] = useState(null);
  const meta = data || {};
  const rows = meta.campaigns || [];
  const open = useMemo(() => rows.find((c) => c.id === openId), [rows, openId]);
  const create = async () => { try { const r = (await api.post(BASE, { name: 'New campaign' })).data; await refetch(); setOpenId(r.id); } catch (e) { toast.error(err(e, 'Could not create')); } };
  const copy = async (id) => { try { const r = (await api.post(`${BASE}/${id}/copy`)).data; await refetch(); setOpenId(r.id); } catch (e) { toast.error(err(e, 'Could not copy')); } };
  const retire = async (c) => { try { await api.post(`${BASE}/${c.id}/retire`, { undo: !!c.retired }); refetch(); } catch (e) { toast.error(err(e, 'Could not change')); } };
  const saveExcl = async () => { try { await api.put('/api/cmtv/campaigns/admin-config', { exclude_emails: excl }); toast.success('Saved'); setExcl(null); refetch(); } catch (e) { toast.error(err(e, 'Could not save')); } };
  return (
    <div className="rs-admin cmp-admin">
      <h1>Campaigns</h1>
      <p className="rs-sub">Branded emails to a group of customers (holiday sale, news). Unsubscribed customers, staff, resellers, panel-only
        and test accounts are always left out. {meta.promo_running ? 'The holiday sale is running.' : 'The holiday sale is not running.'}</p>
      <div className="cmp-row">
        <button type="button" className="rv-btn glow" onClick={create}>New campaign</button>
        <label className="cmp-check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show retired</label>
      </div>
      <table className="cmp-table cmp-list"><thead><tr><th>Name</th><th>Audience</th><th>Status</th><th>When</th><th>Sent</th><th /></tr></thead>
        <tbody>{rows.map((c) => (
          <tr key={c.id} className={c.id === openId ? 'on' : ''}>
            <td><button type="button" className="cmp-link" onClick={() => setOpenId(c.id === openId ? null : c.id)}>{c.name}</button>{c.retired && <span className="cmp-sub"> (retired)</span>}</td>
            <td>{(meta.audiences || {})[c.audience] || c.audience}</td>
            <td><span className={`cmp-st ${c.status}`}>{STATUS[c.status] || c.status}</span></td>
            <td>{c.send_at_local || ''}</td>
            <td>{c.counts ? `${c.counts.sent}${c.counts.failed ? ` (+${c.counts.failed} failed)` : ''}` : ''}</td>
            <td className="cmp-acts"><button type="button" className="rv-btn" onClick={() => copy(c.id)}>Copy</button>
              {!['scheduled', 'sending'].includes(c.status) && <button type="button" className="rv-btn" onClick={() => retire(c)}>{c.retired ? 'Bring back' : 'Retire'}</button>}</td>
          </tr>))}
          {!rows.length && <tr><td colSpan={6} className="cmp-sub">No campaigns yet.</td></tr>}</tbody></table>
      {open && <>
        <Editor key={`${open.id}-${open.updated_at}-${open.status}`} camp={open} meta={meta} onSaved={() => refetch()} onClose={() => setOpenId(null)} />
        <SendPanel key={`s-${open.id}`} camp={open} meta={meta} refetch={refetch} />
        <SendsLog camp={open} />
      </>}
      <details className="cmp-box"><summary>Never email these addresses (your own accounts)</summary>
        <textarea className="cmp-in" rows={3} value={excl ?? (meta.exclude_emails || []).join('\n')} onChange={(e) => setExcl(e.target.value)} />
        <button type="button" className="rv-btn" disabled={excl === null} onClick={saveExcl}>Save list</button>
      </details>
    </div>
  );
}
