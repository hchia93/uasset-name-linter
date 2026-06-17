#!/usr/bin/env python3
# validator.py
#
# Crawl <project>/Content/ for all .uasset/.umap names, classify with rules
# from rules.py, and write export/verified/violation INI buckets.
#
# Idempotent: each run is a full re-fetch and re-classify, no persisted state.
#
# Project root resolution:
#   1. --project-root CLI flag (highest priority)
#   2. [paths] project_root in Config/config.ini
#   3. Auto-detect: walk up from this script looking for a *.uproject file
#
# Output location resolution:
#   [output] path in Config/config.ini, joined to project root.
#   Default: Saved/UAssetNameLinter/

import argparse
import configparser
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import rules

SCRIPT_DIR    = Path(__file__).parent
TOOL_ROOT     = SCRIPT_DIR.parent
CONFIG_FILE   = TOOL_ROOT / 'Config' / 'config.ini'
IGNORE_FILE   = TOOL_ROOT / 'rules' / 'ignores.ini'

ASSET_EXTS = {'.uasset', '.umap'}

# UE-convention paths/files that are always skipped, regardless of ignores.ini.
# These exist in every UE project and are not user-controlled naming.
ALWAYS_SKIP_DIR_SUBSTRINGS = ('__External', '/Splash/')
ALWAYS_SKIP_FILES = {'ProjectThumbnail.uasset'}


def find_project_root_from(start: Path):
    """Walk up from start looking for *.uproject. Return Path or None."""
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
    detected = find_project_root_from(SCRIPT_DIR)
    if detected:
        return detected
    return None


def resolve_output_dir(project_root, cfg):
    rel = cfg.get('output', 'path', fallback='Saved/UAssetNameLinter')
    return (project_root / rel).resolve()


def load_ignore_patterns():
    if not IGNORE_FILE.exists():
        return []
    out = []
    for line in IGNORE_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            out.append(line.replace('\\', '/'))
    return out


def _list_assets_in_tree(top, project_root):
    out = []
    for r, _d, fs in os.walk(top):
        rel_inner = os.path.relpath(r, project_root).replace('\\', '/')
        for f in fs:
            if Path(f).suffix.lower() in ASSET_EXTS:
                out.append(f'{rel_inner}/{f}')
    return out


def crawl_assets(content_dir, project_root, ignore_patterns):
    """Walk content_dir and partition into kept assets vs ignored lists.
    Returns (assets, ignored_asset_paths, ignored_dir_paths).
    assets is a list of (stem, rel_path) tuples; ignored lists are sorted."""
    assets = []
    ignored_asset_paths = []
    ignored_dir_paths = []

    for root, dirs, files in os.walk(content_dir):
        rel_dir = os.path.relpath(root, project_root).replace('\\', '/')
        rel_dir_check = '/' + rel_dir + '/'

        hit_hardcoded = any(pat in rel_dir_check for pat in ALWAYS_SKIP_DIR_SUBSTRINGS)
        hit_user = any(pat in rel_dir for pat in ignore_patterns)
        if hit_hardcoded or hit_user:
            ignored_dir_paths.append(rel_dir)
            ignored_asset_paths.extend(_list_assets_in_tree(root, project_root))
            dirs[:] = []
            continue

        for f in files:
            p = Path(f)
            if p.suffix.lower() not in ASSET_EXTS:
                continue
            if f in ALWAYS_SKIP_FILES:
                ignored_asset_paths.append(f'{rel_dir}/{f}')
                continue
            assets.append((p.stem, f'{rel_dir}/{f}'))

    ignored_asset_paths.sort()
    ignored_dir_paths.sort()
    return assets, ignored_asset_paths, ignored_dir_paths


# INI writers

def _ini_escape(s: str) -> str:
    """Conservatively escape characters that would confuse configparser."""
    return s.replace('=', '\\=').replace('\n', '\\n')


def write_export(out_dir: Path, assets, meta: dict, ignored_dirs, ignored_assets):
    """Write export.ini with summary, paths, and ignored lists."""
    name_to_paths = defaultdict(list)
    for stem, rel in assets:
        name_to_paths[stem].append(rel)
    lines = []
    lines.append('# Full asset name database from this run.')
    lines.append('# [meta]           summary stats')
    lines.append('# [paths]          unique name -> comma-separated kept paths')
    lines.append('# [ignored_dirs]   top-level directories that were skipped')
    lines.append('# [ignored_assets] full asset paths that were skipped')
    lines.append('')
    lines.append('[meta]')
    for k in ('generated_at', 'total_paths', 'unique_names',
              'ignored_assets', 'ignored_dirs',
              'verified', 'violation', 'pending'):
        lines.append(f'{k} = {meta[k]}')
    lines.append('')
    lines.append('[paths]')
    for name in sorted(name_to_paths.keys()):
        joined = ', '.join(sorted(name_to_paths[name]))
        lines.append(f'{name} = {joined}')
    lines.append('')
    lines.append('[ignored_dirs]')
    for d in ignored_dirs:
        lines.append(d)
    lines.append('')
    lines.append('[ignored_assets]')
    for a in ignored_assets:
        lines.append(a)
    (out_dir / 'export.ini').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def write_verified(out_dir: Path, by_reason: dict):
    """Verified bucket. One section, one name per line."""
    lines = []
    lines.append('# Asset names that pass the canonical rule.')
    lines.append('')
    lines.append('[verified]')
    for reason in sorted(by_reason.keys()):
        for name in sorted(by_reason[reason]):
            lines.append(name)
    (out_dir / 'verified.ini').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _r_sort_key(reason_id: str):
    """Sort r1, r2, ..., r10, r11, ..., r99 numerically."""
    if reason_id and reason_id.startswith('r'):
        try:
            return (0, int(reason_id[1:]))
        except ValueError:
            pass
    return (1, reason_id or '')


def write_violation(out_dir: Path, violations: dict, pendings: dict):
    """Violation bucket. Sections keyed by reason id.
    Confirmed violations: [r5: lowercase token start] / name = suggestion.
    TBD entries:          [TBD: r13: leading digit token after prefix] / name (no value)."""
    lines = []
    lines.append('# Asset names that failed naming rules.')
    lines.append('# Section format: [<rN>: <reason text>]')
    lines.append('# Suggested rename appears as the value if available.')
    lines.append('# TBD entries (rule flags but project-level decision pending) live in')
    lines.append('# [TBD: <rN>: <reason>] sections with bare name lines (no value).')
    lines.append('')
    for reason_id in sorted(violations.keys(), key=_r_sort_key):
        items = sorted(violations[reason_id])
        lines.append(f'[{reason_id}: {rules.reason_text(reason_id)}]')
        for name in items:
            fix = rules.suggest_fix(name)
            if fix:
                lines.append(f'{name} = {fix}')
            else:
                lines.append(f'{name} =')
        lines.append('')
    for reason_id in sorted(pendings.keys(), key=_r_sort_key):
        items = sorted(pendings[reason_id])
        lines.append(f'[TBD: {reason_id}: {rules.reason_text(reason_id)}]')
        for name in items:
            lines.append(name)
        lines.append('')
    (out_dir / 'violation.ini').write_text('\n'.join(lines), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description='Validate UE asset names against the project naming rule.')
    ap.add_argument('--project-root', help='Override project root (default: auto-detect from .uproject)')
    args = ap.parse_args()

    cfg = load_config()
    project_root = resolve_project_root(args.project_root, cfg)
    if not project_root:
        sys.stderr.write('ERROR: could not locate project root. '
                         'Pass --project-root or set [paths] project_root in Config/config.ini.\n')
        sys.exit(2)

    content_dir = project_root / 'Content'
    if not content_dir.exists():
        sys.stderr.write(f'ERROR: {content_dir} does not exist.\n')
        sys.exit(2)

    out_dir = resolve_output_dir(project_root, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f'Project root : {project_root}')
    print(f'Content dir  : {content_dir}')
    print(f'Output dir   : {out_dir}')

    ignore_patterns = load_ignore_patterns()
    if ignore_patterns:
        print(f'Ignore       : {ignore_patterns}')

    assets, ignored_asset_paths, ignored_dir_paths = crawl_assets(
        content_dir, project_root, ignore_patterns)
    names = sorted(set(stem for stem, _ in assets))
    print(f'Found {len(assets)} asset paths, {len(names)} unique names '
          f'(ignored {len(ignored_asset_paths)} assets in {len(ignored_dir_paths)} dirs)')

    verdicts = {n: rules.classify(n) for n in names}

    verified = defaultdict(list)
    violations = defaultdict(list)
    pendings = defaultdict(list)
    for n in names:
        v, r = verdicts[n]
        if v == rules.VERIFIED:
            verified[r].append(n)
        elif v == rules.VIOLATION:
            violations[r].append(n)
        else:
            pendings[r].append(n)

    meta = {
        'generated_at':   datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_paths':    len(assets),
        'unique_names':   len(names),
        'ignored_assets': len(ignored_asset_paths),
        'ignored_dirs':   len(ignored_dir_paths),
        'verified':       sum(len(v) for v in verified.values()),
        'violation':      sum(len(v) for v in violations.values()),
        'pending':        sum(len(v) for v in pendings.values()),
    }

    write_export(out_dir, assets, meta, ignored_dir_paths, ignored_asset_paths)
    write_verified(out_dir, verified)
    write_violation(out_dir, violations, pendings)

    counts = {
        rules.VERIFIED:  sum(len(v) for v in verified.values()),
        rules.VIOLATION: sum(len(v) for v in violations.values()),
        rules.PENDING:   sum(len(v) for v in pendings.values()),
    }
    total = sum(counts.values()) or 1
    print()
    print(f'Verified  : {counts[rules.VERIFIED]:>5}  ({counts[rules.VERIFIED]/total*100:5.1f}%)')
    print(f'Violation : {counts[rules.VIOLATION]:>5}  ({counts[rules.VIOLATION]/total*100:5.1f}%)')
    print(f'Pending   : {counts[rules.PENDING]:>5}  ({counts[rules.PENDING]/total*100:5.1f}%)')

    sys.exit(1 if counts[rules.VIOLATION] else 0)


if __name__ == '__main__':
    main()
