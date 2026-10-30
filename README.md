# Multi-Agent Git Orchestrator Skills

[English](README.en.md) | [中文](README.md) | [日本語](README.ja.md)

> **让多个 AI Agent 安全地并行开发同一个 Git 仓库。**

`Multi-Agent Git Orchestrator` 是一个面向 Claude Code、Codex、Cursor、OpenCode、Hermes 等 Coding Agent（以及任何支持 Agent Skills 格式的宿主）的 Git Workflow Skill。

它会主动调查当前仓库的 **Branch / Worktree / Commit / Ahead-Behind / Dependency** 状态，并帮助 Agent 决定：

- 哪些任务可以并行
- 哪些 Worktree 可以复用
- 哪些 Branch 应该 Rebase / Merge
- 哪些 Commit 适合 Cherry-pick
- 哪些分支已经可以安全清理
- 如何避免多个 Agent 同时破坏 `main`
<img width="1254" height="1254" alt="MAGOS2" src="https://github.com/user-attachments/assets/4d450361-25b5-4d35-90d8-d5656bd496cb" />

---

## 它运行什么、发送什么、联网做什么

- **运行什么。** 在 Claude Code 里，插件启用 PreToolUse 钩子（`hooks/hooks.json`）。遇到 shell 命令、子 Agent 启动、创建 worktree，以及会启动会话、shell 或进程的 MCP 工具时，`hooks/run-guard.cmd` 用 Python 运行 `scripts/magos_guard.py`；脚本读取收到的这次工具调用，回答放行、拒绝，或者对 Bash 或 PowerShell 工具里被直接调用的一条 `override`、`arm`、`disarm`、`install` 守卫命令回答询问（Claude Code 随即弹出权限对话框，实际运行的命令带有钩子加上的一次性 `--approval` 令牌；`auto-safe` 级别下，对 `arm` 和复制到默认守卫目录且不带 `--allow-downgrade` 的 `install`，钩子回答放行而不是询问），除下面列出的本地 Git 命令外不运行任何程序。在 Codex 里，插件的 `mcp.json` 声明一个本地 MCP 服务器 `magos`：由 Codex 自己在插件目录里通过 git 启动（`git -c alias.magos-mcp=!<sh script> magos-mcp`：脚本依次选用 `python3`、`py -3` 或 `python`，运行 `scripts/magos_guard.py mcp`），经标准输入输出通信，不联网。它唯一的工具 `magos_approve` 为一条用户专属的守卫命令弹出 Codex 自己的对话框（只有一个 Approve 勾选框：先勾选，再点 Accept 接受），只有你接受之后，才在指定的仓库里以 `scripts/magos_guard.py` 运行这条命令；级别为 `terminal`，或 Codex 自己拒绝（批准策略为 `never`）时，什么都不运行。在 Hermes 里，插件的 `__init__.py` 注册两个 `pre_tool_call` 回调：对每一次 `terminal` 调用，它们把插件自己的 `scripts/magos_guard.py hook hermes pre-tool` 作为本地进程启动（Python，不经 shell，最多 25 秒），由它回答放行、拒绝，或对直接调用的一条用户专属守卫命令，回答带一次性令牌重写的命令和一句问话，由 Hermes 在自己的批准提示里问你；插件更新（`hermes plugins update magos`，然后重启）之后，这对每个使用该插件的 Hermes 用户都会发生，在 Hermes 的环境里设置 `MAGOS_GUARD=off` 或运行 `hermes plugins disable magos` 即可停止。任何宿主上，启动 `magos_guard.py mcp` 或 `hook` 的工具命令都会被拒绝；运行守卫时，子命令不是写在命令里、agent 可以运行的一个普通单词（例如来自变量、命令替换或 xargs）的工具命令同样会被拒绝，写在交给 shell 执行的 here-document 里也一样；超过钩子读取长度（200,000 个字符）且提到 MAGOS 的命令在任何宿主上都会被拒绝。插件的 `mcp.json` 及它启动的守卫文件随插件而来，Codex 的钩子条目来自 `install`；两者都是你信任的代码：钩子变化时 Codex 会在 `/hooks` 里再问你，MCP 服务器变化时不会。
- **读取什么。** 这次工具调用，以及你当前所在仓库的 Git 状态；只通过本地 Git 命令读取（`branch`、`check-ref-format`、`config`、`diff`、`for-each-ref`、`log`、`merge-base`、`rev-list`、`rev-parse`、`status`、`worktree`）。它从不运行与远程通信的命令。在 Hermes 里，钩子还会读取 Hermes 的 `config.yaml` 里的 `approvals` 设置（只读），以判断 Hermes 会不会问人。
- **写入什么。** 只写在该仓库的 `<git-common-dir>/magos/` 里：车道登记、计划记录、覆盖（override）记录、冲突记录（`<git-common-dir>/magos/denials/<fp>.json`：一次被拒绝的创建所冲突的分支，只供覆盖对话框显示，一小时内有效）和一份审计日志（时间、该仓库的 Git 用户名和邮箱以及账户的登录名、分支和它的文件、覆盖的理由、每次运行经哪条路径批准；覆盖的理由是你在终端里输入的，或是代理写的、经你点击批准的，日志里会标明）。在 Claude Code 与 Hermes 里，钩子请你批准一条用户专属的守卫命令时，还会在你点击之前写一条批准记录，放在 `<git-common-dir>/magos/approvals/`：文件名是一次性令牌的 SHA-256（记录里没有令牌本身），记录两分钟内有效（Hermes 里是 Hermes 等你回答的时间，即 `approvals.timeout`，按 120 到 900 秒取值，加 30 秒，默认 330 秒），过期十分钟后由下一次批准清除；`install` 不属于任何仓库，它的记录改放在 `<guard home>/approvals/`（守卫目录是 `MAGOS_HOME`，没有设置时是 `~/.magos`），所以这一条是在你点击之前就写到该目录之外的。在 Codex 里，MCP 服务器在你接受之后才写这条批准记录，位置相同。除此之外，只有经你批准的运行（你在终端里运行，或在宿主自己的批准提示里点一下批准），才会在这个目录之外做两件事：`install` 把守卫复制到 `~/.magos/guard` 并打印一条配置，由你自己合并；`arm` 给该仓库加一个 Git `reference-transaction` 钩子。插件不修改 Claude Code、Codex 或 Hermes 的任何设置和权限规则。
- **发送与联网。** 守卫不发送任何数据，也不联网获取任何内容：没有网络访问、没有遥测、不接触凭据（包测试检查钩子代码不建立任何网络连接，且它的 Git 运行器拒绝所有与远程通信的子命令）。斜杠命令是写给 Agent 的指令：`/GitRecon`、`/GitAnalyze`、`/GitRecommend` 只读；会写入的五个命令只有你亲自输入才会运行（Claude Code 与 Codex 不让模型自己启动它们；Hermes 没有这个开关，适配层靠指令要求 Agent 只在你明确调用时运行），带有 `--apply` 的命令没有它就不会改动任何东西。联网只发生在你要求时：`--remote` 对你的远程运行 `git fetch --prune`，`/GitSweep --apply` 删除已合并的远程分支，`/GitSweep --apply --push` 推送一个分支。
- **关闭方法。** `git config --local magos.guard off`（单个仓库）、`claude plugin disable magos` 或 `hermes plugins disable magos`（整个插件）或 `MAGOS_GUARD=off`；见下文的“车道守卫”一节。

---

## 先用人话说明白（新手请先看这里）

> 完全没学过 Git 也没关系。下面用“几个人同时修改一份文稿”来打比方，把要用到的词讲清楚。

| 你会看到的词 | 用人话说 | 办公室比喻 |
|---|---|---|
| 仓库（repository） | 存放整个项目和它全部历史记录的文件夹 | 一个装满文稿和修订记录的档案柜 |
| 提交（commit） | 一次被记录下来的修改，带一个编号 | 文稿的一次“存档版本” |
| 分支（branch） | 一条独立的修改线路，各条线路互不干扰 | 每个人手里各自的“修订稿” |
| `main` | 通常是“正式稳定版”那条线路 | 已经定稿、对外发布的版本 |
| 合并（merge） | 把一条分支上的修改并进另一条分支 | 把几份修订稿汇总进总稿 |
| 工作区（worktree） | 某条分支正在被修改的那个文件夹 | 每个人各自的办公桌 |
| 远端（remote） | 放在网上（比如 GitHub）的那份仓库 | 公司共享网盘上的备份 |
| 预览 / 执行 | 先只看“打算怎么做”，满意了再真正去做 | 先看装修方案，点头之后才开工 |

**这套命令有一个统一的约定：先看，只在你下令时才动手。** 会真正改动仓库的五个命令（`/GitIntegrate`、`/GitCleanup`、`/GitConverge`、`/GitSweep`、`/GitPlan`）必须由你明确下令才会动手：`/GitCleanup`、`/GitConverge`、`/GitSweep`、`/GitPlan` 默认只预览，加 `--apply` 才执行（`/GitPlan` 收尾用的 `--release` 也会写入）；`/GitIntegrate` 没有预览模式，输入它就是下令集成，它先逐项过检查，全部通过才写入。只要遇到没把握的情况，它们会停下来告诉你原因，而不是硬做。

### 命令怎么写？

在 Claude Code 里直接输入命令，后面可以跟“参数”，参数之间用空格隔开：

```text
/命令名  必填的内容  --开关  --带内容的开关 内容
```

- `<尖括号>` 里的是**必填**内容，要换成你自己的，例如 `<分支名>` 换成 `agent/release`。
- `[方括号]` 里的是**可选**内容，可以不写。
- 以 `--` 开头的叫“开关”。有的单独写就生效（例如 `--apply`），有的后面要跟一个值（例如 `--lang English`）。
- 值里面有空格时，要用英文引号括起来，例如 `--lang "Brazilian Portuguese"`。
- 开关的先后顺序无所谓：`/GitConverge agent/release --apply --lang English` 和 `/GitConverge --lang English agent/release --apply` 是一样的。
- 输入 `--help` 随时可以看说明，它**只显示说明，不会查看或改动你的仓库**。
- 本文统一把命令写作 `/GitRecon`。实际要输入的名字随宿主和安装方式而定：例如从插件市场安装时，Claude Code 里是 `/magos:GitRecon`，Codex 里是 `$magos:git-recon`，Hermes 里是 `/magos:git-recon`。完整对照见“安装”一节。

---

## 三个通用参数

下面三个参数，在支持它们的命令里写法和意思都一样。先把它们弄懂，后面每个命令就都好理解了。

### `--help`：只看说明书

**写法**：`/命令名 --help`。放在命令后面的任何位置都行，也可以和别的参数写在一起；只要出现了 `--help`，就只显示说明。

```text
/GitConverge --help
/GitIntegrate agent/auth --strategy squash --help      ← 前面写了别的参数也没关系，只会显示说明
/GitRecon --help --lang English                         ← 用英文显示说明
```

| 项目 | 说明 |
|---|---|
| 它会做什么 | 显示：这个命令怎么写、每个参数是什么意思、不写参数时的默认行为、几个例子；然后立刻停止 |
| 它不会做什么 | 不读取你的仓库、不运行任何 Git 命令、不改动任何东西 |
| 什么时候用 | 忘了怎么写；不确定某个参数的意思；第一次用某个命令 |
| 哪些命令有 | 八个命令都有 |

> 记住：**拿不准的时候，先在命令后面加 `--help`，它是完全安全的。**

---

### `--remote`：先联网问一下最新情况

**写法**：`/命令名 --remote`，只是一个开关，后面不跟任何值。

```text
/GitRecon --remote
/GitAnalyze agent/auth --remote
/GitRecommend 哪些分支应该先合并 --remote
```

**不加和加上，区别在哪？** 举个例子：昨天你的电脑记下了“网上的 `main` 在第 100 号修改”，今天同事又上传了 3 个新修改。

| 写法 | 它是怎么判断的 | 可能的后果 |
|---|---|---|
| 不加 `--remote`（默认） | 只看你电脑里**已有**的记录，也就是“网上的 `main` 在第 100 号” | 速度快、不需要网络，但结论可能已经过时 |
| 加了 `--remote` | 先联网更新记录，知道“网上的 `main` 现在在第 103 号”，再给结论 | 结论更新，但需要网络，慢一点 |

**它具体做了什么？** 等同于让 Git 更新“远端分支的清单和它们的最新位置”，并清掉网上早已删除的分支留在你电脑里的旧记录。
**它不会做什么**：不会把网上的修改合并进你的分支，不会改动你本地的任何分支和文件，也不会上传任何东西。

| 项目 | 说明 |
|---|---|
| 哪些命令有 | 只有三个“只看”的命令：`/GitRecon`、`/GitAnalyze`、`/GitRecommend`。`/GitSweep` 有一个同名但不同的参数 `--remote <名字>`：后面必须跟远端名，只用来指定要清理哪个远端，从不刷新记录。写在其他命令后面会被当成“不认识的参数”，它会提示并显示说明 |
| 没有网络、或没有访问权限 | 它会说明联网失败，并注明“这次的结论只基于电脑里已有的记录” |
| 什么时候该加 | 你刚听说同事上传了新东西；或者你要依据“网上现在的样子”做决定 |

---

### `--lang <语言>`：让它用哪种语言回答你

**写法**：`--lang 语言`。`--lang` 后面**必须**跟一个语言，中间用空格隔开。

```text
/GitRecon --lang English
/GitAnalyze agent/auth --lang 日本語
/GitConverge agent/release --lang "Brazilian Portuguese"
/GitRecommend 哪些分支应该先合并 --lang en
```

**能写哪些语言？** 写名字或常见代码都可以，模型会写的语言基本都行：

| 想要的语言 | 可以这样写 |
|---|---|
| 中文 | `中文`、`简体中文`、`zh`（也是不写时的默认值） |
| 英文 | `English`、`en` |
| 日文 | `日本語`、`ja` |
| 韩文 | `한국어`、`ko` |
| 法文 / 德文 / 西班牙文 | `Français` / `fr`、`Deutsch` / `de`、`Español` / `es` |
| 名字里有空格的 | 要加英文引号：`"Brazilian Portuguese"` |

**它控制什么？** 它回复你的一切文字：说明、检查报告、向你提的问题、出错提示，以及 `--help` 的说明。

**哪些东西不会被翻译？** 命令名、参数名、分支名、文件路径、提交编号、Git 命令，以及 `BLOCKED_DIRTY`、`MERGE` 这样的状态代码。因为你可能要原样复制它们去运行或搜索。它可能会在旁边用你选的语言加一句白话解释，例如英文回复里写成 `BLOCKED_DIRTY` (unsaved edits in its worktree)。

| 项目 | 说明 |
|---|---|
| 不写会怎样 | **用中文回复**。即使你是用英文提问的，也是中文 |
| 放在哪里 | 命令后面的任何位置。`/GitRecommend 哪些分支应该先合并 --lang English` 里，`--lang English` 会被先摘掉，你的问题就是“哪些分支应该先合并” |
| 写错了会怎样 | `--lang` 后面什么都没写，或写的不是一种语言（比如 `--lang xyz123`），它会用中文告诉你哪里不对并显示用法，**不会继续执行命令** |
| 会影响检查结果吗 | 不会。只换回复的语言，检查和判断的方式完全一样 |
| 哪些命令有 | 八个命令都有 |

---

## Why?

多 Agent 开发很容易变成：

```text
Agent A ─┐
Agent B ─┼── 同一个目录 ── 冲突 / 覆盖 / 历史混乱
Agent C ─┘
```

本 Skill 将其变成：

```mermaid
flowchart LR
    M["main"] --> A["Agent A<br/>Branch + Worktree"]
    M --> B["Agent B<br/>Branch + Worktree"]
    M --> C["Agent C<br/>Branch + Worktree"]

    A --> R["Review / Validation"]
    B --> R
    C --> R

    R --> Q["Merge Queue"]
    Q --> M2["main"]
```

核心原则：

> **One Agent Lane = One Branch + One Worktree**

---

## 核心能力

| 能力 | 说明 |
|---|---|
| Repository Recon | 主动调查 Branch / Worktree / HEAD / Dirty / Ahead-Behind |
| Dependency DAG | 判断 Agent 任务之间的依赖关系 |
| Worktree Isolation | 避免多个 Agent 修改同一个 Checkout |
| Rewrite Safety | 判断什么时候可以 Rebase，什么时候禁止重写历史 |
| Selective Integration | Merge / Squash / Cherry-pick 按实际情况选择 |
| Freshness Gate | 防止 Review 后 `main` 已变化却继续错误集成 |
| Merge Queue | 串行写入共享集成分支 |
| Safe Cleanup | 安全识别已完成 Branch / Worktree |
| Safe Rollback | 私有历史用 Reset，共享历史优先 Revert |
| Branch Strategy | 识别仓库实际遵循的分支模型（分支策略 / ブランチ戦略），按“多 Agent 并行是否安全”的清单审计，只给最小改动建议，从不替你改分支 |
| Lane Planning | 开工前把任务拆成文件互斥的 lane，用乐观锁登记；完成后按依赖顺序合并成一个整体 |

---

## 八个核心命令

| 命令 | 一句话 | 会改动你的仓库吗？ |
|---|---|---|
| `/GitRecon` | 给整个仓库做一次“体检” | 不会，只看 |
| `/GitAnalyze` | 深入检查某一条分支 / 工作区 | 不会，只看 |
| `/GitRecommend` | 根据真实情况，建议下一步怎么做 | 不会，只给建议 |
| `/GitIntegrate` | 把某个 AI 的成果安全地并进主线 | 会，但要先过一连串检查 |
| `/GitCleanup` | 清理已经完成的旧分支和工作区 | 默认不会；加 `--apply` 才会 |
| `/GitConverge` | 把所有分支的成果汇总到一条分支，只留 `main` 和它 | 默认不会；加 `--apply` 才会 |
| `/GitSweep` | 先做 `/GitConverge`，再一并清除远端已合并的分支 | 默认不会；加 `--apply` 才会（含删除远端分支）；再加 `--push` 才会把 `<branch>` 推送一次 |
| `/GitPlan` | 开工前先调查 Git 与代码，写出需求并把任务拆成文件互斥的车道，用需求表和车道表列出清单，之后按依赖顺序合并成一个整体，并在清单上补充每个车道的修改内容概要 | 默认不会；加 `--apply`（或收尾的 `--release`）才会：登记计划，再加 `--create` 才建车道的分支和工作区，`--converge --apply` 才合并，`--land` 再快进落地一次；从不推送、从不删除分支或工作区 |

每个命令都可以加 `--lang <语言>`（回复语言，不写就是中文）和 `--help`（只看说明）；三个只看的命令还有 `--remote`（`/GitSweep` 的 `--remote <名字>` 是另一个参数，见它自己的说明）。它们的详细用法见上面的“三个通用参数”，下面每个命令只写它**自己独有**的参数。

> **不知道自己有哪些分支和工作区？** 先运行 `/GitRecon`，它会把清单列给你。也可以在终端里运行 `git branch`（列出分支）和 `git worktree list`（列出工作区）。

---

### `/GitRecon`

**给整个仓库做一次“体检”，只看不改。**

适合：刚接手一个项目、有好几个 AI 同时在改代码、不知道现在到底有哪些分支和工作区的时候。

```text
/GitRecon
/GitRecon --remote
/GitRecon --lang English
```

它会调查：

```text
工作区（Worktrees）         有几个，各自在哪条分支上
分支（Branches）            各自的最新位置、有没有对应的网上分支
当前位置（HEAD）            现在停在哪里
没保存的修改（Dirty）       哪些工作区里有改了一半的文件
领先 / 落后（Ahead/Behind） 和主线相比，多了几次修改、少了几次修改
游离（Detached）            哪些工作区没挂在任何分支上
网上记录（Remote tracking） 本地分支对应哪条远端分支
已合并（Merge candidates）  哪些分支的内容早就进了主线
风险（Risk）                需要你留意的地方
```

#### 参数详解

`/GitRecon` 没有必填参数，直接输入就能用。可以加的参数：

| 参数 | 写法 | 作用 |
|---|---|---|
| `--remote` | `/GitRecon --remote` | 先联网更新“远端最新记录”再体检，详见上面的“三个通用参数” |
| `--lang <语言>` | `/GitRecon --lang English` | 用指定语言回复，不写则是中文 |
| `--help` | `/GitRecon --help` | 只显示说明 |

---

### `/GitAnalyze`

**深入检查某一条分支或某一个工作区，只看不改。**

适合：你想知道“这条分支现在能不能合并、能不能删”。

```text
/GitAnalyze agent/auth
/GitAnalyze ../wt-auth --remote
```

#### 参数详解

**`<分支名或工作区路径>`（必填）：要检查的对象**

| 项目 | 说明 |
|---|---|
| 写什么 | 两种都可以：**分支名**（终端里 `git branch` 能看到的名字，例如 `agent/auth`），或**工作区的文件夹路径**（例如 `../wt-auth`，也可以写完整路径） |
| 去哪找名字 | 运行 `/GitRecon`，清单里就有所有分支名和工作区路径 |
| 不写会怎样 | 它不会猜，会问你要检查哪一个，同时显示说明 |
| 写错了会怎样 | 提示找不到这个分支或路径，并让你再确认；不会去检查别的对象 |
| 分支名和路径重名 | 它会根据仓库的实际情况判断；如果判断结果会改变结论，它会把歧义告诉你，而不是随便选一个 |

**`--remote`（可选）**：先联网更新“远端最新记录”再分析，详见“三个通用参数”。**`--lang <语言>`（可选）**：回复语言，默认中文。

#### 它会检查什么、怎么看报告

它会找出：这条分支和主线的共同起点、领先落后多少、它独有的修改、改了哪些文件、有没有别的分支依赖它、能不能改写它的历史；最后分别给出 merge、rebase、cherry-pick、压缩（squash）、清理删除这几种操作“安不安全”的结论。示例：

```text
agent/auth

Ahead:     3          ← 比主线多了 3 次修改
Behind:    2          ← 比主线少了 2 次修改（主线上有它还没拿到的新修改）
State:     DIVERGED   ← 双方都有对方没有的修改，已经“分叉”
Depends:   agent/core ← 它建立在 agent/core 的基础上
Rewrite:   FROZEN     ← 不能随便改写它的历史，否则会牵连依赖它的分支

建议：
不要直接 rebase（重写历史）
先把主线同步进来，再重新验证
```

---

### `/GitRecommend`

**根据仓库的真实状态，给出下一步怎么做的建议，只给建议、不动手。**

适合：你拿不准下一步该怎么安排，比如“3 个 AI 该怎么分工”。

```text
/GitRecommend
/GitRecommend 下一步怎么安排 3 个 Agent
/GitRecommend 哪些分支应该先合并 --remote
```

#### 参数详解

**`[你想问的事]`（可选）：你的问题或想达到的目标**

| 项目 | 说明 |
|---|---|
| 怎么写 | 直接用自己的话写在命令后面，**不用加引号**，写多长都行 |
| 不写会怎样 | 它给出一份通用的“下一步建议”，覆盖当前所有分支和工作区 |
| 怎么写才好 | **越具体越好**：说清楚你想达成什么、有几个 AI、哪些分支最要紧 |
| 和其他参数混写 | 可以。`--remote`、`--lang English` 会先被摘出来，剩下的文字才是你的问题 |

写法对比：

```text
/GitRecommend                                          ← 通用建议
/GitRecommend 下一步怎么安排 3 个 Agent                ← 分工建议
/GitRecommend agent/auth 做完了，接下来该怎么收尾      ← 针对某条分支
/GitRecommend 给新任务找最合适的工作区 --lang English   ← 英文回复
```

**`--remote`（可选）**：先联网更新“远端最新记录”。**`--lang <语言>`（可选）**：回复语言，默认中文。

#### 报告长什么样

它会先调查，再按这个结构回答：观察到的事实、最大的风险、按顺序排好的建议、每条建议的理由、以及没法确定的事项。示例：

```text
Agent A → 可以继续并行
Agent B → 和 A 改的文件高度重叠，建议排队，等 A 做完
Agent C → 依赖 A，等待 A 完成

agent/old-ui → 看起来可以清理
agent/auth   → 别人依赖它，暂时不能改写
```

---

### `/GitIntegrate`

**把某个 AI（某条“工作线”）的成果，安全地并进主线。**

适合：某个 AI 说“我做完了”，你想把它的成果正式收进来。**它不会因为 AI 说一句“Done”就动手。**

```text
/GitIntegrate agent/auth
/GitIntegrate agent/auth --strategy squash
/GitIntegrate agent/auth --strategy cherry-pick --lang English
```

#### 参数详解

**`<工作线或分支名>`（必填）：要并入主线的那条分支**

| 项目 | 说明 |
|---|---|
| 写什么 | 分支名，例如 `agent/auth`（用 `/GitRecon` 能看到全部分支名） |
| 不写会怎样 | 它会问你要集成哪一条，**不会自己挑一条** |
| 并到哪里 | 并进仓库的“集成分支”，通常是 `main`；它会根据仓库的实际约定判断，判断不了就如实告诉你，不会猜 |

**`--strategy <方式>`（可选）：用哪种方式并入**

写法：`--strategy` 后面跟下面四个值之一。不写等同于 `--strategy auto`。

| 值 | 白话意思 | 适合什么情况 |
|---|---|---|
| `auto`（默认） | 让它根据仓库的习惯和你的审核结果，自己选最合适的方式 | 不确定选哪个时 |
| `merge` | 整体并入，并且**保留**对方每一次修改的记录（要不要再多加一条“合并记录”，按仓库自己的合并规则） | 想保留完整的修改过程 |
| `squash` | 整体并入，但把对方的所有修改**压成一条**记录（仓库的规则允许时才行） | 对方的修改很零碎，想让主线保持整洁 |
| `cherry-pick` | **只挑**已经确认没问题的那几条修改并入，其余不要 | 对方的成果只有一部分可以接受 |

三种方式在“修改记录”上的区别（`A、B` 是主线原来的记录，`C、D` 是这条分支的两次修改）：

```text
merge          A──B──────M       M 是新增的合并记录，C、D 的记录原样保留
                  \     /
                   C──D

squash         A──B──S           S 是一条新记录，里面包含 C 和 D 的全部修改；C、D 不单独进入主线

cherry-pick    A──B──C'          只把 C 复制过来；D 没有进入主线
```

| 如果… | 它会… |
|---|---|
| 值写错了，例如 `--strategy rebase` | 说明只支持 `auto`、`merge`、`squash`、`cherry-pick`，显示说明，**不继续执行** |
| 写了 `--strategy` 却没写值 | 同上，让你补上 |
| 选了 `cherry-pick`，但不知道你确认了哪几条 | **停下来问你**，需要你说明哪些修改已经审核通过，它不会替你猜 |
| 你指定的方式违反仓库规则或不安全 | 拒绝并说明原因，即使你明确指定了也一样 |

**`--lang <语言>`（可选）**：回复语言，默认中文。

#### 动手之前它会检查什么

逐项检查：有没有审核通过的依据、有没有依赖没完成的部分、主线在你审核之后有没有变过、这条分支在你审核之后有没有新修改、仓库规则是否允许。**任何一项没过就停下来告诉你，不会硬来。** 并入之后，它会重新验证主线；车道守卫已安装时，还会释放这条车道的登记（`magos_guard.py release --branch <分支> --reason integrated`）。

```mermaid
flowchart TD
    A["Agent Lane"] --> B["Refresh"]
    B --> C["Validation"]
    C --> D["Review"]
    D --> E["Freshness Check"]
    E --> F{"接受范围"}
    F -->|"全部"| G["Merge / Squash"]
    F -->|"部分"| H["Cherry-pick"]
    G --> I["Validate main"]
    H --> I
```

---

### `/GitCleanup`

**找出可以安全清理的旧分支和工作区。**

适合：项目里积了一堆已经做完的分支，想整理一下，又怕删错。

```text
/GitCleanup              ← 只列出清单，什么都不删
/GitCleanup --apply      ← 真的去删
/GitCleanup --lang English
```

#### 参数详解

`/GitCleanup` 没有必填参数。

**`--apply`（可选）：真正动手清理**

| 项目 | 说明 |
|---|---|
| 写法 | `/GitCleanup --apply`，只是一个开关，后面不跟值 |
| 不写会怎样 | **只预览**：列出“可清理的对象”和“不能清理的对象及原因”，什么都不删 |
| 写了之后做什么 | 对清单里“可清理”的对象，**逐个再检查一遍现状**，仍然安全才删：先移除它的工作区，再删除分支 |
| 预览和执行之间有对象变了 | 比如那条分支在预览之后又有了新修改：它会**跳过**这一个并告诉你，不会照着旧清单硬删 |
| 它绝对不会做 | 强制删除；清理有未保存修改、做到一半或带被忽略文件的工作区；删除含有“别处找不到的成果”的分支；运行整个仓库范围的 `git worktree prune`；删除 `main`、目标分支或你当前所在的工作区；也不会删除网上（远端）的分支（只有 `/GitSweep` 会删除远端分支） |

建议的用法：**先不加 `--apply` 看清单，满意了再加。**

**`--lang <语言>`（可选）**：回复语言，默认中文。

#### 预览里每个对象的状态

| 状态 | 白话意思 | 会被清理吗 |
|---|---|---|
| `SAFE_CANDIDATE` | 七个条件全满足，可以安全清理 | 加 `--apply` 才会 |
| `BLOCKED_DIRTY` | 它的工作区里有没保存的修改 | 不会 |
| `BLOCKED_UNIQUE_WORK` | 它上面有只存在于这里、别处找不到的成果 | 不会 |
| `BLOCKED_ACTIVE_OWNER` | 现在有人（或某个 AI）正在使用它：它的工作区被锁住、位于代理工具的工作区目录（`.claude/worktrees/`、`~/.codex/worktrees/` 或仓库文档指明的目录）下、记录里属于别人，或这条车道在车道守卫里有未结束的登记（`planned` / `active`）；干净不代表没人在用 | 不会 |
| `BLOCKED_DEPENDENCY` | 别的分支依赖它 | 不会 |
| `BLOCKED_NOT_INTEGRATED` | 它的内容还没完整并入主线 | 不会 |
| `BLOCKED_IN_PROGRESS` | 它的工作区里有操作做到一半（比如改写历史停在中途），看起来干净其实不是 | 不会 |
| `BLOCKED_IGNORED_FILES` | 它的工作区里有被 Git 忽略的文件（比如存放密码的 `.env`），删工作区会把它们一起删掉 | 不会（请自己先移走或删掉这些文件，再重新运行 `/GitCleanup`） |
| `UNKNOWN` | 有关键信息没查清楚：比如工作区没有记录归属（不确定有没有人在用），或者有两条分支的名字只差大小写 | 不会（没把握就不动） |

一个分支要同时满足下面七条，才会成为 `SAFE_CANDIDATE`：

```text
✓ 内容已经完整并入主线
✓ 它的工作区里没有未保存的修改
✓ 它的工作区里没有做到一半的操作
✓ 它的工作区里没有被 Git 忽略的文件
✓ 现在没有人在使用它（如果它有工作区，这个工作区要有记录的归属）
✓ 没有别的分支依赖它
✓ 没有只存在于它上面、别处找不到的成果
```

`main`、目标分支、远端默认分支（`origin/HEAD` 指向的分支）、仓库文档里写明长期保留或受保护的分支、你当前所在的工作区及其分支永远不会进入清理清单。

**注意：一条分支“很久没动”并不代表可以删**，它不会只因为“旧”就把分支列入清理清单。

---

### `/GitConverge`

**把仓库里所有分支的成果汇总进你指定的一条分支，然后只留下 `main` 和这一条分支。**

适合：几个 AI 各自开了一堆分支干完活，你想“收网”——把所有人的成果集中到一处，再把用完的分支清掉。

#### 先看一个例子

假设仓库里现在有这些分支：

```text
main           正式稳定版（有 1 处新修改）
agent/release  你想把所有成果汇总到这里
agent/a        小明做了 2 处修改
agent/b        小红做了 1 处修改（她的工作区在 ../wt-b，没有没保存的东西）
agent/c        内容早就被包含了，没有新东西
```

执行 `/GitConverge agent/release --apply` 之后：

```text
之前：  main  agent/release  agent/a  agent/b  agent/c      （5 条分支）
之后：  main  agent/release                                  （2 条分支）
        └─ agent/release 里已经有了 main、a、b 的全部成果
        └─ a、b、c 被删除，小红的工作区 ../wt-b 也一并清理
```

#### 开始之前：先确认三件事

1. **你要在“放着目标分支的那个文件夹”里运行它。** 目标分支（比如 `agent/release`）当前在哪个文件夹里被使用，就在那个文件夹里打开 Claude Code。如果目标分支正被另一个文件夹使用，它会拒绝并告诉你“请去那个文件夹运行”。
2. **这个文件夹里不能有没保存的修改，也不能处于“做到一半”的状态**（比如正在合并、正在改写历史）。否则它会拒绝并说明原因。
3. **目标分支不能是 `main`。** 要往 `main` 里合并成果，请用 `/GitIntegrate`。

#### 用法：三步走

**第 1 步：先预览（什么都不会改）**

```text
/GitConverge agent/release
```

它会列出一份“计划”：先合并哪些分支、按什么顺序、哪些分支会被删、哪些分支因为什么原因会被**保留**、最后会剩下哪些分支。示意：

```text
计划（这是预览，没有改动任何东西）
目标分支：agent/release

将要合并（按这个顺序）
  1. main        1 处新修改
  2. agent/a     2 处新修改
  3. agent/b     1 处新修改（工作区 ../wt-b 干净，合并后删除）
已经包含、只需删除：agent/c

被保留的分支：无
执行后只剩：main、agent/release
不会动：网上的分支、标签、别人正在用的工作区
```

**第 2 步：看懂计划**

预览里每个分支后面有一个合并状态（`MERGE`、`CONTAINED`、`BLOCKED_UNRELATED_HISTORY`、`BLOCKED_IN_PROGRESS`、`UNKNOWN`），还可以再带零个或多个“保留原因”（从 `BLOCKED_DIRTY` 到 `BLOCKED_UPSTREAM_OF_KEPT` 的六个）。下面是白话翻译：

| 状态 | 白话意思 | 会合并吗 | 会删除吗 |
|---|---|---|---|
| `MERGE` | 有新修改，要并进目标分支 | 会 | 合并后删除 |
| `CONTAINED` | 它的修改早就在目标分支里了 | 不用 | 删除 |
| `BLOCKED_UNRELATED_HISTORY` | 和目标分支毫无关系（比如单独放网页的 `gh-pages`） | 不会 | 保留 |
| `BLOCKED_IN_PROGRESS` | 有人正做到一半（改写历史、挑拣修改等），它的位置不可靠 | 不会 | 保留 |
| `BLOCKED_DIRTY` | 它的工作区里有没保存的修改 | 会（只合并已保存的部分） | 保留 |
| `BLOCKED_LOCKED` | 它的工作区被锁住了（有人或程序在用） | 会 | 保留 |
| `BLOCKED_ACTIVE_OWNER` | 工作区属于别的 AI / 工具，或是主工作区 | 会 | 保留 |
| `BLOCKED_IGNORED_FILES` | 工作区里有被 Git 忽略的文件（比如存放密码的 `.env`） | 会 | 保留（加 `--discard-ignored` 才删） |
| `BLOCKED_SUBMODULE` | 工作区带“子项目”，`git worktree remove` 拒绝删除它：它的 git 目录里有 `modules` 文件夹，或工作区里的子项目文件夹已经有内容。取消初始化也解除不了，这个命令删不掉这个工作区：确认里面没有独有的东西之后，请你自己用 `git worktree remove --force <path>` 删除，或者留着它；工作区还在时，分支也保留 | 会 | 保留 |
| `BLOCKED_UPSTREAM_OF_KEPT` | 另一条被保留的分支依赖它 | 会 | 保留 |
| `UNKNOWN` | 有关键信息没查清楚，或者它和另一条分支的名字只差大小写（两条都不动，报告会告诉你怎样安全地改名），或者它的名字不能安全地交给命令（含有 ASCII 字母、ASCII 数字和 `.` `_` `/` `+` `-` 以外的字符，或以 `-` 或 `+` 开头：它不动，处理办法是用 `git branch -m <old> <new>` 改名） | 不动 | 不动 |

保留原因只决定删不删，不拦合并；“会合并吗”一列写的是该分支有新修改（`MERGE`）时的情况，`CONTAINED` 的分支没有可合并的内容，带保留原因时只是不删。

预览里，`MERGE` 的分支后面可能带 `PREDICTED_CONFLICT`：Git 支持预演合并（`git merge-tree --write-tree`）时，会拿每个分支试合一次，试合出冲突就加这个标记。它还可能带 `PREDICTED_IGNORED_OVERLAP`：该分支改动的某个路径，与你运行命令所在文件夹里的某个被忽略的文件或文件夹相同，或在它的下面或上面，合并会覆盖被忽略的文件，执行时就会停下；报告会写出分支、路径和被忽略的条目。这两个标记都只是提示，不会改动任何分支和工作区；两条分支之间互相冲突的情况两种预演都看不出来，要到第二条合并时才会出现。要消除 `PREDICTED_IGNORED_OVERLAP`，请把报告里写出的、在你运行命令的文件夹里的那些被忽略的条目移走或删除（先留一份，因为 Git 没有记录它们；`--discard-ignored` 对它们不起作用），然后重新运行。

只要有分支被保留，计划里会明确告诉你：“最后不会只剩 `main` 和目标分支”，并写清楚原因和下一步该做什么。

没有锁、不在代理工作区目录（`.claude/worktrees/`、`~/.codex/worktrees/` 或仓库文档指明的目录）下、没有记录过负责人、车道守卫里也没有未结束的登记的干净工作区，即使没有记录负责人，也会随它的分支一起清理；计划里会逐个写明“负责人：未记录”。这一点和 `/GitCleanup` 不同：`/GitCleanup` 对没有记录负责人的工作区一律不动。

**第 3 步：满意了，再执行**

```text
/GitConverge agent/release --apply
```

它会重新检查一遍现状，把这次要做的计划记下来，按计划逐个合并，然后删除已经合并的分支和它们干净的工作区，最后给你一份报告。报告里有：它依据的计划、做了什么、跳过了什么（和原因）、目标分支的起点和终点编号、最后剩下的本地分支、校验结果、每个被删分支原来的编号。

#### 参数详解

**`<分支名>`（必填）：所有成果汇总到哪条分支**

| 项目 | 说明 |
|---|---|
| 写什么 | 一条**本地**分支的名字，例如 `agent/release`。用 `/GitRecon` 或终端的 `git branch` 能看到名字 |
| 要写得**完全一样** | **区分大小写**。`agent/release` 对，`Agent/Release` 不对：它会拒绝，并提示你正确的名字 |
| 不能写什么 | `main`（它永远不会被移动）；不存在的分支；网上的分支名（如 `origin/xxx`）；文件夹路径 |
| 不写会怎样 | 它会问你，并显示说明 |
| 提醒 | 目标分支必须是一条现有的本地分支，它不会替你新建 |

**`--apply`（可选）：真正去合并和删除**

| 项目 | 说明 |
|---|---|
| 写法 | `/GitConverge agent/release --apply`，只是一个开关，后面不跟值 |
| 不写会怎样 | **只预览**，什么都不改。这也是默认行为 |
| 写了之后做什么 | 重新检查现状 → 记下计划 → 先切换到目标分支（如果当前不在上面） → 按顺序逐个合并 → 校验 → 逐个再确认后删除 → 出报告 |
| 合并顺序 | `main` 最先；其余的按“新修改多的优先”，同样多的按名字排序。这样如果甲包含乙，合到甲时乙就已经被带进来了，不会重复合并 |
| 遇到冲突 | 立刻撤销这一次合并，**整体停下，什么都不删**；已经成功的合并保留 |
| 校验 | 能识别出仓库自己的检查（如测试）时才会运行；检查因这次合并而失败，就在删除之前停下并报告；识别不出来时，报告里写“未校验”并继续，删除仍要通过逐个复查 |
| 删除之前 | 每个分支都会再确认：没有新修改、内容确实已经在目标分支里、它的工作区仍然干净 |
| 之前预览过 | 如果你在同一次对话里先预览过，执行时会和那次预览对比：只要有分支的位置变了，就停下来重新给你预览；预览之后新出现的分支或工作区一律不碰 |

**`--discard-ignored`（可选）：允许清理含“被忽略文件”的工作区**

什么是“被忽略文件”？有些文件（比如存放密码和密钥的 `.env`、临时文件夹 `node_modules/`）不会被 Git 记录，所以**一旦删掉就找不回来**。

| 项目 | 说明 |
|---|---|
| 写法 | `/GitConverge agent/release --apply --discard-ignored`，开关，不跟值 |
| 不写会怎样 | 工作区里只要有被忽略文件，这个工作区和它的分支就**被保留**（状态是 `BLOCKED_IGNORED_FILES`），预览里会把这些文件逐个列给你 |
| 写了之后 | 这样的工作区会被清理，**里面被忽略的文件会随之永久消失** |
| 单独写有用吗 | 没有。它只在写了 `--apply` 时才有意义 |
| 什么时候该写 | 你看过预览里列出的被忽略文件，确认都不需要了（比如只是可以重新生成的临时文件） |

> 它**永远不会**覆盖你当前文件夹里已有的被忽略文件：如果某个分支带来的文件会覆盖它们，命令在合并那个分支之前停下并告诉你，不删除任何分支；此前已经完成的合并保留。这和 `--discard-ignored` 无关。

**`--lang <语言>`（可选）**：回复语言，默认中文。**`--help`（可选）**：只显示说明。

示例：

```text
/GitConverge agent/release                              只看计划
/GitConverge agent/release --apply                      照计划执行
/GitConverge agent/release --apply --lang English       照计划执行，用英文回复
/GitConverge agent/release --apply --discard-ignored    连带清理含 .env 的工作区
```

#### 它会拒绝执行的几种情况

下面这些情况，它会**在动手之前**就停下并说明原因，对仓库不做任何改动。没通过的门槛会一次全部列出，每一项都附带处理办法，一次运行就能看到要先清掉的全部事项：

| 情况 | 它会怎么说 | 你该怎么办 |
|---|---|---|
| 目标分支不存在，或大小写不对 | 找不到这个分支；如果只是大小写不同，会告诉你正确的名字 | 用现有的准确名字重新运行，绝不要新建一条只和现有分支差大小写的分支。要新建一个在任何大小写下都不存在的目标分支，先用 `git for-each-ref --format=%(refname) refs/heads` 确认没有任何分支叫这个名字，再运行 `git branch <name> <start>` |
| 目标分支是 `main` | `main` 不能当目标 | 改用 `/GitIntegrate`，或换一条分支 |
| 本地没有 `main` 分支 | 缺少 `main` | 先在仓库里建好 `main`（远端跟踪分支存在时用 `git branch main <remote>/main`；主干叫别的名字（如 `master`）的仓库也需要一条叫 `main` 的分支，请在主干的末端用 `git branch main <trunk>` 建一条，或者不要用这个命令） |
| 目标分支或 `main` 和另一条分支的名字只差大小写 | 名字冲突，分不清是哪一条 | 先运行 `git pack-refs --all`，再用 `git branch -m` 改掉其中一条的名字，然后核对两条分支的提交（不先 pack 就直接改名，可能把另一条分支的提交挪过来并删掉两条） |
| 目标分支正被别的文件夹使用 | 请去那个文件夹运行 | 到它指出的文件夹里重新运行 |
| 当前文件夹有没保存的修改、没挂在分支上、或做到一半 | 当前文件夹不安全 | 先保存或处理好，再重新运行 |
| 目标分支或 `main` 只存在于一个已被删掉的文件夹的记录里 | 记录残缺，没法切换 | 按提示清理那条残缺记录后再运行 |

#### 它一定遵守的规则

```text
✓ 默认只预览。不加 --apply 就不会改动任何东西
✓ main 只被“读取”：不会被移动、重置或删除
✓ 网上的分支、标签、没挂在分支上的工作区，一律不碰；也不会替你上传到网上
✓ 遇到合并冲突就立刻撤销这一次合并并停下，不会删除任何分支；已经完成的合并保留
✓ 有没保存修改、被锁住、做到一半、属于别人的工作区：保留它和它的分支
✓ 绝不覆盖你电脑里被忽略的文件（如 .env）；含这类文件的工作区默认保留
✓ 不用“强制删除”，不用“强制清理工作区”，不做全仓库的“清理悬空记录”
✓ 删每一个分支之前再确认一遍：它没变过、内容确实已在目标分支里
```

#### 出了意外怎么办

- **提示“合并冲突”**：意思是两条分支改了同一个地方、改法还不一样，机器没法替你选。它会把这次合并撤销、停下，**什么都不会删**，并告诉你是哪条分支冲突。你处理完（或者删掉不要的那条分支）再重新执行一遍，已经合并成功的分支会被当作“已包含”，只做删除。
- **想找回被删掉的分支**：报告里有每个被删分支原来的编号（一串字母数字，比如 `8eccc62`）。拿着编号可以随时恢复：

  ```text
  git branch agent/a 8eccc62
  ```

- **想整体撤销这次汇总**：报告里有目标分支的“起点编号”。有 Git 基础的人可以把目标分支改回起点；没基础的话，把这份报告发给懂 Git 的同事或 AI，让他们来处理。
- **不确定该不该动手**：永远可以先不加 `--apply`，只看计划。

#### 常见疑问

- **会不会删掉我还没保存的修改？** 不会。有没保存修改的工作区会连同它的分支一起被保留。
- **会影响 GitHub 上的分支吗？** 不会。它不上传、不删除任何网上的东西。汇总完之后要不要上传，由你自己决定。
- **为什么有些分支没被删？** 看计划里的“状态”表，每一个被保留的分支都写了原因和下一步该做什么。
- **执行到一半断了怎么办？** 重新执行同一条命令即可。它每次都会先重新检查现状，已经合并过的分支只会被删除，不会重复合并。
- **我想让回复是英文？** 在命令最后加 `--lang English`。

```mermaid
flowchart TD
    A["预览计划"] --> B["逐个 merge --no-ff"]
    B -->|"冲突"| X["abort，停止，不删除任何分支"]
    B --> C["校验"]
    C --> D["逐个复查：tip 未变 + 已是 target 祖先"]
    D --> E["worktree remove → branch -d"]
```

---

### `/GitSweep`

**在 `/GitConverge` 的基础上，再一并清除远端已经合并的分支。**

适合：本地已经“收网”，想把 GitHub 等远端上用完的分支也一起清掉，不用再手工逐条删。

分两步，且只有加 `--apply` 才会动手：

1. **本地收敛**：和 `/GitConverge` 完全一样（同样的检查、同样的合并顺序）。遇到冲突或检查失败就整个停下，本地、远端都不会删任何东西。
2. **清除远端**：只删除“提交已经被远端自己保留的分支包含”的远端分支，也就是已并入远端默认分支或远端的 `<branch>` 的那些。判断“已并入”时，`<branch>` 按收敛之后的样子计算（本地的 `<branch>` 加上将被合并进来的各分支），所以预览和随后的执行会给出同样的分类。只在你本地合并过、还没推送的分支，只要 `<branch>` 的推送预计会执行，就标成 `PUSH_THEN_DELETE`（预览里不管有没有写 `--push` 都这样标）：加了 `--push`，它们会在同一次运行里被清除（见下面的 `--push`）；不加 `--push`，运行会留着它们，报告里写明保留的原因是没写 `--push`，要等你加上 `--push` 重跑，或者等本地 `<branch>` 已经包含它的提交之后，自己把 `<branch>` 推上去，再跑一次 `/GitSweep`。

```text
/GitSweep agent/release                          只看计划（不联网）
/GitSweep agent/release --apply                  照计划执行
/GitSweep agent/release --apply --push           照计划执行，并把 agent/release 推送到远端一次
/GitSweep agent/release --apply --remote upstream   清理 upstream 而不是 origin
```

**参数**：`<branch>`（必填，接收所有成果的本地分支）、`--apply`（才真正执行）、`--discard-ignored`（原样交给第一步，允许清理含 `.env` 的工作区）、`--push`（可选，要和 `--apply` 一起写：本地收敛之后、删除远端分支之前，把 `<branch>` 推送到远端一次）、`--remote <名字>`（要清理的远端，默认 `origin`，必须是 `git remote` 列出的名字，否则门槛不通过；注意它和只看命令里的 `--remote` 开关不同，后面要跟名字，也不会 fetch）。

**`--push` 到底做什么？** 它只多做一件事，而且命令固定、不会变：`git push --recurse-submodules=no --no-follow-tags <远端> refs/heads/<branch>:refs/heads/<branch>`。这是一次“快进”推送：绝不强推，绝不跳过钩子（`--no-verify`），也不推标签；远端还没有 `<branch>` 时会新建它，计划和报告都会写明。推出去的是收敛之后的本地 `<branch>` 里远端的任何分支都还没有的提交，预览会把它们列出来（已有的提交，会给出数量，以及将被合并进来的分支）；执行时每合并一个分支最多再多出一个合并提交，所以最多再多推这么多个提交，报告里会写出确切的范围和数量。不管有没有写 `--push`，预览都会根据本地记录预测这次推送：会不会执行、会推出哪些提交、会不会新建远端分支，以及哪些 `PUSH_THEN_DELETE` 分支依赖它；预计不会执行时，写明是哪个条件不满足（例如 `<branch>` 就是远端默认分支）。这样，只合并进本地 `<branch>` 的远端分支，就能在同一次运行里被清除，不用先手动推送、再跑第二遍。远端的 `<branch>` 已经停在本地的位置时，没有什么可发布的：不推送，报告写 `PUBLISH_NOT_NEEDED`。其余情况下，即使没有远端分支依赖这次推送，也照样推送，因为 `--push` 就是你要求发布 `<branch>`。

下面任何一种情况，推送都会被跳过，报告里写明原因（`PUSH_SKIPPED`）：远端上的 `<branch>` 不是本地 `<branch>` 的祖先（别人推送过新提交，请先 `git fetch <远端>` 并把它合并进来）；`<branch>` 是 `main` 或远端的默认分支；本地收敛中途停止，或它之后的校验失败；整个远端清理是 `UNKNOWN`。前两种情况下，不依赖推送的远端删除照常进行；后两种情况下，一条远端分支也不会删。推送被拒绝或出错（受保护分支、钩子、网络）时，命令不重试、不换写法，标为 `PUSH_FAILED`；推送成功之后会核对远端的 `<branch>` 是否停在本地的位置，不一致就标为 `PUSH_UNCONFIRMED`，按失败处理。推送一旦完成，撤销它需要强推，而这个命令从不强推：所以 `--push` 是你明确授权的一次发布。不写 `--push` 或不写 `--apply`，命令都不会发布任何提交（只写 `--apply` 时，仍会删除下文所述的已合并远端分支）。

**预览的结尾：一次完成就绪度。** 预览除了计划，最后还会告诉你这条命令能不能一次做完。“做完”的意思是：本地只剩 `main` 和 `<branch>`，被删除分支的工作区都已移除，远端的分支不是已被删除就是受保护。命令从不去碰的工作区（没挂在分支上的，或挂着 `main` 或其他保留分支的）不属于这个状态，报告会把它列出来。结论评判的是推荐命令（见下），而不是你敲的那条命令。预览显示的是这条命令会到达的状态（比如，推荐 `--discard-ignored` 时，唯一阻塞是被忽略文件的工作区按已清除计算，所以同名的远端分支不会被它拖住）；执行只按你写的开关办事：不写 `--discard-ignored`，这样的工作区和它的分支都留着，同名的远端分支是 `KEPT_LOCAL`。结论有三种：

| 结论 | 含义 |
|---|---|
| `ONE_SHOT` | 没有门槛失败；每个分支都能合并或已被包含，剩下的唯一阻塞只能靠 `--discard-ignored` 解除；没有预计冲突，也没有预计的被忽略文件覆盖，远端清理不是 `UNKNOWN`；每个远端分支都是 `SAFE_CANDIDATE`、`PUSH_THEN_DELETE` 或 `NOT_TOUCHED`。运行推荐命令一次就够（以本地记录能看到的为限，执行时会再核对远端） |
| `PARTIAL` | 没有门槛失败，但还有开关解不开的事项（别的删除阻塞项、做到一半的操作、历史无关的分支、`UNKNOWN`、预计冲突、预计的被忽略文件覆盖、没合并的远端分支、名字不能交给命令的远端分支、预计不会执行推送的 `PENDING_PUSH` 等）。推荐命令照样做它能做的一切，其余的逐项列出：每一项都写明证据、处理办法，以及处理完要不要再跑一次 |
| `BLOCKED` | 有门槛没通过，什么都不能执行（`--remote` 写了 `git remote` 没有列出的名字，也是门槛之一）。所有没通过的门槛一次列全，每一项都附带处理办法 |

**推荐命令**是完整的一行 `/GitSweep <branch> --apply`（你怎么写，它就怎么写，`--remote <名字>` 和 `--lang <语言>` 照抄），只带真正能解除事项的开关：`--discard-ignored` 只在某个工作区唯一的阻塞是被忽略文件时才带，并把将被删除的被忽略文件逐个列在旁边；`--push` 只在有远端分支会是 `PUSH_THEN_DELETE` 时才带（不管你有没有写 `--push`），或者你写了 `--push` 而且推送预计会执行时才带，并把将发布的提交数和是否会新建远端分支写在那一行旁边。你写了 `--push` 但推送不会执行时，它会从那一行里去掉，报告会写明原因。除了你写了而且会执行的 `--push`，没有用的开关绝不推荐，会丢文件或会发布提交的开关绝不会被悄悄加上。开关按 `--apply`、`--discard-ignored`、`--push`、`--remote`、`--lang` 的顺序排列。

**执行报告的结尾：运行状态。** `COMPLETE` 表示目标状态已经达成；`PARTIAL` 表示还有遗留事项：报告列出每一项和它的处理办法，最后是两行，顺序固定。处理办法会改动仓库，而计划比仓库旧的执行会停下并给出新的预览，所以处理完之后第一次运行的是预览：`Next preview:` 是同一行去掉 `--apply`，在处理完之后先运行它，让这次预览成为之前的计划；`Next command:` 是预览之后要运行的那一行（预览推荐了另一行时，运行推荐的那一行）。两行都按推荐命令的同样规则和同样的开关顺序生成，所以 `--remote` 和 `--lang` 照抄。`Next command:` 这一行在下面几种情况下带上 `--push`：有远端分支停在 `PUSH_THEN_DELETE` 或 `PENDING_PUSH`，而且原因是加上 `--push` 重跑可以消除的；或者你写了 `--push`，而且按发布预测推送仍会执行。唯一的原因是 `<branch>` 就是远端默认分支时，它不带 `--push`；远端清理是 `UNKNOWN` 时，只有你写了 `--push` 才带。没有任何重跑能改变结果时，这两行都省略。

**哪些远端分支会被留下**（报告里逐条标出原因）：

| 状态 | 含义 |
|---|---|
| `PUSH_THEN_DELETE` | 只在本地并入了 `<branch>`，而且 `<branch>` 的推送预计会执行（预览里不管有没有写 `--push` 都会这样标）。加了 `--push`，执行时先推送 `<branch>`，再删除它；没加 `--push`，执行时不动它，报告写明保留的原因是没写 `--push`。出路有两条：加 `--push` 重跑（先运行 `Next preview:` 那一行，再运行 `Next command:` 那一行），或者等本地 `<branch>` 已经包含它的提交之后（它的提交只靠一条还没合并的分支带进来时，先不加 `--push` 执行一次 `--apply`），自己 `git push <远端> refs/heads/<branch>:refs/heads/<branch>` 之后重跑 |
| `PENDING_PUSH` | 只在本地并入了 `<branch>`，远端还没有，而且这一次运行里没有任何推送能清掉它：推送预计不会执行（例如 `<branch>` 就是远端默认分支，或远端上的 `<branch>` 不是本地 `<branch>` 的祖先），或者执行时推送被跳过、失败、没能确认（报告会写明是哪个条件）。先处理那个条件，再重跑 |
| `KEPT_NOT_MERGED` | 还有远端没有保留的提交，不删 |
| `KEPT_LOCAL` | 同名本地分支在本地收敛之后仍然保留（被阻塞、历史无关、做到一半、`UNKNOWN`，或预览之后才出现），远端也留着 |
| `STALE` | 执行时发现这条远端分支有了新提交或已不在远端，跳过 |
| `NOT_TOUCHED`（受保护） | 远端默认分支、`main`、`<branch>`、`HEAD`、由其他拉取规则写入的记录（如 `refs/remotes/<远端>/pr/*`），以及仓库文档里写明或有证据表明是长期分支（集成 / 预发 / 发布 / 归档）的分支（证据是：策略文件、CI 触发过滤、对得上的发布标签，或这条分支与远端保留的某条分支之间至少有两次合并提交；一次合并只是车道合并，只凭名字猜出的角色不算） |
| `BLOCKED_UPSTREAM` | 一条会保留的本地分支以它为上游 |
| `BLOCKED_BAD_NAME` | 分支名含有 ASCII 字母、ASCII 数字和 `.` `_` `/` `+` `-` 以外的字符（比如中文或日文名字），或以 `-` 或 `+` 开头，或 `git check-ref-format --branch` 不通过，不会交给任何命令 |
| `UNKNOWN` | 有关键信息没查清楚：只差大小写的两条远端分支都不动；远端默认分支不明（没有 `refs/remotes/<远端>/HEAD`，请运行 `git remote set-head <远端> --auto`）、`remote.<远端>.fetch` 缺少 `refs/heads/*:refs/remotes/<远端>/*` 映射、远端有多个地址或推送地址与拉取地址不同（推送会发往每一个地址）、或 `--apply` 联网核对时远端的 `HEAD` 没有指向任何分支时，整个远端清理标为 `UNKNOWN`（本地收敛照常完成） |

只有 `SAFE_CANDIDATE`（已并入远端保留的分支，且以上都不适用）的远端分支会被删除。

留下来的每一项，报告都写出处理办法（处理之后重新运行：先预览，再执行）：`--remote` 写了 `git remote` 没有列出的名字，改成列出的远端（`git remote -v`），或用 `git remote add <名字> <地址>` 添加；`UNKNOWN` 按上表补全信息（远端有多个地址，或推送地址与拉取地址不同时，只留一个地址，拉取和推送用同一个：对每个多余的地址运行 `git remote set-url --delete <远端> <extra-url>`，单独设了推送地址时再运行 `git config --unset-all remote.<远端>.pushurl`；远端的 `HEAD` 没有指向任何分支时，在远端或它的托管平台上设置默认分支，因为 `git remote set-head <远端> --auto` 解决不了）；没写 `--push` 而保留的 `PUSH_THEN_DELETE` 加上 `--push` 重跑（先运行 `Next preview:` 那一行，再运行 `Next command:` 那一行），或者等本地 `<branch>` 已经包含它的提交之后，自己 `git push <远端> refs/heads/<branch>:refs/heads/<branch>` 之后重跑；`PENDING_PUSH` 先处理报告写明的那个条件，再重跑（`<branch>` 是远端默认分支：自己发布，或走你们的评审流程，命令从不推送远端默认分支；远端的 `<branch>` 不是本地的祖先：`git fetch <远端>` 并把它合并进 `<branch>`，再加 `--push` 重跑；推送失败或被拒绝：满足托管平台的规则（分支保护、钩子）后加 `--push` 重跑，或者自己发布；整个远端清理是 `UNKNOWN`：补全那条信息）；`PUSH_SKIPPED`、`PUSH_FAILED`、`PUSH_UNCONFIRMED` 处理报告写明的条件（拉取并合并更新的远端提交，或满足托管平台的分支保护），或自己发布，然后重跑；`KEPT_LOCAL` 先处理那条本地分支的阻塞；`BLOCKED_UPSTREAM` 在以它为上游的本地分支上运行 `git branch --unset-upstream <分支>`；`KEPT_NOT_MERGED` 请审查后合并进 `<branch>`，或在托管平台上自己删除（命令绝不会替你删；合并之后，预览会把它列为 `PUSH_THEN_DELETE` 并推荐 `--apply --push`，推送预计不会执行时则列为 `PENDING_PUSH` 并写明条件）；`BLOCKED_BAD_NAME` 在托管平台上删除或改名。

`--apply` 会在本地收敛完成之后，才联网核对一次远端。如果远端当前的默认分支和记录对不上（远端的 `HEAD` 没有指向任何分支，也算对不上），或者它用来判断“已合并”的保留分支（远端默认分支、远端上的 `<branch>`）和记录对不上，整个远端清理都不做，不删任何远端分支（本地收敛的结果保留）；请先 `git fetch <远端>`（默认分支变了，再加 `git remote set-head <远端> --auto`）再重跑。如果只是某条待删的远端分支与记录对不上，或已经不在远端，只跳过这一条，标为 `STALE`。加了 `--push` 时，也在这一次核对里记下远端 `<branch>` 现在的位置，推送前据此确认它是本地 `<branch>` 的祖先。

它**绝不会**：推送提交或标签（唯一的例外，是加了 `--push` 时对 `<branch>` 的那一次快进推送）、强推、没写 `--push` 就发布、删除远端默认分支 / `main` / `<branch>` 本身、删除没有并入的远端分支。每条远端分支单独删除，并带上“远端仍停在记录的 SHA”的保护，对方期间有新提交就会拒绝。推送绝不会到达你指定的远端之外的仓库，也绝不会递归进子模块：两条推送命令都带 `--recurse-submodules=no`，远端有多个地址时整个清理标为 `UNKNOWN`。每条 git 命令都以参数列表运行，绝不拼成 shell 字符串；待收敛的来源分支，以及不属于 `NOT_TOUCHED` 的远端分支，只要名字含有 ASCII 字母、ASCII 数字和 `.` `_` `/` `+` `-` 以外的字符（或以 `-` 或 `+` 开头），就绝不会交给命令。删除远端分支会让以它为源的未合并 PR 被关闭；在一些平台上，以它为目标的 PR 也会被关闭或改指向别处，请先确认，预览看不到它们。报告里会列出每条被删分支的 SHA，可用 `git push <remote> <sha>:refs/heads/<name>` 恢复。

---

### `/GitPlan`

**在子 Agent 开工之前，先调查 Git 与代码，写出任务的需求，把任务拆成文件互斥的几条“车道”（lane），并用两张表给你一份简明清单：需求、承担它的车道和计划成果的对应关系一目了然；任务做完后，再按依赖顺序把它们合并成一个整体，并在最初的清单上补充每个车道改了什么。**

适合：你要让几个 AI 并行完成同一个任务，想先把“要达成什么、谁来做、谁改哪些文件”说清楚，并且在最后合并时有一份清单当 TODO 对照，合并完还能看到每个车道的修改内容概要。

这份清单有三个用途：开工前，它是**你审阅的计划**；任务做完、合并时，它是**合并时的 TODO 参考**：`--status` 和 `--converge` 会按记录重新打印这两张表，标出每个车道的状态，再列出“还剩什么”；车道合并之后，它还是**结果汇总**：原来的每一行、每一列都保留，补上每个车道的修改内容概要。默认只预览，只有 `--apply`（以及收尾的 `--release`）才写入；写入只经过车道守卫 `magos_guard.py` 的 `set-plan`、`set-update`、`set-release`。它从不推送、从不强推、从不删除分支或工作区，也从不动 `main`。

先认几个词：

| 词 | 用人话说 |
|---|---|
| set（计划） | 一次任务拆分的名字，例如 `sweep-readiness`，写法是 `[a-z0-9][a-z0-9-]{0,23}`，区分大小写，也不能是 Windows 的设备名（`con`、`nul`、`com1` 等）。计划记录和各车道的登记都用这个名字，它也是各车道分支和工作区名字的一部分 |
| requirement（需求） | 任务要达成的一个结果，一句话，编号 `R1`、`R2`……。每条需求至少由一个车道承担，每个车道至少承担一条需求；没有车道承担的需求，守卫会拒绝（退出码 24） |
| lane（车道） | 一个子 Agent 用的分支加工作区，外加一份“它能改哪些文件”的清单（manifest）和它要交付的成果（outcome）。各车道的清单两两不相交，所以不会互相覆盖。车道的 id、分支和工作区都以修改内容的主题命名，见下面的“命名规则” |
| 清单（sheet） | 不超过 8192 个字符的简明清单：一张需求表（需求、承担它的车道、计划成果）和一张车道表（分支、工作区、负责的文件、依赖、验收标准），再加一行合并、共享文件的归属和最多 5 条风险 |
| 集成分支 | `agent/<set>/integration`，各车道合并之后的“整体”落在这里 |
| revision 与 base | 计划的版本号，以及计划所依据的目标分支提交；用来发现过期的计划（见下面的“乐观锁”） |

#### 用法：四步走

**第 1 步：先预览（什么都不会改）**

```text
/GitPlan sweep-readiness --into develop
```

它先调查 Git（分支、工作区、已有的车道登记、目标分支的最新提交；远端新旧只按本地记录判断，不联网）和代码（目录结构、入口、构建与测试命令、共享文件、最常被改动的文件、文件之间的引用），再写出任务的需求（`R1`、`R2`……）并拆分任务，用 `magos_guard.py set-plan --dry-run` 证明各车道的文件清单两两不相交、每条需求都有车道承担；最后给出需求表、车道表和结论 `READY` 或 `BLOCKED`，每个没通过的门槛都附带处理办法，报告里还有一段“命名”，说明每个车道的名字取自哪条需求和哪些文件，以及一段“修正”，列出守卫拒绝之后执行者改了 spec 的哪些地方。预览唯一的写入，是放在所有工作区之外的一个临时 spec 文件。表格取自守卫证明过的 spec，清单长这样：

```text
# 计划 sweep-readiness -> develop  base 3fa9c21
## 需求
| 编号 | 需求 | 承担的车道 | 计划成果 |
|---|---|---|---|
| R1 | 所有 claim 都从同一个存储读取 | claim-store | claim-store: src/claims 读取所有 claim |
| R2 | 清扫的就绪结论有文档说明 | sweep-docs | sweep-docs: docs/sweep.md 讲清就绪结论 |
| R3 | 现有的清扫测试和文档里的示例仍然通过 | claim-store, sweep-docs | claim-store: src/claims 读取所有 claim; sweep-docs: docs/sweep.md 讲清就绪结论 |
## 车道
| 车道 | 分支 | 工作区 | 负责的文件 | 依赖 | 验收 |
|---|---|---|---|---|---|
| claim-store | agent/sweep-readiness/claim-store | `/work/app-sweep-readiness-claim-store` | `src/claims/`, `tests/claims/`, `pyproject.toml` | - | tests/claims 通过 |
| sweep-docs | agent/sweep-readiness/sweep-docs | `/work/app-sweep-readiness-sweep-docs` | `docs/` | claim-store | docs/sweep.md 里的示例可以运行 |
- [ ] 合并 claim-store -> sweep-docs 到 agent/sweep-readiness/integration；运行 pytest -q；落到 develop
共享文件: pyproject.toml -> claim-store ; post-merge: 更新 CHANGELOG.md -> 合并步骤
风险: docs/sweep.md 引用 src/claims 的接口，所以 sweep-docs 依赖 claim-store
```

**第 2 步：登记**

```text
/GitPlan sweep-readiness --into develop --apply
/GitPlan sweep-readiness --into develop --apply --create
```

登记的就是刚才预览的那一份 spec，一个字节都不差；没有预览过、预览之后你要求改过、或目标分支已经前进时，它会重新预览并停下，不会直接登记。登记一次写入每个车道的登记、集成分支的登记（它不占用任何文件，也不限制任何车道的清单，只是让守卫允许用普通的 `git switch -c` 创建那条分支）和计划记录（连同任务的需求、每个车道承担的需求与成果）：要么全部写入，要么什么都不留。加 `--create` 才会替你创建各车道的分支和工作区（从记录里的 `base` 出发，建在登记的路径）；不加，它把要你自己运行的 `git worktree add` 命令打印出来。登记之后的报告用同样的两张表（取自读回的记录）列出登记结果；每个车道还会带一段交接说明：标题、分支、工作区、清单、依赖、成果、验收标准，以及负责人记录进度的两行命令。

**第 3 步：开工、记进度**

各车道的负责人（子 Agent）只改自己清单里的文件。开始时记 `active`，提交之后记 `ready` 并附上它的最新提交：

```text
magos_guard.py set-update --repo /work/app-sweep-readiness-claim-store --set sweep-readiness --expect-revision <rev> --lane claim-store --state active
magos_guard.py set-update --repo /work/app-sweep-readiness-claim-store --set sweep-readiness --expect-revision <rev> --lane claim-store --state ready --head <tip>
```

`<rev>` 取自 `magos_guard.py set-show --repo /work/app-sweep-readiness-claim-store --set sweep-readiness --json` 里的 `record.revision`（负责人在车道的工作区里运行这几行，`--repo` 写的就是它；仓库的任何一个工作区都可以）；退出码 19 表示它已经变了，重新读一次。记 `ready` 时守卫会核对：这个提交确实是分支的最新提交，而且这个车道改过的每一个文件都在它的清单里（越界就是退出码 22，并列出文件）。随时可以用 `--status` 看进度：

```text
/GitPlan sweep-readiness --status
```

它按记录重新打印这两张表：车道表多出 `状态` 和 `提交` 两列，`ready` 或 `integrated` 的车道打勾并附上记录的提交，最后是“还剩什么”。只要有车道已经 `integrated`，它打印的就是补充了修改内容的清单（见第 4 步）：车道表多一列 `修改`，需求表多一列 `结果`，下面是修改内容概要和合计。报告的标题行写着 revision（这个例子里是 5），清单本身不带 revision。

```text
# 计划 sweep-readiness -> develop  base 3fa9c21
## 需求
| 编号 | 需求 | 承担的车道 | 计划成果 | 结果 |
|---|---|---|---|---|
| R1 | 所有 claim 都从同一个存储读取 | claim-store | claim-store: src/claims 读取所有 claim | claim-store: Add claim_store module |
| R2 | 清扫的就绪结论有文档说明 | sweep-docs | sweep-docs: docs/sweep.md 讲清就绪结论 | 待合并: sweep-docs |
| R3 | 现有的清扫测试和文档里的示例仍然通过 | claim-store, sweep-docs | claim-store: src/claims 读取所有 claim; sweep-docs: docs/sweep.md 讲清就绪结论 | claim-store: Add claim_store module; 待合并: sweep-docs |
## 车道
| 车道 | 分支 | 工作区 | 负责的文件 | 依赖 | 验收 | 状态 | 提交 | 修改 |
|---|---|---|---|---|---|---|---|---|
| claim-store | agent/sweep-readiness/claim-store | `/work/app-sweep-readiness-claim-store` | `src/claims/`, `tests/claims/`, `pyproject.toml` | - | tests/claims 通过 | [x] integrated | 8b1d4e0 | 3 个提交, 7 个文件, +212/-48 |
| sweep-docs | agent/sweep-readiness/sweep-docs | `/work/app-sweep-readiness-sweep-docs` | `docs/` | claim-store | docs/sweep.md 里的示例可以运行 | [ ] active | - | active |
- [ ] 合并 claim-store -> sweep-docs 到 agent/sweep-readiness/integration；运行仓库检查；落到 develop

修改内容概要
- claim-store - 3 个提交, 7 个文件 (+212/-48): Add claim_store module; Read every claim through src/claims; Test the claim store [路径: `src/claims`, `tests/claims`]
- sweep-docs - active, 未合并
合计: 2 个车道中 1 个已合并, 3 个提交, 7 个文件, +212/-48

还剩什么
1. 完成 sweep-docs: active; 验收 docs/sweep.md 里的示例可以运行
2. 在 agent/sweep-readiness/integration 上运行仓库检查
3. post-merge: 更新 CHANGELOG.md
```

计划要改，就用 `--amend`：`/GitPlan sweep-readiness --amend --expect-revision 5` 重新调查并预览修改后的计划（还在的车道保留分支、工作区、状态和修改内容概要，`base` 移到目标分支的当前位置；需求可以增加、改写或删除，但每条需求仍要有车道承担，开了工的车道不能改名），满意再加 `--apply`；没有任何变化的修改会直接说明，不登记任何东西，revision 也不变。已经有未合并提交的车道不能被删掉，它的清单也不能缩小到少于它已经改过的文件（守卫会拒绝，退出码 16）。

**第 4 步：合并、落地、收尾**

```text
/GitPlan sweep-readiness --converge
/GitPlan sweep-readiness --converge --apply --expect-revision 6
/GitPlan sweep-readiness --converge --apply --land
/GitPlan sweep-readiness --release
```

先预览合并：结论 `READY`（每个车道都已经 `READY` 或 `INTEGRATED`，一次运行就能全部合并）、`PARTIAL`（有车道还没好，这次只合并 `READY` 的，并写明每个没好的车道还缺什么）或 `BLOCKED`（有门槛没通过）。`READY` 只针对合并；预览还会预测同一次运行能不能落地（每个车道都已完成，目标分支仍停在集成分支的起点或将要切出的位置，而且没有在别的工作区检出）。推荐的下一条命令是 `/GitPlan <set> --converge --apply --expect-revision <预览里显示的 revision>`，只有这个预测成立时才加上 `--land`；否则报告写明哪个落地条件不满足、怎样解除，“还剩什么”里也留着这一项。运行命令的工作区要停在目标分支上（集成分支已经存在时，也可以停在集成分支上），被 Git 跟踪的文件没有改动，也没有做到一半的合并、变基之类的操作；没有被 Git 跟踪的文件（比如上一次运行的检查生成的文件）既不挡住预览，也不挡住运行，报告会列出它们。Git 在切换分支或合并时拒绝覆盖其中某个文件，运行就会停下：删除或移走列出的文件，再重新运行。

`--converge --apply` 是你对报告里那份计划的接受：先重新调查，记下这次的计划（车道顺序、各车道登记的提交、目标分支的提交、revision）；和你之前预览过的不一样就停下，给你新的预览。然后：

1. 只有写了 `--include-active`，才把相对目标分支有自己改动的 `active` 车道按当前提交记成 `ready`（这就是你对这些提交的接受），守卫同时核对它改过的文件都在清单里。只接进了目标分支提交的车道没有自己的改动，不算在内。预览在 Head 列里显示被纳入车道的当前提交，标上 `(--include-active)`；这个提交在预览之后变了，运行就停下，给你新的预览。
2. 集成分支不存在时，在你运行命令的工作区（必须停在目标分支上，被 Git 跟踪的文件没有改动）用普通的 `git switch -c agent/<set>/integration <目标分支的当前提交>` 创建它。
3. 按依赖顺序，逐个用 `git merge --no-ff` 合并 `READY` 车道登记的那个提交，每合并一个就用 `set-update` 记成 `integrated`。
4. 在集成分支上运行仓库自己的检查（构建、测试、lint）；检查失败就在落地之前停下，认不出检查时报告“未校验”并继续。
5. 只有写了 `--land`：每个车道都已 `integrated`、而目标分支还停在集成分支的起点时，用一次 `git merge --ff-only` 把目标分支快进到集成分支；否则报告 `LAND_REFUSED` 并停下，什么也不再做。工作区里没有被 Git 跟踪的文件（比如检查生成的文件）不会挡住落地，报告会列出它们；被跟踪文件的改动则会挡住。Git 拒绝覆盖其中某个未跟踪的文件时，同样是 `LAND_REFUSED`：删除或移走列出的文件，再加 `--land` 重新运行。

合并完成后，清单不是被替换，而是**在原来的基础上补充**：`--converge --apply` 的报告、之后的 `--status` 和 `--release` 打印的，仍是最初那两张表（每一行、每一列都在），再加上守卫在把车道记为 `integrated` 的那一刻用 git 算出并存进记录的修改内容：车道表多一列 `修改`（`3 个提交, 7 个文件, +212/-48` 这样的一格；还没合并的车道写它的状态），需求表多一列 `结果`（承担这条需求的各车道的第一条提交标题，还没合并的列在 `待合并` 后面），表格下面是 `修改内容概要`（每个车道一行：提交数、文件数、增删行数、提交标题，以及改动集中在哪些路径）和一行 `合计`。下面是 `--land` 之后 `--status` 或 `--release` 打印的样子（合并那一行已经打勾），只剩更新 CHANGELOG 和收尾两件事：

```text
# 计划 sweep-readiness -> develop  base 3fa9c21
## 需求
| 编号 | 需求 | 承担的车道 | 计划成果 | 结果 |
|---|---|---|---|---|
| R1 | 所有 claim 都从同一个存储读取 | claim-store | claim-store: src/claims 读取所有 claim | claim-store: Add claim_store module |
| R2 | 清扫的就绪结论有文档说明 | sweep-docs | sweep-docs: docs/sweep.md 讲清就绪结论 | sweep-docs: Document the readiness verdict |
| R3 | 现有的清扫测试和文档里的示例仍然通过 | claim-store, sweep-docs | claim-store: src/claims 读取所有 claim; sweep-docs: docs/sweep.md 讲清就绪结论 | claim-store: Add claim_store module; sweep-docs: Document the readiness verdict |
## 车道
| 车道 | 分支 | 工作区 | 负责的文件 | 依赖 | 验收 | 状态 | 提交 | 修改 |
|---|---|---|---|---|---|---|---|---|
| claim-store | agent/sweep-readiness/claim-store | `/work/app-sweep-readiness-claim-store` | `src/claims/`, `tests/claims/`, `pyproject.toml` | - | tests/claims 通过 | [x] integrated | 8b1d4e0 | 3 个提交, 7 个文件, +212/-48 |
| sweep-docs | agent/sweep-readiness/sweep-docs | `/work/app-sweep-readiness-sweep-docs` | `docs/` | claim-store | docs/sweep.md 里的示例可以运行 | [x] integrated | c04a7f2 | 2 个提交, 3 个文件, +36/-4 |
- [x] 合并 claim-store -> sweep-docs 到 agent/sweep-readiness/integration；运行仓库检查；落到 develop

修改内容概要
- claim-store - 3 个提交, 7 个文件 (+212/-48): Add claim_store module; Read every claim through src/claims; Test the claim store [路径: `src/claims`, `tests/claims`]
- sweep-docs - 2 个提交, 3 个文件 (+36/-4): Document the readiness verdict; Add runnable examples [路径: `docs/sweep.md`, `docs/sweep-examples.md`, `docs/index.md`]
合计: 2 个车道中 2 个已合并, 5 个提交, 10 个文件, +248/-52

还剩什么
1. post-merge: 更新 CHANGELOG.md
2. 收尾（release）
```

`--release` 先打印补充了修改内容概要的最终清单，再移除各车道的登记和计划记录；车道分支、工作区和集成分支都不动。登记没了，`/GitCleanup` 就不再把它们看作有人在用，可以去清理已经合并的那些。车道还没合并、还没进入目标分支，或工作区有未保存的修改时，以及集成分支还没进入目标分支、或它的某个工作区有未保存的修改时，守卫会拒绝（退出码 16），并指出是哪个车道或集成分支。

#### 两张表：需求、车道与成果

清单由两张表和几行说明组成。表里的内容都取自守卫保存的数据（预览取自 `set-plan --dry-run` 的结果，其后取自 `set-show` 读回的记录），不凭记忆书写；单元格里的竖线 `|` 写成 `∣`，清单项和路径用反引号写成代码，例如 `src/claims/`。标题、列标题、标签和固定的词（提交、文件、路径、合并那一行、仓库检查）都用回复语言写，保存下来的清单也一样，用预览时的语言。清单本身不带 revision，revision 写在每份报告的标题行里（车道 id、分支名、路径、命令、SHA 和状态码不翻译）。

| 表 | 每一行 | 列 |
|---|---|---|
| 需求表 | 任务的一条需求 | `编号`、`需求`、`承担的车道`、`计划成果`；合并之后多一列 `结果` |
| 车道表 | 一个车道 | `车道`、`分支`、`工作区`、`负责的文件`、`依赖`、`验收`；`--status` 与 `--converge` 多 `状态`、`提交` 两列，合并之后再多一列 `修改` |
| 修改内容概要 | 一个车道（没合并的写它的状态） | 提交数、文件数、增删行数、提交标题，以及改动集中在哪些路径；表格下面还有一行合计 |

规划时，执行者替你写出任务的需求 `R1`、`R2`……；每条需求至少由一个车道承担，每个车道至少承担一条需求并写明它交付的成果，否则守卫拒绝这份计划（退出码 24），并指出是哪个字段。守卫在车道被记为 `integrated` 的那一刻，用 git 对照当时本地的目标分支算出它的修改内容并存进记录：提交数（不算合并提交）、最多 8 条提交标题（从旧到新）、文件数、增删行数，以及最多 12 个改动集中的路径；同一个车道再次被记为 `integrated` 时只更新备注，不改这份摘要。

#### 命名规则：名字就是修改内容的主题

- **车道 id 是主题 slug**：`[a-z0-9][a-z0-9-]{0,23}`，1 至 3 个小写英文单词用连字符连起来，说的是这个车道**修改的对象**，例如 `claim-store`、`sweep-readiness`、`launcher-exit-codes`、`readme-gitplan`。执行者从这个车道主要承担的需求和它负责的文件推出主题；两个车道的主题相同时，加上区分的名词（`claim-store-api`、`claim-store-docs`）。
- **分支和工作区跟着 id**：分支恰好是 `agent/<set>/<id>`，工作区的目录名以 `-<set>-<id>` 结尾（默认是 `<主工作区的上级目录>/<仓库目录名>-<set>-<id>`，例如 `/work/app-sweep-readiness-claim-store`），所以 `git branch` 和 `git worktree list` 读起来就是一份主题清单。集成分支仍是 `agent/<set>/integration`。
- **守卫拒绝序号式和泛称的 id**（退出码 24，提示按主题命名）：只有数字、只有一个字母，以及 `l1`、`lane-2`、`task3`、`worker-1`、`step-4` 这类（`l`、`lane`、`task`、`agent`、`worker`、`wt`、`t`、`n`、`w`、`work`、`part`、`step`、`item` 加数字），还有保留的 `integration`。分支或工作区的名字不是上面的形式时，同样是退出码 24，并给出合规的名字。需求编号 `R1`、`R2` 和 set 的名字不受这条限制。

#### 参数详解

| 写法 | 作用 |
|---|---|
| `<set>`（必填，`--help` 除外） | 计划的名字，写法见上面的“词”表 |
| `--into <branch>` | 规划时必填：计划针对的本地分支，也是 `--land` 以后要快进的分支。要写得完全一样（区分大小写），不能是 `main`；其他形式从计划记录里读它 |
| `--apply` | 配合 `--into`：登记预览过的那份计划；配合 `--amend`：登记修改后的计划；配合 `--converge`：合并各车道。不写就只预览 |
| `--create` | 配合计划或修改的 `--apply`：同时创建登记过、但还不存在的车道分支和工作区。不写就打印 `git worktree add` 命令 |
| `--status` | 只看：两张表、各车道的状态（有车道已合并时还有修改内容概要）、还剩什么 |
| `--amend` | 重新规划已登记的计划，必须写 `--expect-revision`；加 `--apply [--create]` 才登记 |
| `--expect-revision <n>` | 你读到的计划记录的 revision（正整数）：配合 `--amend` 必填，配合 `--converge --apply` 可选；记录已经是别的 revision 就停下 |
| `--converge` | 预览把各车道按依赖顺序合并进 `agent/<set>/integration`；加 `--apply` 才执行 |
| `--include-active` | 配合 `--converge`：把相对目标分支有自己改动的 `active` 车道按当前提交当作 `ready`，预览把这个提交显示为它的 Head；执行时这就是你对这些提交的接受 |
| `--land` | 配合 `--converge --apply`：合并并检查之后，把 `<branch>` 快进到集成分支 |
| `--release` | 各车道都已合并之后收尾：先打印补充了修改内容概要的清单，再移除它们的登记和计划记录 |
| `--lang <语言>`、`--help` | 回复语言（默认中文）；只看说明 |

“选形式”的选项（`--into`、`--status`、`--amend`、`--converge`、`--release`）决定这次做哪一件事。同时写两个，或写了这一形式不认的选项，都算用法错误：它说明原因、显示用法，什么也不执行。

示例：

```text
/GitPlan sweep-readiness --into develop                              只看计划
/GitPlan sweep-readiness --into develop --apply --create             登记，并创建所有车道的分支和工作区
/GitPlan sweep-readiness --status                                    看进度和还剩什么
/GitPlan sweep-readiness --converge --apply --land --lang English    合并、落到 develop，用英文回复
/GitPlan --help                                                      只看说明
```

#### 合并时每个车道的状态

| 状态 | 白话意思 | 这次会合并吗 |
|---|---|---|
| `INTEGRATED` | 记录里已经是 `integrated`，它的提交已经合并过 | 已完成，不会再合并 |
| `READY` | 负责人记了 `ready`，而且一切一致 | 会，按依赖顺序 |
| `NOT_READY`、`BLOCKED`、`WAITING` | 记录里还是 `planned` 或 `active`；记录里是 `blocked`；它依赖的车道既没有合并、也不是 `READY` | 不会，只是这个车道不参加这一次，不拦别的车道（写了 `--include-active` 时，相对目标分支有自己改动的 `active` 车道按当前提交参加） |
| `MISSING_BRANCH`、`DIRTY`、`IN_PROGRESS`、`NO_MERGE_BASE` | 分支不见了；工作区有未保存的修改；工作区里有做到一半的合并、变基等操作；分支与目标分支没有共同历史 | 失败，整个命令停下 |
| `OUT_OF_LANE`、`SHARED_CHANGE`、`MOVED`、`CLAIM_DRIFT` | 改了清单之外的文件；两个车道改了同一个文件；记 `ready` 之后又有了新提交；车道的登记与计划记录对不上 | 失败，整个命令停下 |
| `STALE_PLAN` | 目标分支前进了，而且它新提交改动的文件与某个车道的清单有交集，各车道不再独立于已经落下的内容（这个计划自己的车道合并或落地之后从不算在内） | 失败，整个命令停下 |
| `PREDICTED_CONFLICT` | 预演合并（`git merge-tree --write-tree`）预计会冲突；只是提示，看不出两个车道之间的冲突 | 提示，仍会尝试 |

排队的状态只让那个车道这一次不参加；失败的状态会让整个命令停下，因为一个已经 `ready` 却不一致的车道不能被绕过去合并。每一项都附带处理办法，命令自己从不去做：车道的负责人（或你）去做，处理完重新运行。

#### 乐观锁：没有人持锁，过期的计划只会被发现

登记的计划带着一个 revision 和它依据的目标分支提交（`base`），没有任何人在车道工作期间持有锁。每次改动都要拿着你读到的 revision 来比对，对不上就停下，所以过期的计划只会被发现，不会被覆盖。

| 你会看到 | 白话意思 | 你该怎么办 |
|---|---|---|
| 退出码 19，`kind` 是 `base` | 预览之后目标分支前进了，计划依据的提交不是它现在的位置 | 重新运行：新的预览会调查新的位置 |
| 退出码 19，`kind` 是 `revision`，或 `--expect-revision` 对不上 | 计划记录在你读取之后被改过，比如某个车道的负责人记录了进度 | 先运行 `--status`，按它显示的 revision 重做；修改（`--amend`）会先按当前记录重新预览，再登记，所以期间记下的内容不会丢失 |
| `STALE_PLAN` | 见上表：目标分支上落下的内容与某个车道的清单有交集 | `--amend --expect-revision <n>`：新的预览基于新的位置，修改会把 `base` 移过去；修改之后，有交集且还没有 `integrated` 的每个车道由负责人把目标分支的新提交合并进自己的分支，再记一次 `ready`（`blocked` 的车道，以及分支已经存在的 `planned` 车道，要先记成 `active`，因为守卫不允许它们直接变成 `ready`）；即使修改已经让这一项消失，这一步也必须做，否则合并会停在冲突上。有交集但已经 `integrated` 的车道保持分支不动：由你把目标分支的新提交合并进集成分支 `agent/<set>/integration`，在那里解决冲突，否则落地会停下 |
| 退出码 20、21 | 这个名字的计划已经存在；或者不存在这个名字的计划 | 用 `--status` 看，用 `--amend` 改，用 `--release` 收尾，或换个名字；检查名字，或先用 `--into` 规划 |
| 退出码 22，`OUT_OF_LANE` | 某个车道改了清单之外的文件，守卫拒绝把它记成 `ready` | 负责人撤销这些改动，或用 `--amend` 把这些文件划给设计上拥有它们的那一个车道，然后重新记 `ready` |
| 退出码 23 | 计划记录由更新版本的 MAGOS 写入 | 升级守卫（见“车道守卫”）；在此之前这份记录不会被读取或修改 |
| 退出码 24 或 12 | 计划无效：字段写错（比如车道 id 是序号或泛称、分支或工作区的名字不带主题、某条需求没有车道承担），或与仓库里已有的分支、路径冲突；提示会指出是哪个字段 | 改掉那个字段，重新证明（执行者会按主题改名、给没人承担的需求补上车道，再重新预览）；需求超过 12 条、车道超过 12 个、清单超过 8192 个字符的计划要缩小 |

计划存在期间，每个未结束的车道登记（`planned` 或 `active`）都会让 `/GitCleanup`、`/GitConverge`、`/GitSweep` 把这个车道报告为 `BLOCKED_ACTIVE_OWNER`：这是有意的，`--release` 之后解除。

#### 它一定遵守的规则

```text
✓ 默认只预览。不加 --apply（也不是 --release）就不会登记、创建或合并任何东西，也不联网
✓ 登记的就是预览过的那份计划；没有预览过，就先预览、然后停下
✓ 登记和进度只经过车道守卫的 set-plan、set-update、set-release；从不手改 .git/magos，从不用 override
✓ 只合并车道登记的那个提交，只合并进集成分支；加 --land 才再多一次 --ff-only 快进，而且只在目标分支还停在集成分支起点时
✓ 遇到冲突就 git merge --abort 并停下；从不用 ours 或 theirs，也不手工解决；已经完成的合并只留在集成分支上
✓ 从不推送，从不强推，从不联网；从不删除分支或工作区，从不 git worktree prune
✓ 从不动 main，也不能把 main 当目标；从不变基、压缩、cherry-pick 或 reset
✓ 从不往车道的工作区里写任何东西；--create 只创建登记过的车道（在登记的路径，从记录的 base 出发）
✓ 车道的 id、分支和工作区都以修改内容的主题命名，从不用序号；每条需求至少由一个车道承担，每个车道至少承担一条需求
✓ 表格取自守卫证明过的 spec 或守卫保存的记录，不凭记忆书写；合并之后在原来的清单上补充修改内容概要，不替换它
```

#### 常见疑问

- **守卫版本不够怎么办？** `/GitPlan` 一开始就检查守卫的版本，需要 1.0.4 或更新；较老的守卫没有 `set-*` 子命令，命令会停下并让你刷新守卫副本（运行 `doctor`，再运行它打印的 `install --host <host>` 命令）。
- **能发现文件之间语义上的耦合吗？** 不能。守卫只证明文件清单不相交，不懂代码之间的依赖；有引用关系的文件，规划时应该放进同一个车道。
- **计划记录放在哪里？** 放在这个克隆自己的 git 目录里（`<git-common-dir>/magos/sets/<set>.json`），只能经守卫读写，不会随 fetch 或 push 同步给别的克隆。
- **合并到一半断了怎么办？** 重新运行同一条命令：它重新调查，在同一条集成分支上接着做，已经 `integrated` 的车道会跳过。
- **车道为什么不能叫 `l1`、`task3`？** 因为 `git branch` 和 `git worktree list` 里只剩序号时，没人看得出哪个车道改什么。车道按修改内容的主题命名（`claim-store`、`sweep-docs`）；守卫拒绝序号式和泛称的 id（退出码 24），执行者改名之后重新预览。
- **合并之后，清单里的“修改”是怎么来的？** 守卫在车道被记为 `integrated` 的那一刻用 git 算出，存在这个车道的记录里（提交数、提交标题、文件数、增删行数、路径）；它按当时本地的目标分支计算，之后不会随目标分支前进而变化，也不是执行者凭记忆写的。
- **我想让回复是英文？** 在命令最后加 `--lang English`。

---

## 多 Agent 生命周期

```mermaid
stateDiagram-v2
    [*] --> PLANNED
    PLANNED --> ACTIVE
    ACTIVE --> READY
    READY --> APPROVED
    APPROVED --> INTEGRATING
    INTEGRATING --> INTEGRATED

    READY --> BLOCKED
    READY --> REJECTED
```

每条 Agent Lane 都记录：

```text
Task
Owner
Branch
Worktree
Base Branch
Base SHA
Current HEAD
Dependencies
Acceptance Criteria
Validation Evidence
Integration Decision
```

---

## Git 操作决策

```text
整个 Agent 成果都要
        ↓
      Merge

只要部分 Commit
        ↓
   Cherry-pick

Agent 私有分支落后 main
        ↓
  Rewrite-safe?
    ↓       ↓
   YES      NO
 Rebase    Merge target into lane

私有历史走错
        ↓
      Reset

已经进入共享历史后出错
        ↓
      Revert
```

---

## 安全原则

```text
Observe first.
Advise second.
Mutate only when needed.
```

本 Skill 默认禁止：

- 多个 Agent 同时修改同一个 Checkout
- 未调查仓库就给出具体 Branch / Worktree 建议
- 随意 Rebase 已被其他 Agent 依赖的 Branch
- 对共享历史执行 destructive reset
- 默认 Force Push
- 未检查依赖就 Cherry-pick
- Review 已过期仍然继续 Integration
- 仅因为 Branch 很旧就判断可以删除

---

## 车道守卫

MAGOS 带有车道守卫（`scripts/magos_guard.py`）：创建分支或工作树之前，新车道要修改的文件必须先登记成清单（`plan`）；计划修改的文件与其他分支、工作树或已登记的车道重叠时，创建会被拒绝，并列出每一个冲突的车道。已有车道只会被读取：没有任何钩子会阻止已有车道里的写入、提交或合并。代理遵守的契约见 `references/lane-split.md`；安装、升级与已知限制见 `references/installation.md`。

- **在哪里生效。**Claude Code 插件会启用 PreToolUse 钩子（`hooks/hooks.json` 调用 `hooks/run-guard.cmd`，再由它运行 `scripts/magos_guard.py`），作用于在 Claude Code 里打开的每个仓库。Codex 的插件安装不会启用钩子，只带来批准服务器 `magos`（`mcp.json`）。Codex 的钩子来自 `py -3 scripts/magos_guard.py install --host codex`（macOS / Linux 用 `python3`）：把它打印的条目合并进 `~/.codex/hooks.json`，并在 Codex 的 `/hooks` 里信任一次；`install` 还会生成并打印 `[mcp_servers.magos]` 条目（`guard/generated/codex-mcp.toml`），只有没有装插件的 Codex 才需要把它写进配置，它从不改 Codex 的配置。插件启动的服务器使用中文文本；`install` 打印的条目会传入 `MAGOS_LANG`，沿用你的钩子的语言。在 Codex 里，代理可以在你勾选 Approve 并点 Accept 之后经工具 `magos_approve` 替你运行这条 `install`。Hermes 的插件自己运行守卫，没有要合并的条目：`hermes plugins update magos` 并重启 Hermes 之后，它的两个 `pre_tool_call` 回调对每一次 `terminal` 调用运行守卫，用户专属命令在 Hermes 自己的批准提示里批准；`install --host hermes` 用于没有安装插件的 Hermes，它生成的 `hooks:` 条目拒绝每一条用户专属命令，装了插件之后请把这条条目删掉。在某个仓库里运行 `arm` 后，Git 的 `reference-transaction` 兜底会否决任何工具用 git 创建的、没有清单的新分支。
- **模式。**AUTO（默认）：命名的工作树创建总是需要清单，只建分支的创建仅在已有其他车道时需要，所以在只有一个工作树、没有未合并分支的仓库里，只建分支的创建不受影响。ARMED（`arm` 之后）：每个新分支都需要清单，钩子与 Git 都检查。OFF：`git config --local magos.guard off`，关闭该仓库的宿主钩子；已 `arm` 的仓库里 Git 兜底不受影响。
- **关闭。**`git config --local magos.guard off`（单个仓库），`claude plugin disable magos`（整个 Claude Code 插件），或在宿主进程的环境里设置 `MAGOS_GUARD=off`（它同样关闭 Hermes 插件的回调；`hermes plugins disable magos` 也会停掉它们）。这三种都只关闭宿主钩子，不动 Git 兜底：已 `arm` 的仓库，请让 `disarm` 运行把它撤掉（代理先问你，你在宿主自己的批准提示里点一下批准（Claude Code、Codex、Hermes）；也可以在自己的终端里运行）。
- **要求。**Python 3.9+（钩子启动器在 POSIX 与 Git Bash 上依次找 `python3`、`py -3`、`python`；在 Windows 的 cmd 上依次找 `py -3`、`python`、`python.bat`、`python.cmd`）与 Git 2.36+（其他 MAGOS 命令需要 Git 2.30+）；`magos_guard.py doctor` 会检查两者，`magos_guard.py version` 输出正在运行的守卫版本。
- **Set 子命令。**`/GitPlan` 通过守卫的四个子命令登记并维护计划：`set-plan`（证明各车道的文件清单两两不相交并登记）、`set-show`（只读）、`set-update`（车道负责人记录进度）和 `set-release`（收尾）。它们都不是只有你能运行的命令，和 `plan`、`release` 一样经过宿主钩子。登记会写入每个车道的登记（带 `set=` 与 `lane=`）、集成分支 `agent/<set>/integration` 的登记（不占用任何文件）和计划记录（`<git-common-dir>/magos/sets/<set>.json`）；退出码 19 到 24 属于这些子命令（过期、已存在、不存在、越界、记录来自更新版本、规划无效）。计划记录里有任务的需求、每个车道承担的需求与成果，以及车道被记为 `integrated` 时守卫算出的修改内容；守卫也检查命名与对应关系：车道 id 必须是主题 slug（序号式和泛称的 id 被拒绝），分支必须恰好是 `agent/<set>/<id>`，工作区目录名以 `-<set>-<id>` 结尾，每条需求至少由一个车道承担。计划存在期间，普通的 `plan` 会拒绝写入它的车道或集成分支的登记（包括 `--amend` 和 `override` 之后的重新登记），普通的 `release` 也会拒绝它的登记：计划只能经 `/GitPlan` 修改。
- **由你批准。**`override`、`arm`、`disarm`、`install` 只有经你批准才会运行，`magos.*` 的 git 配置（例如 `magos.guard`、`magos.approval`）也只有你能写。批准的级别用 `git config --local magos.approval <级别>` 设置（你可以在自己的终端里设置，代理从不设置；取值比较时不区分大小写，也忽略首尾空白，其他取值按 `terminal` 处理）：`terminal`——你在真实终端里运行命令；`prompt`（默认）——代理先问你，你同意后它运行守卫命令（在 Codex 里是调用工具 `magos_approve`），宿主弹出自己的批准提示（Claude Code 的权限对话框、Codex 带 Approve 勾选框的对话框、Hermes 的批准提示），写明批准的是什么和代理写的理由，你点一下就是批准（在 Codex 里是先勾选 Approve，再点 Accept）；`auto-safe`——同 `prompt`，但只增加保护的 `arm`，以及复制到默认守卫目录且不带 `--allow-downgrade` 的 `install`（只复制守卫），不用点击，你的设置本身就是批准，`override`、`disarm` 与 `install` 的其他写法仍然要问你。没有让代理无人值守地覆盖的级别；想关掉守卫，由你自己运行 `git config --local magos.guard off`。在 Codex 里 `auto-safe` 与 `prompt` 一样要问你（Codex 的路径没有不点击就运行的情形），批准策略为 `never` 时 Codex 会自己拒绝；Hermes 在 `/yolo`、`--yolo` 或 `approvals.mode: off` 下不经你就批准，守卫看得到这种情形时就拒绝点击路径。终端路径始终可用。Claude Code 里只有 Bash 与 PowerShell 工具有对话框，Hermes 里只有 `terminal` 工具。代理用其他任何方式运行它们，都会被钩子拒绝，钩子启动器也只运行钩子。在新控制台窗口里启动的命令也能通过控制台检查，所以控制台检查、覆盖与批准令牌都不是访问控制：挡在 `override` 与 `disarm` 前面的是宿主自己的批准提示（Codex 的路径只证明有人点击，以 Codex 本身能证明的为限；Hermes 的路径以 Hermes 的批准关口为限），审计日志里的 `via` 与 `reason_by` 是尽力而为的来源记录，不是证明。
- **每次升级之后。**重启正在运行的 Claude Code、Codex 与 Hermes 会话（Hermes 在 `hermes plugins update magos` 之后）；为 `doctor` 列出的每个宿主重新运行 `install`（`doctor` 会打印确切的命令；用 `install --home <目录>` 装的副本，运行 `doctor --home <目录>`），打印的条目与宿主配置里已合并的条目不同时替换它（Codex 要在 `/hooks` 里重新信任，Hermes 要重新批准；装了 Hermes 插件时不需要 Hermes 条目，`config.yaml` 里 `hooks:` 下的 MAGOS 条目请删掉，它在 Hermes 询问之前就拒绝每一条用户专属命令）；在已 `arm` 的仓库里运行 `doctor`，它打印 `arm` 命令时，重新运行该命令（在宿主的批准提示里点一下批准，或在自己的终端里运行）。1.0.4 起，`/GitPlan` 需要守卫的 `set-*` 子命令，较老的守卫副本没有它们：运行 `doctor`，再运行它打印的 `install --host <host>` 命令刷新副本，否则 `/GitPlan` 会在开头检查版本并停下。
- **限制。**钩子读的是命令文本；找不到 Python 或守卫脚本时放行调用（Claude Code 的 `EnterWorktree` 钩子和 Hermes 插件的回调除外，它们拒绝调用）；Git 兜底看不到分支改名与复制（`git branch -m/-c`），钩子则在任何选项写法下都拒绝它们。`override` 与 `disarm` 前面只有一道屏障，就是宿主自己的批准提示；批准令牌不是访问控制，审计日志里的 `via` 与 `reason_by` 是尽力而为的来源记录，不是证明（见“由你批准”）。全部限制见 `references/lane-split.md` 第 12 节。

---

## 安装

仓库的目录结构如下（只列主要文件；另有 `tests/`、`.github/`、`.quality/`，以及根目录的文档、许可证与配置文件）。Claude Code 的 clone 安装使用整个目录；同步脚本给 Codex 与 Hermes 只复制 `SKILL.md`、`references/` 和 `skills/` 下的八个命令 Skill。各平台的安装方式见下面各节：

```text
multi-agent-git-orchestrator/
├── SKILL.md
├── plugin.json                # Agent Plugins 清单：把整个仓库当作一个插件导入时使用
├── mcp.json                   # Agent Plugins 的 MCP 文件：Codex 为点击批准而启动的本地 MCP 服务器 magos
├── .claude-plugin/
│   ├── plugin.json            # Claude Code 插件清单
│   └── marketplace.json       # Claude Code 与 Codex 的插件市场清单
├── plugin.yaml + __init__.py  # Hermes 原生插件清单：注册 /magos:git-* 命令和车道守卫回调
├── CHANGELOG.md               # 每个版本的变化、安全说明与升级步骤
├── commands/                  # Claude Code command prompts
├── skills/                    # Codex / Hermes command adapters，以及插件入口 git-orchestrator
├── hooks/
│   ├── hooks.json             # Claude Code 插件钩子：车道守卫
│   └── run-guard.cmd          # 启动器（cmd 与 sh 通用），用 Python 运行守卫
├── scripts/
│   ├── magos_guard.py         # 车道守卫
│   └── sync_hosts.py          # 把 Skill 包复制给 Codex 与 Hermes，或把命令文件复制给 Claude Code
└── references/
    ├── commands.md
    ├── reconnaissance.md
    ├── branch-strategy.md
    ├── decision-matrix.md
    ├── handoff-and-state.md
    ├── design-rationale.md
    ├── pressure-tests.md
    ├── lane-split.md          # 车道守卫的契约
    └── installation.md        # 各平台的安装、固定版本、升级与回滚；车道守卫
```

Skill 可以通过语义自动触发。除多 Agent 协作和各种“互相覆盖、分支泛滥”的症状外，当你要选择、审计或调整**某个具体仓库**（尤其是多 Agent / 多 Worktree / 多人共用的仓库）的分支策略时，它也会自动出现；单纯问“gitflow 和 trunk-based 有什么区别”这类概念问题不会触发。它只给建议：真正执行仍走对应的 `/Git...` 命令并保留各自的安全检查，哪个命令做什么见 `references/branch-strategy.md` 的 **Strategy Changes**；重命名分支没有对应命令，需要你在协调好依赖方之后手动完成。注意：用同步脚本安装时，Hermes 的 Skill 索引只显示 description 的前约 57 个字符，所以这种安装下请直接加载这个 Skill（或用 `/git-recommend`）来做分支策略建议；用 Hermes 插件安装时，插件自带的索引描述已写明分支策略。

### 从插件市场安装（推荐，三个平台都支持）

三个平台都能直接从本仓库安装插件 `magos`，不用复制文件，也不用跑脚本：

| 平台 | 安装 | 更新 |
|---|---|---|
| Claude Code | 在会话里输入 `/plugin marketplace add UlyssesLeoLee/MAGOS`，再输入 `/plugin install magos@magos` | `/plugin marketplace update magos`，然后 `/plugin update magos@magos`，再重启每一个正在运行的 Claude Code 会话 |
| Codex | `codex plugin marketplace add UlyssesLeoLee/MAGOS`，再 `codex plugin add magos@magos` | `codex plugin marketplace upgrade magos`，然后再执行一次 `codex plugin add magos@magos`，再重启 Codex 并刷新守卫副本（`install --host codex`） |
| Hermes | `hermes plugins install UlyssesLeoLee/MAGOS --enable` | `hermes plugins update magos`（安全扫描要求确认时改用 `hermes plugins install UlyssesLeoLee/MAGOS --force --enable`；固定版本的安装改为移动固定点，见“固定版本”），再重启 Hermes |

Claude Code 也可以在终端里执行：`claude plugin marketplace add UlyssesLeoLee/MAGOS && claude plugin install magos@magos`。

装好后（重新开启会话），三个平台的名字是统一的：

| 用途 | Claude Code | Codex | Hermes |
|---|---|---|---|
| 八个命令 | `/magos:GitRecon` … `/magos:GitPlan` | `$magos:git-recon` … `$magos:git-plan` | `/magos:git-recon` … `/magos:git-plan` |
| 总规则（描述问题时自动触发） | `magos:git-orchestrator` | `magos:git-orchestrator` | `magos:git-orchestrator`（Hermes 把它列进系统提示的 `<available_skills>`，模型按描述自行加载） |

- Claude Code 里只会看到八个 `/magos:GitXxx` 命令：小写的 `/magos:git-recon` 等是给 Codex 与 Hermes 用的适配层，插件在 Claude Code 里把它们隐藏了。总规则 `magos:git-orchestrator` 也不在 `/` 菜单里，描述问题时由 Claude 自己加载。
- 插件宿主只加载 `skills/` 下的 Skill，不加载根目录的 `SKILL.md`，所以插件里多了一个入口 Skill `git-orchestrator`，它会去读根目录的 `SKILL.md`。clone 到 `~/.claude/skills/magos` 时它同样会加载；只有用同步脚本安装的 Codex 与 Hermes 包不需要它，同步脚本也不会复制它。
- 版本号写在清单里，Claude Code 只有在版本号变化时才会更新已安装的插件。正在运行的会话继续使用它启动时那个版本的钩子，所以更新后要重启每一个会话。
- Claude Code 的插件安装会同时启用车道守卫钩子；Codex 的插件安装带来批准服务器 `magos`，Codex 的钩子来自 `install --host codex`；Hermes 的插件通过自己的回调运行守卫（见“车道守卫”）。各平台的升级细节（包括守卫副本与回滚）见 `references/installation.md`，每个版本的变化见 `CHANGELOG.md`。
- Hermes 显示“custom (unreviewed) source”是正常的：MAGOS 不在 Hermes 官方插件目录里。列入官方目录需要仓库所有者向 NousResearch/hermes-agent 提交 PR（固定到某个 commit SHA）；列入官方目录的插件可以用 `hermes plugins install magos` 安装。
- 一台机器上可以有多份 Hermes，每份有自己的主目录（例如 PATH 里排在前面的是另一个 Hermes 实例）。`hermes` 命令只作用于当前解析到的那一份：`hermes plugins update magos` 报 “No plugin named 'magos'”，说明这一份里没有装 magos。用 `hermes plugins list` 确认；Windows 上用 `Get-Command hermes -All` 列出全部 `hermes`，对装了 magos 的那份用它的完整路径运行，每一份各自安装、各自更新。
- 已经用旧方式装过的，请先删掉旧安装，避免同一套命令出现两次：`~/.claude/commands/Git*.md`、`~/.claude/skills/magos`、Codex 的 `~/.agents/skills/MAGOS` 与旧位置 `$CODEX_HOME/skills/MAGOS`（默认 `~/.codex/skills/MAGOS`）、Hermes 的 `<Hermes home>/skills/multi-agent-git-orchestrator` 与 `<Hermes home>/skills/MAGOS`。

### 固定版本

从 1.0.1 起，每个发布都有标签 `v<版本号>`（见 `CHANGELOG.md`）；1.0.0 没有标签，不要安装或固定它；标签 `v1.0` 是插件化与改号之前的 3.4.0 版 Skill，不是插件版本，也不要固定到它。上面的命令跟随默认分支；要停留在某个版本：

```bash
claude plugin marketplace add UlyssesLeoLee/MAGOS@v1.0.9    # 然后：claude plugin install magos@magos
git clone --branch v1.0.9 https://github.com/UlyssesLeoLee/MAGOS ~/.claude/skills/magos
hermes plugins install UlyssesLeoLee/MAGOS --ref <v1.0.9 的 40 位 commit SHA> --enable    # 已经安装过 MAGOS 时加 --force
```

固定版本收不到之后的修复，包括守卫的安全修复：请关注 `CHANGELOG.md` 并移动固定点。标签的 commit SHA 是 `git ls-remote https://github.com/UlyssesLeoLee/MAGOS refs/tags/v1.0.9 "refs/tags/v1.0.9^{}"` 输出里 `refs/tags/v1.0.9^{}` 那一行的 SHA（没有这一行时取 `refs/tags/v1.0.9` 那一行）。Hermes 把带 `--ref` 的安装记为固定：`hermes plugins update magos` 会拒绝它，不带 `--ref` 的 `hermes plugins install UlyssesLeoLee/MAGOS --force` 会重装原来固定的提交。移动固定点用 `--ref <新的 SHA> --force --enable`；要重新跟随默认分支，先 `hermes plugins remove magos`，再 `hermes plugins install UlyssesLeoLee/MAGOS --enable`。细节以及如何固定 Codex 与同步脚本安装，见 `references/installation.md`。

### Claude Code：clone 到 Skill 目录

不想用插件市场时，也可以把仓库直接 clone 到 Claude Code 的 Skill 目录，效果相同，`git pull` 即更新：

```bash
git clone https://github.com/UlyssesLeoLee/MAGOS ~/.claude/skills/magos
```

```powershell
git clone https://github.com/UlyssesLeoLee/MAGOS "$HOME\.claude\skills\magos"
```

仓库根目录有 `.claude-plugin/plugin.json`，Claude Code 会把这个文件夹当作插件 `magos@skills-dir` 加载，每次会话都自动生效，不需要 `/plugin install`。重新开启会话后可以用：

- 八个命令：`/magos:GitRecon`、`/magos:GitAnalyze`、`/magos:GitRecommend`、`/magos:GitIntegrate`、`/magos:GitCleanup`、`/magos:GitConverge`、`/magos:GitSweep`、`/magos:GitPlan`（输入 `/magos:` 即可补全）；
- 总规则入口 `magos:git-orchestrator`，描述问题时会自动触发；
- `skills/` 下的八个跨工具适配层（Hermes 里是 `/magos:git-recon` 等，Codex 里是 `$magos:git-recon` 等）。它们和上面的命令等价，在 Claude Code 里被隐藏，那里只列 `/magos:GitXxx`。

以后更新只要在该目录执行 `git pull`（按“固定版本”克隆在标签上的，改为执行 `git fetch --tags` 与 `git checkout v<新版本>`），再重启所有正在运行的 Claude Code 会话，命令、规则和车道守卫会一起更新。用 `claude plugin list` 可以确认它显示为 `magos@skills-dir` 且状态为 loaded。

如果之前按下面的旧方式复制过 `~/.claude/commands/Git*.md`，请删掉这八个文件，否则会同时出现一套旧的 `/GitXxx` 命令。

### Claude Code：旧方式（复制命令文件）

不想用插件时，也可以把 `commands/` 下的命令文件复制到用户级命令目录（所有项目可用）或某个项目的 `.claude/commands/`（仅该项目可用），命令名就是 `/GitRecon` 这样不带前缀的形式：

```text
commands/
├── GitRecon.md
├── GitAnalyze.md
├── GitRecommend.md
├── GitIntegrate.md
├── GitCleanup.md
├── GitConverge.md
├── GitSweep.md
└── GitPlan.md
```

推荐用同步脚本：

```bash
python -X utf8 scripts/sync_hosts.py --host claude --apply --create-roots
python -X utf8 scripts/sync_hosts.py --host claude --verify
```

也可以手动复制：

```bash
mkdir -p ~/.claude/commands && cp commands/Git*.md ~/.claude/commands/
```

```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\commands"; Copy-Item commands\Git*.md "$HOME\.claude\commands\"
```

复制出去的命令文件**不会随仓库更新**。每次 `git pull` 或升级版本后都要重新同步（或重新复制）；`--verify` 会列出缺失或过期的命令文件。`--host claude` 只管 `~/.claude/commands`，命令运行时读取的 Skill 本身（例如 `~/.claude/skills/MAGOS`）要另外更新。已经按插件方式装好时，同步脚本会提示 `NOTE`，不必再复制。安装后**重新开启会话**，输入 `/Git` 即可看到八个命令。

也可以显式调用：

```text
/GitRecon
/GitAnalyze <branch>
/GitRecommend [goal]
/GitIntegrate <lane-or-branch>
/GitCleanup
/GitConverge <branch>
/GitSweep <branch>
/GitPlan <set> --into <branch>
```

八个命令的跨宿主名称和说明：

| 命令 | Claude Code | Hermes | Codex | 说明 |
|---|---|---|---|---|
| GitRecon | `/GitRecon` | `/git-recon` | `$git-recon` | 检查仓库 branch / worktree 状态并生成快照 |
| GitAnalyze | `/GitAnalyze` | `/git-analyze` | `$git-analyze` | 分析指定目标的差异、依赖和操作风险 |
| GitRecommend | `/GitRecommend` | `/git-recommend` | `$git-recommend` | 根据当前状态建议 Git 与多 Agent 下一步 |
| GitIntegrate | `/GitIntegrate` | `/git-integrate` | `$git-integrate` | 通过安全门禁后集成指定 lane 或 branch |
| GitCleanup | `/GitCleanup` | `/git-cleanup` | `$git-cleanup` | 默认预览可清理项；`--apply` 才允许删除 |
| GitConverge | `/GitConverge` | `/git-converge` | `$git-converge` | 把所有本地分支合并进指定分支并只保留 `main` 和它；默认预览，`--apply` 才执行 |
| GitSweep | `/GitSweep` | `/git-sweep` | `$git-sweep` | `/GitConverge` 之后再删除远端已合并分支；默认预览且不联网，`--apply` 才执行，`--push`（需要 `--apply`）才把 `<branch>` 推送一次 |
| GitPlan | `/GitPlan` | `/git-plan` | `$git-plan` | 先调查并把任务拆成文件互斥的车道，用需求表和车道表列出清单，登记计划，之后按依赖顺序合并并补充修改内容概要；默认预览，`--apply`（或 `--release`）才写入 |

斜杠入口说明：

| 宿主 | 从 `/` 进入 | 前提条件 |
|---|---|---|
| Claude Code | 直接输入 `/GitRecon` 等八个命令 | `~/.claude/commands/Git*.md` 已安装（`sync_hosts.py --host claude`），并已新开会话 |
| Hermes | 直接输入 `/git-recon` 等八个命令 | 包已安装到 `<Hermes home>/skills/`，并已新开会话或执行 `/reload-skills` |
| Codex | 输入 `/skills`，打开 Skill 列表后选择 `git-*`；也可以直接输入 `$git-recon` | 包已安装到 `~/.agents/skills/MAGOS`（`sync_hosts.py --host codex`），并已重启 Codex |

Codex 的 `/` 菜单只包含内置命令（源码 `codex-rs/tui/src/bottom_pane/command_popup.rs` 中只有 `Builtin` 与 `ServiceTier` 两类条目），无法注册自定义的 `/git-*`。因此在 Codex 中，斜杠入口是内置的 `/skills`。

### 参数提示与帮助

Claude Code 会在命令补全中显示 `commands/` 文件里的 `argument-hint`，例如 `/GitAnalyze <branch|worktree> [--remote] [--lang <language>] [--help]`。Codex 的 Skill 列表和 Hermes 的 Slash Command 说明会尽量带上简短用法；选中后可用 `--help` 查看完整参数说明和示例。`--help` 只显示说明，不检查或修改仓库。

```text
Claude Code: /GitIntegrate agent/auth --strategy squash
Hermes:      /git-integrate agent/auth --strategy squash
Codex:       $git-integrate agent/auth --strategy squash

Claude help: /GitIntegrate --help
Hermes help: /git-integrate --help
Codex help:  $git-integrate --help
```

运行源码契约检查：`python -X utf8 tests/codex/contracts/run_contract_cases.py`。每个用例的输入和结果保存在 `tests/codex/contracts/cases/<group>/<case>/evidence/`；加 `--check` 时只运行检查，不写任何文件。这些检查不启动 AI 宿主；其中 `package/install-layout` 会把 Codex 与 Hermes 包安装到临时 home，确认适配层引用的每个文件都存在，并按两个宿主的发现规则（复刻版）确认每个 Skill 只被发现一次，直接 `git clone` 到 Skill 目录时也一样；`package/agent-plugin` 检查仓库是否符合 Agent Plugins 1.0.0 插件格式（见“作为 Agent Plugin 导入”）。

### Codex / Hermes 的包结构

Codex 和 Hermes 都安装同一个宿主中立的包，目录结构必须与仓库一致，`skills/git-*/SKILL.md` 才能通过 `../../SKILL.md`、`../../references/*.md` 找到共享规则：

```text
MAGOS/                       # Codex 包根；Hermes 使用 multi-agent-git-orchestrator/
├── SKILL.md                 # 根 Skill：multi-agent-git-orchestrator（语义自动触发）
├── references/*.md          # 全部参考文档
└── skills/git-*/            # 八个命令适配层
    ├── SKILL.md
    └── agents/openai.yaml   # Codex：显示说明 + allow_implicit_invocation: false
```

`commands/` 只供 Claude Code 使用，Codex / Hermes 包中不需要。`plugin.json` 也不在这个包里，它只在把整个仓库当作插件导入时使用。推荐用同步脚本安装或更新（`--create-roots` 会创建缺失的安装根目录；脚本从不删除文件）：

```bash
python -X utf8 scripts/sync_hosts.py --host codex --host hermes --apply --create-roots
python -X utf8 scripts/sync_hosts.py --host codex --host hermes --verify
```

### Codex：启用命令 Skill

Codex 的自定义入口是 Skill 选择器（`$`），不是任意命名的 `/Git...` Slash Command。Codex 递归扫描 Skill 根目录，因此会同时加载根 Skill 和 `skills/` 下的八个命令 Skill；`agents/openai.yaml` 中的简短说明会显示在 Skill 列表里。八个命令 Skill 都设置了 `policy.allow_implicit_invocation: false`，只在显式选择时运行，语义自动触发由根 Skill 负责。

用户级安装位置是 `~/.agents/skills/MAGOS`。已经安装在旧位置 `$CODEX_HOME/skills/MAGOS`（默认 `~/.codex/skills/MAGOS`）的，同步脚本会继续更新旧位置；两个位置不要同时保留，否则 Codex 会看到重复的 Skill。手动复制出来的包里要删掉入口 Skill `git-orchestrator`：它只供插件安装使用，同步脚本也不复制它；留着它，Codex 会多看到一个与根 Skill 描述相同的 Skill。下面每段命令的最后一行就是做这件事。手动安装（Windows PowerShell）：

```powershell
$codexPackage = Join-Path $HOME ".agents\skills\MAGOS"
New-Item -ItemType Directory -Force $codexPackage | Out-Null
Copy-Item -Path .\SKILL.md, .\references, .\skills -Destination $codexPackage -Recurse -Force
Remove-Item (Join-Path $codexPackage "skills\git-orchestrator") -Recurse -Force -ErrorAction SilentlyContinue
```

macOS / Linux：

```bash
mkdir -p "$HOME/.agents/skills/MAGOS"
cp -R SKILL.md references skills "$HOME/.agents/skills/MAGOS/"
cd "$HOME/.agents/skills/MAGOS" && rm -r skills/git-orchestrator
```

重新启动 Codex 后，输入 `$` 选择命令 Skill，或直接调用 `$git-recon`、`$git-analyze`、`$git-recommend`、`$git-integrate`、`$git-cleanup`、`$git-converge`、`$git-sweep`、`$git-plan`。`/skills` 可打开 Skill 浏览入口。参数写在 Skill 名后面，例如 `$git-analyze agent/auth --remote`；加 `--help` 可查看完整参数说明。

### Hermes：启用 Slash Skill

Hermes 会把已安装的每个 Skill 自动注册成一个 Slash Command（名称取自 frontmatter 的 `name`），并将 `description` 用作命令说明。安装后会出现 `/multi-agent-git-orchestrator` 和八个 `/git-*` 命令。

Hermes 的 home 目录依次取 `HERMES_HOME`、Windows 上的 `%LOCALAPPDATA%\hermes`、其他系统上的 `~/.hermes`；home 不是来自 `HERMES_HOME` 时，如果其中的 `active_profile` 指定了非 `default` 且目录存在的 profile，则改用 `profiles/<name>`。Skill 放在 home 下的 `skills/`。同步脚本按同样规则定位；下面的手动安装不处理 `active_profile`，有非默认的 `active_profile` 时请用同步脚本。如果已有 `<Hermes home>/skills/MAGOS`（例如直接 `git clone` 的安装），脚本会沿用它；如果它是 git checkout，脚本会拒绝复制文件，请改用 git 更新。手动复制出来的包里要删掉入口 Skill `git-orchestrator`：它只供插件安装使用，同步脚本也不复制它；留着它，会多出一个与根 Skill 描述相同的 Skill，Hermes 里还会多出 `/git-orchestrator`。下面每段命令的最后一行就是做这件事。手动安装（Windows PowerShell）：

```powershell
$hermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$hermesSkills = Join-Path $hermesHome "skills\multi-agent-git-orchestrator"
New-Item -ItemType Directory -Force $hermesSkills | Out-Null
Copy-Item -Path .\SKILL.md, .\references, .\skills -Destination $hermesSkills -Recurse -Force
Remove-Item (Join-Path $hermesSkills "skills\git-orchestrator") -Recurse -Force -ErrorAction SilentlyContinue
```

macOS / Linux：

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/skills/multi-agent-git-orchestrator"
cp -R SKILL.md references skills "${HERMES_HOME:-$HOME/.hermes}/skills/multi-agent-git-orchestrator/"
cd "${HERMES_HOME:-$HOME/.hermes}/skills/multi-agent-git-orchestrator" && rm -r skills/git-orchestrator
```

重新启动 Hermes 后，可运行 `hermes skills list` 查看各命令说明，并调用 `/git-recon`、`/git-analyze`、`/git-recommend`、`/git-integrate`、`/git-cleanup`、`/git-converge`、`/git-sweep` 或 `/git-plan`。参数直接跟在命令后面，例如 `/git-analyze main --remote`，也可用 `/git-analyze --help` 查看完整说明。Hermes 的 Skill 查看工具不接受含 `..` 的路径，适配层会改用 `[Skill directory: ...]` 给出的绝对路径读取共享文件。Hermes 没有按 Skill 关闭自动调用的开关，因此 `/git-integrate`、`/git-cleanup`、`/git-converge`、`/git-sweep` 与 `/git-plan` 在适配层中规定：未经用户显式调用时不写入仓库。

如果宿主不支持自定义 Slash Command，也可以直接输入：

```text
GitRecon
GitAnalyze agent/auth
GitRecommend
```

### 作为 Agent Plugin 导入

仓库根目录的 `plugin.json` 是一份插件“说明书”，格式遵循 [Agent Plugins 1.0.0 规范](https://agent-plugins.org/specification)。支持这个规范的工具（例如 Codex 的插件安装）可以把整个仓库当作一个名叫 `magos` 的插件导入；上面“从插件市场安装”在 Codex 里走的就是它。紧挨着它的根目录 `mcp.json`（Agent Plugins 的 MCP 文件）声明了 Codex 为点击批准而启动的本地 MCP 服务器 `magos`。

导入后会是这样：

| 你关心的问题 | 答案 |
|---|---|
| 能用哪些命令？ | `skills/` 下的八个命令 Skill：`git-recon`、`git-analyze`、`git-recommend`、`git-integrate`、`git-cleanup`、`git-converge`、`git-sweep`、`git-plan`，外加入口 Skill `git-orchestrator`。有的工具会加上插件名前缀，例如 Codex 显示为 `magos:git-recon`。 |
| 根目录的 `SKILL.md`（总规则）呢？ | 它不算插件 Skill，因为规范只认 `skills/` 下面的文件夹。所以插件里有入口 Skill `git-orchestrator`，它带着同样的描述（会自动触发），内容是去读根目录的 `SKILL.md`；八个命令也会去读它和 `references/` 里的规则。已在 Claude Code、Codex、Hermes 里实测：插件能安装、启用，Skill 名字如上表；各命令完整跑一遍还没有逐一实测。 |
| Claude Code 能用吗？ | Claude Code 不读这个文件，它读的是 `.claude-plugin/plugin.json` 和 `.claude-plugin/marketplace.json`。请按上面“从插件市场安装”的方法安装。 |
| Hermes 用哪种方式？ | 两种都行。`hermes plugins install UlyssesLeoLee/MAGOS --enable` 读的是 Hermes 原生清单 `plugin.yaml`（不是这个 `plugin.json`），命令是 `/magos:git-recon` 这样的名字，带 `[Skill directory: …]` 路径提示；插件里的每个 Skill 都会列进系统提示的 `<available_skills>`，描述取自 `__init__.py` 里的 `INDEX_DESCRIPTIONS`（Hermes 不读插件 Skill 的 SKILL.md 描述，不传这一行的话模型只看到名字）：总规则那行写明触发场景，会修改仓库的命令那几行写明“只在用户明确输入时运行，不要自己加载”。五个会修改仓库的命令只认用户明确输入的 `/magos:git-*`、`/git-*`、`$magos:git-*` 或 `$git-*` 调用（Claude Code 里同名的 `/magos:Git*` 命令也是明确调用）。 |

仓库根目录有 `.claude-plugin/`（Claude Code 的 `plugin.json` 和 Claude Code、Codex 共用的 `marketplace.json`）和 Hermes 的 `plugin.yaml`、`__init__.py`，故意没有 `.codex-plugin/` 或 `.cursor-plugin/`。Codex 一看到 `.claude-plugin/`、`.codex-plugin/` 或 `.cursor-plugin/` 就会给 Skill 加上插件名前缀，仓库带着其中的 `.claude-plugin/`，所以**把仓库直接 `git clone` 到 Codex 的 Skill 目录时，命令会变成 `$magos:git-recon` 这样的名字**。Codex 和 Hermes 请用同步脚本安装：它复制 `SKILL.md`、`references/*.md` 和八个命令 Skill（各自的 `SKILL.md` 与 `agents/openai.yaml`），不会带上 `.claude-plugin/` 和入口 Skill `git-orchestrator`，命令名仍是 `$git-recon`、`/git-recon`。只有根目录的 `plugin.json` 不会触发改名。

一处已知的偏差：规范第 8 节要求“只给某一个工具用的文件”放进以反向域名命名的文件夹（例如 `com.example.client/`）。`commands/` 只给 Claude Code 用，`plugin.yaml` 和 `__init__.py` 只给 Hermes 用，却都放在顶层。插件工具会直接忽略它们，不影响导入；安装脚本和测试都按顶层路径使用它们。

改版本号时，`plugin.json`、`.claude-plugin/plugin.json` 和 `plugin.yaml` 的 `version`，`SKILL.md` 与 `skills/git-orchestrator/SKILL.md` 的 `metadata.version`，`scripts/magos_guard.py` 的 `GUARD_VERSION`，以及 `references/commands.md` 第 3 行要一起改（源码契约与守卫测试会检查它们是否一致），并在 `CHANGELOG.md` 里写上这个版本的一节。发布前的检查需要 pytest 与 PyYAML（没有 PyYAML 时供应链检查失败）：用 `python -m pip install --require-hashes --only-binary :all: -r .github/requirements/tests-py314.txt` 安装（Python 3.9 用 `.github/requirements-py39/tests-py39.txt`），第五条另需 `.github/requirements/coverage.txt`。运行：

```bash
python -X utf8 tests/codex/contracts/run_contract_cases.py --check
python -X utf8 tests/claude/scripts/run_claude_contracts.py --check
python -X utf8 tests/codex/contracts/test_agent_plugin.py
python -m pytest tests/codex/guard -q -p no:cacheprovider
python -X utf8 tests/codex/coverage_gate.py
```

前两条运行全部源码契约用例（包括检查插件格式的 `package/agent-plugin`），不写任何文件，有失败时以退出码 1 结束；第三条故意制造各种错误（清单写错、版本号对不上、文件夹里多出链接等），确认检查真的能把它们找出来；第四条运行车道守卫的测试；第五条是覆盖率门槛，见下面的“覆盖率门槛”。

CI 由 `.github/` 下的三个工作流和 Dependabot 配置承担：

- `.github/workflows/test.yml`：在 Windows 与 Linux、Python 3.9 / 3.14 上运行前四条，在 Windows 与 Python 3.14 上运行第五条，并检查发布标签 `v<版本号>` 与包的版本号一致。
- `.github/workflows/security.yml`：在推送到 `main`、`develop`、`develop_codex` 及向它们发起拉取请求时、推送 `v*` 标签时和每周运行：在 Windows 与 Linux、Python 3.14 上重放 1.0.2 审计确认的问题（`tests/codex/guard/data/security_regressions.jsonl`，每例都规定判定结果，拒绝时还规定理由），运行加固与评审测试和供应链检查（Action 按提交 SHA 固定；除 CodeQL 上传结果外每个作业的权限都只读；安装包按版本与 sha256 固定且只用 wheel；被跟踪的文件中没有凭据；守卫与启动器不导入网络模块，守卫只启动 git，其 git 执行器拒绝本地子命令以外的一切子命令；部分克隆（partial clone）中 git 读取差异时会自行从 promisor 远端补取缺失的对象）；工作流只能运行列出的命令行、只能设置列出的环境变量；并用 zizmor 审计工作流与 Dependabot 配置（不接受行内忽略和配置文件，收集全部输入），有任何发现或无法解析的文件即失败。
- `.github/workflows/codeql.yml`：在推送到 `main`、向 `main` 发起拉取请求时和每周运行，用 CodeQL 分析 Python 源码与工作流。
- `.github/dependabot.yml`：每周发起拉取请求，把 `.github/workflows` 里按提交 SHA 固定的 Action 和 `.github/requirements`（Python 3.14）里按 hash 固定的包更新到最新版本，新版本发布满 7 天后才更新；`.github/requirements-py39` 不更新。

**按 hash 固定的安装。**CI 的每次安装都只从 `.github/requirements`（Python 3.14）或 `.github/requirements-py39`（固定为支持 3.9 的最后版本）中按 hash 固定的 wheel 安装。

**覆盖率门槛。**第五条运行 `.quality/qguard.json` 的覆盖率命令，任何源文件或整个项目的行覆盖率不高于 90% 时以退出码 1 结束。

---

## 适用场景

特别适合：

- Claude Code / Codex / Cursor 多 Agent 开发
- Git Worktree 并行开发
- AI 自动任务拆分
- 大量 Agent Branch 管理
- Human-in-the-loop Review
- Agent Worktree 可视化
- 自动 Merge Queue
- AI 生成代码的选择性集成

---

## Philosophy

Git 不只是版本管理工具。

在多 Agent 软件工程中，它还可以成为：

```text
Isolation Layer
+
Dependency Graph
+
Review Boundary
+
Integration Protocol
+
Rollback System
```

**让 Agent 可以大胆开发，让主分支保持可控。**

---

## License

Apache-2.0
