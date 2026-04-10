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
#   Default: Saved/Tools/UAssetNameLinter/

import argparse
import configparser
import os
import sys
from collections import defaultdict
from pathlib import Path

import rules

SCRIPT_DIR    = Path(__file__).parent
TOOL_ROOT     = SCRIPT_DIR.parent
CONFIG_FILE   = TOOL_ROOT / 'Config' / 'config.ini'
IGNORE_FILE   = TOOL_ROOT / 'rules' / 'ignores.ini'

ASSET_EXTS = {'.uasset', '.umap'}


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
    rel = cfg.get('output', 'path', fallback='Saved/Tools/UAssetNameLinter')
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


def fetch_assets(content_dir, project_root, ignore_patterns):
    """Yield (stem, rel_path) for every asset under content_dir not ignored.
    rel_path is forward-slash and relative to project_root."""
    for root, dirs, files in os.walk(content_dir):
        rel_dir = os.path.relpath(root, project_root).replace('\\', '/')
        if '__External' in rel_dir:
            dirs[:] = []
            continue
        if any(pat in rel_dir for pat in ignore_patterns):
            dirs[:] = []
            continue
        for f in files:
            p = Path(f)
            if p.suffix.lower() in ASSET_EXTS:
                yield p.stem, f'{rel_dir}/{f}'


# INI writers

def _ini_escape(s: str) -> str:
    """Conservatively escape characters that would confuse configparser."""
    return s.replace('=', '\\=').replace('\n', '\\n')


def write_export(out_dir: Path, assets):
    """Write export.ini with [paths] section: name = comma-separated paths."""
    name_to_paths = defaultdict(list)
    for stem, rel in assets:
        name_to_paths[stem].append(rel)
    lines = []
    lines.append('# Full asset name database from this run.')
    lines.append('# Format: name = comma-separated paths (project-relative).')
    lines.append('')
    lines.append('[paths]')
    for name in sorted(name_to_paths.keys()):
        joined = ', '.join(sorted(name_to_paths[name]))
        lines.append(f'{name} = {joined}')
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


def write_violation(out_dir: Path, violations: dict, pendings: dict):
    """Violation bucket. Sections grouped by reason.
    Confirmed violations: [reason] / name = suggestion (blank if none).
    TBD entries:          [TBD: reason] / name (no value)."""
    lines = []
    lines.append('# Asset names that failed naming rules.')
    lines.append('# Confirmed violations have section [<reason>], one entry per line.')
    lines.append('# Suggested rename appears as the value if available.')
    lines.append('# TBD entries (rule flags but decision pending) live in [TBD: <reason>]')
    lines.append('# sections with bare name lines (no value).')
    lines.append('')
    for reason in sorted(violations.keys()):
        items = sorted(violations[reason])
        lines.append(f'[{reason}]')
        for name in items:
            fix = rules.suggest_fix(name)
            if fix:
                lines.append(f'{name} = {fix}')
            else:
                lines.append(f'{name} =')
        lines.append('')
    for reason in sorted(pendings.keys()):
        items = sorted(pendings[reason])
        lines.append(f'[TBD: {reason}]')
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

    assets = list(fetch_assets(content_dir, project_root, ignore_patterns))
    names = sorted(set(stem for stem, _ in assets))
    print(f'Found {len(assets)} asset paths, {len(names)} unique names')

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

    write_export(out_dir, assets)
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
