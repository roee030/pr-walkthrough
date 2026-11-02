#!/usr/bin/env python3
"""pr-walkthrough analyzer.

Reads a git diff (or a patch file) and writes facts.json:
changed files, import graph + blast radius, reading order, entry points,
dependency changes, security findings, a transparent PR review-risk score.

Pure static heuristics (regex, no AST). Good for JS/TS/React Native and
reasonable for Python. Findings are leads for a human, not verdicts.

Usage:
  analyze.py [--base REF] [--staged | --worktree] [--diff-file PATCH] [--out facts.json]
"""
import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import sys

JS_EXT = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')
SRC_EXT = JS_EXT + ('.py',)
MAX_REPO_FILES = 4000
MAX_FILE_BYTES = 500_000

TEST_RE = re.compile(r'(^|/)(__tests__|tests?|spec|e2e|__mocks__)/|\.(test|spec)\.[jt]sx?$|_test\.py$|(^|/)test_[^/]*\.py$')
DOC_RE = re.compile(r'\.(md|mdx|txt|rst)$|(^|/)docs?/', re.I)
LOCK_RE = re.compile(r'(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Podfile\.lock|poetry\.lock|Gemfile\.lock|bun\.lockb?)$')
CONFIG_RE = re.compile(
    r'(^|/)(package\.json|tsconfig[^/]*\.json|babel\.config\.[jt]s|metro\.config\.[jt]s|app\.json|app\.config\.[jt]s|'
    r'Dockerfile[^/]*|docker-compose[^/]*|\.env[^/]*|build\.gradle|Podfile|AndroidManifest\.xml|Info\.plist|'
    r'requirements[^/]*\.txt|pyproject\.toml|\.eslintrc[^/]*|eslint\.config\.[jt]s)$|^\.github/workflows/|(^|/)ci\.ya?ml$')
STYLE_RE = re.compile(r'\.(css|scss|sass|less|svg|png|jpe?g|gif|webp|ttf|otf|woff2?)$', re.I)
SENSITIVE_RE = re.compile(
    r'auth|login|logout|signin|signup|session|token|password|credential|secret|permission|oauth|jwt|'
    r'payment|billing|checkout|purchase|crypto|encrypt|keychain|keystore|biometric|migration|schema|'
    r'\.env|dockerfile|\.github/workflows', re.I)
ENTRY_NAME_RE = re.compile(r'(^|/)(index|main|app|_layout|page|route|server|App)\.[jt]sx?$|(^|/)(main|__main__|app|manage)\.py$')

GENERIC_NAMES = {
    'data', 'result', 'results', 'res', 'resp', 'response', 'temp', 'tmp', 'val', 'value', 'item', 'items', 'obj',
    'handler', 'handle', 'process', 'helper', 'helpers', 'util', 'utils', 'manager', 'info', 'stuff', 'thing',
    'foo', 'bar', 'baz', 'dostuff', 'run', 'execute', 'callback', 'cb', 'arr', 'list', 'x', 'y', 'ret', 'out', 'fn', 'func',
}
VAGUE_SUFFIX_RE = re.compile(r'(Helper|Util|Utils|Manager|Handler|Processor|Wrapper|Service|Impl)$')

# (id, severity, regex, message, flags)
SEC_RULES = [
    ('hardcoded-secret', 'high',
     re.compile(r'(api[_-]?key|secret|token|passwd|password|private[_-]?key|client[_-]?secret)\w*\s*[:=]\s*[\'"][^\'"\s]{8,}[\'"]', re.I),
     'Looks like a hardcoded secret or credential'),
    ('aws-key', 'high', re.compile(r'AKIA[0-9A-Z]{16}'), 'AWS access key id pattern'),
    ('github-token', 'high', re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'), 'GitHub token pattern'),
    ('private-key', 'high', re.compile(r'-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'), 'Private key committed'),
    ('eval', 'high', re.compile(r'(?<![\w.])eval\s*\(|new\s+Function\s*\('), 'Dynamic code execution (eval / new Function)'),
    ('xss-html', 'high', re.compile(r'dangerouslySetInnerHTML|\.innerHTML\s*=|document\.write\s*\('), 'Raw HTML injection point (XSS risk)'),
    ('shell-exec', 'high',
     re.compile(r'(child_process|execSync|spawnSync|\bexec\s*\()[^\n]*(\$\{|\+\s*\w)|os\.system\s*\(|subprocess\.[a-z_]+\([^\n]*shell\s*=\s*True'),
     'Shell command built from dynamic input'),
    ('sql-concat', 'high',
     re.compile(r'[\'"`]\s*(SELECT|INSERT|UPDATE|DELETE)\b[^\n]*(\$\{|[\'"]\s*\+\s*\w|%s|\.format\()', re.I),
     'SQL built by string concatenation (injection risk)'),
    ('tls-off', 'high',
     re.compile(r'rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED|verify\s*=\s*False'), 'TLS verification disabled'),
    ('pickle', 'high', re.compile(r'pickle\.loads?\(|yaml\.load\((?![^)]*SafeLoader)'), 'Unsafe deserialization'),
    ('cleartext-http', 'medium', re.compile(r'[\'"`]http://(?!localhost|127\.0\.0\.1|10\.0\.2\.2|0\.0\.0\.0)[^\'"`\s]+'),
     'Cleartext http:// URL'),
    ('token-storage', 'medium',
     re.compile(r'(AsyncStorage|localStorage|sessionStorage)\.setItem\([^)]*(token|password|secret|jwt|credential)', re.I),
     'Sensitive value stored in unencrypted storage (consider Keychain/Keystore/SecureStore)'),
    ('log-secret', 'medium', re.compile(r'(console\.(log|info|debug)|print|logger\.\w+)\([^)]*(token|password|secret|jwt)', re.I),
     'Possible secret written to logs'),
    ('cors-any', 'medium', re.compile(r'origin\s*:\s*[\'"]\*[\'"]|Access-Control-Allow-Origin[\'"]?\s*[:,]\s*[\'"]\*'),
     'CORS allows any origin'),
    ('webview-open', 'medium', re.compile(r'originWhitelist\s*=?\s*[:=]?\s*\{?\s*\[\s*[\'"]\*[\'"]|javaScriptEnabled\s*=\s*\{?true'),
     'WebView with broad origin/JS access'),
    ('open-url', 'medium', re.compile(r'Linking\.openURL\(\s*[A-Za-z_]'), 'openURL with a variable (validate scheme/host)'),
    ('android-cleartext', 'medium', re.compile(r'usesCleartextTraffic\s*=\s*"true"|NSAllowsArbitraryLoads'),
     'Cleartext traffic allowed at platform level'),
    ('new-permission', 'medium', re.compile(r'<uses-permission|NS\w+UsageDescription'), 'New platform permission requested'),
    ('ts-ignore', 'low', re.compile(r'@ts-ignore|@ts-nocheck|eslint-disable'), 'Type/lint check suppressed'),
    ('as-any', 'low', re.compile(r'\bas\s+any\b|:\s*any\b'), 'Type safety bypassed with any'),
]


def run(cmd, cwd=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


def repo_root():
    out = run(['git', 'rev-parse', '--show-toplevel'])
    return out.strip() if out else os.getcwd()


def pick_base(root, requested):
    if requested:
        return requested
    for ref in ('origin/main', 'origin/master', 'main', 'master'):
        if run(['git', 'rev-parse', '--verify', '-q', ref], root) is not None:
            head = run(['git', 'rev-parse', 'HEAD'], root)
            ref_sha = run(['git', 'rev-parse', ref], root)
            if head and ref_sha and head.strip() != ref_sha.strip():
                return ref
    return 'HEAD~1'


def get_diff(args, root, ctx=0):
    if args.diff_file:
        with open(args.diff_file, encoding='utf-8', errors='replace') as f:
            return f.read(), 'patch-file', None
    flags = ['--no-color', '--no-ext-diff', f'-U{ctx}', '--find-renames']
    if args.staged:
        return run(['git', 'diff', '--cached'] + flags, root) or '', 'staged', 'HEAD'
    if args.worktree:
        return run(['git', 'diff', 'HEAD'] + flags, root) or '', 'worktree', 'HEAD'
    base = pick_base(root, args.base)
    out = run(['git', 'diff', f'{base}...HEAD'] + flags, root)
    if out is None:
        out = run(['git', 'diff', base, 'HEAD'] + flags, root)
    return out or '', f'{base}...HEAD', base


def parse_diff(text):
    files, cur, in_hunk, newline = [], None, False, 0
    for raw in text.splitlines():
        if raw.startswith('diff --git '):
            m = re.match(r'diff --git a/(.*?) b/(.*)$', raw)
            path = m.group(2) if m else raw.split(' b/')[-1]
            cur = {'path': path, 'old_path': m.group(1) if m else path, 'status': 'modified',
                   'added_lines': [], 'adds': 0, 'dels': 0, 'binary': False}
            files.append(cur)
            in_hunk = False
            continue
        if cur is None:
            continue
        if not in_hunk:
            if raw.startswith('new file mode'):
                cur['status'] = 'added'
            elif raw.startswith('deleted file mode'):
                cur['status'] = 'deleted'
            elif raw.startswith('rename from '):
                cur['status'] = 'renamed'
                cur['old_path'] = raw[len('rename from '):]
            elif raw.startswith('Binary files'):
                cur['binary'] = True
            elif raw.startswith('+++ '):
                p = raw[4:].strip()
                if p != '/dev/null':
                    cur['path'] = p[2:] if p.startswith('b/') else p
            elif raw.startswith('--- '):
                p = raw[4:].strip()
                if p != '/dev/null':
                    cur['old_path'] = p[2:] if p.startswith('a/') else p
        if raw.startswith('@@'):
            m = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', raw)
            newline = int(m.group(1)) if m else 0
            in_hunk = True
            continue
        if in_hunk:
            if raw.startswith('+'):
                cur['added_lines'].append((newline, raw[1:]))
                cur['adds'] += 1
                newline += 1
            elif raw.startswith('-'):
                cur['dels'] += 1
    for f in files:
        if f['status'] == 'deleted':
            f['path'] = f['old_path']
    return files


MAX_DIFF_LINES = 300


def split_blocks(text):
    blocks, cur, in_hunk = {}, None, False
    for raw in text.splitlines():
        if raw.startswith('diff --git '):
            m = re.match(r'diff --git a/(.*?) b/(.*)$', raw)
            cur = []
            in_hunk = False
            if m:
                blocks[m.group(2)] = cur
            continue
        if cur is None:
            continue
        if raw.startswith('@@'):
            in_hunk = True
        if in_hunk or raw.startswith('Binary files'):
            cur.append(raw)
    return blocks


def kind_of(path):
    if TEST_RE.search(path):
        return 'test'
    if LOCK_RE.search(path):
        return 'lock'
    if CONFIG_RE.search(path):
        return 'config'
    if DOC_RE.search(path):
        return 'docs'
    if STYLE_RE.search(path):
        return 'asset'
    if path.endswith(SRC_EXT):
        return 'source'
    return 'other'


def list_repo_files(root):
    out = run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], root)
    if out is not None:
        names = out.splitlines()
    else:
        names = []
        for d, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x not in ('node_modules', '.git', 'dist', 'build', '__pycache__')]
            for f in fs:
                names.append(os.path.relpath(os.path.join(d, f), root))
    names = [n for n in names if n.endswith(SRC_EXT) and 'node_modules/' not in n]
    return names[:MAX_REPO_FILES]


def read_file(root, rel):
    p = os.path.join(root, rel)
    try:
        if os.path.getsize(p) > MAX_FILE_BYTES:
            return None
        with open(p, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


JS_IMPORT_RES = [
    re.compile(r'''(?:import|export)\s+(?:type\s+)?(?:[^'";]*?\s+from\s+)?['"]([^'"]+)['"]'''),
    re.compile(r'''require\(\s*['"]([^'"]+)['"]\s*\)'''),
    re.compile(r'''import\(\s*['"]([^'"]+)['"]\s*\)'''),
]
PY_IMPORT_RES = [re.compile(r'^\s*from\s+([.\w]+)\s+import', re.M), re.compile(r'^\s*import\s+([\w.]+)', re.M)]


def extract_imports(path, text):
    res = PY_IMPORT_RES if path.endswith('.py') else JS_IMPORT_RES
    out = []
    for r in res:
        out.extend(r.findall(text))
    return out


CTX = {'aliases': [], 'base_url': '', 'deps': set(), 'stems': {}}
ASSET_SPEC_RE = re.compile(r'\.(png|jpe?g|gif|svg|webp|ttf|otf|json|css|scss|less|mp[34]|wav|lottie)$', re.I)


def load_json_loose(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            txt = fh.read()
    except OSError:
        return None
    txt = re.sub(r'^\s*//.*$', '', txt, flags=re.M)
    txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.S)
    txt = re.sub(r',(\s*[}\]])', r'\1', txt)
    try:
        return json.loads(txt)
    except ValueError:
        return None


def load_context(root, fileset):
    aliases, base_url = [], ''
    for name in ('tsconfig.json', 'tsconfig.base.json', 'jsconfig.json'):
        j = load_json_loose(os.path.join(root, name))
        if not isinstance(j, dict):
            continue
        co = j.get('compilerOptions') or {}
        bu = co.get('baseUrl')
        if bu:
            b = os.path.normpath(bu).replace('\\', '/')
            base_url = '' if b == '.' else b
        for pat, targets in (co.get('paths') or {}).items():
            aliases.append((pat, [os.path.normpath(os.path.join(bu or '.', t)).replace('\\', '/') for t in targets]))
    for name in ('babel.config.js', 'babel.config.json', '.babelrc', '.babelrc.js'):
        try:
            with open(os.path.join(root, name), encoding='utf-8', errors='replace') as fh:
                txt = fh.read()
        except OSError:
            continue
        if 'module-resolver' in txt:
            for k, v in re.findall(r"""['"]([@~#\w/.-]+)['"]\s*:\s*['"]\.{1,2}/?([^'"]*)['"]""", txt):
                tgt = os.path.normpath(v or '.').replace('\\', '/')
                aliases.append((k + '/*', [tgt + '/*']))
                aliases.append((k, [tgt]))
    deps = set()
    pkgs = (run(['git', 'ls-files', '*package.json'], root) or 'package.json').splitlines()
    for pj in pkgs[:60]:
        j = load_json_loose(os.path.join(root, pj))
        if isinstance(j, dict):
            for sec in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
                deps.update((j.get(sec) or {}).keys())
            if j.get('name'):
                deps.add(j['name'])
    stems = {}
    for f in fileset:
        st = os.path.splitext(f)[0]
        stems[st] = f
        if os.path.basename(st) == 'index':
            stems.setdefault(os.path.dirname(st), f)
    CTX.update({'aliases': aliases, 'base_url': base_url, 'deps': deps, 'stems': stems})


def try_stem(stem, fileset):
    stem = stem.replace('\\', '/')
    cands = [stem] + [stem + e for e in JS_EXT] + [stem + '/index' + e for e in JS_EXT]
    m = re.match(r'(.*)\.(m?jsx?|cjs)$', stem)  # ESM-style "./x.js" that points at x.ts
    if m:
        cands += [m.group(1) + e for e in JS_EXT]
    for c in cands:
        if c in fileset:
            return c
    return None


def resolve(spec, from_path, fileset, is_py):
    if is_py:
        if spec.startswith('.'):
            dots = len(spec) - len(spec.lstrip('.'))
            base = os.path.dirname(from_path)
            for _ in range(dots - 1):
                base = os.path.dirname(base)
            rest = spec.lstrip('.').replace('.', '/')
            stem = os.path.join(base, rest) if rest else base
        else:
            stem = spec.replace('.', '/')
        for c in (stem + '.py', stem + '/__init__.py'):
            c = c.replace('\\', '/')
            if c in fileset:
                return c
        return None
    if spec.startswith('.'):
        return try_stem(os.path.normpath(os.path.join(os.path.dirname(from_path), spec)), fileset)
    for pat, targets in CTX['aliases']:
        if pat.endswith('*'):
            pre = pat[:-1]
            if spec.startswith(pre):
                rest = spec[len(pre):]
                for t in targets:
                    r = try_stem(t.replace('*', rest), fileset)
                    if r:
                        return r
        elif spec == pat:
            for t in targets:
                r = try_stem(t, fileset)
                if r:
                    return r
    if spec.startswith(('@/', '~/', '#/')):
        for pre in ('src', 'app', ''):
            r = try_stem(os.path.join(pre, spec[2:]), fileset)
            if r:
                return r
    if package_name(spec) in CTX['deps']:
        return None
    bu = CTX['base_url']
    r = try_stem(os.path.join(bu, spec), fileset) if bu else None
    if r:
        return r
    if spec[0] in '@~#':  # alias-looking, config not found: unique suffix match, at least 2 path segments
        parts = spec.lstrip('@~#/').split('/')
        for k in range(len(parts) - 1):
            t = '/'.join(parts[k:])
            hits = [f for s, f in CTX['stems'].items() if s == t or s.endswith('/' + t)]
            if len(hits) == 1:
                return hits[0]
    return None


def package_name(spec):
    if spec.startswith('@'):
        return '/'.join(spec.split('/')[:2])
    return spec.split('/')[0]


IDENT_RES = [
    re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)'),
    re.compile(r'^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)'),
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[:=]'),
    re.compile(r'^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)'),
    re.compile(r'^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)'),
    re.compile(r'^\s*class\s+([A-Za-z_]\w*)'),
]


def new_identifiers(added_lines):
    seen, out = set(), []
    for ln, text in added_lines:
        for r in IDENT_RES:
            m = r.match(text)
            if m and m.group(1) not in seen:
                name = m.group(1)
                seen.add(name)
                smell = None
                if name.lower() in GENERIC_NAMES:
                    smell = 'generic name'
                elif VAGUE_SUFFIX_RE.search(name) and len(name) > len('Helper'):
                    smell = 'vague suffix'
                elif len(name) > 32:
                    smell = 'very long'
                out.append({'name': name, 'line': ln, 'smell': smell})
                break
    return out[:30]


def scan_security(path, added_lines, kind):
    findings = []
    for ln, text in added_lines:
        if len(text) > 600:
            continue
        for rid, sev, rx, msg in SEC_RULES:
            if rx.search(text):
                s = sev
                if kind == 'test' and sev == 'high':
                    s = 'low'
                if rid in ('new-permission',) and not re.search(r'AndroidManifest|Info\.plist', path):
                    continue
                findings.append({'file': path, 'line': ln, 'severity': s, 'rule': rid, 'message': msg,
                                 'snippet': text.strip()[:140]})
    return findings


def dependency_changes(root, base, files):
    added, removed, changed = [], [], []
    for f in files:
        if os.path.basename(f['path']) == 'package.json' and f['status'] != 'deleted':
            new_txt = read_file(root, f['path'])
            old_txt = run(['git', 'show', f'{base}:{f["old_path"]}'], root) if base else None
            try:
                new = json.loads(new_txt) if new_txt else {}
            except ValueError:
                new = {}
            try:
                old = json.loads(old_txt) if old_txt else {}
            except ValueError:
                old = {}
            if new or old:
                for sec in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
                    n, o = new.get(sec, {}), old.get(sec, {})
                    for k, v in n.items():
                        if k not in o:
                            added.append({'name': k, 'version': v, 'section': sec, 'file': f['path']})
                        elif o[k] != v:
                            changed.append({'name': k, 'from': o[k], 'to': v, 'section': sec, 'file': f['path']})
                    for k, v in o.items():
                        if k not in n:
                            removed.append({'name': k, 'version': v, 'section': sec, 'file': f['path']})
            else:
                for ln, text in f['added_lines']:
                    m = re.match(r'\s*"([^"]+)"\s*:\s*"([\^~<>=*\w.\-]+)"\s*,?\s*$', text)
                    if m and m.group(1) not in ('name', 'version', 'main', 'license', 'description'):
                        added.append({'name': m.group(1), 'version': m.group(2), 'section': 'unknown', 'file': f['path']})
        elif re.search(r'requirements[^/]*\.txt$', f['path']):
            for ln, text in f['added_lines']:
                m = re.match(r'\s*([A-Za-z0-9_.\-]+)\s*([=<>~!]=?[^\s#]*)?', text)
                if m and not text.strip().startswith('#'):
                    added.append({'name': m.group(1), 'version': m.group(2) or '*', 'section': 'requirements', 'file': f['path']})
    return added, removed, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base')
    ap.add_argument('--staged', action='store_true')
    ap.add_argument('--worktree', action='store_true')
    ap.add_argument('--diff-file')
    ap.add_argument('--out', default='facts.json')
    args = ap.parse_args()

    root = repo_root()
    diff_text, mode, base = get_diff(args, root)
    disp_text, _m, _b = get_diff(args, root, 3)
    blocks = split_blocks(disp_text or diff_text)
    files = parse_diff(diff_text)
    if not files:
        print('No changes found. Try --base <ref>, --staged, --worktree or --diff-file.', file=sys.stderr)
        sys.exit(2)

    repo_files = list_repo_files(root)
    fileset = set(repo_files)
    changed_paths = {f['path'] for f in files}
    for f in files:
        f['kind'] = kind_of(f['path'])
        if f['kind'] == 'source':
            fileset.add(f['path']) if f['status'] != 'deleted' else None

    # forward imports for the whole repo -> reverse map
    reverse = collections.defaultdict(set)
    external = collections.defaultdict(set)
    forward = {}
    load_context(root, fileset)
    unresolved = collections.defaultdict(set)
    for rel in sorted(fileset):
        txt = read_file(root, rel)
        if txt is None:
            continue
        is_py = rel.endswith('.py')
        outs = []
        for spec in extract_imports(rel, txt):
            tgt = resolve(spec, rel, fileset, is_py)
            if tgt and tgt != rel:
                outs.append(tgt)
                reverse[tgt].add(rel)
            elif not is_py and not ASSET_SPEC_RE.search(spec):
                if spec.startswith('.') or (spec[0] in '~#@' and package_name(spec) not in CTX['deps']):
                    unresolved[rel].add(spec)
                else:
                    external[rel].add(package_name(spec))
        forward[rel] = outs

    # per-file facts
    security = []
    for f in files:
        p = f['path']
        # fall back to added lines when the file is not on disk (patch-file mode)
        if p not in forward and f['kind'] == 'source' and f['status'] != 'deleted':
            outs = []
            for spec in extract_imports(p, '\n'.join(t for _, t in f['added_lines'])):
                tgt = resolve(spec, p, fileset, p.endswith('.py'))
                if tgt:
                    outs.append(tgt)
                    reverse[tgt].add(p)
            forward[p] = outs
        f['imports'] = sorted(set(forward.get(p, [])))
        f['external_imports'] = sorted(external.get(p, []))
        f['imported_by'] = sorted(reverse.get(p, []))
        f['imports_in_change'] = [x for x in f['imports'] if x in changed_paths]
        f['imported_by_in_change'] = [x for x in f['imported_by'] if x in changed_paths]
        f['new_identifiers'] = new_identifiers(f['added_lines']) if f['kind'] == 'source' else []
        f['findings'] = scan_security(p, f['added_lines'], f['kind'])
        security.extend(f['findings'])

        reasons, pts = [], 0
        m = SENSITIVE_RE.search(p)
        if m and f['kind'] not in ('docs', 'asset', 'lock'):
            reasons.append(f'sensitive area: "{m.group(0).lower()}" in path')
            pts += 3
        highs = [x for x in f['findings'] if x['severity'] == 'high']
        meds = [x for x in f['findings'] if x['severity'] == 'medium']
        if highs:
            reasons.append(f'{len(highs)} high-severity finding(s)')
            pts += 3
        if meds:
            reasons.append(f'{len(meds)} medium-severity finding(s)')
            pts += 2
        if f['status'] == 'deleted' and f['kind'] == 'source':
            reasons.append('file deleted')
            pts += 2
        if f['status'] == 'added' and f['adds'] > 150 and f['kind'] == 'source':
            reasons.append(f'large new file ({f["adds"]} lines)')
            pts += 1
        if f['adds'] + f['dels'] > 250 and f['kind'] == 'source':
            reasons.append('large change')
            pts += 1
        if f['kind'] == 'config' and not LOCK_RE.search(p):
            reasons.append('config / build / CI file')
            pts += 2
        if f['kind'] == 'source' and len(f['imported_by']) >= 8:
            reasons.append(f'wide blast radius ({len(f["imported_by"])} importers)')
            pts += 2
        if f['kind'] in ('docs', 'asset', 'lock') and not highs:
            pts = 0
        if f['kind'] == 'test' and not highs and not meds:
            pts = min(pts, 1)
        f['risk_points'] = pts
        f['risk'] = 'red' if pts >= 4 else 'yellow' if pts >= 2 else 'green'
        f['risk_reasons'] = reasons
        if f['kind'] == 'source':
            if ENTRY_NAME_RE.search(p):
                f['entry_hint'] = 'conventional entry file name'
            elif not f['imported_by']:
                f['entry_hint'] = 'imported by nothing in the repo (entry point, route, or dead code)'
            else:
                f['entry_hint'] = None
        else:
            f['entry_hint'] = None
        f['symbol_count'] = len(f['new_identifiers'])
        f['unresolved_imports'] = sorted(unresolved.get(p, []))[:8]
        dl = blocks.get(p, [])
        if f['kind'] == 'lock':
            f['diff'], f['diff_truncated'] = [], len(dl)
        else:
            f['diff'], f['diff_truncated'] = dl[:MAX_DIFF_LINES], max(0, len(dl) - MAX_DIFF_LINES)
        del f['added_lines']  # keep facts.json small

    by_path = {f['path']: f for f in files}
    sources = [f for f in files if f['kind'] == 'source' and f['status'] != 'deleted']

    # reading order: roots first, then follow imports (BFS)
    roots = [f for f in sources if not f['imported_by_in_change']]
    roots.sort(key=lambda f: (0 if (f['entry_hint'] or not f['imported_by']) else 1, -(f['adds'] + f['dels'])))
    order, seen = [], set()
    queue = collections.deque(r['path'] for r in roots)
    while queue:
        p = queue.popleft()
        if p in seen:
            continue
        seen.add(p)
        order.append(p)
        for q in by_path[p]['imports_in_change']:
            if q not in seen:
                queue.append(q)
    for f in sources:
        if f['path'] not in seen:
            order.append(f['path'])
            seen.add(f['path'])
    for kind in ('config', 'other', 'asset', 'docs', 'lock', 'test'):
        for f in files:
            if f['kind'] == kind and f['path'] not in seen:
                order.append(f['path'])
                seen.add(f['path'])
    for f in files:
        if f['path'] not in seen:
            order.append(f['path'])
    entry_points = [r['path'] for r in roots]

    # graph (changed files + a few affected importers)
    nodes, edges, node_ids = [], [], {}

    def nid(p, changed):
        if p not in node_ids:
            node_ids[p] = f'n{len(node_ids)}'
            nodes.append({'id': node_ids[p], 'path': p, 'changed': changed,
                          'risk': by_path[p]['risk'] if p in by_path else None,
                          'adds': by_path[p]['adds'] if p in by_path else 0,
                          'dels': by_path[p]['dels'] if p in by_path else 0,
                          'status': by_path[p]['status'] if p in by_path else 'unchanged'})
        return node_ids[p]

    for f in sources + [x for x in files if x['kind'] == 'test']:
        nid(f['path'], True)
    for f in files:
        if f['kind'] in ('source', 'test') and f['path'] in node_ids:
            for q in f['imports']:
                if q in changed_paths and q in node_ids:
                    edges.append([node_ids[f['path']], node_ids[q], 'solid'])
    affected = 0
    for f in sources:
        extra = [x for x in f['imported_by'] if x not in changed_paths][:3]
        for x in extra:
            if affected >= 25:
                break
            edges.append([nid(x, False), node_ids[f['path']], 'dashed'])
            affected += 1

    add_deps, rem_deps, chg_deps = dependency_changes(root, base, files)

    # score
    total_adds = sum(f['adds'] for f in files if f['kind'] != 'lock')
    total_dels = sum(f['dels'] for f in files if f['kind'] != 'lock')
    churn = total_adds + total_dels
    breakdown = []
    score = 10.0

    def deduct(label, d, key=None, n=None):
        nonlocal score
        if d:
            breakdown.append({'label': label, 'key': key, 'n': n, 'delta': -round(d, 1)})
            score -= d

    deduct(f'Size: {churn} changed lines (lockfiles excluded)', 0 if churn <= 200 else 1 if churn <= 500 else 2 if churn <= 1000 else 3, 'size', churn)
    highs = [x for x in security if x['severity'] == 'high']
    meds = [x for x in security if x['severity'] == 'medium']
    deduct(f'Security: {len(highs)} high finding(s)', min(4, 2 * len(highs)), 'sec_high', len(highs))
    deduct(f'Security: {len(meds)} medium finding(s)', min(2, len(meds)), 'sec_med', len(meds))
    reds = [f for f in files if f['risk'] == 'red']
    deduct(f'{len(reds)} red-risk file(s)', min(2, len(reds)), 'red', len(reds))
    deduct(f'{len(add_deps)} new dependenc{"y" if len(add_deps) == 1 else "ies"}', min(1.5, 0.5 * len(add_deps)), 'deps', len(add_deps))
    src_churn = sum(f['adds'] + f['dels'] for f in files if f['kind'] == 'source')
    has_tests = any(f['kind'] == 'test' for f in files)
    if src_churn > 50 and not has_tests:
        deduct('No test files changed alongside >50 changed source lines', 1, 'no_tests', src_churn)
    lows = [x for x in security if x['rule'] in ('ts-ignore', 'as-any')]
    if len(lows) >= 5:
        deduct(f'{len(lows)} type/lint suppressions added', 0.5, 'suppress', len(lows))
    score = max(1.0, round(score, 1))
    grade_key = 'low' if score >= 8 else 'moderate' if score >= 6 else 'high' if score >= 4 else 'very_high'
    grade = grade_key.replace('_', ' ') + ' review risk'

    facts = {
        'meta': {'mode': mode, 'base': base, 'root': root,
                 'generated': datetime.datetime.now().isoformat(timespec='seconds'),
                 'note': 'Static heuristics (regex), not an AST or a security audit. Findings are leads for a human.'},
        'totals': {'files': len(files), 'added': total_adds, 'deleted': total_dels,
                   'source_files': len(sources), 'test_files': sum(1 for f in files if f['kind'] == 'test')},
        'risk_summary': {c: sum(1 for f in files if f['risk'] == c) for c in ('red', 'yellow', 'green')},
        'score': {'value': score, 'out_of': 10, 'grade': grade, 'grade_key': grade_key, 'breakdown': breakdown},
        'entry_points': entry_points,
        'reading_order': order,
        'files': files,
        'graph': {'nodes': nodes, 'edges': edges,
                  'solid_edges': sum(1 for x in edges if x[2] == 'solid'),
                  'unresolved_total': sum(len(v) for v in unresolved.values() if v),
                  'unresolved_examples': sorted({s for p in changed_paths for s in unresolved.get(p, [])})[:6]},
        'dependencies': {'added': add_deps, 'removed': rem_deps, 'changed': chg_deps},
        'security': sorted(security, key=lambda x: {'high': 0, 'medium': 1, 'low': 2}[x['severity']]),
    }
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(facts, fh, indent=2, ensure_ascii=False)
    print(f'facts -> {args.out} | {len(files)} files, +{total_adds}/-{total_dels}, '
          f'score {score}/10 ({grade}), security: {len(highs)} high / {len(meds)} medium')


if __name__ == '__main__':
    main()
