import React from 'react';

// CMTV local addition 2026-09-24: product descriptions with simple formatting, typed straight into the product's
// description box:  a blank line starts a new paragraph, lines starting with "- " or "• " become bullets,
// and **text** is bold. Plain text is escaped by React, so nothing typed here can inject HTML.

function inline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4
      ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
      : <React.Fragment key={i}>{part}</React.Fragment>
  );
}

export default function FormattedText({ text, className = '' }) {
  if (!text) return null;
  const blocks = [];
  let bullets = null;
  let para = [];
  const flushPara = () => { if (para.length) { blocks.push({ type: 'p', lines: para }); para = []; } };
  const flushBullets = () => { if (bullets) { blocks.push({ type: 'ul', items: bullets }); bullets = null; } };

  String(text).replace(/\r/g, '').split('\n').forEach((raw) => {
    const line = raw.trim();
    const bullet = line.match(/^[-•*]\s+(.*)$/);
    if (bullet) { flushPara(); (bullets = bullets || []).push(bullet[1]); }
    else if (line === '') { flushPara(); flushBullets(); }
    else { flushBullets(); para.push(line); }
  });
  flushPara(); flushBullets();

  return (
    <div className={`space-y-2 ${className}`}>
      {blocks.map((b, i) => b.type === 'ul' ? (
        <ul key={i} className="list-disc pl-5 space-y-1">
          {b.items.map((item, j) => <li key={j}>{inline(item)}</li>)}
        </ul>
      ) : (
        <p key={i}>{b.lines.map((l, j) => <React.Fragment key={j}>{j > 0 && <br />}{inline(l)}</React.Fragment>)}</p>
      ))}
    </div>
  );
}
