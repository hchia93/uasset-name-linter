# uasset-name-linter

**English** | [中文](README_CN.md)

![Claude Code](https://img.shields.io/badge/Claude_Code-black?style=flat&logo=anthropic&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white)
![Unreal Engine 5.7](https://img.shields.io/badge/Unreal_Engine-5.7-blue?logo=unrealengine&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

A naming convention validator for Unreal Engine `.uasset` and `.umap` files.

It crawls a UE project's `Content/` folder, classifies every asset filename against a configurable rule, and produces machine-readable INI buckets plus a team-facing HTML report. Designed to be wired into a VCS pre-commit hook so unconventional names cannot enter the project in the first place.

## What problem it solves

Asset naming drift makes everything downstream worse:

- Regex-based tooling becomes fragile (`Footstep1` vs `Footstep_01` vs `FootstepA`)
- Content Browser filtering breaks (`SM_Player_Body` clusters, `SM_Body1` does not)
- Lexicographic sort fails on un-padded indices (`_1`, `_10`, `_2`)
- Material Instance derivation chains lose ownership info
- Asset audits become path-dependent rather than name-dependent

This tool catches the structural problems before they accumulate, and it works per-name without parsing `.uasset` binary content, so it stays fast and dependency-free.

## How it solves it

A single rule set drives three usage surfaces:

1. **Local scan**: run `validator.py` to get verified / violation / pending buckets
2. **Team report**: run `make-report.py` to generate an HTML report grouped by author, top 3 wear medals
3. **VCS interception**: install `pre-commit.bat` on the SVN server so violating new names are rejected at commit time

Rule definitions live in `src/rules.py`. Each detector has a stable r-id (r1, r2, ...) and the file ships with a built-in self-test runnable as `python src/rules.py`.

## The Rule

```
<Prefix>_<Name>[_<Variant>][_<Index>]
  Prefix  : [A-Z]+               e.g. SM, T, BP, MI, SFX
  Name    : Token(_Token)*       e.g. Player, Player_Body, Boss_Attack
  Token   : PascalCase chunk ([A-Z][a-z]+) or all-caps acronym ([A-Z]{2,})
  Variant : single uppercase letter [A-Z]    e.g. _A
  Index   : 2+ digits [0-9]{2,}              e.g. _01
```

### Accepted

| Name | Notes |
|---|---|
| `SM_Player` | Prefix + name, no variant, no index |
| `SM_Player_01` | Prefix + name + index |
| `SM_Player_A` | Prefix + name + variant |
| `SM_Player_A_01` | Prefix + name + variant + index |
| `SM_Player_Body_L_02` | Multi-token name |
| `T_UI_Button` | Acronym token mixed with PascalCase |
| `BP_HUDIcon` | Acronym + PascalCase token |
| `SM_BossAI_01` | PascalCase ending in acronym |

### Rejected (with r-id and auto-suggestion)

| r-id | Name | Reason | Auto-suggestion |
|---|---|---|---|
| r1  | `Slash-Attack-L_v01` | hyphen not allowed | `Slash_Attack_L_V_01` |
| r2  | `Sample__Small_Cymbal` | double underscore | `Sample_Small_Cymbal` |
| r3  | `attackDodge` | no prefix separator | `XX_AttackDodge` |
| r3  | `BiteIcon` | no prefix separator | `XX_BiteIcon` |
| r4  | `MyGame_ArtPush_HeartIcon` | prefix must be all uppercase | (needs human) |
| r5  | `SW_bite` | lowercase token start | `SW_Bite` |
| r6  | `SM_Test_01_A` | variant must come before index | `SM_Test_A_01` |
| r7  | `BP_Prefab_Block_03B` | variant fused after index | `BP_Prefab_Block_B_03` |
| r8  | `SM_TestA` | variant fused into name | `SM_Test_A` |
| r9  | `L_WhiteBox_Sub_01PoolRoom` | digit fused with following text | `L_WhiteBox_Sub_01_PoolRoom` |
| r10 | `SM_Footstep1` | index fused into trailing text | `SM_Footstep_01` |
| r11 | `SM_Test_1` | index must be zero-padded | `SM_Test_01` |
| r12 | `MF_DynamicSCurve` | lone single uppercase in middle | (needs human) |
| r13 | `MF_00_FlatNormal` | leading digit token after prefix (TBD) | (needs human) |
| r14 | `Box_5C5F67FD` | UE-generated BSP brush hash name | (needs human, rename based on usage) |
| r99 | (rare structures) | unknown structure | (needs human) |

Conventions:

- **r-ids are permanently stable**. Reason text may change, but the r-id never gets reassigned. If a rule is removed, its r-id stays reserved as a placeholder and is never reused.
- **`XX_` is a placeholder prefix**. The r3 auto-suggestion prepends `XX_` to indicate "real prefix needed here". The user is expected to replace `XX` with the appropriate type prefix (`SM_`, `T_`, `BP_`, etc).
- **(needs human)** cases cannot be auto-renamed because the fix requires semantic input (the correct prefix, what a stuck letter actually represents, the actual purpose of a generated brush, etc).
- **r13** is a pending TBD, not a confirmed violation. Each project decides whether to accept this pattern.

The complete detector set lives in `src/rules.py` and is covered by an in-file self-test:

```bash
python src/rules.py
```

## Layout

```
uasset-name-linter/
  README.md / README_CN.md
  LICENSE
  pre-commit.bat                 VCS hook entry (Windows)
  Config/
    config.ini                   Output location + optional project root override
  rules/
    ignores.ini                  Path substring ignore list
  src/
    rules.py                     Single source of truth for naming rules + r-ids + suggestions
    validator.py                 Project scan, writes export/verified/violation
    make-report.py               Reads outputs, queries VCS, writes report.html
    vcs-hook.py                  Pre-commit hook implementation
```

Output is generated to `<UEProject>/Saved/UAssetNameLinter/`, protected by UE's standard `Saved/` ignore convention so it won't be tracked by VCS.

## Installation

Drop the entire `uasset-name-linter/` folder into your UE project's `Tools/` directory:

```
<UEProject>/
  Content/                       must exist
  *.uproject
  Tools/
    UAssetNameLinter/            ← here (PascalCase folder name to mirror plugin convention)
```

Requirements: Python 3.8+. No third-party dependencies.

`validator.py` defaults to auto-detecting the project root by walking up from the script location looking for a `*.uproject` file. To run against a different project, pass `--project-root <path>`.

## Usage

### Scan the project

```bash
python src/validator.py
```

Crawls `Content/`, classifies every name, writes three INIs:

- `output/export.ini` — every asset name found this run, plus the ignored lists and meta
- `output/verified.ini` — names that passed the rule
- `output/violation.ini` — names that failed, with auto-suggestions

Console prints pass/violation counts. Exit code is `0` for zero violations, `1` if any violation exists.

### Generate the team report

```bash
python src/make-report.py
```

Reads the validator outputs, queries VCS for the last-modified author of each violating file, and writes `output/report.html`. Each contributor gets an action list grouped by violation reason with auto-suggestions next to each entry. The author table places 🥇🥈🥉 next to the top 3 contributors and 🫨 next to everyone else.

### Pre-commit hook

Place `pre-commit.bat` in your SVN server's `<repo>/hooks/` directory. It calls `src/vcs-hook.py`, which on each transaction:

1. Skips the check if the commit message contains `[skip-lint]`
2. Filters added (`A`) `.uasset` and `.umap` paths
3. Classifies each name and rejects the commit on any violation

The hook only inspects added files, so existing assets are never re-evaluated. Renaming an asset (`D + A` in SVN terms) does trigger the check, which is intentional: a rename is the natural moment to fix the name.

Currently SVN-only. Git support is planned.

## Configuration

### `Config/config.ini`

```ini
# Output location, resolved relative to the auto-detected project root (nearest *.uproject)
[output]
path = Saved/UAssetNameLinter

# Optional: explicit project root override.
# When set, disables auto-detection of .uproject.
# Useful for CI, tests, or running outside a UE project.
# [paths]
# project_root = D:/SomeProject
```

### `rules/ignores.ini`

Newline-separated path substrings, case-sensitive. Any asset whose project-relative path contains one of these substrings is excluded from classification.

```ini
# Comments start with #
TempContent
ThirdPartyPack
_GENERATED
```

**Hardcoded skips** (in `validator.py`, always applied regardless of this file):

| Pattern | Reason |
|---|---|
| `__External*` | UE5 World Partition external actor folders |
| `Content/Splash/` | UE-generated splash screen folder |
| `ProjectThumbnail.uasset` | UE-generated project thumbnail |

These three are universal UE conventions present in every project, so `ignores.ini` cannot turn them back on.

## Output Format

### `verified.ini` / `violation.ini`

Sections grouped by r-id. One name per line, with the suggestion as the value when available.

```ini
[r1: hyphen not allowed]
Slash-Attack-L_v01 = Slash_Attack_L_V_01

[r10: index fused into text (need _NN separator)]
SM_Footstep1 = SM_Footstep_01
SM_Tile12 = SM_Tile_12

[r2: double underscore]
Sample__Small_Cymbal = Sample_Small_Cymbal

[TBD: r13: leading digit token after prefix]
MF_00_FlatNormal
M_00_Basic
```

Conventions:

- `[rN: ...]` section = confirmed violation
- `[TBD: rN: ...]` section = rule flagged it, but the project hasn't decided whether it counts as a violation
- Empty value (`name =`) = no auto-suggestion available, needs human input
- Bare name lines (no `=`) = TBD section format

### `export.ini`

The full data dump for this run, four sections:

```ini
[meta]
generated_at = 2026-04-10 19:06:39
total_paths = 992
unique_names = 972
ignored_assets = 6865
ignored_dirs = 7
verified = 642
violation = 317
pending = 13

[paths]
SM_Player = Content/Asset/SM_Player.uasset
SM_Footstep1 = Content/Audio/SM_Footstep1.uasset

[ignored_dirs]
Content/InputGlyph
Content/TempContent
Content/__ExternalActors__

[ignored_assets]
Content/InputGlyph/SGamepad/Default/T_S_A.uasset
Content/InputGlyph/SGamepad/Default/T_S_LB.uasset
...
```

`make-report.py` reads `[meta]` for the summary stats, `[paths]` for the name→path lookup, and `[ignored_*]` for the foldable ignored lists.

### `report.html`

Browser-renderable team report. Structure:

- **Title** `<code>.uasset</code> Name Linter Report` plus a generated timestamp (precise to seconds)
- **Header stats** `Total Scanned: N assets`, `Ignored: N assets and N directories`
- **Foldable Ignored Directories** full path list
- **Foldable Ignored Assets** full path list (scrollable, often very long)
- **Summary** verified / violation / TBD with percentages
- **Violations by Author** table sorted by file count, leftmost column: 🥇🥈🥉 for top 3, 🫨 for rank 4+
- **Violations by Reason** table sorted by r-id
- **Top 20 Dirty Directories** worst offending directories
- **Per-Author Action Lists** each author wrapped in a `<details open>` block, sub-grouped by r-id, with auto-suggestions for every entry

## Extending the Rules

Rule logic is intentionally a single file with no abstraction layers, so adding a detector is read-and-edit, not browse-and-trace.

1. Open `src/rules.py`
2. Append a new r-id to the `REASONS` dict (**always append, never reuse old ids**)
3. Add a new regex constant
4. Add a branch in `classify()` returning `(VIOLATION, 'rNN')`
5. (Optional) Add a transformation to `suggest_fix()` for auto-rename
6. Add accept / reject cases to the self-test list at the bottom, with the expected r-id
7. Run `python src/rules.py` to verify all cases pass
8. Re-run `python src/validator.py`

## Known Limitations

- **Mixed-case acronyms** (`AoE`, `IoT`, `MoBA`) are rejected. Use either all-caps (`AOE`) or pure PascalCase (`Aoe`)
- **r13 (leading digit token after prefix)** is currently classified as TBD with no auto-suggestion. Whether this is acceptable as a marketplace convention is project-specific
- **Texture channel suffixes** (`_N`, `_D`, `_M`, `_R`, `_AO`, `_ORM`, `_RGH`, etc) are currently parsed as the `Variant` slot. While syntactically valid, channel markers and variants are semantically distinct. Planned: introduce a dedicated channel slot for the `T_` prefix family so `T_Something_N` and `T_Something_D` are recognized as different channels of the same asset rather than variants
- **Asset packs containing single-letter tokens** (input glyph atlases like `T_S_A`, `T_X_LB`) need to be excluded via `ignores.ini`, because single-letter tokens are syntactically indistinguishable from the variant slot
- **r3 auto-suggestions are placeholders**. The `XX` in `XX_AttackDodge` is not a real prefix; the user must manually replace it with the correct type prefix
- **Auto-suggestion is best-effort**. For names with multiple stacked errors, a single pipeline pass may not produce a fully canonical result; re-run the validator after applying the fix to check for residual issues

## Status

Private, used in an active UE5 project. Rules continue to evolve as new edge cases surface.

## License

MIT, see [LICENSE](LICENSE).
