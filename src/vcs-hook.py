#!/usr/bin/env python3
# vcs-hook.py
#
# VCS pre-commit hook implementation. Currently supports SVN.
# Git support is planned.
#
# Invoked from pre-commit.bat on the SVN server with REPOS and TXN args.
# Filters added (status A) .uasset/.umap paths and classifies each name.
# Exits non-zero on any violation, blocking the commit.
#
# Bypass: include "[skip-lint]" in the commit message.

import argparse
import subprocess
import sys
from pathlib import Path

import rules

ASSET_EXTS = {'.uasset', '.umap'}


def lint_svn_txn(repos: str, txn: str):
    # Bypass keyword
    log = subprocess.check_output(
        ['svnlook', 'log', '-t', txn, repos],
        text=True, encoding='utf-8', errors='replace'
    )
    if '[skip-lint]' in log:
        return []

    out = subprocess.check_output(
        ['svnlook', 'changed', '-t', txn, repos],
        text=True, encoding='utf-8', errors='replace'
    )
    violations = []
    for line in out.splitlines():
        if not line or line[0] != 'A':
            continue
        path = line[4:].strip()
        if Path(path).suffix.lower() not in ASSET_EXTS:
            continue
        verdict, reason = rules.classify(Path(path).stem)
        if verdict == rules.VIOLATION:
            fix = rules.suggest_fix(Path(path).stem)
            violations.append((path, reason, fix))
    return violations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--svn-txn', nargs=2, metavar=('REPOS', 'TXN'),
                    help='SVN pre-commit hook mode')
    args = ap.parse_args()

    if not args.svn_txn:
        ap.print_help()
        sys.exit(2)

    violations = lint_svn_txn(*args.svn_txn)
    if violations:
        sys.stderr.write('[uasset-name-linter] commit blocked. Violations:\n')
        for path, reason, fix in violations:
            sys.stderr.write(f'  {path}\n')
            sys.stderr.write(f'    reason: {reason}\n')
            if fix:
                sys.stderr.write(f'    suggest: {fix}\n')
        sys.stderr.write('\nBypass with [skip-lint] in commit message.\n')
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
