# 用户级安装同步与验收

从仓库根目录运行以下命令。不带参数时列出每个目标文件的状态以及源文件、已安装文件的 SHA-256，不会写入文件。

```powershell
python -X utf8 scripts/sync_hosts.py
python -X utf8 scripts/sync_hosts.py --verify
python -X utf8 scripts/sync_hosts.py --apply --create-roots
python -X utf8 scripts/sync_hosts.py --verify
```

用 `--host codex` 只检查、同步或校验 Codex；重复 `--host` 可以选择多个宿主。

`--verify` 在所有文件都匹配时返回 0，存在缺失或差异时返回 1；缺少安装根目录、仓库源文件，或目标路径不安全时返回 2。`--apply` 会先检查所有目标，预检查失败时不写入任何文件。安装根目录不存在时，加 `--create-roots` 由脚本创建，否则预检查失败；`--create-roots` 只在其余预检查都通过时才创建目录。复制中断后，可以再运行 `--verify` 查看状态，再重试 `--apply`。使用 `--json` 可以保存机器可读的验收记录。

同步范围如下：

| 目标 | 安装根目录 | 同步文件 |
| --- | --- | --- |
| Claude | `~/.claude/commands` | 仓库 `commands/Git*.md`，共 6 个 |
| Codex | `~/.agents/skills/MAGOS`。如果已有旧位置 `$CODEX_HOME/skills/MAGOS`（默认 `~/.codex/skills/MAGOS`）且新位置不存在，则继续使用旧位置 | 宿主中立包：`SKILL.md`、`references/*.md` 全部、每个 `skills/git-*/SKILL.md` 与 `agents/openai.yaml` |
| Hermes | `<Hermes home>/skills/multi-agent-git-orchestrator`。Hermes home 依次取 `HERMES_HOME`、Windows 的 `%LOCALAPPDATA%\hermes`、其他系统的 `~/.hermes`，有非默认的 `active_profile` 时取其 `profiles/<name>`；已有 `<Hermes home>/skills/MAGOS` 时沿用它 | 与 Codex 相同的宿主中立包 |

- **文件清单：**宿主中立包的清单由 `scripts/sync_hosts.py` 的 `package_files()` 根据仓库内容生成，测试工具 `tests/codex/run_host_cases.py` 用同一个函数准备 fixture，因此测试布局与真实安装一致。
- **`plugin.json`：**Agent Plugins 1.0.0 清单，只在把整个仓库当作插件导入时使用，不在同步范围内。仓库不放 `.codex-plugin/`、`.claude-plugin/`、`.cursor-plugin/`，否则 git clone 安装的 Codex 会把 Skill 改名为 `magos:<name>`。
- **`commands/`：**Codex 与 Hermes 包不再需要它。旧版本安装留下的 `commands/` 不会被删除，适配层也不会读取它。
- **写入规则：**脚本只更新表中的相对路径，并创建这些路径所需的子目录；不会删除任何文件。文件已匹配时不会重写。`--apply` 采用同目录临时文件替换目标文件。
- **git checkout：**安装根目录本身是 git checkout（含 `.git`，例如直接 clone 到 Skill 目录）时，脚本拒绝写入，并提示改用 git 更新，以免弄脏该 checkout 所在分支。
- **重复安装：**Codex 同时扫描 `~/.agents/skills` 和 `$CODEX_HOME/skills`。两个位置都有 MAGOS 时，脚本会输出 `NOTE` 提示重复安装，请只保留一个。
- **自定义安装位置：**可用 `--codex-root PATH`、`--hermes-root PATH` 覆盖默认安装根目录。

如需在隔离目录验证脚本，可以指定 `--home PATH`（此时忽略 `CODEX_HOME`、`HERMES_HOME` 和 `LOCALAPPDATA`，Windows 上的 Hermes home 取 `<home>\AppData\Local\hermes`）。例如：

```powershell
python -X utf8 scripts/sync_hosts.py --host codex --host hermes --home C:\temp\magos-test-home --apply --create-roots --json
```

源码契约用例 `package/install-layout` 会自动执行上述临时安装，并检查以下各项：

- 适配层中的每个 `../../` 引用都能解析；
- 根 `SKILL.md` 引用的 `references/` 文件都存在；
- 适配层不经由 `commands/`；
- 六个 `agents/openai.yaml` 都设置了 `allow_implicit_invocation: false`；
- 按 Codex 与 Hermes 的发现规则（复刻版，并非真实宿主），每个 Skill 只出现一次；对提交后会进入仓库的文件（已跟踪文件，加上未被忽略的未跟踪文件；相当于直接 git clone 到 Skill 目录）也做同样检查；
- 每个 SKILL.md 的 frontmatter 都在严格 YAML 子集内（无 flow 写法、普通值不含 `: `、metadata 只有字符串），装了 PyYAML 时还会交叉核对；
- 仓库里没有 `.codex-plugin/`、`.claude-plugin/`、`.cursor-plugin/`。

源码契约用例 `package/agent-plugin` 检查 Agent Plugins 1.0.0 格式：`plugin.json` 符合封闭的清单 schema，版本号与 `SKILL.md`、`references/commands.md` 一致，`skills/` 下恰好发现六个适配层且都符合 Agent Skills 规则，路径不越出插件根目录、没有链接。`python -X utf8 tests/codex/contracts/test_agent_plugin.py` 逐一植入各种缺陷（清单字段错误、版本号漂移、多余的链接、frontmatter 写法不合规等），确认每种都会被对应的检查发现；它还单独测试严格 frontmatter 读取器，并在 git 仓库里检查未暂存的新文件。

`--verify` 只校验磁盘上的安装内容。参数灰字提示由各宿主的命令或 Skill 选择界面决定；更新安装文件后，可能需要重新载入宿主会话才能看到新的说明，界面效果仍需在对应宿主中单独检查。
