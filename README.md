# uasset-name-linter

![Claude Code](https://img.shields.io/badge/Claude_Code-black?style=flat&logo=anthropic&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white)
![Unreal Engine 5.7](https://img.shields.io/badge/Unreal_Engine-5.7-blue?logo=unrealengine&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

针对 Unreal Engine `.uasset` 和 `.umap` 文件的命名规范校验器。

扫描 UE 项目的 `Content/` 目录，按可配置的规则对每一个 asset 文件名分类，输出机器可读的 INI 数据和给团队看的 HTML 报告。设计上与 VCS pre-commit hook 配合，让不合规命名在进入项目前就被拦下。

## 它解决什么问题

Asset 命名漂移会让下游一切变难：

- 基于正则的工具变脆弱（`Footstep1` vs `Footstep_01` vs `FootstepA`）
- Content Browser 过滤失效（`SM_Player_Body` 能聚拢，`SM_Body1` 不能）
- 字典序排序在未补零的索引上崩坏（`_1, _10, _2`）
- 派生 Material Instance 的链路失去归属信息
- Asset 审计被迫依赖目录结构而非命名本身

这个工具在结构性问题积累之前就抓住它们，并且只检查 filename，不解析 `.uasset` 二进制内容，所以速度快且无外部依赖。

## 它如何解决

只用一份命名规则贯穿三个使用面：

1. **本地扫描**：手动跑 `validator.py`，得到 verified / violation / pending 三个 bucket
2. **团队报告**：跑 `make-report.py` 生成 HTML，按提交者分组列出每个人的修名清单
3. **VCS 拦截**：把 `pre-commit.bat` 装在 SVN 服务器，新增的违规命名直接被拒绝 commit

规则定义集中在 `src/rules.py`，内置 self-test，改规则后跑一下就知道有没有破坏现有判定。

## 命名规则

```
<Prefix>_<Name>[_<Variant>][_<Index>]
  Prefix  : [A-Z]+               例如 SM, T, BP, MI, SFX
  Name    : Token(_Token)*       例如 Player, Player_Body, Boss_Attack
  Token   : PascalCase chunk ([A-Z][a-z]+) 或全大写缩写 ([A-Z]{2,})
  Variant : 单个大写字母 [A-Z]    例如 _A
  Index   : 至少 2 位数字 [0-9]{2,}    例如 _01
```

### 接受

| 名字 | 说明 |
|---|---|
| `SM_Player` | 前缀 + 名字，无 variant，无 index |
| `SM_Player_01` | 前缀 + 名字 + index |
| `SM_Player_A` | 前缀 + 名字 + variant |
| `SM_Player_A_01` | 前缀 + 名字 + variant + index |
| `SM_Player_Body_L_02` | 多 token 名字 |
| `T_UI_Button` | 缩写 token 与 PascalCase 混用 |
| `BP_HUDIcon` | 缩写 + PascalCase 拼接 |
| `SM_BossAI_01` | PascalCase 结尾接缩写 |

### 拒绝

| 名字 | 原因 | 自动建议 |
|---|---|---|
| `Test1` | 缺前缀分隔符 | `Test_01` |
| `SM_Test1` | 索引黏在文本上 | `SM_Test_01` |
| `SM_TestA` | variant 黏在名字上 | `SM_Test_A` |
| `SM_Test_1` | 索引必须补零 | `SM_Test_01` |
| `SM_Test_1_A` | variant 必须在 index 之前 | `SM_Test_A_01` |
| `BP_Prefab_Block_03B` | variant 黏在 index 后面 | `BP_Prefab_Block_B_03` |
| `MyGame_ArtPush_HeartIcon` | 前缀必须全大写 | （需人工） |
| `Sample__Small_Cymbal` | 双下划线 | `Sample_Small_Cymbal` |
| `Slash-Attack-L_v01` | 不允许连字符 | `Slash_Attack_L_v_01` |
| `MF_DynamicSCurve` | 单字母大写卡在 PascalCase 中间 | （需人工） |
| `mat_1` | token 小写开头 | （需人工） |

标记"需人工"的 case 不能自动改名，因为修复需要语义判断（确定的前缀是什么、卡住的字母代表的真实词是什么等）。

完整的检测器集合在 `src/rules.py`，所有 case 由文件内的 self-test 覆盖：

```bash
python src/rules.py
```

## 目录结构

```
uasset-name-linter/
  README.md
  pre-commit.bat                 VCS hook 入口（Windows）
  Config/
    config.ini                   输出位置 + 可选项目根目录覆盖
  rules/
    ignores.ini                  路径子串忽略列表
  src/
    rules.py                     命名规则唯一真相
    validator.py                 项目扫描，写 export/verified/violation
    make-report.py               读输出，查 VCS，写 report.html
    vcs-hook.py                  pre-commit hook 实现
```

输出生成到 `<UEProject>/Saved/Tools/UAssetNameLinter/`，受 UE 标准的 `Saved/` 忽略保护，不会被 VCS 追踪。

## 安装

把整个 `uasset-name-linter/` 文件夹放进你的 UE 项目下的 `Tools/`：

```
<UEProject>/
  Content/                       必须存在
  *.uproject
  Tools/
    UAssetNameLinter/            ← 这里（PascalCase 文件夹名跟 plugin 视觉对齐）
```

要求：Python 3.8+，无第三方依赖。

`validator.py` 默认会自动从脚本位置往上找 `*.uproject` 文件来定位项目根目录。如果要在 UE 项目之外跑，传 `--project-root <path>`。

## 使用方法

### 扫描项目

```bash
python src/validator.py
```

爬 `Content/`，分类每个名字，输出三份 INI：

- `output/export.ini` — 本次跑到的所有 asset 名字（含路径）
- `output/verified.ini` — 通过规则的名字
- `output/violation.ini` — 违规名字 + 自动建议

控制台打印通过 / 违规计数。退出码 `0` 表示零违规，`1` 表示有违规。

### 生成团队报告

```bash
python src/make-report.py
```

读 validator 的输出，对每个违规文件查 VCS 的最后修改作者，生成 `output/report.html`。每个人有自己的"待修清单"，按违规原因分组，每条都附自动建议。

### Pre-commit hook

把 `pre-commit.bat` 放进 SVN 服务器的 `<repo>/hooks/` 目录。它调用 `src/vcs-hook.py`，在 transaction 中：

1. 检查 commit message 是否含 `[skip-lint]`，命中则放行
2. 过滤 `A` 状态的 `.uasset` / `.umap` 路径
3. 对每个名字跑分类，遇到违规拒绝 commit

Hook 只检查新增文件，所以存量永远不会被回查。Rename（SVN 里是 `D + A`）会触发，因为 rename 本来就是顺手清理命名的好时机。

目前只支持 SVN，Git 支持计划中。

## 配置

### `Config/config.ini`

```ini
# 输出位置，相对于自动检测出的 project root（最近的 *.uproject）
[output]
path = Saved/Tools/UAssetNameLinter

# 可选：显式覆盖 project root
# 设置后会跳过 .uproject 自动检测
# 适合 CI、test、UE 项目之外的场景
# [paths]
# project_root = D:/SomeProject
```

### `rules/ignores.ini`

按行写要忽略的路径子串，大小写敏感。任何 project-relative 路径包含其中一行的 asset 都不会被分类。

```ini
# 注释以 # 开头
TempContent
ThirdPartyPack
_GENERATED
```

`__External*`（UE5 World Partition 自动生成的目录）在 `validator.py` 里硬编码跳过，不能由 ignores.ini 关闭。

## 输出格式

### `verified.ini` / `violation.ini`

按检测原因分 section。每行一个名字，suggestion 如果存在就作为 value。

```ini
[index fused into text (need _NN separator)]
SM_Footstep1 = SM_Footstep_01
SM_Tile12 = SM_Tile_12

[double underscore]
Sample__Small_Cymbal = Sample_Small_Cymbal

[TBD: leading digit token after prefix]
MF_00_FlatNormal
M_00_Basic
```

约定：

- `[reason]` section = 已确认违规
- `[TBD: reason]` section = 规则标到了，但项目层面尚未拍板要不要算违规
- 空 value（`name =`）= 没有自动建议，需要人工命名

### `export.ini`

本次扫描到的所有 asset 名字，附 project-relative 路径，供 diff 对比和外部脚本消费：

```ini
[paths]
SM_Player = Content/Asset/SM_Player.uasset
SM_Footstep1 = Content/Audio/SM_Footstep1.uasset
```

### `report.html`

浏览器可渲染的团队报告，包含：

- 总览（违规数量、TBD 数量）
- 按作者排序的违规计数表
- 按原因排序的违规分类表
- Top 20 违规最严重的目录
- 每个作者的待修清单（按原因分组，每条附建议）

## 扩展规则

规则逻辑刻意压在单文件里没有抽象层，加 detector 是 read-and-edit 而不是 browse-and-trace。

1. 打开 `src/rules.py`
2. 加新的正则常量
3. 在 `classify()` 里加一条分支返回 `(VIOLATION, '<reason>')`
4. （可选）给 `suggest_fix()` 加一个变换，实现 auto rename
5. 在文件底部的 self-test 列表里加 accept / reject case
6. 跑 `python src/rules.py` 验证全部 case 通过
7. 重新跑 `python src/validator.py`

## 已知限制

- **单字母 token 不允许在名字中间**。包含单字母 token 的资源包（input glyph 贴图集合 `T_S_A`、`T_X_LB` 等）需要通过 `ignores.ini` 排除。
- **混合大小写缩写**（`AoE`、`IoT`、`MoBA`）会被拒。请用全大写（`AOE`）或纯 PascalCase（`Aoe`）。
- **前缀后立刻跟数字 token**（`MF_00_FlatNormal`）目前归类为 TBD，没有自动建议。这是不是合法 marketplace 风格由各项目自决。
- **Texture channel 后缀**（`_N`、`_D`、`_M`、`_R`、`_AO`、`_ORM`、`_RGH` 等）目前会被解析成 `Variant` slot。语法上能通过，但语义上 channel 标记和变体是两种不同的东西。规划中：为 `T_` 前缀引入专属的 channel slot，让 `T_Something_N` 和 `T_Something_D` 被识别为同一资源的不同 channel，而不是 variant。
- **自动建议是 best-effort**。对于多重错误叠加的名字，一遍 pipeline 可能改不到完全合规；改完后重跑 validator 检查残留。

## 状态

私用阶段，活跃 UE5 项目实战中。规则会随新边界 case 出现而继续演化。

## License

MIT，详见 [LICENSE](LICENSE)。
