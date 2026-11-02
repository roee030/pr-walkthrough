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
        'method': 'Method', 'notes': 'Reviewer notes', 'libs': 'Libraries used', 'show_code': 'Show the code', 'more_lines': 'more lines not shown', 'lock_hidden': 'Lockfile: diff hidden.', 'no_edges': 'No import links between the changed files were found.', 'unres': 'Imports that could not be resolved (path alias not detected?)',
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
        'method': 'שיטה', 'notes': 'הערות סוקר', 'libs': 'ספריות בשימוש', 'show_code': 'הצג את הקוד', 'more_lines': 'שורות נוספות לא מוצגות', 'lock_hidden': 'קובץ lock: ההפרש מוסתר.', 'no_edges': 'לא נמצאו קשרי ייבוא בין הקבצים ששונו.', 'unres': 'ייבואים שלא נפתרו (אולי alias של נתיב שלא זוהה?)',
        'p_red': 'אדום', 'p_yellow': 'צהוב', 'p_green': 'ירוק', 'grades': {'low': 'סיכון סקירה נמוך', 'moderate': 'סיכון סקירה בינוני', 'high': 'סיכון סקירה גבוה', 'very_high': 'סיכון סקירה גבוה מאוד'},
        'bd': {'size': '{n} שורות ששונו', 'sec_high': 'אבטחה: {n} ממצאים חמורים', 'sec_med': 'אבטחה: {n} ממצאים בינוניים',
               'red': '{n} קבצים בסיכון אדום', 'deps': '{n} תלויות חדשות', 'no_tests': 'לא שונו טסטים לצד {n} שורות קוד',
               'suppress': '{n} השתקות של טיפוסים/lint נוספו'},
        'cols': ('חומרה', 'קובץ', 'ממצא', 'קוד'), 'smell': {'generic name': 'שם גנרי', 'vague suffix': 'סיומת עמומה', 'very long': 'ארוך מאוד'},
        'disclaimer': 'היוריסטיקות סטטיות (regex), לא AST ולא ביקורת אבטחה. הציון מודד כמה מסוכן לסקור את השינוי, לא אם הקוד נכון.',
    },
}

HE_RULES = {
    'hardcoded-secret': 'נראה כמו סיסמה או מפתח סודי שכתוב ישר בקוד',
    'aws-key': 'נראה כמו מפתח גישה של AWS', 'github-token': 'נראה כמו טוקן של GitHub', 'private-key': 'מפתח פרטי נשמר בקוד',
    'eval': 'הרצת קוד דינמית (eval), מסוכן', 'xss-html': 'הזרקת HTML גולמי, סיכון XSS',
    'shell-exec': 'פקודת מערכת שנבנית מקלט דינמי', 'sql-concat': 'שאילתת SQL שנבנית משרשור טקסט, סיכון להזרקה',
    'tls-off': 'בדיקת אישור TLS כבויה', 'pickle': 'פענוח נתונים לא בטוח',
    'cleartext-http': 'כתובת http לא מוצפנת', 'token-storage': 'טוקן או סיסמה באחסון לא מוצפן (עדיף Keychain/Keystore)',
    'log-secret': 'ייתכן שסוד נכתב ללוג', 'cors-any': 'CORS מאפשר כל מקור',
    'webview-open': 'WebView עם הרשאות רחבות', 'open-url': 'openURL עם משתנה, כדאי לאמת כתובת',
    'android-cleartext': 'תעבורה לא מוצפנת מותרת ברמת המערכת', 'new-permission': 'הרשאה חדשה במערכת ההפעלה',
    'ts-ignore': 'בדיקת טיפוסים או lint הושתקה', 'as-any': 'עקיפת טיפוסים עם any',
}
SEV_HE = {'high': 'חמור', 'medium': 'בינוני', 'low': 'נמוך'}


def rule_msg(x, lang):
    return HE_RULES.get(x['rule'], x['message']) if lang == 'he' else x['message']


def sev_word(s, lang):
    return SEV_HE.get(s, s) if lang == 'he' else s


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
.diagram{overflow:hidden;max-width:100%;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.mermaid{text-align:center}
ul{margin:6px 0;padding-inline-start:22px}
.method{font-size:.82rem;color:var(--mute);margin-top:28px;border-top:1px solid var(--line);padding-top:12px}
.tag{font-size:.72rem;border:1px solid var(--line);border-radius:6px;padding:0 6px;color:var(--mute)}
@media (max-width:600px){.hero{gap:14px}}
.tldr{font-size:1.08rem;line-height:1.6;margin:10px 0 4px;font-weight:500}
.rel{margin-top:10px;line-height:1.9}
.codebox{margin-top:12px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.codebox summary{cursor:pointer;padding:8px 12px;font-weight:600;font-size:.9rem;background:var(--code);user-select:none}
pre.code{margin:0;padding:8px 0;overflow-x:auto;max-height:560px;overflow-y:auto;font-size:.82rem;line-height:1.5;background:var(--card)}
pre.code code{background:none;padding:0;white-space:pre;overflow-wrap:normal;display:block;min-width:max-content}
.ln{display:block;padding:0 12px;white-space:pre}
.ln.add{background:var(--greenbg);color:var(--green)}
.ln.del{background:var(--redbg);color:var(--red)}
.ln.hunk{color:var(--mute);background:var(--code)}
.dg-narrow{display:none}
@media (max-width:640px){.dg-wide{display:none}.dg-narrow{display:block}}
"""


def e(x):
    return html.escape(str(x), quote=True)


def svg_diagram(graph, max_nodes=40, avail=940, uid='w', lr_limit=1340):
    nodes, edges = list(graph['nodes']), list(graph['edges'])
    hidden = 0
    if len(nodes) > max_nodes:
        order = {'red': 0, 'yellow': 1, 'green': 2}
        keep = sorted(nodes, key=lambda n: (0 if n['changed'] else 1, order.get(n['risk'], 3), -(n['adds'] + n['dels'])))[:max_nodes]
        ids = {n['id'] for n in keep}
        hidden = len(nodes) - len(keep)
        nodes = [n for n in nodes if n['id'] in ids]
        edges = [x for x in edges if x[0] in ids and x[1] in ids]
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
    lr_width = PAD * 2 + (max(cols) + 1) * W + max(cols) * GX
    pos, vertical = {}, lr_width > lr_limit
    if not vertical:
        for lv, ns in cols.items():
            for i, n in enumerate(ns):
                pos[n['id']] = (PAD + lv * (W + GX), PAD + i * (H + GY))
        width = lr_width
        height = PAD * 2 + max(len(v) for v in cols.values()) * H + (max(len(v) for v in cols.values()) - 1) * GY
    else:  # top-to-bottom bands, wrapped so the diagram never grows wider than the page
        per_row = max(1, (avail - PAD * 2 + 24) // (W + 24))
        y = PAD
        for lv in sorted(cols):
            ns = cols[lv]
            for i, n in enumerate(ns):
                pos[n['id']] = (PAD + (i % per_row) * (W + 24), y + (i // per_row) * (H + GY))
            y += ((len(ns) - 1) // per_row + 1) * (H + GY) + 34
        width = PAD * 2 + per_row * W + (per_row - 1) * 24
        height = y - 34 + PAD
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
         f'style="display:block;width:100%;max-width:{width}px;height:auto;margin:0 auto;font-family:system-ui,sans-serif" role="img">'
         f'<defs><marker id="arr-{uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" fill="var(--mute)"/></marker></defs>']
    for a, b, style in edges:
        ax, ay = pos[a]
        bx, by = pos[b]
        if vertical:
            x1, y1, x2, y2 = ax + W / 2, ay + H, bx + W / 2, by
            if y2 <= y1:  # same band or upward: side-to-side hop
                x1, y1, x2, y2 = (ax + W, ay + H / 2, bx, by + H / 2) if bx > ax else (ax, ay + H / 2, bx + W, by + H / 2)
                dx = (x2 - x1) / 2
                d = f'M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}'
            else:
                dy = (y2 - y1) / 2
                d = f'M{x1},{y1} C{x1},{y1 + dy} {x2},{y2 - dy} {x2},{y2}'
        else:
            x1, y1, x2, y2 = ax + W, ay + H / 2, bx, by + H / 2
            if x2 <= x1:
                x1, x2, y1, y2 = ax + W / 2, bx + W / 2, ay + H, by + H
                d = f'M{x1},{y1} C{x1},{y1 + 40} {x2},{y2 + 40} {x2},{y2}'
            else:
                dx = (x2 - x1) / 2
                d = f'M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}'
        dash = ' stroke-dasharray="5 4"' if style == 'dashed' else ''
        o.append(f'<path d="{d}" fill="none" stroke="var(--mute)" stroke-width="1.6" opacity=".75"{dash} marker-end="url(#arr-{uid})"/>')
    for n in nodes:
        x, y = pos[n['id']]
        d, b = os.path.split(n['path'])
        name = b if len(b) <= 22 else b[:21] + '…'
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
    if hidden:
        o.append(f'<div class="meta" dir="ltr" style="text-align:center;margin-top:6px">+{hidden} more files not drawn (lowest risk / unchanged first). Full list below.</div>')
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
        out.append(f'<h2>{e(t["diagram"])}</h2><div class="diagram dg-wide" dir="ltr">{svg_diagram(facts["graph"], avail=940, uid="w")}</div>'
                   f'<div class="diagram dg-narrow" dir="ltr">{svg_diagram(facts["graph"], avail=380, uid="n", lr_limit=0)}</div>'
                   f'<div class="meta" style="margin-top:6px">{e(t["legend"])}</div>')
        g = facts['graph']
        if not g.get('solid_edges'):
            msg = e(t['no_edges'])
            if g.get('unresolved_total'):
                msg += f' {e(t["unres"])}: ' + ' '.join(f'<code>{e(q)}</code>' for q in g.get('unresolved_examples', []))
            out.append(f'<div class="card meta">{msg}</div>')

    # security
    out.append(f'<h2>{e(t["security"])}</h2><div class="card">')
    sec = facts['security']
    if sec:
        out.append(f'<table><tr><th>{e(t["cols"][0])}</th><th>{e(t["cols"][1])}</th><th>{e(t["cols"][2])}</th><th>{e(t["cols"][3])}</th></tr>')
        for x in sec:
            out.append(f'<tr><td class="sev {x["severity"]}">{e(sev_word(x["severity"], lang))}</td>'
                       f'<td><code>{e(x["file"])}:{x["line"]}</code></td><td>{e(rule_msg(x, lang))}</td>'
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
        tldr = x.get('tldr') or x.get('what')
        if tldr:
            out.append(f'<p class="tldr">{e(tldr)}</p>')
        elif f['kind'] not in ('lock', 'docs', 'asset'):
            out.append(f'<p class="meta" style="margin-top:8px">{e(t["noexp"])}</p>')
        if x.get('tldr') and x.get('what'):
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
            out.append(f'<div class="meta" style="margin-top:8px"><span class="sev {fi["severity"]}">{e(sev_word(fi["severity"], lang))}</span> '
                       f'<code>:{fi["line"]}</code> {e(rule_msg(fi, lang))}</div>')
        rel = []
        if f['imports_in_change']:
            rel.append(f'{e(t["imports"])}: ' + ' '.join(f'<code>{e(q)}</code>' for q in f['imports_in_change']))
        if f['imported_by']:
            more = f' +{len(f["imported_by"]) - 5}' if len(f['imported_by']) > 5 else ''
            rel.append(f'{e(t["by"])}: ' + ' '.join(f'<code>{e(q)}</code>' for q in f['imported_by'][:5]) + e(more))
        if f.get('external_imports'):
            rel.append(f'{e(t["libs"])}: ' + ' '.join(f'<code>{e(q)}</code>' for q in f['external_imports'][:8]))
        if f['risk_reasons']:
            rel.append(f'{e(t["reason"])}: {e(" · ".join(f["risk_reasons"]))}')
        if f.get('entry_hint'):
            rel.append(f'↳ {e(f["entry_hint"])}')
        if rel:
            out.append('<div class="rel meta">' + '<br>'.join(rel) + '</div>')
        # code, collapsed by default
        if f.get('diff'):
            body = []
            for ln in f['diff']:
                cls = 'add' if ln.startswith('+') else 'del' if ln.startswith('-') else 'hunk' if ln.startswith('@@') else ''
                body.append(f'<span class="ln {cls}">{e(ln) if ln else " "}</span>')
            more = f'<span class="ln hunk">… +{f["diff_truncated"]} {e(t["more_lines"])}</span>' if f.get('diff_truncated') else ''
            out.append(f'<details class="codebox"><summary>{e(t["show_code"])} <span class="mono meta">+{f["adds"]} −{f["dels"]}</span></summary>'
                       f'<pre class="code" dir="ltr"><code>{"".join(body)}{more}</code></pre></details>')
        elif f.get('kind') == 'lock':
            out.append(f'<div class="meta" style="margin-top:8px">{e(t["lock_hidden"])}</div>')
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
