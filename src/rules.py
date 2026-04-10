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

# Variant fused into name. State-machine equivalent:
#   scan boundaries, find a single uppercase preceded by lowercase and
#   followed by `_` or end of string.
# 'somethingA' -> match (gA, A is single, end)
# 'EatME'      -> no match (M is followed by E, ME is acronym)
EMBEDDED_VARIANT = re.compile(r'[a-z][A-Z](?:_|$)')

# Index fused into text without separator
# 'Footstep1', 'Tile12'
EMBEDDED_INDEX = re.compile(r'[A-Za-z]\d+(?:_|$)')

# Index immediately followed by single uppercase variant, no separator
# 'Pillar_03B' (03 + B at end). Distinct from EMBEDDED_VARIANT because the
# preceding char is a digit, not a lowercase letter.
INDEX_VARIANT_FUSED = re.compile(r'\d+[A-Z](?:_|$)')

# Digit run followed directly by 2+ alphabetic chars (no separator)
# Catches '01PoolRoom', 'WW3Boss', '4Combo' (lowercase after)
# and '05BProcessing', '2DMonitor' (uppercase after).
# Trailing single uppercase like '03B' at end is handled by INDEX_VARIANT_FUSED.
DIGIT_TEXT_FUSED = re.compile(r'\d+[A-Za-z]{2}')

# Double underscore
DOUBLE_UNDERSCORE = re.compile(r'__')

# Lone single uppercase letter sandwiched between PascalCase boundaries
# 'DynamicSCurve' (S stuck), 'BossYTester' (Y stuck)
# Window pattern: lowercase, upper, upper, lowercase
LONE_CAP_IN_MIDDLE = re.compile(r'[a-z][A-Z][A-Z][a-z]')

# Other clear anti-patterns
SINGLE_DIGIT_INDEX   = re.compile(r'_\d(?=_|$)')
INDEX_BEFORE_VARIANT = re.compile(r'_\d{2,}_[A-Z](?:_|$)')
LOWERCASE_TOKEN      = re.compile(r'(?:^|_)[a-z]')
HYPHEN               = re.compile(r'-')

# Pending patterns (no decision yet)
LEADING_DIGIT_TOKEN  = re.compile(r'^[A-Z]+_\d+(?:_|$)')


def classify(stem: str):
    """Return (verdict, reason). verdict is one of VERIFIED/VIOLATION/PENDING."""
    if CANONICAL_RE.match(stem):
        return VERIFIED, 'canonical'

    # Structural
    if HYPHEN.search(stem):
        return VIOLATION, 'hyphen not allowed'
    if DOUBLE_UNDERSCORE.search(stem):
        return VIOLATION, 'double underscore'
    if '_' not in stem:
        return VIOLATION, 'no prefix separator'

    # Prefix slot must be all uppercase letters
    prefix = stem.split('_', 1)[0]
    if not prefix.isalpha() or not prefix.isupper():
        return VIOLATION, 'prefix must be all uppercase letters'

    # Token-level
    if LOWERCASE_TOKEN.search(stem):
        return VIOLATION, 'lowercase token start'
    if INDEX_BEFORE_VARIANT.search(stem):
        return VIOLATION, 'variant must come before index'
    if INDEX_VARIANT_FUSED.search(stem):
        return VIOLATION, 'variant fused after index (need underscore)'
    if EMBEDDED_VARIANT.search(stem):
        return VIOLATION, 'variant fused into name (need _A separator)'
    if DIGIT_TEXT_FUSED.search(stem):
        return VIOLATION, 'digit fused with following text (need _NN_ separator)'
    if EMBEDDED_INDEX.search(stem):
        return VIOLATION, 'index fused into text (need _NN separator)'
    if SINGLE_DIGIT_INDEX.search(stem):
        return VIOLATION, 'index must be zero-padded (>=2 digits)'
    if LONE_CAP_IN_MIDDLE.search(stem):
        return VIOLATION, 'lone single uppercase in middle (use full word or _separator_)'

    if LEADING_DIGIT_TOKEN.search(stem):
        return PENDING, 'leading digit token after prefix'

    return PENDING, 'unknown structure'


def suggest_fix(stem: str):
    """Apply known transformations. Returns a string different from stem,
    or None if no useful suggestion can be produced. Best-effort: result may
    still not match canonical for cases requiring semantic input (unknown
    prefix, lone middle capital, etc)."""
    s = stem
    for _ in range(6):
        prev = s
        s = s.replace('-', '_')
        while '__' in s:
            s = s.replace('__', '_')
        s = s.strip('_')
        s = re.sub(r'_(\d)(?=_|$)', lambda m: f'_0{m.group(1)}', s)
        s = re.sub(r'([A-Za-z])(\d+)(?=_|$)',
                   lambda m: f'{m.group(1)}_{m.group(2).zfill(2)}', s)
        s = re.sub(r'([a-z])([A-Z])(?=_|$)', r'\1_\2', s)
        s = re.sub(r'_(\d+)([A-Z])(?=_|$)', r'_\2_\1', s)
        s = re.sub(r'_(\d{2,})_([A-Z])(?=_|$)', r'_\2_\1', s)
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
    'Test1',
    'TestA',
    'SM_Test1',
    'SM_TestA',
    'SM_Test_A1',
    'SM_Test_1_A',
    'SM_Test1_A',
    'SM_TestA_1',
    'SM_Test_1',
    'sm_Player',
    'SM_player',
    'SM_Player_01_A',
    'SM_Footstep1',
    'BP_Prefab_Block_03B',
    'L_WhiteBox_Sub_01PoolRoom',
    'Sample__Small_Cymbal',
    'Anim_GettingUp',
    'MyGame_ArtPush_HeartIcon',
    'MyDemo_Font',
    'MF_DynamicSCurve',
    'SM_BossYTester',
    'mat_1',
    'AS_Boss_Slash-Attack-L_v01',
]

_PENDING = [
    'MF_00_FlatNormal',
    'MLB_00_VertexColor',
]


def _selftest():
    fails = 0
    print('Accept:')
    for n in _ACCEPT:
        v, r = classify(n)
        mark = 'OK ' if v == VERIFIED else 'BAD'
        if v != VERIFIED:
            fails += 1
        print(f'  [{mark}] {n}  ({r})')
    print()
    print('Reject:')
    for n in _REJECT:
        v, r = classify(n)
        mark = 'OK ' if v == VIOLATION else 'BAD'
        if v != VIOLATION:
            fails += 1
        fix = suggest_fix(n)
        fix_str = f'  -> {fix}' if fix else ''
        print(f'  [{mark}] {n}  ({r}){fix_str}')
    print()
    print('Pending:')
    for n in _PENDING:
        v, r = classify(n)
        mark = 'OK ' if v == PENDING else 'BAD'
        if v != PENDING:
            fails += 1
        print(f'  [{mark}] {n}  ({r})')
    print()
    total = len(_ACCEPT) + len(_REJECT) + len(_PENDING)
    print(f'Pass: {total - fails}/{total}')
    return fails


if __name__ == '__main__':
    import sys
    sys.exit(1 if _selftest() else 0)
