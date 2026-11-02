#!/usr/bin/env python3
"""Render facts.json (+ optional explanations.json) into one self-contained report.html.

explanations.json (written by the agent) shape, every key optional:
{
  "language": "he" | "en",
  "title": "short PR title",
  "summary": "what the change is and why, 2-4 lines",
  "simplest": "what the simplest version would look like (estimate)",
  "start_here": "where the flow begins and how it travels",
  "files": {
    "path/to/file.ts": {
      "what": "...", "why": "...", "inferred": true,
      "names": [{"name": "processData", "verdict": "generic", "suggest": "normalizeCartItems"}],
      "removable": "..."
    }
  },
  "security_notes": "judgement on the automated findings, false positives, what scanner can't see",
  "verify": ["...", "..."]
}
"""
import argparse
import html
import json
import os

L = {
    'en': {
        'score': 'PR review-risk score', 'summary': 'Summary', 'simplest': 'Simplest version',
        'start': 'Where it starts', 'diagram': 'Relationship map', 'security': 'Security',
        'deps': 'Dependencies', 'files': 'Every part, in reading order', 'verify': 'Still yours to verify',
        'nofind': 'No automated findings.', 'noexp': 'No explanation written for this file.',
        'what': 'What changed', 'why': 'Why', 'names': 'Names', 'remove': 'Could be removed',
        'inferred': 'inferred', 'imports': 'Imports (in this change)', 'by': 'Imported by',
        'added': 'added', 'removed': 'removed', 'changed': 'version changed', 'none': 'none',
        'legend': 'Solid = import between changed files. Dashed = unchanged file that imports a changed one (blast radius).',
        'files_word': 'files', 'entry': 'Entry points of this change', 'reason': 'Why this level',
        'method': 'Method', 'notes': 'Reviewer notes',
        'grades': {'low': 'low review risk', 'moderate': 'moderate review risk', 'high': 'high review risk', 'very_high': 'very high review risk'},
        'bd': {'size': '{n} changed lines', 'sec_high': 'Security: {n} high finding(s)', 'sec_med': 'Security: {n} medium finding(s)',
               'red': '{n} red-risk file(s)', 'deps': '{n} new dependencies', 'no_tests': 'No tests changed alongside {n} source lines',
               'suppress': '{n} type/lint suppressions added'},
        'cols': ('Severity', 'File', 'Finding', 'Code'), 'smell': {'generic name': 'generic name', 'vague suffix': 'vague suffix', 'very long': 'very long'},
        'disclaimer': 'Static heuristics (regex), not an AST or a security audit. The score measures how risky this is to review, not whether the code is correct.',
    },
    'he': {
        'score': 'ציון סיכון ל-PR', 'summary': 'סיכום', 'simplest': 'הגרסה הכי פשוטה',
        'start': 'מאיפה הכול מתחיל', 'diagram': 'מפת קשרים', 'security': 'אבטחה',
        'deps': 'תלויות', 'files': 'הסבר לכל חלק, לפי סדר קריאה', 'verify': 'עדיין עליך לאמת',
        'nofind': 'לא נמצאו ממצאים אוטומטיים.', 'noexp': 'לא נכתב הסבר לקובץ הזה.',
        'what': 'מה השתנה', 'why': 'למה', 'names': 'שמות', 'remove': 'אפשר להסיר',
        'inferred': 'הסקה', 'imports': 'מייבא (בתוך השינוי)', 'by': 'מיובא על ידי',
        'added': 'נוספו', 'removed': 'הוסרו', 'changed': 'גרסה השתנתה', 'none': 'אין',
        'legend': 'קו רציף = ייבוא בין קבצים ששונו. קו מקווקו = קובץ שלא שונה אבל מייבא קובץ ששונה (רדיוס פגיעה).',
        'files_word': 'קבצים', 'entry': 'נקודות כניסה של השינוי', 'reason': 'למה הדרגה הזו',
        'method': 'שיטה', 'notes': 'הערות סוקר',
        'p_red': 'אדום', 'p_yellow': 'צהוב', 'p_green': 'ירוק', 'grades': {'low': 'סיכון סקירה נמוך', 'moderate': 'סיכון סקירה בינוני', 'high': 'סיכון סקירה גבוה', 'very_high': 'סיכון סקירה גבוה מאוד'},
        'bd': {'size': '{n} שורות ששונו', 'sec_high': 'אבטחה: {n} ממצאים חמורים', 'sec_med': 'אבטחה: {n} ממצאים בינוניים',
               'red': '{n} קבצים בסיכון אדום', 'deps': '{n} תלויות חדשות', 'no_tests': 'לא שונו טסטים לצד {n} שורות קוד',
               'suppress': '{n} השתקות של טיפוסים/lint נוספו'},
        'cols': ('חומרה', 'קובץ', 'ממצא', 'קוד'), 'smell': {'generic name': 'שם גנרי', 'vague suffix': 'סיומת עמומה', 'very long': 'ארוך מאוד'},
        'disclaimer': 'היוריסטיקות סטטיות (regex), לא AST ולא ביקורת אבטחה. הציון מודד כמה מסוכן לסקור את השינוי, לא אם הקוד נכון.',
    },
}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1a1a1a;--mute:#6b6b66;--line:#e4e4df;--accent:#2b5fd9;
--red:#d1342c;--yellow:#b7791f;--green:#2f855a;--redbg:#fdeceb;--yellowbg:#fdf4e3;--greenbg:#e8f5ee;--code:#f0f0ec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141414;--card:#1d1d1c;--ink:#ececea;--mute:#9a9a94;--line:#2e2e2b;--accent:#7aa2ff;
--red:#ff7b72;--yellow:#e3b341;--green:#56d364;--redbg:#3a1d1b;--yellowbg:#3a2f14;--greenbg:#16301f;--code:#262624}}
:root[data-theme="dark"]{--bg:#141414;--card:#1d1d1c;--ink:#ececea;--mute:#9a9a94;--line:#2e2e2b;--accent:#7aa2ff;
--red:#ff7b72;--yellow:#e3b341;--green:#56d364;--redbg:#3a1d1b;--yellowbg:#3a2f14;--greenbg:#16301f;--code:#262624}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:1.6rem;margin:0 0 4px;line-height:1.25}
h2{font-size:1.2rem;margin:36px 0 12px}
.sub{color:var(--mute);font-size:.9rem}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.88em;direction:ltr;unicode-bidi:isolate}
code{background:var(--code);padding:1px 6px;border-radius:5px;white-space:pre-wrap;overflow-wrap:anywhere}
.card{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
.hero{display:flex;gap:24px;align-items:center;flex-wrap:wrap}
.ring{width:128px;height:128px;flex:none;position:relative}
.ring svg{width:128px;height:128px;transform:rotate(-90deg)}
.ring .num{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;font-weight:700;font-size:2rem;line-height:1}
.ring .num small{font-size:.7rem;font-weight:500;color:var(--mute);margin-top:4px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
.pill{border-radius:999px;padding:3px 12px;font-size:.85rem;border:1px solid var(--line);background:var(--card)}
.pill.red{background:var(--redbg);color:var(--red);border-color:transparent}
.pill.yellow{background:var(--yellowbg);color:var(--yellow);border-color:transparent}
.pill.green{background:var(--greenbg);color:var(--green);border-color:transparent}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{text-align:start;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.03em}
.sev{font-weight:700;font-size:.78rem;text-transform:uppercase}
.sev.high{color:var(--red)}.sev.medium{color:var(--yellow)}.sev.low{color:var(--mute)}
.fhead{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dot{width:12px;height:12px;border-radius:50%;flex:none}
.dot.red{background:var(--red)}.dot.yellow{background:var(--yellow)}.dot.green{background:var(--green)}
.path{font-weight:600;word-break:break-all}
.meta{color:var(--mute);font-size:.82rem}
.kv{margin:8px 0 0}
.kv b{display:block;font-size:.78rem;color:var(--mute);text-transform:uppercase;letter-spacing:.03em;margin-top:10px}
.diagram{overflow-x:auto;max-width:100%;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.mermaid{text-align:center}
ul{margin:6px 0;padding-inline-start:22px}
.method{font-size:.82rem;color:var(--mute);margin-top:28px;border-top:1px solid var(--line);padding-top:12px}
.tag{font-size:.72rem;border:1px solid var(--line);border-radius:6px;padding:0 6px;color:var(--mute)}
@media (max-width:600px){.hero{gap:14px}}
"""


def e(x):
    return html.escape(str(x), quote=True)


def svg_diagram(graph):
    nodes, edges = graph['nodes'], graph['edges']
    by = {n['id']: n for n in nodes}
    level = {n['id']: 0 for n in nodes}
    for _ in range(len(nodes) + 1):
        moved = False
        for a, b, _s in edges:
            if level[b] < level[a] + 1 and level[a] + 1 <= len(nodes):
                level[b] = level[a] + 1
                moved = True
        if not moved:
            break
    cols = {}
    for n in nodes:
        cols.setdefault(level[n['id']], []).append(n)
    W, H, GX, GY, PAD = 200, 62, 90, 18, 14
    pos = {}
    for lv, ns in cols.items():
        for i, n in enumerate(ns):
            pos[n['id']] = (PAD + lv * (W + GX), PAD + i * (H + GY))
    width = PAD * 2 + (max(cols) + 1) * W + max(cols) * GX
    height = PAD * 2 + max(len(v) for v in cols.values()) * H + (max(len(v) for v in cols.values()) - 1) * GY
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
         f'style="max-width:none;font-family:system-ui,sans-serif" role="img">'
         '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" fill="var(--mute)"/></marker></defs>']
    for a, b, style in edges:
        x1, y1 = pos[a][0] + W, pos[a][1] + H / 2
        x2, y2 = pos[b][0], pos[b][1] + H / 2
        if x2 <= x1:  # same column or back edge: loop around below
            x1, x2 = pos[a][0] + W / 2, pos[b][0] + W / 2
            y1, y2 = pos[a][1] + H, pos[b][1] + H
            d = f'M{x1},{y1} C{x1},{y1 + 40} {x2},{y2 + 40} {x2},{y2}'
        else:
            dx = (x2 - x1) / 2
            d = f'M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}'
        dash = ' stroke-dasharray="5 4"' if style == 'dashed' else ''
        o.append(f'<path d="{d}" fill="none" stroke="var(--mute)" stroke-width="1.6"{dash} marker-end="url(#arr)"/>')
    for n in nodes:
        x, y = pos[n['id']]
        d, b = os.path.split(n['path'])
        name = b if len(b) <= 26 else b[:25] + '…'
        folder = ('…/' + os.path.basename(d)) if d else '.'
        if n['changed']:
            col = {'red': 'var(--red)', 'yellow': 'var(--yellow)', 'green': 'var(--green)'}.get(n['risk'], 'var(--mute)')
            bg = {'red': 'var(--redbg)', 'yellow': 'var(--yellowbg)', 'green': 'var(--greenbg)'}.get(n['risk'], 'var(--card)')
            sub = f'+{n["adds"]} −{n["dels"]}  ·  {folder}'
            attrs = f'fill="{bg}" stroke="{col}" stroke-width="2"'
        else:
            sub = f'unchanged  ·  {folder}'
            attrs = 'fill="none" stroke="var(--mute)" stroke-width="1.4" stroke-dasharray="5 4"'
        o.append(f'<g><title>{e(n["path"])}</title><rect x="{x}" y="{y}" width="{W}" height="{H}" rx="9" {attrs}/>'
                 f'<text x="{x + 12}" y="{y + 26}" font-size="14" font-weight="600" fill="var(--ink)" direction="ltr">{e(name)}</text>'
                 f'<text x="{x + 12}" y="{y + 47}" font-size="11.5" fill="var(--mute)" direction="ltr">{e(sub)}</text></g>')
    o.append('</svg>')
    return ''.join(o)


def ring(score):
    pct = max(0, min(10, score)) / 10
    c = 2 * 3.14159 * 54
    col = 'var(--green)' if score >= 8 else 'var(--yellow)' if score >= 5 else 'var(--red)'
    return (f'<svg viewBox="0 0 128 128"><circle cx="64" cy="64" r="54" fill="none" stroke="var(--line)" stroke-width="12"/>'
            f'<circle cx="64" cy="64" r="54" fill="none" stroke="{col}" stroke-width="12" stroke-linecap="round" '
            f'stroke-dasharray="{c * pct:.1f} {c:.1f}"/></svg>')


def para(text):
    return ''.join(f'<p>{e(p)}</p>' for p in str(text).split('\n') if p.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--facts', default='facts.json')
    ap.add_argument('--explain', default='explanations.json')
    ap.add_argument('--out', default='report.html')
    a = ap.parse_args()
    facts = json.load(open(a.facts, encoding='utf-8'))
    ex = {}
    if os.path.exists(a.explain):
        ex = json.load(open(a.explain, encoding='utf-8'))
    lang = ex.get('language', 'en')
    t = L.get(lang, L['en'])
    rtl = lang in ('he', 'ar')
    by = {f['path']: f for f in facts['files']}
    s = facts['score']
    rs = facts['risk_summary']
    tot = facts['totals']
    title = ex.get('title') or 'PR walkthrough'

    out = []
    out.append(f'<!doctype html><html lang="{e(lang)}" dir="{"rtl" if rtl else "ltr"}"><head><meta charset="utf-8">'
               f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} report</title>'
               f'<style>{CSS}</style></head><body><div class="wrap">')
    out.append(f'<h1>{e(title)}</h1><div class="sub"><bdi dir="ltr">{e(facts["meta"]["mode"])}</bdi> · {tot["files"]} {t["files_word"]} · '
               f'<bdi dir="ltr">+{tot["added"]} −{tot["deleted"]}</bdi></div>')

    # hero
    out.append('<div class="card hero">')
    out.append(f'<div class="ring">{ring(s["value"])}<div class="num" dir="ltr">{s["value"]:g}<small>/ 10</small></div></div>')
    out.append(f'<div style="flex:1;min-width:240px"><b>{e(t["score"])}</b> · {e(t["grades"].get(s.get("grade_key"), s["grade"]))}')
    out.append(f'<div class="stats"><span class="pill red">{rs["red"]} {e(t.get("p_red","red"))}</span><span class="pill yellow">{rs["yellow"]} {e(t.get("p_yellow","yellow"))}</span>'
               f'<span class="pill green">{rs["green"]} {e(t.get("p_green","green"))}</span></div>')
    if s['breakdown']:
        out.append('<ul>' + ''.join(f'<li>{e(t["bd"][b["key"]].format(n=b["n"]) if b.get("key") in t["bd"] else b["label"])} <bdi dir="ltr" class="mono">({b["delta"]:g})</bdi></li>' for b in s['breakdown']) + '</ul>')
    out.append('</div></div>')

    if ex.get('summary'):
        out.append(f'<h2>{e(t["summary"])}</h2><div class="card">{para(ex["summary"])}</div>')
    if ex.get('simplest'):
        out.append(f'<h2>{e(t["simplest"])}</h2><div class="card">{para(ex["simplest"])}</div>')

    # start + order
    out.append(f'<h2>{e(t["start"])}</h2><div class="card">')
    if ex.get('start_here'):
        out.append(para(ex['start_here']))
    if facts['entry_points']:
        out.append(f'<div class="meta">{e(t["entry"])}</div><ul>' +
                   ''.join(f'<li><code>{e(p)}</code></li>' for p in facts['entry_points']) + '</ul>')
    out.append('</div>')

    # diagram
    if facts['graph']['nodes']:
        out.append(f'<h2>{e(t["diagram"])}</h2><div class="diagram" dir="ltr">{svg_diagram(facts["graph"])}</div>'
                   f'<div class="meta" style="margin-top:6px">{e(t["legend"])}</div>')

    # security
    out.append(f'<h2>{e(t["security"])}</h2><div class="card">')
    sec = facts['security']
    if sec:
        out.append(f'<table><tr><th>{e(t["cols"][0])}</th><th>{e(t["cols"][1])}</th><th>{e(t["cols"][2])}</th><th>{e(t["cols"][3])}</th></tr>')
        for x in sec:
            out.append(f'<tr><td class="sev {x["severity"]}">{e(x["severity"])}</td>'
                       f'<td><code>{e(x["file"])}:{x["line"]}</code></td><td>{e(x["message"])}</td>'
                       f'<td><code>{e(x["snippet"])}</code></td></tr>')
        out.append('</table>')
    else:
        out.append(f'<p>{e(t["nofind"])}</p>')
    if ex.get('security_notes'):
        out.append(f'<div class="kv"><b>{e(t["notes"])}</b>{para(ex["security_notes"])}</div>')
    out.append('</div>')

    # deps
    d = facts['dependencies']
    if d['added'] or d['removed'] or d['changed']:
        out.append(f'<h2>{e(t["deps"])}</h2><div class="card"><table>')
        for x in d['added']:
            out.append(f'<tr><td>{e(t["added"])}</td><td><code>{e(x["name"])}@{e(x["version"])}</code></td><td class="meta">{e(x["section"])}</td></tr>')
        for x in d['removed']:
            out.append(f'<tr><td>{e(t["removed"])}</td><td><code>{e(x["name"])}</code></td><td class="meta">{e(x["section"])}</td></tr>')
        for x in d['changed']:
            out.append(f'<tr><td>{e(t["changed"])}</td><td><code>{e(x["name"])}: {e(x["from"])} → {e(x["to"])}</code></td><td class="meta">{e(x["section"])}</td></tr>')
        out.append('</table></div>')

    # files
    out.append(f'<h2>{e(t["files"])}</h2>')
    for i, p in enumerate(facts['reading_order'], 1):
        f = by.get(p)
        if not f:
            continue
        x = ex.get('files', {}).get(p, {})
        out.append('<div class="card">')
        out.append(f'<div class="fhead"><span class="dot {f["risk"]}"></span><span class="mono meta">{i}</span>'
                   f'<span class="path mono">{e(p)}</span><span class="tag">{e(f["status"])}</span><span class="tag">{e(f["kind"])}</span>'
                   f'<span class="meta mono">+{f["adds"]} −{f["dels"]}</span></div>')
        if f['risk_reasons']:
            out.append(f'<div class="meta">{e(t["reason"])}: {e(" · ".join(f["risk_reasons"]))}</div>')
        if f.get('entry_hint'):
            out.append(f'<div class="meta">↳ {e(f["entry_hint"])}</div>')
        if f['imports_in_change']:
            out.append(f'<div class="kv"><b>{e(t["imports"])}</b>' + ' '.join(f'<code>{e(q)}</code>' for q in f['imports_in_change']) + '</div>')
        if f['imported_by']:
            shown = f['imported_by'][:6]
            more = f' +{len(f["imported_by"]) - 6}' if len(f['imported_by']) > 6 else ''
            out.append(f'<div class="kv"><b>{e(t["by"])}</b>' + ' '.join(f'<code>{e(q)}</code>' for q in shown) + e(more) + '</div>')
        if x:
            if x.get('what'):
                out.append(f'<div class="kv"><b>{e(t["what"])}</b>{para(x["what"])}</div>')
            if x.get('why'):
                tag = f' <span class="tag">{e(t["inferred"])}</span>' if x.get('inferred') else ''
                out.append(f'<div class="kv"><b>{e(t["why"])}{tag}</b>{para(x["why"])}</div>')
        names = x.get('names') or [
            {'name': n['name'], 'verdict': t['smell'].get(n['smell'], n['smell']), 'suggest': ''} for n in f['new_identifiers'] if n['smell']]
        if names:
            out.append(f'<div class="kv"><b>{e(t["names"])}</b><table>')
            for n in names:
                out.append(f'<tr><td><code>{e(n.get("name", ""))}</code></td><td>{e(n.get("verdict", ""))}</td>'
                           f'<td>{("→ <code>" + e(n["suggest"]) + "</code>") if n.get("suggest") else ""}</td></tr>')
            out.append('</table></div>')
        if x.get('removable'):
            out.append(f'<div class="kv"><b>{e(t["remove"])}</b>{para(x["removable"])}</div>')
        for fi in f['findings']:
            out.append(f'<div class="meta" style="margin-top:8px"><span class="sev {fi["severity"]}">{e(fi["severity"])}</span> '
                       f'<code>:{fi["line"]}</code> {e(fi["message"])}</div>')
        if not x and not f['risk_reasons'] and f['kind'] in ('lock', 'docs', 'asset'):
            pass
        elif not x:
            out.append(f'<div class="meta" style="margin-top:8px">{e(t["noexp"])}</div>')
        out.append('</div>')

    if ex.get('verify'):
        out.append(f'<h2>{e(t["verify"])}</h2><div class="card"><ul>' + ''.join(f'<li>{e(v)}</li>' for v in ex['verify']) + '</ul></div>')

    out.append(f'<div class="method"><b>{e(t["method"])}.</b> {e(t["disclaimer"])}</div>')
    out.append('</div>')
    out.append('</body></html>')
    with open(a.out, 'w', encoding='utf-8') as fh:
        fh.write(''.join(out))
    print(f'report -> {a.out}')


if __name__ == '__main__':
    main()
