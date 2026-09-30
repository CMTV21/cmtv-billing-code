// CMTV local addition 2026-09-30: pick your own Imperium channel groups (backend: cmtv_lineups.py /lineups/{key}/groups).
// The line-up sets which groups start ticked; the customer can tick or untick any group the panel allows. value = null means
// "the line-up as it is"; otherwise an array of group ids. Same price either way.
import React, { useEffect, useMemo, useState } from 'react';
import api from '../../api/api';

const SECTIONS = [
  ['main', 'Main channels'], ['vod', 'Movies & series'], ['world', 'International'], ['adult', 'Adult'],
];
const n = (v) => Number(v || 0).toLocaleString('en-CA');
const count = (g) => (g.live ? `${n(g.live)} ch` : g.movies ? `${n(g.movies)} movies` : g.series ? `${n(g.series)} series` : '');

export const customName = (name, ids) => (ids && ids.length ? `${name} · custom channels (${ids.length} groups)` : name);

export default function ChannelPicker({ productId, lineup, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState(null);   // null = not loaded, 'error', or the list
  useEffect(() => { setGroups(null); onChange(null); }, [lineup, productId]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open || groups) return;
    api.get(`/api/cmtv/lineups/${lineup}/groups`, { params: { product_id: productId } })
      .then((r) => setGroups(r.data.groups || []))
      .catch(() => setGroups('error'));
  }, [open, groups, lineup, productId]);
  const list = Array.isArray(groups) ? groups : [];
  const standard = useMemo(() => list.filter((g) => g.standard).map((g) => g.id), [list]);
  const picked = value || standard;
  const set = (ids) => {
    const same = ids.length === standard.length && ids.every((i) => standard.includes(i));
    onChange(same ? null : ids);
  };
  const toggle = (id) => set(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const live = list.filter((g) => picked.includes(g.id)).reduce((a, g) => a + g.live, 0);
  const hasVod = list.some((g) => picked.includes(g.id) && (g.movies || g.series));
  const box = { background: 'var(--deep, #0a1020)', border: '1px solid var(--line, #27345a)', borderRadius: 12, padding: 12, marginTop: 8 };
  return (
    <div style={{ margin: '0 0 10px' }}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        style={{ background: 'none', border: 0, padding: 0, color: 'var(--gold, #d8b35a)', fontWeight: 700, fontSize: 13, cursor: 'pointer' }}>
        {open ? '▾' : '▸'} Customize channels{value ? ` (${value.length} groups picked)` : ''}
      </button>
      {open && (
        <div style={box}>
          {groups === null && <small>Loading the channel groups...</small>}
          {groups === 'error' && <small>The channel groups can't be loaded right now. You can still order this line-up as it is.</small>}
          {list.length > 0 && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 8, fontSize: 13 }}>
                <b style={{ color: 'var(--text, #e9edf8)' }}>{picked.length} of {list.length} groups · {n(live)} live channels{hasVod ? ' · movies & series' : ''}</b>
                <button type="button" onClick={() => onChange(null)} disabled={!value}
                  style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--line, #27345a)', color: 'var(--muted, #9aa6c6)', borderRadius: 999, padding: '3px 10px', fontSize: 12, cursor: value ? 'pointer' : 'default' }}>
                  Reset to the line-up</button>
              </div>
              {SECTIONS.map(([key, label]) => {
                const gs = list.filter((g) => g.section === key);
                if (!gs.length) return null;
                const all = gs.every((g) => picked.includes(g.id));
                return (
                  <fieldset key={key} style={{ border: 0, padding: 0, margin: '0 0 10px' }}>
                    <legend style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 12, letterSpacing: 1, textTransform: 'uppercase', color: 'var(--muted, #9aa6c6)', marginBottom: 4 }}>
                      {label}
                      {gs.length > 1 && (
                        <button type="button" onClick={() => set(all ? picked.filter((i) => !gs.some((g) => g.id === i)) : [...new Set([...picked, ...gs.map((g) => g.id)])])}
                          style={{ background: 'none', border: 0, padding: 0, color: 'var(--cyan, #22e6f2)', fontSize: 12, cursor: 'pointer', textTransform: 'none', letterSpacing: 0 }}>
                          {all ? 'Untick all' : 'Tick all'}</button>
                      )}
                    </legend>
                    {key === 'adult' && <small style={{ display: 'block', marginBottom: 4 }}>Adult channels (18+). Off unless you tick it.</small>}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '2px 10px', maxHeight: key === 'world' ? 220 : 'none', overflowY: key === 'world' ? 'auto' : 'visible' }}>
                      {gs.map((g) => (
                        <label key={g.id} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13, color: 'var(--text, #e9edf8)', padding: '3px 0', cursor: 'pointer' }}>
                          <input type="checkbox" checked={picked.includes(g.id)} onChange={() => toggle(g.id)} />
                          <span>{g.name} <small style={{ color: 'var(--muted, #9aa6c6)' }}>{count(g)}</small></span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                );
              })}
              <small>Your line gets exactly these groups. Same price. You can change them later by messaging support.</small>
            </>
          )}
        </div>
      )}
    </div>
  );
}
