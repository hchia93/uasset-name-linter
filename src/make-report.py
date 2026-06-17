#!/usr/bin/env python3
# make-report.py
#
# Reads validator outputs (export.ini, violation.ini), queries the VCS
# for last-modified author per violating file, and writes a team-facing
# HTML report.
#
# Currently supports SVN. Git support is planned.

import argparse
import configparser
import html
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rules

SCRIPT_DIR  = Path(__file__).parent
TOOL_ROOT   = SCRIPT_DIR.parent
CONFIG_FILE = TOOL_ROOT / 'Config' / 'config.ini'


def find_project_root_from(start: Path):
    cur = start.resolve()
    for _ in range(10):
        if any(cur.glob('*.uproject')):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def load_config():
    cfg = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        cfg.read(CONFIG_FILE, encoding='utf-8')
    return cfg


def resolve_project_root(cli_root, cfg):
    if cli_root:
        return Path(cli_root).resolve()
    if cfg.has_option('paths', 'project_root'):
        return Path(cfg.get('paths', 'project_root')).resolve()
    return find_project_root_from(SCRIPT_DIR)


def resolve_output_dir(project_root, cfg):
    rel = cfg.get('output', 'path', fallback='Saved/UAssetNameLinter')
    return (project_root / rel).resolve()


def read_export(out_dir):
    """Return (name_to_paths, meta, ignored_dirs, ignored_assets)."""
    cfg = configparser.ConfigParser(allow_no_value=True)
    cfg.optionxform = str
    cfg.read(out_dir / 'export.ini', encoding='utf-8')
    name_to_paths = {}
    if cfg.has_section('paths'):
        for name in cfg.options('paths'):
            paths = [p.strip() for p in cfg.get('paths', name).split(',') if p.strip()]
            name_to_paths[name] = paths
    meta = {}
    if cfg.has_section('meta'):
        for k in cfg.options('meta'):
            meta[k] = cfg.get('meta', k)
    ignored_dirs = list(cfg.options('ignored_dirs')) if cfg.has_section('ignored_dirs') else []
    ignored_assets = list(cfg.options('ignored_assets')) if cfg.has_section('ignored_assets') else []
    return name_to_paths, meta, ignored_dirs, ignored_assets


_SECTION_RE = re.compile(r'^(?:TBD:\s*)?(r\d+):\s*(.+)$')


def _parse_section(section):
    """Return (reason_id, reason_text, is_tbd) from a section name like
    'r5: lowercase token start' or 'TBD: r13: leading digit token after prefix'."""
    is_tbd = section.startswith('TBD: ')
    m = _SECTION_RE.match(section)
    if m:
        return m.group(1), m.group(2), is_tbd
    rest = section[5:] if is_tbd else section
    return '?', rest, is_tbd


def read_violations(out_dir):
    """Return list of (name, reason_id, reason_text, suggestion_or_None, is_tbd)."""
    cfg = configparser.ConfigParser(allow_no_value=True)
    cfg.optionxform = str
    cfg.read(out_dir / 'violation.ini', encoding='utf-8')
    out = []
    for section in cfg.sections():
        rid, rtext, is_tbd = _parse_section(section)
        for name in cfg.options(section):
            value = cfg.get(section, name)
            suggestion = value if value else None
            out.append((name, rid, rtext, suggestion, is_tbd))
    return out


def get_svn_authors(project_root):
    """Run svn ls --xml -R Content and return {full_path: author}."""
    try:
        out = subprocess.check_output(
            ['svn', 'ls', '--xml', '-R', 'Content'],
            text=True, encoding='utf-8', errors='replace',
            cwd=str(project_root)
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    root = ET.fromstring(out)
    authors = {}
    for entry in root.findall('.//entry'):
        if entry.get('kind') != 'file':
            continue
        name_el = entry.find('name')
        commit_el = entry.find('commit')
        if name_el is None or commit_el is None:
            continue
        author_el = commit_el.find('author')
        if author_el is None:
            continue
        rel = name_el.text.replace('\\', '/')
        authors[f'Content/{rel}'] = author_el.text
    return authors


HTML_HEADER = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>uasset-name-linter Report</title>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; max-width: 1200px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { border-bottom: 2px solid #444; padding-bottom: 0.3em; }
  h1 code { background: #f0f0f0; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.9em; }
  h2 { border-bottom: 1px solid #ccc; padding-bottom: 0.2em; margin-top: 2em; }
  h3 { color: #444; margin: 0; display: inline; }
  .header-meta { color: #555; margin: 0.4em 0; }
  table { border-collapse: collapse; margin: 1em 0; }
  th, td { border: 1px solid #ccc; padding: 0.4em 0.8em; text-align: left; vertical-align: top; }
  th { background: #f0f0f0; }
  td.num { text-align: right; }
  td.rid { font-family: Consolas, Menlo, monospace; color: #555; }
  td.rank { text-align: center; font-size: 1.3em; line-height: 1; width: 2em; }
  details.ignored { margin: 0.4em 0; }
  details.ignored > summary { cursor: pointer; padding: 0.3em 0; font-weight: 600; color: #555; }
  details.ignored > summary:hover { background: #f6f6f6; }
  details.ignored > .scroll-box {
    max-height: 320px;
    overflow-y: auto;
    border: 1px solid #ddd;
    background: #fafafa;
    padding: 0.5em 1em;
    margin: 0.3em 0;
  }
  details.ignored .scroll-box ul { padding-left: 0; }
  details.ignored .scroll-box li { margin: 0.1em 0; }
  ul { list-style: none; padding-left: 1em; }
  li { margin: 0.2em 0; font-family: Consolas, Menlo, monospace; font-size: 0.9em; }
  .arrow { color: #888; }
  .suggest { color: #060; }
  .tbd { background: #fff8c5; padding: 0.1em 0.4em; border-radius: 3px; font-size: 0.8em; color: #886000; }
  .nofix { color: #888; font-style: italic; }
  details.author { margin: 1em 0; border-left: 3px solid #ddd; padding-left: 1em; }
  details.author > summary { cursor: pointer; padding: 0.4em 0; font-weight: 600; list-style: revert; }
  details.author > summary:hover { background: #f6f6f6; }
  .reason-block { margin: 0.6em 0 0.6em 0.5em; }
  .reason-block .rid { color: #888; font-family: Consolas, Menlo, monospace; font-size: 0.85em; margin-right: 0.4em; }
</style>
</head>
<body>
'''

HTML_FOOTER = '</body>\n</html>\n'


def _r_sort_key(rid: str):
    if rid and rid.startswith('r'):
        try:
            return (0, int(rid[1:]))
        except ValueError:
            pass
    return (1, rid or '')


def render_report(out_dir, project_root, name_to_paths, meta, ignored_dirs_param, ignored_assets_param, violations, authors):
    by_author = defaultdict(list)
    reason_count = defaultdict(int)        # rid -> total count
    reason_text_lookup = {}                # rid -> text
    by_dir = defaultdict(int)

    for name, rid, rtext, sugg, is_tbd in violations:
        reason_text_lookup[rid] = rtext
        paths = name_to_paths.get(name, [])
        if not paths:
            continue
        for p in paths:
            author = authors.get(p, '(unknown)')
            by_author[author].append((name, p, rid, rtext, sugg, is_tbd))
            reason_count[rid] += 1
            parent = '/'.join(p.split('/')[:-1])
            by_dir[parent] += 1

    # Pull stats from meta (validator-authoritative)
    total_paths    = int(meta.get('total_paths', 0))
    ignored_assets = int(meta.get('ignored_assets', 0))
    ignored_dirs   = int(meta.get('ignored_dirs', 0))
    verified_n     = int(meta.get('verified', 0))
    violation_n    = int(meta.get('violation', 0))
    pending_n      = int(meta.get('pending', 0))
    generated_at   = meta.get('generated_at', '')
    classified_total = verified_n + violation_n + pending_n
    # Lists referenced inside the function
    ignored_dirs_list = ignored_dirs_param
    ignored_assets_list = ignored_assets_param

    def pct(n, total):
        return f'{(n / total * 100):.1f}%' if total else '0.0%'

    h = []
    h.append(HTML_HEADER)
    h.append('<h1><code>.uasset</code> Name Linter Report</h1>')
    h.append(f'<p class="header-meta">Generated: {html.escape(generated_at)}</p>')
    h.append(f'<p class="header-meta">Total Scanned: <strong>{total_paths}</strong> assets.</p>')
    h.append(f'<p class="header-meta">Ignored: <strong>{ignored_assets}</strong> assets and '
             f'<strong>{ignored_dirs}</strong> directories.</p>')

    h.append('<details class="ignored"><summary>Ignored Directories ({})</summary>'.format(len(ignored_dirs_list)))
    h.append('<div class="scroll-box"><ul>')
    for d in ignored_dirs_list:
        h.append(f'<li><code>{html.escape(d)}</code></li>')
    h.append('</ul></div></details>')

    h.append('<details class="ignored"><summary>Ignored Assets ({})</summary>'.format(len(ignored_assets_list)))
    h.append('<div class="scroll-box"><ul>')
    for a in ignored_assets_list:
        h.append(f'<li><code>{html.escape(a)}</code></li>')
    h.append('</ul></div></details>')

    h.append('<h2>Summary</h2>')
    h.append('<table>')
    h.append(f'<tr><th>Verified</th><td class="num">{verified_n} ({pct(verified_n, classified_total)})</td></tr>')
    h.append(f'<tr><th>Confirmed violations</th><td class="num">{violation_n} ({pct(violation_n, classified_total)})</td></tr>')
    h.append(f'<tr><th>TBD (pending decision)</th><td class="num">{pending_n} ({pct(pending_n, classified_total)})</td></tr>')
    h.append('</table>')

    h.append('<h2>Violations by Author</h2>')
    h.append('<table><tr><th></th><th>Author</th><th>Files</th></tr>')
    sorted_authors = sorted(by_author.keys(), key=lambda a: (-len(by_author[a]), a))
    for idx, author in enumerate(sorted_authors):
        if idx == 0:
            rank_cell = '<td class="rank">&#129351;</td>'   # gold medal
        elif idx == 1:
            rank_cell = '<td class="rank">&#129352;</td>'   # silver medal
        elif idx == 2:
            rank_cell = '<td class="rank">&#129353;</td>'   # bronze medal
        else:
            rank_cell = '<td class="rank">&#129768;</td>'   # shaking / distorted face
        h.append(f'<tr>{rank_cell}<td>{html.escape(author)}</td>'
                 f'<td class="num">{len(by_author[author])}</td></tr>')
    h.append('</table>')

    h.append('<h2>Violations by Reason</h2>')
    h.append('<table><tr><th>ID</th><th>Reason</th><th>Count</th></tr>')
    for rid in sorted(reason_count.keys(), key=_r_sort_key):
        h.append(f'<tr><td class="rid">{html.escape(rid)}</td>'
                 f'<td>{html.escape(reason_text_lookup.get(rid, ""))}</td>'
                 f'<td class="num">{reason_count[rid]}</td></tr>')
    h.append('</table>')

    h.append('<h2>Top 20 Dirty Directories</h2>')
    h.append('<table><tr><th>Directory</th><th>Violations</th></tr>')
    for d, c in sorted(by_dir.items(), key=lambda x: (-x[1], x[0]))[:20]:
        h.append(f'<tr><td><code>{html.escape(d)}</code></td><td class="num">{c}</td></tr>')
    h.append('</table>')

    h.append('<h2>Per-Author Action Lists</h2>')
    h.append('<p><em>Click an author name to expand or collapse.</em></p>')
    for author in sorted(by_author.keys(), key=lambda a: (-len(by_author[a]), a)):
        items = by_author[author]
        h.append(f'<details class="author" open><summary><h3>{html.escape(author)} ({len(items)})</h3></summary>')
        sub_by_reason = defaultdict(list)
        for name, path, rid, rtext, sugg, is_tbd in items:
            sub_by_reason[rid].append((name, path, rtext, sugg, is_tbd))
        for rid in sorted(sub_by_reason.keys(), key=_r_sort_key):
            sub = sub_by_reason[rid]
            rtext = sub[0][2]
            h.append(f'<div class="reason-block"><p><span class="rid">[{html.escape(rid)}]</span>'
                     f'<strong>{html.escape(rtext)}</strong> ({len(sub)})</p>')
            h.append('<ul>')
            for name, path, _rtext, sugg, is_tbd in sorted(sub):
                tbd_label = ' <span class="tbd">TBD</span>' if is_tbd else ''
                if sugg:
                    h.append(f'<li><code>{html.escape(path)}</code>{tbd_label} '
                             f'<span class="arrow">&rarr;</span> '
                             f'<code class="suggest">{html.escape(sugg)}</code></li>')
                else:
                    h.append(f'<li><code>{html.escape(path)}</code>{tbd_label} '
                             f'<span class="nofix">(needs human)</span></li>')
            h.append('</ul></div>')
        h.append('</details>')

    h.append(HTML_FOOTER)
    (out_dir / 'report.html').write_text(''.join(h), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project-root', help='Override project root (default: auto-detect)')
    args = ap.parse_args()

    cfg = load_config()
    project_root = resolve_project_root(args.project_root, cfg)
    if not project_root:
        sys.stderr.write('ERROR: could not locate project root.\n')
        sys.exit(2)

    out_dir = resolve_output_dir(project_root, cfg)
    if not (out_dir / 'export.ini').exists():
        sys.stderr.write(f'ERROR: {out_dir / "export.ini"} not found. Run validator.py first.\n')
        sys.exit(2)

    print(f'Reading {out_dir} ...')
    name_to_paths, meta, ignored_dirs_list, ignored_assets_list = read_export(out_dir)
    violations = read_violations(out_dir)
    print(f'  {len(violations)} entries')

    print('Querying SVN for authorship ...')
    authors = get_svn_authors(project_root)
    print(f'  {len(authors)} files indexed')

    render_report(out_dir, project_root, name_to_paths, meta,
                  ignored_dirs_list, ignored_assets_list, violations, authors)
    print(f'Report written: {out_dir / "report.html"}')


if __name__ == '__main__':
    main()
