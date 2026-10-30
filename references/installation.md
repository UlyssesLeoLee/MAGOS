# 用户级安装同步与验收

## 插件市场安装（推荐）

三个平台都能直接从仓库安装插件 `magos`，不需要下面的同步脚本：

| 平台 | 安装 | 读取的清单 | 命令名 |
| --- | --- | --- | --- |
| Claude Code | `/plugin marketplace add UlyssesLeoLee/MAGOS`，然后 `/plugin install magos@magos` | `.claude-plugin/marketplace.json` → `.claude-plugin/plugin.json` | `/magos:GitRecon` … `/magos:GitPlan` |
| Codex | `codex plugin marketplace add UlyssesLeoLee/MAGOS`，然后 `codex plugin add magos@magos` | `.claude-plugin/marketplace.json`（Codex 也读这个路径）→ 根目录 `plugin.json`（Agent Plugins）与 `mcp.json`（批准服务器 `magos`） | `$magos:git-recon` … `$magos:git-plan` |
| Hermes | `hermes plugins install UlyssesLeoLee/MAGOS --enable` | `plugin.yaml` + `__init__.py`（原生插件，优先于 `plugin.json`） | `/magos:git-recon` … `/magos:git-plan` |

- 市场清单只列一个插件 `magos`，来源是仓库根目录 `./`，Claude Code 与 Codex 都接受这个写法。
- 插件宿主只加载 `skills/<name>/SKILL.md`，不加载根目录 `SKILL.md`，所以插件里带有入口 Skill `skills/git-orchestrator`（描述与根 Skill 相同，内容是读取 `../../SKILL.md`）。同步脚本的 `PLUGIN_ONLY_SKILLS` 会把它排除在 Codex / Hermes 包之外，因为这两种安装已经有根 Skill。
- Hermes 的可移植 Agent Plugin 会把命令命名为 `/agent-plugin-magos-<hash>:git-recon`；`plugin.yaml` 与 `__init__.py`（调用 `ctx.register_skill()`，并为守卫注册两个 `pre_tool_call` 回调）让 Hermes 改按原生插件加载，命令名才是 `/magos:git-*`。Hermes 会把插件里每个 Skill 列进系统提示的 `<available_skills>`；描述取自 `__init__.py` 的 `INDEX_DESCRIPTIONS`（SKILL.md 里的描述会被 Hermes 截成 60 个字符，不传的话模型只看到名字）。总规则那行写触发场景，会写仓库的命令那几行写“不要自己加载”。
- Claude Code 里每个命令只有一套：`commands/` 里的 `/magos:GitRecon` … `/magos:GitPlan`。`skills/git-*` 八个适配层是给 Codex 与 Hermes 用的，头信息设置了 `user-invocable: false` 与 `disable-model-invocation: true`，所以 Claude Code 不在 `/` 菜单里列出它们，模型也不会自己调用；Codex 只读它认识的字段，Hermes 把头信息当作映射读取，两者都忽略这两个键。入口 Skill `git-orchestrator` 只设置了 `user-invocable: false`：它不在 `/` 菜单里，由 Claude 在你描述问题时自己加载，菜单里只剩 `/magos:GitXxx` 一种写法。会写仓库的五个命令（`GitIntegrate`、`GitCleanup`、`GitConverge`、`GitSweep`、`GitPlan`）在 `commands/*.md` 里也设置了 `disable-model-invocation: true`：只有用户输入的斜杠命令能运行它们，模型不能自己调用。
- Hermes 官方插件目录（`hermes plugins install magos`）需要仓库所有者向 NousResearch/hermes-agent 提交 `plugin-catalog/magos.yaml`，并固定一个 40 位 commit SHA。
- 车道守卫：Claude Code 的插件安装同时启用守卫钩子（`hooks/hooks.json`，作用于在 Claude Code 里打开的每个仓库）；Codex 的插件安装不启用钩子：Codex 的钩子来自另外运行的 `install --host codex`，把它打印的条目合并进 `~/.codex/hooks.json`，并在 `/hooks` 里信任一次（Codex 不读 Agent Plugins 清单的插件里的钩子）；插件安装带来批准服务器 `magos`（插件根目录的 `mcp.json`），所以在 Codex 里，`install` 可以由代理调用工具 `magos_approve`，你在 Codex 的对话框里先勾选 Approve 再点 Accept（接受）后运行。Hermes 的插件自己运行守卫：`hermes plugins update magos` 并重启 Hermes 之后，插件的两个 `pre_tool_call` 回调对每一次 `terminal` 调用运行守卫，用户专属命令经 Hermes 自己的批准提示批准，不需要 `install --host hermes`，也没有要合并的条目（`MAGOS_GUARD=off` 关闭）；`install --host hermes` 只用于没有安装插件的路线，它生成的条目拒绝每一条用户专属命令（见“车道守卫”）。
- 以上安装流程以本机的仓库副本作为插件来源实测过：Claude Code 2.1.296、Codex CLI 0.162.1、Hermes（2026.9.24）都能安装并启用，命令名与上表一致。从 GitHub 来源安装或更新时，Hermes 还会先扫描插件目录（见“升级”）。

## 固定版本

每个版本的发布提交带有标签 `v<版本号>`（例如 `v1.0.9`），各版本的变化、安全说明与升级步骤见仓库根目录的 `CHANGELOG.md`。上面的安装命令跟随默认分支；要停留在某个版本，用下面的写法安装：

| 安装方式 | 固定到 `v1.0.9` |
| --- | --- |
| Claude Code 插件市场 | `claude plugin marketplace add UlyssesLeoLee/MAGOS@v1.0.9`，然后 `claude plugin install magos@magos` |
| Claude Code clone 到 Skill 目录 | `git clone --branch v1.0.9 https://github.com/UlyssesLeoLee/MAGOS ~/.claude/skills/magos` |
| Hermes 插件 | `hermes plugins install UlyssesLeoLee/MAGOS --ref <v1.0.9 的 40 位 commit SHA> --enable`；已经安装过 MAGOS 时加 `--force` |
| Codex 与同步脚本 | 在 `git clone --branch v1.0.9 https://github.com/UlyssesLeoLee/MAGOS` 得到的目录里运行同步脚本与 `install --host codex` |

- Hermes 只接受 40 位 commit SHA。`git ls-remote https://github.com/UlyssesLeoLee/MAGOS refs/tags/v1.0.9 "refs/tags/v1.0.9^{}"` 只列出这一个标签：有 `refs/tags/v1.0.9^{}` 一行时取那一行的 SHA（它是标签指向的提交），否则取 `refs/tags/v1.0.9` 一行的 SHA。其他版本把两处 `v1.0.9` 换成那个标签；不要用 `refs/tags/v1.0.9*` 这样的通配写法，它也会列出 `v1.0.90` 等其他标签。
- Hermes 把带 `--ref` 的安装记为固定（pinned）。对固定的安装，`hermes plugins update magos` 会拒绝并提示带 `--ref` 的重装命令；不带 `--ref` 的 `hermes plugins install UlyssesLeoLee/MAGOS --force --enable` 会重新安装原来固定的那个提交，而不是最新版本。
- 移动固定点（包括回滚之后重新升级）：`hermes plugins install UlyssesLeoLee/MAGOS --ref <新标签的 40 位 commit SHA> --force --enable`，安装仍然是固定的。
- 回到跟随默认分支：`hermes plugins remove magos`，然后 `hermes plugins install UlyssesLeoLee/MAGOS --enable`。两条命令之间插件目录不存在，指向 `<Hermes home>/plugins/magos/hooks/run-guard.cmd` 的 Hermes 钩子条目（`config.yaml` 里还留着它时；插件路线不需要它，见“升级”）找不到启动器，`fail_closed: true` 会拒绝每一次 terminal 调用，所以两条命令要紧接着运行。
- 确认 Hermes 装的是哪个提交：`<Hermes home>/plugins/.install-metadata.json` 里 `magos` 的 `revision` 与 `pinned`；或者 `py -3 "<Hermes home>/plugins/magos/scripts/magos_guard.py" version`（macOS / Linux 用 `python3`）输出的守卫版本。
- 固定版本收不到之后的修复，包括守卫的安全修复。固定后请关注 `CHANGELOG.md`，有新版本时把固定点移到新标签，并按下面的“升级”步骤处理守卫副本。
- 标签 `v1.0` 是插件化与改号之前的 3.4.0 版 Skill，不是插件版本；1.0.0 没有标签，也不要固定到它（原因见 `CHANGELOG.md`）。

## 升级

### Claude Code

1. 插件市场安装：`claude plugin marketplace update magos`，然后 `claude plugin update magos@magos`（会话里是 `/plugin marketplace update magos` 与 `/plugin update magos@magos`）。清单写有版本号，Claude Code 只在版本号变化时更新已安装的插件。
2. 重启每一个正在运行的 Claude Code 会话。插件钩子从 `~/.claude/plugins/cache/magos/magos/<版本>/` 运行，更新之前启动的会话继续运行旧版本的钩子与守卫。
3. 确认：`claude plugin list` 显示新版本；`py -3 "<新版本的插件目录>/scripts/magos_guard.py" version` 输出守卫版本、文件 sha256 与路径。

**同一个命令出现两套时**：正常只有一套 `/magos:GitXxx`。多出来的通常是 `~/.claude/commands/Git*.md` 里的命令文件副本（`sync_hosts.py --host claude` 写入的位置，多出无前缀的 `/GitRecon` 一类命令；同步脚本不删除任何文件，请自己删除这些文件），或者把仓库 clone 在 `~/.claude/skills/` 下时，根目录的 `SKILL.md` 另作为个人 Skill `MAGOS` 加载，协调器 Skill 因此出现两份（只用插件时把 clone 移出该目录）。`claude plugin list` 显示的版本应是最新版本。

clone 到 `~/.claude/skills/magos` 的安装在该目录执行 `git pull`（固定在标签上时执行 `git fetch --tags` 与 `git checkout v<新版本>`），然后同样重启所有会话。复制命令文件的旧方式按下面“同步脚本安装”重新同步。用 `install --host claude` 生成过用户级片段的，按下面“守卫副本与生成的配置”处理。

### Codex

1. 插件市场安装：`codex plugin marketplace upgrade magos`，然后 `codex plugin add magos@magos`，再重启 Codex（这组升级命令没有在真实的 Codex 上实测过）。同步脚本安装：在仓库目录 `git pull`，然后 `python -X utf8 scripts/sync_hosts.py --host codex --apply`。
2. Codex 的钩子运行 `~/.magos/guard` 下的守卫副本，升级插件不会改变它；按下面“守卫副本与生成的配置”刷新。批准服务器 `magos` 随插件升级（插件根目录的 `mcp.json` 运行插件目录里的 `scripts/magos_guard.py mcp`），重启 Codex 后生效。

### Hermes

1. 没有固定版本的安装：`hermes plugins update magos`。Hermes 在发布新版本之前扫描插件目录；扫描结果需要确认时 `update` 会拒绝，而且它没有 `--force`，这时改用 `hermes plugins install UlyssesLeoLee/MAGOS --force --enable`。固定版本的安装（`update` 提示插件已固定）按上面“固定版本”移动固定点。仓库的契约测试保证发布的文件里没有 Hermes 扫描器评为高危的写法（例如“echo 文本交给 shell 执行”）。
2. 用 `--force` 重装后，`<Hermes home>/plugins/` 下如果留有 `.previous-*` 目录（上一版本的备份），确认新版本可用后删除它；删除失败时（例如其中的 `__pycache__` 删不掉），先把它移出 `plugins/` 目录，再运行下一个 `hermes` 命令。
3. Hermes 插件自己通过 `pre_tool_call` 回调运行守卫（用插件目录里的 `scripts/magos_guard.py`），不需要 `install`，也没有要合并的条目：`hermes plugins update magos` 并重启 Hermes 之后，守卫对每一次 terminal 调用生效，包括只为 Skill 才装了插件的用户；`MAGOS_GUARD=off`（写在 Hermes 进程的环境里）、`hermes plugins disable magos` 或 `git config --local magos.guard off` 关闭它。`config.yaml` 里 `install --host hermes` 生成过的 MAGOS `hooks:` 条目要删掉：它在 Hermes 询问之前就拒绝每一条用户专属命令，还让守卫在每次 terminal 调用里多运行一次，`doctor` 把这种情形报告为问题。仍然保留这条条目时：它指向 Hermes 插件自己的启动器 `<Hermes home>/plugins/magos/hooks/run-guard.cmd` 时，随插件一起升级；指向 `~/.magos/guard` 下的副本时，按下面“守卫副本与生成的配置”刷新；用新版本运行的 `doctor` 会检查 `guard/generated/hermes.yaml` 里的启动器：启动器不存在（Hermes 插件已被删除，`fail_closed` 会拒绝每一次 terminal 调用），或它旁边的守卫版本与正在运行的守卫不同，都报告为问题。
4. 重启 Hermes。

### 守卫副本与生成的配置

`install` 把守卫与启动器复制到守卫目录（默认 `~/.magos`，可用 `--home` 或 `MAGOS_HOME` 指定）下的 `guard/`，Codex 钩子（以及不运行 Hermes 插件启动器时的 Hermes 钩子）运行这份副本。升级 MAGOS 后：

1. 用新版本运行 `py -3 "<新版本的 MAGOS 目录>/scripts/magos_guard.py" doctor`（macOS / Linux 用 `python3`）；用 `install --home <目录>` 安装过副本的，运行 `doctor --home <目录>`（或设置同样的 `MAGOS_HOME`），否则 `doctor` 找不到那份副本。它输出正在运行的守卫版本，并逐字节比较副本；副本与它不同时，它以退出码 1 结束并打印刷新命令（每个生成过配置的宿主一条 `install --host <宿主>`，给了 `--home` 时命令也带同样的 `--home`；没有生成过配置时三个宿主各一条）。副本比正在运行的守卫新时，它不打印 `install` 命令（`install` 会以退出码 18 拒绝），而是请你用 `VERSION.json` 记录的那个更新的 MAGOS 运行 `doctor`。它还输出一行 `guard copy provenance: <版本> (<sha256 前 12 位>) from <来源>, installed <时间>`，内容取自 `VERSION.json`，只供参考。从副本本身运行 `doctor` 时，它与 `VERSION.json` 记录的来源比较，并说明比较的是哪个文件。
2. 运行这些 `install` 命令：在 Claude Code 里（`magos.approval` 为 `prompt`，即默认值），代理先问你，你同意后它运行命令，宿主弹出权限对话框，点一下即批准（`auto-safe` 时，复制到默认守卫目录且不带 `--allow-downgrade` 的 `install` 不弹框）；在 Codex 里，代理调用工具 `magos_approve`，你在 Codex 的对话框里先勾选 Approve 再点 Accept（`auto-safe` 时也弹出）；在 Hermes 里（装了 Hermes 插件时），代理用 `terminal` 工具运行命令，你在 Hermes 的批准提示里批准（`auto-safe` 时，复制到默认守卫目录且不带 `--allow-downgrade` 的 `install` 不询问）；`magos.approval` 为 `terminal`，或宿主没有批准提示（Codex 的批准策略为 `never`，Hermes 在 `/yolo` 或 `approvals.mode: off` 下不经人批准），由你在自己的终端里运行（`install` 需要真实控制台）。输出 `guard copy <旧版本> -> <新版本>`（没有版本号的旧副本显示为 `unversioned`）或 `guard copy unchanged (<版本>)`。
3. 把 `install` 打印的片段（也保存在 `<守卫目录>/guard/generated/<宿主>.json|yaml`；`install --host codex` 还写出 `codex-mcp.toml`，里面是没有装插件的 Codex 用的 `[mcp_servers.magos]` 条目，`doctor` 会检查它）与宿主配置里已合并的条目对比：不同时替换它（Codex 替换后在 `/hooks` 里重新信任，Hermes 在首次使用时重新批准），相同时不用改配置。
4. 在已武装（`arm`）的仓库里运行 `doctor`：它报告钩子内容与本版本不同、记录的守卫命令指向不存在的脚本，或记录的守卫比正在运行的守卫旧时，重新运行它打印的 `arm` 命令（在宿主的批准提示里点一下批准；`terminal` 级别或没有批准提示时，在自己的终端里运行）。`~/.magos`（或 `MAGOS_HOME`）下有与正在运行的守卫同版本的副本时，`arm` 记录这份副本的路径，插件升级不会让它失效；否则记录正在运行的守卫。
5. 由 1.0.0 或 1.0.1 武装过的仓库：那些版本的 `arm` 把 `gc.packRefs` 与 `maintenance.pack-refs.enabled` 设为 `false`，却没有记录原来的值，所以重新 `arm` 记录到的也是 `false`，之后 `disarm` 让两项保持 `false`（没有记录时 `disarm` 会打印下面两条命令）。要恢复 Git 的默认值，`disarm` 之后在该仓库运行 `git config --local --unset gc.packRefs` 与 `git config --local --unset maintenance.pack-refs.enabled`。

### 回滚

回滚到旧版本会带回该版本之后修复的问题，包括守卫的安全问题（每个版本修复了什么见 `CHANGELOG.md`）；只在新版本无法使用时回滚，并尽快重新升级。

- Claude Code：`claude plugin uninstall magos@magos`、`claude plugin marketplace remove magos`，再按“固定版本”从旧标签安装，并重启所有会话；clone 安装在该目录 `git checkout v<旧版本>`。只想停用时运行 `claude plugin disable magos`。
- Hermes：`hermes plugins install UlyssesLeoLee/MAGOS --ref <旧版本的 40 位 commit SHA> --force --enable`，然后重启 Hermes。这样的安装是固定的：重新升级时按“固定版本”移动固定点或回到跟随默认分支，`hermes plugins update magos` 与不带 `--ref` 的重装都不会离开旧版本。
- Codex 与同步脚本安装：在旧标签的 checkout 里运行同步脚本。
- 守卫副本：用回滚后的版本运行 `install --host <宿主>`。1.0.2 及之后的守卫不会用旧版本替换更新的副本（退出码 18），需要加 `--allow-downgrade`；更早的守卫直接复制。已武装的仓库用回滚后的版本重新运行 `arm`。
- 清单（claim）文件从 1.0.0 起都是格式 1，各版本都能读取。

## 同步脚本安装

从仓库根目录运行以下命令。不带参数时列出每个目标文件的状态以及源文件、已安装文件的 SHA-256，不会写入文件。

```powershell
python -X utf8 scripts/sync_hosts.py
python -X utf8 scripts/sync_hosts.py --verify
python -X utf8 scripts/sync_hosts.py --apply --create-roots
python -X utf8 scripts/sync_hosts.py --verify
```

用 `--host codex` 只检查、同步或校验 Codex；重复 `--host` 可以选择多个宿主。

`--verify` 在所有文件都匹配时返回 0，存在缺失或差异时返回 1；缺少安装根目录、仓库源文件，或目标路径不安全时返回 2。`--apply` 会先检查所有目标，预检查失败时不写入任何文件。安装根目录不存在时，加 `--create-roots` 由脚本创建，否则预检查失败；`--create-roots` 只在其余预检查都通过时才创建目录。复制中断后，可以再运行 `--verify` 查看状态，再重试 `--apply`。同步出去的文件不会随仓库更新：每次 `git pull` 或升级版本后都要再运行一次 `--apply`，`--verify` 会把过期的文件报告为差异。使用 `--json` 可以保存机器可读的验收记录。

同步范围如下：

| 目标 | 安装根目录 | 同步文件 |
| --- | --- | --- |
| Claude | `~/.claude/commands` | 仓库 `commands/Git*.md`，共 8 个（旧方式；推荐改用下面的 Claude Code 插件安装，不需要同步） |
| Codex | `~/.agents/skills/MAGOS`。如果已有旧位置 `$CODEX_HOME/skills/MAGOS`（默认 `~/.codex/skills/MAGOS`）且新位置不存在，则继续使用旧位置 | 宿主中立包：`SKILL.md`、`references/*.md` 全部、每个 `skills/git-*/SKILL.md` 与 `agents/openai.yaml` |
| Hermes | `<Hermes home>/skills/multi-agent-git-orchestrator`。Hermes home 依次取 `HERMES_HOME`、Windows 的 `%LOCALAPPDATA%\hermes`、其他系统的 `~/.hermes`，有非默认的 `active_profile` 时取其 `profiles/<name>`；已有 `<Hermes home>/skills/MAGOS` 时沿用它 | 与 Codex 相同的宿主中立包 |

- **文件清单：**宿主中立包的清单由 `scripts/sync_hosts.py` 的 `package_files()` 根据仓库内容生成，测试工具 `tests/codex/run_host_cases.py` 用同一个函数准备 fixture，因此测试布局与真实安装一致。守卫（`scripts/`、`hooks/`）不在包里，由 `install` 另外复制。
- **`plugin.json`：**Agent Plugins 1.0.0 清单，只在把整个仓库当作插件导入时使用，不在同步范围内。
- **`.claude-plugin/`、`plugin.yaml`、`__init__.py`：**插件清单（见上一节）。`.claude-plugin/plugin.json` 也让 `git clone` 到 `~/.claude/skills/magos` 的仓库被 Claude Code 加载为插件 `magos@skills-dir`。它们的 `name`、`version` 必须与 `plugin.json` 一致；`.claude-plugin/plugin.json` 不声明组件路径，`plugin.yaml` 不声明 hook、工具或依赖。它们都不在同步范围内：Codex 一看到 `.claude-plugin/` 就会给 Skill 加上 `magos:` 前缀，所以直接 git clone 到 Codex Skill 目录会得到 `$magos:git-recon`；用同步脚本安装的 Codex 与 Hermes 包不含它们，命令名不变。仓库不放 `.codex-plugin/`、`.cursor-plugin/`。
- **同时装了插件与命令副本：**Claude Code 已经加载 MAGOS 插件时，`--host claude` 会输出 `NOTE`，提示命令副本只会多出一套旧的 `/GitXxx`。识别两种插件安装：`~/.claude/skills/*/.claude-plugin/plugin.json` 的 `name` 为 `magos` 的 clone；插件市场安装，即 `~/.claude/plugins/installed_plugins.json` 里 `magos@<市场>` 有 `scope` 为 `user` 的条目（该文件不存在或格式不对时，改看 `~/.claude/plugins/cache/<市场>/<插件>/<版本>/.claude-plugin/plugin.json` 的 `name` 是否为 `magos`）。只装在某个项目里（`project`、`local`）的不算。不带 `--host` 运行时，发现这样的插件就跳过 Claude，只处理 Codex 与 Hermes；仍要复制命令时请显式加 `--host claude`。
- **`commands/`：**Codex 与 Hermes 包不包含 `commands/`。旧版本安装留下的 `commands/` 不会被删除，适配层也不读取它。
- **写入规则：**脚本只更新表中的相对路径，并创建这些路径所需的子目录；不会删除任何文件。文件已匹配时不会重写。`--apply` 采用同目录临时文件替换目标文件。
- **git checkout：**安装根目录本身是 git checkout（含 `.git`，例如直接 clone 到 Skill 目录）时，脚本拒绝写入，并提示改用 git 更新，以免弄脏该 checkout 所在分支。Codex 的 checkout 里有 `.claude-plugin/` 时，提示里还会说明 Skill 已变成 `$magos:git-*`，应把它移出 Skill 目录并改用同步脚本安装。
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
- 八个 `agents/openai.yaml` 都设置了 `allow_implicit_invocation: false`；
- 按 Codex 与 Hermes 的发现规则（复刻版，并非真实宿主），每个 Skill 只出现一次；对提交后会进入仓库的文件（已跟踪文件，加上未被忽略的未跟踪文件；相当于直接 git clone 到 Skill 目录）也做同样检查；
- 每个 SKILL.md 的 frontmatter 都在严格 YAML 子集内（无 flow 写法、普通值不含 `: `、metadata 只有字符串），装了 PyYAML 时还会交叉核对；
- 仓库里的宿主插件清单只有 `.claude-plugin/plugin.json` 与 `.claude-plugin/marketplace.json`（没有 `.codex-plugin/`、`.cursor-plugin/`）；Claude 清单的 `name`、`version` 与 `plugin.json` 一致、只含元数据字段；市场清单只列一个来源为 `./` 的插件 `magos`；`plugin.yaml` 的 `name`、`version` 与 `plugin.json` 一致，`__init__.py` 只注册 Skill；
- 同步出去的 Codex 与 Hermes 包里没有任何宿主插件清单。

源码契约用例 `package/agent-plugin` 检查 Agent Plugins 1.0.0 格式：`plugin.json` 符合封闭的清单 schema；版本号与 `SKILL.md`、`references/commands.md`、入口 Skill `skills/git-orchestrator/SKILL.md`（写有版本号时）和守卫的 `GUARD_VERSION` 一致；`skills/` 下恰好发现八个命令适配层与入口 Skill `git-orchestrator`，且都符合 Agent Skills 规则；只有五个会写仓库的适配层设置 `disable-model-invocation: true`；路径不越出插件根目录、没有链接。`python -X utf8 tests/codex/contracts/test_agent_plugin.py` 逐一植入各种缺陷（清单字段错误、版本号漂移、多余的链接、frontmatter 写法不合规等），确认每种都会被对应的检查发现；它还单独测试严格 frontmatter 读取器，并在 git 仓库里检查未暂存的新文件。

## 车道守卫（强约束钩子）

创建分支或工作树之前必须先登记计划修改的文件清单；清单与任何已有分支、工作树或已声明车道重叠时，创建动作被拒绝，并列出每一个冲突的分支与工作树。契约见 `references/lane-split.md`，实现是单文件 `scripts/magos_guard.py`（Python 3.9+，只用标准库）与启动器 `hooks/run-guard.cmd`；守卫需要 Git 2.36+（`doctor` 会报告更旧的 Git）。守卫不属于 `sync_hosts.py` 的同步范围，也不改任何插件清单；它不会自己写入宿主配置。

| 层 | 作用（检查的工具） | 怎么装 |
| --- | --- | --- |
| Claude Code 钩子 | 创建前拒绝：Bash、PowerShell、Monitor，带 worktree 隔离的 Agent / Task / Workflow，会话类 MCP 工具（名字含 `start_session`、`worktree`、`branch`、`hand_off_to_session`），可能执行命令的 MCP 工具（名字含 `run_in_terminal`、`terminal`、`shell`、`exec_command`、`execute_command`、`start_process`、`command`、`run_command`、`exec`、`execute`、`process`、`bash`、`powershell`、`cmd`），以及 EnterWorktree。每个被检查的工具与每个 MCP 工具只要带有字符串 `command`，都按命令行检查 | 随插件加载根目录 `hooks/hooks.json`；也可 `py -3 scripts/magos_guard.py install --host claude` 生成用户级片段（Claude Code 里由代理运行并经你点击批准，或在自己的终端里运行），自己合并进 `~/.claude/settings.json` |
| Codex 批准服务器 | 用户专属命令的点击批准（MCP 工具 `magos_approve`，钩子不检查它）：表单只有一个必选的 Approve 勾选框，勾选后点 Accept 才批准，没有不点击就运行的情形 | Codex 插件安装后由 Codex 自己启动：插件根目录的 `mcp.json` 经 git 运行 `scripts/magos_guard.py mcp`，本地进程，经标准输入输出通信，不联网；随 `codex plugin marketplace upgrade magos` 一起升级。`install --host codex` 另外生成 `<守卫目录>/guard/generated/codex-mcp.toml`，连同 `codex mcp add` 命令一起打印；只有没有装插件的 Codex 才需要把它写进 Codex 配置（插件已经启动一个名为 `magos` 的服务器），守卫从不改 `~/.codex/config.toml` |
| Codex 钩子 | 同上，检查 Bash 与会话类 MCP 工具 | `install --host codex` 生成 `<守卫目录>/guard/generated/codex.json`，自己合并进 `~/.codex/hooks.json`，并在 Codex 的 `/hooks` 里信任它 |
| Hermes 插件回调 | 同上，检查 terminal；用户专属命令交给 Hermes 自己的批准提示（你批准后命令才运行）；Hermes 会不经人批准时（`/yolo`、`--yolo`、`approvals.mode: off`）守卫看得到就拒绝 | 随 Hermes 插件加载：`__init__.py` 注册两个 `pre_tool_call` 回调，运行插件目录里的 `scripts/magos_guard.py`；`hermes plugins update magos` 并重启 Hermes 之后对每一次 terminal 调用生效，不需要 `install`，也没有要合并的条目；`MAGOS_GUARD=off`（写在 Hermes 进程的环境里）或 `hermes plugins disable magos` 关闭 |
| Hermes 钩子条目（没有插件时） | 同上，检查 terminal，拒绝每一条用户专属命令 | `install --host hermes` 生成 `<守卫目录>/guard/generated/hermes.yaml`，自己合并进 `config.yaml`，并批准一次（`hooks_auto_accept: true`，`hermes acp` 用 `HERMES_ACCEPT_HOOKS=1`；没有批准过的条目被 Hermes 悄悄跳过）。与插件同时存在时，它在 Hermes 询问之前就拒绝，请删掉它。插件目录存在、插件里的守卫与运行 `install` 的守卫版本相同，并且（Windows 上）插件启动器的路径不含下面列出的 cmd 字符时，条目运行 Hermes 插件自己的启动器（`<Hermes home>/plugins/magos/hooks/run-guard.cmd`），随 Hermes 插件一起升级；否则运行守卫目录下的副本，`install` 会说明原因（例如插件的守卫是另一个版本时，提示先更新 Hermes 插件） |
| Git 兜底 | 任何工具用 git 创建没有清单的分支，都被 `reference-transaction` 拒绝；分支改名与复制（`git branch -m/-M/-c/-C`）除外；不需要 Python | 在目标仓库里运行 `arm`，`disarm` 撤销（都要用户批准：在宿主的批准提示里点一下，或在真实终端里运行，终端路径需要控制台），`doctor` 自检 |

- `install` 把守卫和 `hooks/run-guard.cmd` 复制到 `~/.magos/guard/`（`--home` 或 `MAGOS_HOME` 可改），每次都重写 `guard/VERSION.json`（版本、sha256、来源、时间），在 `<守卫目录>/audit.log` 追加一行记录，并打印 `guard copy <旧> -> <新>`；副本与源文件相同时打印 `guard copy unchanged (<版本>)`，不复制。副本比运行的守卫新时拒绝（退出码 18），加 `--allow-downgrade` 才替换。两个文件先都写成临时文件再逐个替换；替换失败时放回已替换的旧文件，副本不会一半新一半旧（POSIX 上启动器保持可执行）。Windows 上，守卫目录里启动器的路径含有 cmd.exe 会当作运算符、分隔符或变量展开的字符（`&`、`(`、`)`、`^`、`%`、`;`、`,`、`=`）时，`install` 拒绝（退出码 2），什么也不写，请用 `--home` 或 `MAGOS_HOME` 换一个不含这些字符的目录。升级 MAGOS 后按上面“守卫副本与生成的配置”刷新。
- `version` 输出正在运行的守卫的版本、文件 sha256、路径与 Python 版本（`--json` 输出同样的字段），只读。`doctor [--home <目录>]` 还会比较守卫目录下的副本与正在运行的守卫，检查 Hermes 条目的启动器，在 Codex 方面确认批准服务器能回答 `initialize` 与 `tools/list`、`install --host codex` 生成的 `[mcp_servers.magos]` 条目指向的解释器与守卫存在且版本一致，并打印插件 `mcp.json` 的 sha256 前 12 位，有 Hermes 主目录时报告 Hermes 路线（插件是否运行本版本的守卫、`plugins.enabled` 是否列出 magos、是否还有与插件并存的 `hooks:` 条目、条目是否被批准过，以及 `approvals.mode` 与 `HERMES_YOLO_MODE` 是否让 Hermes 不经人批准），并检查 Python、Git 版本、`magos.approval` 的取值（不是 `terminal`、`prompt`、`auto-safe` 之一时报告问题）、仓库状态与 Git 兜底；它的自检用自己的 Git 时间预算，只有兜底钩子自己的否决行（`MAGOS BLOCKED: ` 或 `MAGOS 拒绝: `）才算通过。
- 默认是 AUTO：命名的工作树创建总是受控，只建分支的创建仅在已有其他车道时受控，单工作树、无未合并分支的仓库不受影响。`arm` 后进入 ARMED：每个新分支都需要清单。`arm` 会关闭该仓库的 `gc.packRefs` 与 `maintenance.pack-refs.enabled`，并把原来的值记在 `<git 公共目录>/magos/arm-config.json`，`disarm` 时恢复（1.0.0、1.0.1 武装过的仓库见上面“守卫副本与生成的配置”第 5 步）。`arm` 与 `disarm` 都在 `<git 公共目录>/magos/audit.log` 追加记录。
- 每个创建都在它实际作用的仓库里判断：`--git-dir` / `GIT_DIR` 重定向的目标，否则是 `cd`、`git -C` 之后所在的目录；无法解析的重定向一律拒绝。`cd` 到不存在的目录时，后面的命令按原目录判断。详见 `references/lane-split.md` 第 6 节。
- 关闭：`git config --local magos.guard off`（只关闭该仓库的宿主钩子），`disarm`（关闭 Git 兜底），`claude plugin disable magos`（关闭 Claude 插件钩子），`hermes plugins disable magos`（关闭 Hermes 插件的守卫回调，也关闭它的 Skill），宿主进程环境变量 `MAGOS_GUARD=off`（Hermes 插件的回调也读它）。
- 覆盖（`override`）、`arm`、`disarm`、`install` 须经用户批准，有两条路。终端路径需要真实控制台与命令自己的挑战（没有真实控制台时退出码 17；`arm`、`disarm`、`install` 的 `--dry-run` 除外），所有宿主、所有级别都可用。批准路径在宿主自己的批准提示里问你。Claude Code 里只对 Bash 与 PowerShell 工具：钩子对只直接调用一次守卫脚本、行里没有别的东西（没有管道、命令列表、替换、包装、`start`、`eval`）的这几个子命令，回答宿主自己的权限对话框，用户点一下，命令不需要控制台就运行（见下一条）；`auto-safe` 级别下，钩子对 `arm`，以及复制到默认守卫目录且不带 `--allow-downgrade` 的 `install`，不弹框，用户的设置本身就是批准（Hermes 里同样）。Codex 里的批准路径是插件的 MCP 服务器 `magos` 的工具 `magos_approve`：服务器由 Codex 自己作为本地进程启动，经标准输入输出通信；工具按字段接收子命令与参数（不接收命令行，也没有 `--home` 与 `--allow-downgrade` 的字段），`prompt` 与 `auto-safe` 下都经 Codex 自己的对话框（MCP elicitation 表单，只有一个必选的 Approve 勾选框）问你，只有你勾选之后接受，服务器才写批准记录并用这个守卫文件运行这一条命令；拒绝、取消、没勾选就接受、120 秒内不回答、客户端不支持表单、Codex 的批准策略为 `never`（Codex 自己拒绝）或级别为 `terminal` 时，什么都不运行，并给出你在终端里要运行的命令。Hermes 里，Hermes 插件通过两个 `pre_tool_call` 回调对每一次 `terminal` 调用运行守卫：对工具直接调用（前台、不带伪终端、bash）的一条命令，守卫把带一次性令牌重写的命令和一句问话交给 Hermes，Hermes 自己的批准提示问你，你批准后命令才运行；Hermes 会不经人批准时（`/yolo`、`--yolo`、`approvals.mode: off`、无人值守的运行），守卫看得到就拒绝，只留下终端路径；没有插件时，`install --host hermes` 生成的 `hooks:` 条目拒绝每一条用户专属命令。任何宿主上，启动守卫 `mcp` 子命令的工具命令都被拒绝：这个服务器只由宿主启动。其余写法（其他工具也在内），无论前面的全局选项怎么写、写的是守卫脚本还是启动器 `run-guard.cmd`、是否套在 `start`、`cmd /c start`、`Start-Process` 或子 shell 里，也包括代理自己写了 `--approval` 的命令，钩子都拒绝；启动器本身只运行 `hook` 子命令，其他子命令一律拒绝（退出码 2）。在新控制台窗口里启动的命令（`start`、`Start-Process`）也算真实控制台，所以控制台检查与覆盖都不是访问控制：挡住代理的是钩子对这些命令的识别与启动器的拒绝。覆盖记录只由 `plan` 读取，用户覆盖之后要重新 `plan`。守卫的清单存放在 `<git 公共目录>/magos/`，不随 fetch、push、clone 传输。
- 批准级别：`git config --local magos.approval <级别>`（只读该仓库的本地配置，`-c`、`GIT_CONFIG_*` 与全局、系统配置都不能设置它；和 `magos.guard` 一样只有用户写，用户可以在自己的终端里设置，代理从不设置，守卫也没有替代理设置它的命令）。`terminal`：只走终端路径，钩子拒绝，由用户在自己的终端里运行命令。`prompt`（未设置时的默认值）：在 Claude Code 里，钩子对一次直接调用 `override`、`arm`、`disarm` 或 `install` 回答宿主自己的权限对话框（Codex 与 Hermes 的批准提示见上一条），对话框写明批准的是什么（子命令与是否试运行、仓库，`install` 则是宿主、复制守卫及其启动器的来源目录、目标目录，带 `--allow-downgrade` 时还写明它会替换更新版本的守卫副本，`override` 还有指纹、这次点击放行的 lane 及其目标、被拒绝时冲突的分支，以及代理写的理由，理由标明由代理所写，引号包着并截短），点一下即批准。`auto-safe`：同 `prompt`，但 `arm` 与复制到默认守卫目录且不带 `--allow-downgrade` 的 `install`（它们只增加保护或只复制守卫）不弹框，`override`、`disarm` 与 `install` 的其他写法仍然弹框。取值比较时不区分大小写，也忽略首尾空白（` Auto-Safe ` 即 `auto-safe`）；其他取值按 `terminal` 处理，`doctor` 报告问题。在仓库之外（`install`）级别按 `prompt` 处理。在 Codex 里 `auto-safe` 与 `prompt` 一样弹出提示：MCP 路径没有不点击就运行的情形。Claude Code 里只有 Bash 与 PowerShell 工具有对话框，Hermes 里只有 `terminal` 工具有批准提示，其他工具仍是拒绝。没有让代理无人值守运行 `override` 或 `disarm` 的级别：代理自己批准自己的绕过就不是守卫，诚实的关闭方式是用户自己设置 `git config --local magos.guard off`。在 Claude Code 与 Hermes 里，钩子给它交给宿主的命令加上一次性令牌 `--approval=<令牌>`，并在用户点击之前写下对应的批准记录（文件名是令牌的 SHA-256，记录里没有令牌本身）：`override`、`arm`、`disarm` 的放在 `<git 公共目录>/magos/approvals/`，`install` 的放在 `<守卫目录>/approvals/`（守卫目录是 `MAGOS_HOME`，否则 `~/.magos`，不随 `--home` 变化）。在 Codex 里，MCP 服务器在你接受之后才写同样的记录，并把令牌交给它自己运行的命令，令牌不经过代理。记录两分钟内有效（Hermes 里询问的记录，有效期是 Hermes 等你回答的时间（`approvals.timeout`，未设置时 300 秒，按 120 到 900 秒取值）加 30 秒，默认 330 秒），绑定子命令、参数与仓库（`install` 则是守卫目录），所以令牌只适用于那一条命令。命令用令牌代替真实控制台与挑战，用掉令牌，只跳过这两项检查；令牌不通过时，命令在写任何东西之前结束，不会退回到询问，并说明原因：退出码 25 令牌不认识（不是令牌，或这个存放处里没有它的记录），26 已过期，27 已用过，28 与这条命令不符（另一个子命令、参数、仓库或守卫目录）。覆盖对话框显示的冲突分支读自 `<git 公共目录>/magos/denials/<指纹>.json`，由 `plan` 与钩子在拒绝一次创建时写下，一小时内有效。每次批准的运行都在审计日志里记 `via`（`terminal`、`prompt` 或 `auto-safe`），经 MCP 服务器或在 Hermes 里批准的运行还记 `route`（`mcp` 与客户端的名称和版本，或 `hermes`），经点击批准的覆盖，理由标明是代理所写（`reason_by`）。令牌与覆盖、控制台检查一样不是访问控制：挡在 `override` 与 `disarm` 前面的是宿主自己的批准提示（Codex 的路径只证明有人点击，以 Codex 本身能证明的为限；Hermes 的路径以 Hermes 的批准关口为限），审计里的 `via` 与 `reason_by` 是尽力而为的来源记录，不是证明。
- 已知限制：钩子读命令文本，脚本或混淆命令可能漏判；钩子拒绝任何选项写法的分支改名与复制，但 Git 兜底看不到分支改名与复制（`git branch -m/-M/-c/-C`）、`git -c core.hooksPath`、之后才设置的 `core.hooksPath`、直接改 `.git/refs`、libgit2 与克隆；Codex 钩子、Hermes 钩子与 Claude 的非 strict 组在基础设施故障（找不到 Python、守卫脚本缺失或出错）时放行，只在 stderr 写一行警告，Hermes 的 `fail_closed: true` 只在启动器无法启动或超时时拒绝（在条目的 `hook` 前加 `--strict` 可改为故障时拒绝，代价是 Python 或守卫出问题时该工具的每次调用都被拒绝）；Hermes 插件的回调在守卫无法启动、出错或超过 25 秒时拒绝该次 terminal 调用，拒绝信息写明 `MAGOS_GUARD=off` 与 `hermes plugins disable magos`；文件工具（Write、Edit 等）、Hermes 的 `process_manage` 向运行中进程写入的文本不经过钩子；Codex 的批准路径只证明 Codex 能证明的（MCP 服务器分不清是谁启动了它，会运行自己代码的同用户代理可以自己启动一个服务器并回答自己的对话框，与伪造批准记录是同一类限制），插件的 `mcp.json` 与它运行的守卫文件是你随插件信任的代码，MCP 服务器变化时 Codex 不会再问；Hermes 的路径只和 Hermes 的批准关口一样强（Hermes 在 `/yolo`、`--yolo`、`approvals.mode: off` 下不经人批准，守卫看得到就拒绝，会话里的 `/yolo` 并不总是看得到）；防篡改只匹配常见的写入命令，而且对守卫状态（包括 `~/.magos`）的保护只在已武装或有登记的仓库里生效；Git 兜底否决发生在 git 创建引用时，带起点的 `switch -c` 与 `--orphan` 的检出步骤可能已经执行。详见 `references/lane-split.md` 第 12 节。

`--verify` 只校验磁盘上的安装内容。参数灰字提示由各宿主的命令或 Skill 选择界面决定；更新安装文件后，可能需要重新载入宿主会话才能看到新的说明，界面效果仍需在对应宿主中单独检查。
