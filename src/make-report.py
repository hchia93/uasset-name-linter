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
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

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
    rel = cfg.get('output', 'path', fallback='Saved/Tools/UAssetNameLinter')
    return (project_root / rel).resolve()


def read_export(out_dir):
    """Return {name: [paths]}."""
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read(out_dir / 'export.ini', encoding='utf-8')
    name_to_paths = {}
    if cfg.has_section('paths'):
        for name in cfg.options('paths'):
            paths = [p.strip() for p in cfg.get('paths', name).split(',') if p.strip()]
            name_to_paths[name] = paths
    return name_to_paths


def read_violations(out_dir):
    """Return list of (name, reason, suggestion_or_None, is_tbd)."""
    cfg = configparser.ConfigParser(allow_no_value=True)
    cfg.optionxform = str
    cfg.read(out_dir / 'violation.ini', encoding='utf-8')
    out = []
    for section in cfg.sections():
        is_tbd = section.startswith('TBD: ')
        reason = section[5:] if is_tbd else section
        for name in cfg.options(section):
            value = cfg.get(section, name)
            suggestion = value if value else None
            out.append((name, reason, suggestion, is_tbd))
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
  h2 { border-bottom: 1px solid #ccc; padding-bottom: 0.2em; margin-top: 2em; }
  h3 { color: #444; margin-top: 1.5em; }
  table { border-collapse: collapse; margin: 1em 0; }
  th, td { border: 1px solid #ccc; padding: 0.4em 0.8em; text-align: left; }
  th { background: #f0f0f0; }
  td.num { text-align: right; }
  ul { list-style: none; padding-left: 0; }
  li { margin: 0.2em 0; font-family: Consolas, Menlo, monospace; font-size: 0.9em; }
  .arrow { color: #888; }
  .suggest { color: #060; }
  .tbd { background: #fff8c5; padding: 0.1em 0.4em; border-radius: 3px; font-size: 0.8em; color: #886000; }
  .nofix { color: #888; font-style: italic; }
</style>
</head>
<body>
'''

HTML_FOOTER = '</body>\n</html>\n'


def render_report(out_dir, project_root, name_to_paths, violations, authors):
    by_author = defaultdict(list)
    by_reason = defaultdict(int)
    by_dir = defaultdict(int)
    tbd_total = 0
    violation_total = 0

    for name, reason, sugg, is_tbd in violations:
        paths = name_to_paths.get(name, [])
        if not paths:
            continue
        for p in paths:
            author = authors.get(p, '(unknown)')
            by_author[author].append((name, p, reason, sugg, is_tbd))
            by_reason[reason] += 1
            parent = '/'.join(p.split('/')[:-1])
            by_dir[parent] += 1
            if is_tbd:
                tbd_total += 1
            else:
                violation_total += 1

    h = []
    h.append(HTML_HEADER)
    h.append(f'<h1>uasset-name-linter Report</h1>')
    h.append(f'<p><em>Generated: {date.today().isoformat()}</em></p>')

    h.append('<h2>Summary</h2>')
    h.append('<table>')
    h.append(f'<tr><th>Confirmed violations</th><td class="num">{violation_total}</td></tr>')
    h.append(f'<tr><th>TBD (pending decision)</th><td class="num">{tbd_total}</td></tr>')
    h.append(f'<tr><th>Authors involved</th><td class="num">{len([a for a in by_author if a != "(unknown)"])}</td></tr>')
    h.append('</table>')

    h.append('<h2>Violations by Author</h2>')
    h.append('<table><tr><th>Author</th><th>Files</th></tr>')
    for author in sorted(by_author.keys(), key=lambda a: (-len(by_author[a]), a)):
        h.append(f'<tr><td>{html.escape(author)}</td><td class="num">{len(by_author[author])}</td></tr>')
    h.append('</table>')

    h.append('<h2>Violations by Reason</h2>')
    h.append('<table><tr><th>Reason</th><th>Count</th></tr>')
    for reason, c in sorted(by_reason.items(), key=lambda x: (-x[1], x[0])):
        h.append(f'<tr><td>{html.escape(reason)}</td><td class="num">{c}</td></tr>')
    h.append('</table>')

    h.append('<h2>Top 20 Dirty Directories</h2>')
    h.append('<table><tr><th>Directory</th><th>Violations</th></tr>')
    for d, c in sorted(by_dir.items(), key=lambda x: (-x[1], x[0]))[:20]:
        h.append(f'<tr><td><code>{html.escape(d)}</code></td><td class="num">{c}</td></tr>')
    h.append('</table>')

    h.append('<h2>Per-Author Action Lists</h2>')
    for author in sorted(by_author.keys(), key=lambda a: (-len(by_author[a]), a)):
        items = by_author[author]
        h.append(f'<h3>{html.escape(author)} ({len(items)})</h3>')
        sub_by_reason = defaultdict(list)
        for name, path, reason, sugg, is_tbd in items:
            sub_by_reason[reason].append((name, path, sugg, is_tbd))
        for reason in sorted(sub_by_reason.keys()):
            sub = sub_by_reason[reason]
            h.append(f'<p><strong>{html.escape(reason)}</strong> ({len(sub)})</p>')
            h.append('<ul>')
            for name, path, sugg, is_tbd in sorted(sub):
                tbd_label = ' <span class="tbd">TBD</span>' if is_tbd else ''
                if sugg:
                    h.append(f'<li><code>{html.escape(path)}</code>{tbd_label} '
                             f'<span class="arrow">&rarr;</span> '
                             f'<code class="suggest">{html.escape(sugg)}</code></li>')
                else:
                    h.append(f'<li><code>{html.escape(path)}</code>{tbd_label} '
                             f'<span class="nofix">(needs human)</span></li>')
            h.append('</ul>')

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
    name_to_paths = read_export(out_dir)
    violations = read_violations(out_dir)
    print(f'  {len(violations)} entries')

    print('Querying SVN for authorship ...')
    authors = get_svn_authors(project_root)
    print(f'  {len(authors)} files indexed')

    render_report(out_dir, project_root, name_to_paths, violations, authors)
    print(f'Report written: {out_dir / "report.html"}')


if __name__ == '__main__':
    main()
