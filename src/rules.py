#!/usr/bin/env python3
# rules.py
#
# Single source of truth for asset naming rules. Imported by:
#   - validator.py    (project scan)
#   - vcs-hook.py     (VCS pre-commit hook)
#
# Run directly to execute the built-in self-test:
#   python rules.py

import re

# Verdict tags
VERIFIED  = 'verified'
VIOLATION = 'violation'
PENDING   = 'pending'

# Reason IDs are stable across iterations. Renaming a reason text does NOT
# change its r-id, so external references (commit messages, issue tracking)
# stay valid. New rules append to this table; old ids are never reused.
REASONS = {
    'r1':  'hyphen not allowed',
    'r2':  'double underscore',
    'r3':  'no prefix separator',
    'r4':  'prefix must be all uppercase letters',
    'r5':  'lowercase token start',
    'r6':  'variant must come before index',
    'r7':  'variant fused after index (need underscore)',
    'r8':  'variant fused into name (need _A separator)',
    'r9':  'digit fused with following text (need _NN_ separator)',
    'r10': 'index fused into text (need _NN separator)',
    'r11': 'index must be zero-padded (>=2 digits)',
    'r12': 'lone single uppercase in middle (use full word or _separator_)',
    'r13': 'leading digit token after prefix',
    'r14': 'generated brush/asset (try rename based on usage)',
    'r99': 'unknown structure',
}


def reason_text(reason_id: str) -> str:
    return REASONS.get(reason_id, reason_id or '')


# Canonical rule
#   <Prefix>_<Name>[_<Variant>][_<Index>]
#     Prefix  : [A-Z]+
#     Token   : (PascalChunk | AcronymChunk)+
#       PascalChunk  : [A-Z][a-z]+
#       AcronymChunk : [A-Z]{2,}
#     Name    : Token(_Token)*
#     Variant : single [A-Z]
#     Index   : [0-9]{2,}
TOKEN        = r'(?:[A-Z][a-z]+|[A-Z]{2,})+'
NAME         = rf'{TOKEN}(?:_{TOKEN})*'
CANONICAL_RE = re.compile(rf'^[A-Z]+_{NAME}(?:_[A-Z])?(?:_\d{{2,}})?$')

# Generated brush / BSP export name: <Word>_<8 hex chars>
# UE produces these on brush conversion (Box_5C5F67FD, Cylinder_355FA85C).
# Detected first because the prefix check would mis-diagnose it as
# 'prefix must be all uppercase letters'.
GENERATED_BRUSH = re.compile(r'^[A-Z][a-z]+_[0-9A-F]{8}$')

# Variant fused into name. State-machine equivalent:
#   scan boundaries, find a single uppercase preceded by lowercase and
#   followed by `_` or end of string.
EMBEDDED_VARIANT = re.compile(r'[a-z][A-Z](?:_|$)')

# Index fused into text without separator
EMBEDDED_INDEX = re.compile(r'[A-Za-z]\d+(?:_|$)')

# Index immediately followed by single uppercase variant, no separator
INDEX_VARIANT_FUSED = re.compile(r'\d+[A-Z](?:_|$)')

# Digit run followed directly by 2+ alphabetic chars (no separator)
DIGIT_TEXT_FUSED = re.compile(r'\d+[A-Za-z]{2}')

# Double underscore
DOUBLE_UNDERSCORE = re.compile(r'__')

# Lone single uppercase letter sandwiched between PascalCase boundaries
LONE_CAP_IN_MIDDLE = re.compile(r'[a-z][A-Z][A-Z][a-z]')

SINGLE_DIGIT_INDEX   = re.compile(r'_\d(?=_|$)')
INDEX_BEFORE_VARIANT = re.compile(r'_\d{2,}_[A-Z](?:_|$)')
LOWERCASE_TOKEN      = re.compile(r'(?:^|_)[a-z]')
HYPHEN               = re.compile(r'-')

LEADING_DIGIT_TOKEN  = re.compile(r'^[A-Z]+_\d+(?:_|$)')


def classify(stem: str):
    """Return (verdict, reason_id). reason_id is one of REASONS keys, or
    None when verdict is VERIFIED."""
    if CANONICAL_RE.match(stem):
        return VERIFIED, None

    # Generated brush comes first so it short-circuits the prefix check
    if GENERATED_BRUSH.match(stem):
        return VIOLATION, 'r14'

    if HYPHEN.search(stem):
        return VIOLATION, 'r1'
    if DOUBLE_UNDERSCORE.search(stem):
        return VIOLATION, 'r2'
    if '_' not in stem:
        return VIOLATION, 'r3'

    prefix = stem.split('_', 1)[0]
    if not prefix.isalpha() or not prefix.isupper():
        return VIOLATION, 'r4'

    if LOWERCASE_TOKEN.search(stem):
        return VIOLATION, 'r5'
    if INDEX_BEFORE_VARIANT.search(stem):
        return VIOLATION, 'r6'
    if INDEX_VARIANT_FUSED.search(stem):
        return VIOLATION, 'r7'
    if EMBEDDED_VARIANT.search(stem):
        return VIOLATION, 'r8'
    if DIGIT_TEXT_FUSED.search(stem):
        return VIOLATION, 'r9'
    if EMBEDDED_INDEX.search(stem):
        return VIOLATION, 'r10'
    if SINGLE_DIGIT_INDEX.search(stem):
        return VIOLATION, 'r11'
    if LONE_CAP_IN_MIDDLE.search(stem):
        return VIOLATION, 'r12'

    if LEADING_DIGIT_TOKEN.search(stem):
        return PENDING, 'r13'

    return PENDING, 'r99'


def suggest_fix(stem: str):
    """Apply known transformations. Returns a string different from stem,
    or None if no useful suggestion can be produced. Best-effort: result may
    still not match canonical for cases requiring semantic input (unknown
    prefix, lone middle capital, generated brush hash, etc).

    For names with no prefix separator (r3), prepends a placeholder 'XX_'
    to indicate "real prefix needed here". The user is expected to replace
    XX with the appropriate type prefix (SM, T, BP, ...) and may also do
    semantic word reordering at the same time."""

    # Generated brush hashes have no useful auto-rename
    if GENERATED_BRUSH.match(stem):
        return None

    s = stem
    # No prefix separator: prepend placeholder. Pipeline below will then
    # capitalize the first letter (XX_attackDodge -> XX_AttackDodge) and
    # apply other normalizations.
    if '_' not in s:
        s = 'XX_' + s

    for _ in range(6):
        prev = s
        s = s.replace('-', '_')
        while '__' in s:
            s = s.replace('__', '_')
        s = s.strip('_')
        # Capitalize lowercase token starts (after underscore)
        s = re.sub(r'_([a-z])', lambda m: '_' + m.group(1).upper(), s)
        # Pad single-digit index
        s = re.sub(r'_(\d)(?=_|$)', lambda m: f'_0{m.group(1)}', s)
        # Index fused into text at end
        s = re.sub(r'([A-Za-z])(\d+)(?=_|$)',
                   lambda m: f'{m.group(1)}_{m.group(2).zfill(2)}', s)
        # Variant fused into name at end
        s = re.sub(r'([a-z])([A-Z])(?=_|$)', r'\1_\2', s)
        # Variant fused after index at end
        s = re.sub(r'_(\d+)([A-Z])(?=_|$)', r'_\2_\1', s)
        # Variant before index at end
        s = re.sub(r'_(\d{2,})_([A-Z])(?=_|$)', r'_\2_\1', s)
        # Digit run followed by 2+ letters
        s = re.sub(r'(\d+)([A-Z][a-z])', r'\1_\2', s)
        s = re.sub(r'(\d+)([A-Z]{2})', r'\1_\2', s)
        if s == prev:
            break
    return s if s != stem else None


# Self-test (NDA-clean: no project-specific identifiers)
_ACCEPT = [
    'SM_Test',
    'SM_Test_01',
    'SM_Test_A',
    'SM_Test_A_01',
    'SM_Player_Body',
    'SM_Player_Body_L_02',
    'T_UI_Button',
    'BP_HUDIcon',
    'A_Boss_Attack_Combo_03',
    'SM_BossAI_01',
    'SM_BossABCTest',
]

_REJECT = [
    ('Test1',                            'r3'),
    ('TestA',                            'r3'),
    ('attackDodge',                      'r3'),
    ('chaliceConsumed',                  'r3'),
    ('Splash',                           'r3'),
    ('BiteIcon',                         'r3'),
    ('SM_Test1',                         'r10'),
    ('SM_TestA',                         'r8'),
    ('SM_Test_A1',                       'r10'),
    ('SM_Test_1_A',                      'r11'),
    ('SM_Test1_A',                       'r10'),
    ('SM_TestA_1',                       'r8'),
    ('SM_Test_1',                        'r11'),
    ('sm_Player',                        'r4'),
    ('SM_player',                        'r5'),
    ('SM_Player_01_A',                   'r6'),
    ('SM_Footstep1',                     'r10'),
    ('BP_Prefab_Block_03B',              'r7'),
    ('L_WhiteBox_Sub_01PoolRoom',        'r9'),
    ('Sample__Small_Cymbal',             'r2'),
    ('Anim_GettingUp',                   'r4'),
    ('MyGame_ArtPush_HeartIcon',         'r4'),
    ('MyDemo_Font',                      'r4'),
    ('MF_DynamicSCurve',                 'r12'),
    ('SM_BossYTester',                   'r12'),
    ('mat_1',                            'r4'),
    ('AS_Boss_Slash-Attack-L_v01',       'r1'),
    ('SW_bite',                          'r5'),
    ('Box_5C5F67FD',                     'r14'),
    ('Cylinder_355FA85C',                'r14'),
]

_PENDING = [
    ('MF_00_FlatNormal',                 'r13'),
    ('MLB_00_VertexColor',               'r13'),
]


def _selftest():
    fails = 0
    print('Accept:')
    for n in _ACCEPT:
        v, r = classify(n)
        mark = 'OK ' if v == VERIFIED else 'BAD'
        if v != VERIFIED:
            fails += 1
        print(f'  [{mark}] {n}')
    print()
    print('Reject:')
    for n, expected_r in _REJECT:
        v, r = classify(n)
        ok = (v == VIOLATION) and (r == expected_r)
        mark = 'OK ' if ok else 'BAD'
        if not ok:
            fails += 1
        fix = suggest_fix(n)
        fix_str = f'  -> {fix}' if fix else ''
        print(f'  [{mark}] {n}  [{r}: {reason_text(r)}]{fix_str}')
    print()
    print('Pending:')
    for n, expected_r in _PENDING:
        v, r = classify(n)
        ok = (v == PENDING) and (r == expected_r)
        mark = 'OK ' if ok else 'BAD'
        if not ok:
            fails += 1
        print(f'  [{mark}] {n}  [{r}: {reason_text(r)}]')
    print()
    total = len(_ACCEPT) + len(_REJECT) + len(_PENDING)
    print(f'Pass: {total - fails}/{total}')
    return fails


if __name__ == '__main__':
    import sys
    sys.exit(1 if _selftest() else 0)
