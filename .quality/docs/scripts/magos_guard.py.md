# Technical Design: `scripts/magos_guard.py`

Source: `scripts/magos_guard.py`

Source-SHA256: `e1c0e5432ba0f969d5ac3bca4842e1a6351a87bf8b8ec74f32179527961c0495`

## Responsibility

`magos_guard.py` is the lane guard of the MAGOS package. It is a single stdlib-only Python 3.9+ file that makes the
rule "a lane is a registered file manifest before it is a branch" enforceable instead of advisory.

The guard stops the lane that is being created, never a lane that already exists:

- A new branch or worktree must have a planned file manifest registered before the creating command runs.
- If any planned file overlaps a file that another branch, worktree or declared lane has changed, is changing or has
  declared, the creation is denied before it happens and every conflicting branch and worktree is named.
- Existing branches and worktrees are only read. No hook denies a write, commit or merge inside an existing lane.
- "Changed" is measured against the integration target. Every worktree contains every file; a lane claims a file only
  if it differs from the target in that file (committed, staged, unstaged, untracked or in progress) or declared it.

The file holds seven cooperating parts.

1. **Manifest and overlap engine.** Entries are normalised (NFC, case-folded, separators unified, trailing dots and
   spaces stripped) and compared with an exact glob-intersection dynamic programme at character level and at path level.
   A `**` segment matches any number of directories; `*` and `?` never cross `/`; brackets are ordinary characters.
   Entry-versus-path and entry-versus-entry use the same function, so declared manifests of lanes that do not exist yet
   collide with each other.
2. **Evidence gatherer.** A Git runner (argv lists, scrubbed environment, pinned options that turn off the fsmonitor
   and the untracked cache, `-z` machine formats, per-call timeout and a total deadline that every Git call of one hook
   invocation shares) enumerates claimants: every non-bare worktree, every local branch not merged into the target,
   every unmerged remote-tracking branch, and every open claim. The runner runs only the local subcommands
   `--version`, `branch`, `check-ref-format`, `config`, `diff`, `for-each-ref`, `merge-base`, `rev-parse`, `status` and
   `worktree` (`LOCAL_GIT`), read after any leading `--git-dir=` or `--work-tree=` argument; for any other first
   argument (another subcommand, an option such as `-c` or `--config-env`, or none) it raises `GitFail` `GIT_FAILED`
   before git starts.
   Committed evidence is the three-dot diff against each merge base minus content the target already holds; a detached
   worktree contributes the commits of its own HEAD, and a detached worktree at the lane's own registered path is the
   lane itself and is not compared. Uncommitted evidence is `status --porcelain=v2 -z --untracked-files=all` (a rename
   claims both names). A merge, rebase, cherry-pick or revert in progress is a warning; `git am`, unreadable operation
   metadata or a locked worktree that is missing on disk is unknown; a branch with no history in common with the target
   is ignored with a warning because a merge could not collide. Bare repositories and submodules are opened like any
   other repository. A Git call that exits non-zero without writing to stderr is reported with its exit code
   (`git <args>: exit code N`). Within one hook call the evidence of a repository (its opening, mode, refs, claims,
   engagement and gathered claimant evidence) is collected at most once, whatever number of directory or redirect
   states of the command line lead to it.
3. **Claim store.** `<git-common-dir>/magos/claims/<branch>.claim` files, written under an OS file lock with a
   temporary file and `os.replace`, plus an append-only `audit.log`. The store is shared by all worktrees, is never part
   of a work tree and is not carried by fetch, push, clone, bundle or mirror. Every claim carries a format number; the
   guard reads format `CLAIM_FORMAT = 1` and refuses to act on a claim written in a newer format instead of misreading
   it.
4. **Command detector.** A lexer for bash, PowerShell and cmd that unwraps `bash -c`, `pwsh -Command`,
   `-EncodedCommand`, `cmd /c`, `env` (also `env -S` / `--split-string`, whose value is split into the command it runs),
   `sudo`, `doas`, `xargs` and similar wrappers (depth 3), tracks `cd`, `git -C`, `env -C` and `sudo -D`, and recognises
   lane-creating git commands and harness tools. The value of a `sudo` or `doas` option (`-u <user>`, `-g <group>`) and
   of an `env` option that takes one (`-C`, `-u`, `-S`, `-P`, `-a` and their long forms) is never taken for the wrapped
   program. `powershell` and `pwsh` read their options the way PowerShell reads them, through one reading used by the
   walk, by the tamper filter's child-shell text and for a Codex argv: an option word written with `-`, `--` or `/`
   whose name is a prefix of `Command` (`-c`, `-co`, `-Comm`, `-command`) or is `-cwa` or a prefix of
   `CommandWithArgs` longer than `command` runs the words after it as PowerShell text, and one that is `-ec` or a
   prefix of `EncodedCommand` (`-e`, `-en`, `-enc`, `-EncodedC`) runs the base64 UTF-16LE text of the next word (an
   undecodable value counts as a dynamic creation); `-ex` (`ExecutionPolicy`) and `-encodeda` (`EncodedArguments`) are
   neither. bash, sh, zsh, dash and ksh read `-c` and bundled short options ending in `c` (`-lc`, `-ec`); cmd reads
   `/c` and `/k`. `Start-Process` runs git with its `-ArgumentList` value in its `-WorkingDirectory`, each named in
   full, by a unique prefix (`-a`, `-wo`) or in the colon form (`-WorkingDirectory:<dir>`); the directory is resolved
   against the directory the shell is in, and a dynamic value makes the repository unknown (the session directory's
   repository decides, as for any computed directory). In PowerShell the command on the right of `$name =` runs (`$out = git switch -c x` is a creation), and the
   text of `( .. )` and `@( .. )` inside a command is judged like `$( .. )`; text inside a quoted string is not. Dynamic
   words (`$x`, backticks, `%x%`) in a lane-creating position are treated as unparseable. The script a shell runs is the
   `-File` value or the first readable file among the first four candidates after option values. Text echoed or quoted
   into a shell through a pipe is inspected also when prefix assignments, wrappers (`env`, `command`, `builtin`, `exec`,
   `nohup`, `nice`, `time`, `setsid`, `stdbuf`, `sudo`, `doas`) and their options stand between the pipe and the shell
   (`FOO=1 sh`, `env FOO=1 bash`, `sudo -E sh`, `command sh`, `doas -u <user> sh`). Command text longer than 200,000
   characters is not inspected: it counts as an unparseable creation and, once claims or the git layer exist, as a
   protected command. Every pattern runs in time linear in the command length: each word a pattern reads excludes `|`,
   `;` and `&`, and has one reading; the lexer reads each character once. The walk of one command line, nested text and
   every further state included, is bounded by a budget of 1,600,000 characters (eight times the inspection limit;
   walking one command in one further state counts 128, and walking one substituted text in one state for the states it
   leaves counts 1,024); a line that exceeds it is denied under the overflow rule below.
   - Quoting. Text a POSIX shell runs is read with POSIX quoting: the `Bash` and `Monitor` tools, the `-c` text of
     `bash`, `sh`, `zsh`, `dash` and `ksh`, a script such a shell runs or sources, a git alias that starts with `!`, and
     text echoed or quoted into such a shell. Outside quotes a backslash removes itself and makes the next character
     literal, so an escaped space, `;`, `|` or `&` stays inside the word; inside double quotes a backslash is removed
     only before `$`, a backtick, `"`, `\` and a newline; inside single quotes it stays. Every test the detector makes on
     such a word (the program name, the git subcommand, the option that creates a branch, a branch name, a worktree
     directory name) reads the unescaped text:
     `git swi\tch -c feat\ure` creates `feature`, `g\it` is `git`, `bash -\c` is `bash -c`, and
     `git worktree add ../wt\q` creates `wtq`. A quoted backslash that survives (`"feat\ure"`) leaves a name git
     refuses, which is no creation. PowerShell and cmd text keep their backslashes, which are path separators there.
     In PowerShell text a backtick outside quotes is the escape character, read as PowerShell's tokenizer reads it: it
     removes itself and makes the next character literal (``g`it`` is `git`, ``fe`at`` is `feat`, ``ma`gos`` is
     `magos`), except that `` `0 ``, `` `a ``, `` `b ``, `` `e ``, `` `f ``, `` `n ``, `` `r ``, `` `t `` and `` `v ``
     stand for NUL, bell, backspace, escape, form feed, newline, carriage return, tab and vertical tab (``gi`t`` is `gi`
     followed by a tab, which is no git). In cmd text a caret outside double quotes removes itself and makes the
     next character literal, as cmd reads it (`git switch -c feat^ure` creates `feature`). In text whose shell is not
     known, a git subcommand or a branch name that holds a backslash is dynamic, because the shell may remove it;
     paths keep their backslashes there (a `cd` target, a `-C` value, a `--git-dir` value, a worktree directory),
     because a Windows shell reads them as separators. A program word there that holds a backslash, a backtick or a
     caret and is no program the detector knows, but names one once the backtick and caret, or all three characters,
     are removed (`g\it`, `g^it`, ``g`it``), is read as that program: every creation it makes is dynamic, and every
     directory or redirect change it makes is possible, because the shell may or may not remove the escape. In text a POSIX shell runs, a backslash-newline is removed and
     the words around it join, as the shell joins them (`git switch -c main\<newline>2` creates `main2`); a PowerShell
     backtick-newline, and a backslash-newline in text whose shell is not known, read as a space. A `#` that starts a
     word outside quotes starts a comment that runs to the end of the line in bash and PowerShell text (the newline
     still ends the command), so a quote character in a comment (`# Let's ...`) opens no string; in cmd text and text
     whose shell is not known, the rest of such a line is read with its quote characters as ordinary characters, so
     no quote reaches past the line and the words of the line are still read.
   - Word gate. A line, and each text found inside it, is walked only when it may create something: its text, read with
     every backslash, backtick, caret, `'` and `"` removed (`g''it`, `"g"it` and ``g`it`` read `git`), names `git`, `gh`,
     `gt`, `claude`, `eval`, `iex`, `Invoke-Expression`, `source`, `-enc`, `base64`, or a `.sh`, `.bash` or `.ps1`
     file, or holds a word that runs a script or a shell (`.`, `bash`, `sh`, `zsh`, `dash`, `ksh`, `powershell`,
     `pwsh`, `cmd`, also with `.exe`) standing where a command may start. So `. ./mk`, `bash ./mk`, `$(. ./mk)`,
     `$(bash ./mk)` and a here-document that runs `. ./mk` are walked, and the script they run is read.
   - Git invocations. The global options of git that take a separate value (`-C`, `-c`, `--git-dir`, `--work-tree`,
     `--namespace`, `--exec-path`, `--config-env`, `--attr-source`, `--super-prefix`, `--list-cmds`, `--shallow-file`)
     are skipped together with their value, so the word after the value is the subcommand. Short options are read the way git
     reads them: the letters of `-xyz` from left to right, and at the first letter that takes a value the rest of the
     word, when it is not empty, is the value, else the next word. So `git switch -cNAME`, `git switch -CNAME`,
     `git checkout -bNAME`, `git checkout -BNAME`, `git checkout -qbNAME` and `git worktree add -bNAME <dir>` create
     NAME (never the start point or the directory name), and `--orphan=NAME` names NAME. `claude -w<name>` and
     `claude --worktree=<name>` start a worktree like `claude -w <name>` and `claude --worktree <name>`: an auto-named
     creation. `git branch` renames or copies
     when a short-option word holds `m`, `M`, `c` or `C` before any letter that takes a value (`-mf`, `-fm`, `-cf`, `-Cf`,
     `-qm`), or when a long option of at least two letters is a prefix of exactly one of `git branch`'s long options
     and that option is `--move` or `--copy` (`--mo`, `--mov`, `--cop`; `--co` names several options and is no
     rename); the last positional word is then the new branch. The creating long options of `git switch` (`--create`,
     `--force-create`, `--orphan`) and of `git checkout` (`--orphan`) match from their second letter (`--cr`, `--or`).
     `git branch --sort <key>` and `git branch --format <format>` (and `--so`, `--sor`, `--form`, `--forma`) take
     their value as the next word and do not select list mode: the value is no branch name, the word after it is. `git push` into a local repository creates the
     branch in that repository. The value of an option that takes a separate value is skipped before the repository
     argument is read: for `git push` `--repo`, `--receive-pack`, `--exec`, `--push-option` and `-o`, for `git fetch`
     and `git pull` `--upload-pack`, `--server-option`, `--depth`, `--deepen`, `--shallow-since`, `--shallow-exclude`,
     `--refmap`, `--negotiation-tip`, `--jobs`, `--filter`, `--recurse-submodules-default`, `--submodule-prefix`, `-o`
     and `-j` (long options also by a unique prefix of at least three letters). When the repository argument is `.`, a path (`./x`, `../x`, an absolute or drive path, a
     `file://` URL, or a word that names an existing directory), the destinations of its refspecs (under `refs/heads/`
     or bare names) are creations judged in the repository at that path, which for `.` and for a path that names the
     current repository is the current one; a dynamic repository argument (`"$PWD"`, `$(..)`) leaves the repository
     unknown and the creation is denied `UNPARSEABLE`. A push to a remote name, or to a URL other than `file://`, is not
     judged: the branch it creates is in the remote's repository, which the hook does not resolve (also when the
     remote's configured URL is a local path). A fetch,
     pull or push refspec whose destination branch contains `*` creates branches whose names the hook cannot list: a
     dynamic creation. The command text git itself runs is inspected like `bash -c` text, in the directory and GIT_DIR
     state of that invocation: the value of `git rebase -x`, `--exec <cmd>` and `--exec=<cmd>` (also written with a
     unique prefix of `--exec` of at least two letters, `--ex` and `--exe`, with the value after `=` or as the next
     word), and the words after `git bisect run`. A ref under `refs/heads/` names a branch whatever the case of `heads`
     (`refs/HEADS/x`, `refs/Heads/x`), on every platform, because the case-insensitive file systems of Windows and
     macOS store such a ref as the branch: `git update-ref`, `git symbolic-ref`, the destination of a fetch, pull or
     push refspec and an `update-ref --stdin` instruction read `heads` in any case. `git update-ref` reads its options
     as git does: `-m` takes the rest of its word, or else the next word, as its value (`-m -d` writes the message
     `-d` and deletes nothing), a short-option word deletes when it holds `d` before any `m` (`-d`, `-zd`, `-dm <msg>`),
     `--stdin` is also written as a unique prefix (`--s`, `--std`), and the first positional word is the ref it
     writes. Aliases: when any git invocation of the line names a subcommand that is not a built-in git
     command, the aliases of the session directory's repository (with the user's global aliases git reports there) are
     loaded and every git invocation of the line is checked against them, whatever else the line creates. The
     subcommand of each `git` word for this test is its first word after the global options and the values of those
     that take one (`git -C ../B nb x` names `nb`), found in one pass over the words, linear in the line's length; the
     test reads the text with every backslash, backtick, caret, `'` and `"` removed.
   - Repositories. The detector also records the repository each git invocation acts on, as the following items state.
     A repository redirect (`--git-dir`, `GIT_DIR` or `GIT_COMMON_DIR`, spellings under Public Contract) is resolved
     per git invocation, as Git resolves it: a relative value is joined to the directory that invocation runs in (the
     shell directory after every earlier `cd` and after every `-C` of the invocation, whatever the option order), not to
     the directory where an exported variable was assigned. The result is carried as the creation's `gitdir`; relative
     worktree paths still resolve against the directory the invocation runs in, never against the redirect. A redirect
     whose value is dynamic or cannot be resolved marks the repository unknown. A removal of the variable ends a
     redirect recorded earlier in the command line, so later invocations are judged in the directory they run in, as
     Git then finds its repository there: `unset GIT_DIR`, `export -n GIT_DIR`, `Remove-Item Env:GIT_DIR`,
     `$env:GIT_DIR = $null` and `$env:GIT_DIR = ''` for every later invocation, `env -u GIT_DIR` for the invocation it
     wraps, and the same removals of `GIT_COMMON_DIR`. `--git-dir` replaces `GIT_DIR` only. `--work-tree` and
     `GIT_WORK_TREE` alone do not change the judged repository, because Git writes the ref into the repository it finds
     from the working directory.
   - A change of `GIT_DIR` or `GIT_COMMON_DIR` in a spelling the walker does not model makes the repository of every
     later git invocation of the line unknown, so a creation after it is denied `UNPARSEABLE` with the redirect message:
     the operand of `read`, `readarray`, `mapfile`, `printf -v`, `getopts` and `declare -n`, a `+=` assignment
     (standalone, exported or as a prefix), `export`, `declare`, `typeset`, `local` or `readonly` behind `builtin` or
     `command`, `Set-Content`, `sc`, `Add-Content` and `ac` on `Env:GIT_DIR`, and any other word that names one of the
     two variables in an assignment position.
   - Under `GIT_COMMON_DIR` Git splits the repository: it writes the branch into the repository it finds from its
     directory or `GIT_DIR`, while it reads the config, runs the hooks and stores the objects of the `GIT_COMMON_DIR`
     repository, and a value that is not a repository makes it fail. Which of the two holds the lane is therefore not
     resolved: a creation under `GIT_COMMON_DIR` is judged both in the `GIT_COMMON_DIR` repository and in the
     repository the invocation would use without it (the `GIT_DIR` target, else the directory it runs in), and the
     stricter verdict applies.
   - Assignments and removals of `GIT_DIR` and `GIT_COMMON_DIR` take effect as the shell that runs the line performs
     them. The `Bash` and `Monitor` tools run bash, the `PowerShell` tool runs PowerShell, `bash -c`, `pwsh -Command`
     and `cmd /c` name their own shell, and the shell of any other tool is not known. An assignment or removal written
     for another shell, or in a shell the hook cannot name (cmd's `set` in bash, `export` in PowerShell,
     `$env:GIT_DIR=` in bash), may not take effect, so the creation is judged both with and without it; `sudo`, `doas`
     and `wsl` may start git with a clean environment, so a redirect that reaches git through them is judged both ways
     as well (`sudo -E` and `sudo --preserve-env` keep it). Recognised beside the Public Contract spellings:
     `declare -x` / `typeset -x`, `Set-Item` and `New-Item` on `Env:GIT_DIR`, and
     `[Environment]::SetEnvironmentVariable('GIT_DIR', <p>)` for the process. On Windows git reads the environment
     without regard to case, so every case of `GIT_DIR` and `GIT_COMMON_DIR` is a redirect, while a bash removal ends
     only the spelling it names. `update-ref --stdin`, `gh pr checkout` and the other auto-named tools are judged in the
     directory and `GIT_DIR` state of their own invocation, like any git invocation; an `update-ref --stdin` whose
     input the hook cannot see counts as a dynamic creation. The instructions of an `update-ref --stdin` are read from
     the text of the line: the name after `create refs/heads/` or `update refs/heads/` ends at whitespace, a quote or a
     backslash. A backslash right after the name that is `\0` not followed by an octal digit, `\n`, `\t` or `\r` ends
     it as the separator `printf` writes (`printf 'create refs/heads/x\0HEAD\0'` creates `x`); any other backslash after
     it, an empty name and a name git refuses make the record dynamic, because `printf` or `echo -e` may turn the text
     into another name (`printf 'create refs/heads/a\x62c HEAD'` creates `abc`). `popd` and `Pop-Location` return to the directory the
     line's own `pushd` or `Push-Location` left; without one the directory is unknown.
   - A line is walked in a set of states, each a directory, the `GIT_DIR` and `GIT_COMMON_DIR` values and a `pushd`
     stack. The line is a list of commands joined by `&&` and `||` and ended by `;`, a newline or `&`; a parenthesised
     group `( .. )`, a brace block `{ .. }` (a function body, a PowerShell script block) and a compound command (`if`,
     `while`, `until`, `for`, `select` and `case` up to `fi`, `done` and `esac`; read in every shell but PowerShell and
     cmd, whose blocks are braces and parentheses) hold lists of their own. A change of the directory (`cd`, `pushd`,
     `popd`, `chdir`, `Set-Location`, `sl`, `Push-Location`, `Pop-Location`) or of `GIT_DIR` / `GIT_COMMON_DIR` is
     definite for a later command only when the shell certainly makes it first: it is the first command of its list,
     which always runs, or `&&` alone joins it to the later command and it is itself the first command of its list or
     joined by `&&` to the command before it (`cd X && git switch -c y`, `cd X; git switch -c y`,
     `git fetch && cd X && git switch -c y`). A definite change replaces the states. Every other change is possible: the
     commands after it are walked in every state before and after it, and the stricter verdict applies. Possible are a
     change after `&&` or `||` for the commands after the list (`false && cd X; git branch y`) or after a later `||`
     (`true || cd X && git branch y`), every change inside a compound command (inside it and after it), a change inside
     a brace block (for the commands after it), and a change made by text the current shell runs itself (`eval`, `iex`
     and `Invoke-Expression`, `source`, `.`, a PowerShell script, called or dot-sourced).
   - Subshells. Bash runs a group `( .. )`, a list sent to the background by `&`, every command of a pipeline but the
     last, and text substituted into a command (`$( .. )`, `<( .. )`, backticks) in a subshell, so in text a POSIX shell
     runs a change there never reaches the commands after it: a group hands on the states it was opened in, a
     background list the states it started in, and a pipeline command other than the last and substituted text the
     states before them. The last command of a pipeline keeps the states before and after it (zsh and bash's
     `lastpipe` run it in the current shell). PowerShell runs `( .. )`, `@( .. )` and `$( .. )` and every pipeline
     command in the current scope, so a change there is possible, and a group or a pipeline command in cmd is possible
     as well. In a tool whose shell the hook cannot name (the Codex and Hermes shell tools, MCP tools) a change inside a
     group, a background list, any pipeline command or substituted text is possible. A command inside substituted text
     is no command of the line. Inside a group, a brace block or the evaluated or substituted text, its own definite
     changes hold. In cmd `&` runs the next command after the first one and ends a list like `;`. A change in a child
     shell (`bash -c`, `bash x.sh`, `pwsh -Command`, `cmd /c`) never reaches the line. A builtin started through a
     program wrapper (`env`, `sudo`, `doas`, `nohup`, `nice`, `xargs`, `timeout`, `watch`, `wsl`, `uv`, `npx`,
     `stdbuf`, `setsid`, `exec`) changes nothing, because the wrapper starts a program and no program can change the
     shell (`env cd X` fails); `command cd` and `builtin cd` change the directory. Every later command applies to every
     state, so a later `cd` to an absolute directory leaves one state.
   - `env -C <dir>`, `env --chdir[=]<dir>`, `sudo -D <dir>` and `sudo --chdir[=]<dir>` run the program they wrap in
     `<dir>`, resolved against the directory the shell is in, like `git -C` for that invocation; a dynamic value makes
     the repository unknown.
   - Text the line runs from inside itself (`$(..)`, backticks, here-documents and quoted text fed to a shell) is
     judged in every directory and redirect state the line passes through. Overflow rule: a line whose walk reaches more
     than eight states, and a line with such text in more than eight states or in more than 4,096 pairs of text and
     state, is denied `UNPARSEABLE` only when the walk of the whole line yields a creation (a named, dynamic or
     auto-named creation, or an `update-ref --stdin`) or reads a script or shell text by a relative path (text that may
     differ from one directory to another, so a state beyond the eighth may hold what the first eight do not); a line
     that creates nothing and reads no such text places nothing in a repository, so the extra states lose nothing and
     the line is not denied for them. A line that exceeds the walking budget is denied in every case, because its walk
     is incomplete. These denials apply unless the session directory's repository is off or `MAGOS_GUARD=off` is set
     (Invariant 6); outside a repository they apply.
   - A `cd`, `pushd`, `chdir`, `Set-Location` or `sl` to a directory that does not exist when the hook runs leaves the
     shell where it was, so later commands are judged in that prior directory and the creation is marked unresolved. A
     later relative path (a `cd` or `pushd` target, a `-C`, `env -C` or `sudo -D` directory, a push target, a script, a
     `--git-dir` value) resolves against the directory the shell is really in: that prior directory, or, for the later
     elements of an `&&` chain whose earlier element creates the target, the target (`mkdir -p lanes && cd lanes &&
     git worktree add feat -b feat` creates `lanes/feat`). This holds on every platform, for absolute, relative, drive and
     POSIX-rooted targets and for `;`, `&&` and newline separators. bash and PowerShell refuse a `cd` with a second
     directory argument (`cd /d <dir>` in bash, `cd <dir> extra`), which follows the same rule; redirections (`>x`,
     `2>&1`, `> x`) are no directory arguments. cmd's `cd /d <dir>` changes the drive and the directory, and cmd's `cd`
     reads the rest of the line as one path.
   - Inside an `&&` chain the elements after a `cd` run only when the `cd` succeeded, so for those later elements of the
     same chain the hook follows the `cd` into its target `T` when an earlier element of that chain creates `T`: after
     `git init T` or `git clone <src> T`, or when a `git init` runs in `T` earlier in the chain, nothing is judged (a new
     repository holds no lane), except a creation redirected by `--git-dir`, `GIT_DIR` or `GIT_COMMON_DIR` to a git
     directory outside `T`, which is judged in the repository it names; after `git worktree add T` the creation is judged in the repository that worktree
     belongs to; after `mkdir T` (or `mkdir -p` of `T` or of a directory above it) it is judged in the repository of
     `T`'s nearest existing ancestor, where git finds its repository. This applies only to the later elements of that
     chain. Where nothing earlier in the chain creates the target, and for every command after the chain ends, the
     missing-directory rule above applies: `cd missing && git switch -c x` and `mkdir x; cd x; git init; git switch -c y`
     (written with `;`) are judged in the prior directory and unresolved.
   - Git Bash spellings (`/c/Users/x`, `//c/x`) map to drive paths on Windows. A POSIX-rooted spelling that cannot be
     mapped to a drive (`/does/not/exist`) resolves to no directory and follows the missing-directory rule; the guard
     never classifies these spellings with `os.path.isabs`, whose Windows result differs from Python 3.13 on.
   - Records of one creation that the walk reached in several states are judged once per distinct repository: records
     are grouped by repository (common directory and worktree top), redirect target, verb, names, kind, worktree path,
     start point and the dynamic and unresolved marks, and each group is judged once. Before that grouping the walk
     drops a record only when every field equals another record's, where a directory after a `cd` to a missing
     directory counts with its prior directory and the `&&` chain it follows (`cd /missing` reached from two
     directories gives two records, each judged with its own prior directory); the directory states in which text
     found inside the line is judged are kept apart by the same fields.
5. **Host hook entry.** `hook <claude|codex|hermes> pre-tool` reads one PreToolUse payload from stdin and prints either
   `{}` (allow) or one deny object that carries the full conflict message. The hooked tools are named in one constant:
   the shell tools `Bash`, `PowerShell`, `Monitor`, `terminal`, `shell` and `local_shell`; the worktree-creating tools
   (`EnterWorktree`, `Agent`, `Task` and `Workflow` with worktree isolation); the MCP session tools, whose name contains
   `start_session`, `worktree`, `branch` or `hand_off_to_session`; and the names and substrings that route an MCP tool
   that may run a command, in this order: `run_in_terminal`, `terminal`, `shell`, `exec_command`, `execute_command`,
   `start_process`, `command`, `run_command`, `exec`, `execute`, `process`, `bash`, `powershell` and `cmd`. Every hooked
   tool and every MCP tool whose `tool_input.command` is a string is inspected as a command line. An argv list from
   Codex is turned into one command line: when its program is a shell (`bash`, `sh`, `zsh`, `dash`, `ksh`,
   `powershell`, `pwsh`, `cmd`) and it carries a script after `-c`, `-Command` or `/c`, that script, read in that
   shell's dialect; otherwise its words joined with POSIX quoting (a word holding a space, a quote, a backslash or a
   shell character is quoted), read as bash. The `Bash` and `Monitor` tools run bash, the `PowerShell` tool runs
   PowerShell, and the shell of every other tool's string command is not known. The command line is judged in addition to, never instead of, the
   judgement the tool itself calls for: an `Agent`, `Task` or `Workflow` call with worktree isolation, an
   `EnterWorktree` call and an MCP session tool are judged as such whether or not they carry a command. An MCP tool that
   is not a session tool and has no string command is answered `{}` before any repository is opened or any git runs.
   The session directory is `tool_input.workdir`, else `tool_input.cwd`, else the payload's `cwd`, else the process
   directory; a leading `~` or `~user` in it is expanded, and a Git Bash drive spelling mapped, before it is used, and a
   relative `tool_input.workdir` or `tool_input.cwd` is joined to the payload's `cwd` (else to the process directory).
6. **Git layer.** A pure POSIX `sh` `reference-transaction` hook, embedded as a constant and written by `arm`. It needs
   no Python and vetoes the creation of any branch that has no claim, whatever tool ran Git: a ref under `refs/heads/`
   and a HEAD set to such a ref (an unborn or orphan branch), with `heads` matched in any case (`refs/HEADS/x` is the
   branch `x` on a case-insensitive file system; elsewhere it needs a claim for `x` as well). A branch
   rename or copy (`git branch -m/-M/-c/-C`) writes the new ref outside a reference transaction, so the git layer does
   not see it; the host hook denies it in every option spelling (bundled short options and abbreviated long options
   included).
7. **Version, installer and doctor.** `GUARD_VERSION` is the single version constant of the guard (1.0.3) and equals
   the package version. `version` reports the running guard; `install` keeps the user-level copy that the Codex hook
   (and the Hermes hook when it cannot run the Hermes plugin's own launcher) runs, records where the copy came from in
   `VERSION.json` on every install and appends to `<guard home>/audit.log`; `doctor` checks the interpreter, Git, the
   copy, the Hermes entry, the repository and the backstop.

## Dependencies

Upstream: Python 3.9+ standard library only (`argparse`, `base64`, `collections`, `functools`, `getpass`, `hashlib`,
`json`, `os`, `re`, `shlex`, `subprocess`, `sys`, `threading`, `time`, `unicodedata`, `concurrent.futures`, `msvcrt` or
`fcntl`, and `ctypes` for the Windows console check). On Windows the module
sets `NoDefaultCurrentDirectoryInExePath=1` in its own environment at import, before any subprocess starts, so `git`
and every other child program are never resolved from the hook's working directory. Git 2.36+ (`status --porcelain=v2`,
`worktree list --porcelain -z` (2.36), `rev-parse --path-format=absolute` (2.31), `for-each-ref --merged`,
`reference-transaction`); `doctor` reports an older Git. The guard imports no network module, starts no program but
git (at one place, `Git.run`), and runs no git subcommand that talks to a remote: `Git.run` refuses every subcommand
outside `LOCAL_GIT` before git starts; in a partial clone, git itself fetches objects missing from the local store from
the promisor remote when the guard reads a diff.

Interpreters: the minimum is Python 3.9; the hooks run under whatever interpreter the launcher finds (`python3`, `py -3`
or `python`; CPython 3.14 on the reference machine), so path handling never depends on version-specific results of
`os.path` functions.

Downstream callers:

- `hooks/hooks.json` (Claude Code plugin hook wiring, loaded from the plugin root next to `.claude-plugin/`) and
  `hooks/run-guard.cmd` (polyglot launcher) call `hook claude pre-tool`. The matcher of the non-strict group is the
  string `host_snippet('claude')` builds from the hooked-tool constant:
  `^(Bash|PowerShell|Monitor|Agent|Task|Workflow)$|^mcp__.*(<names>)`, where `<names>` joins with `|`, in the order of
  section 5, the MCP session names and then the MCP command names and substrings; the strict group matches
  `^EnterWorktree$`. A contract test compares `hooks/hooks.json`, `host_snippet('claude')` and the constant.
- `hooks/run-guard.cmd`: both halves accept only `hook` as the first argument after an optional `--strict`; any other
  first argument (`arm`, `disarm`, `install`, `doctor`, `version` and the rest) is refused with exit 2 and the stderr
  line `MAGOS guard: the launcher runs only the hook subcommand; run other commands with the guard script itself in
  your own terminal`, and the guard is never started. The cmd half sets `NoDefaultCurrentDirectoryInExePath=1` right
  after `setlocal` and looks its interpreters up on PATH with cmd's `%~$PATH:` search, which never looks in the working
  directory: `py.exe` (run as `py -3`), then `python.exe`, `python.bat` and `python.cmd` (run as `python`). A name that
  is not on PATH is skipped without being started, because `call` of a program that does not exist sets exit code 1,
  not 9009, which cannot be told from a guard failure; the first one found runs by its full path through `call`, so
  that an interpreter that is a `.bat` or `.cmd` shim returns to the launcher, and one that exits 9009 (the Windows
  Store stub) moves on to the next, as does `py.exe` exiting 103 or 112 (the Python launcher found no runtime, or
  none at the path it was given). When no name is found, or every one found exits that way, the launcher reports that no
  Python was found. The guard's stderr reaches the host unchanged. The POSIX half exports the same variable, locates itself with `${0%/*}`, takes the
  directory's spelling with the shell builtin `pwd -W` where the shell provides it (MSYS and Git Bash, which hands a
  Windows Python a path it can open whatever characters it holds; elsewhere `pwd`), reads stdin once and runs the guard
  directly with each candidate interpreter (`python3`, `py -3`, `python`: a `python` that is Python 2 is reached only
  when neither Python 3 name exists), moving to the next candidate only on exit
  127, exit 9009 or the Windows Store stub, and for `py -3` on exit 103 or 112; only shell builtins run before the guard. A missing script, no Python or a
  non-zero guard exit prints a warning that names the absolute guard path and a host-neutral way to stop the guard.
- The user-level Codex and Hermes hook entries generated by `install` call `hook codex|hermes pre-tool`. The Hermes
  entry runs the Hermes plugin's own launcher (`<hermes home>/plugins/magos/hooks/run-guard.cmd`) when that file
  exists, the guard script beside it (`<hermes home>/plugins/magos/scripts/magos_guard.py`) declares the installing
  guard's `GUARD_VERSION` and, on Windows, its path holds none of the characters `install` refuses in a guard home
  (Public Contract), else the copied launcher.
- `references/lane-split.md` and `SKILL.md` tell agents to run `check`, `plan`, `list` and `release`; `version` is
  read-only and agents may run it as well.
- `/GitIntegrate`, `/GitRecon`, `/GitCleanup`, `/GitConverge` and `/GitSweep` read or release claims through `list` and
  `release` as `references/commands.md` describes; the read-only commands never write claims.
- Package manifests: `plugin.json`, `.claude-plugin/plugin.json`, `plugin.yaml`, `SKILL.md` (`metadata.version`),
  `skills/git-orchestrator/SKILL.md` (when it states a version) and line 3 of `references/commands.md` carry the same
  version as `GUARD_VERSION`; a contract test reads all of them. `__init__.py` registers the skills only.
  `scripts/sync_hosts.py` copies `SKILL.md`, `references/*.md` and the skill adapters, never the guard, so `install`
  copies the guard to `~/.magos/guard/` for the hosts that run it outside the plugin directory.

## Public Contract

Invocation: `py -3 -X utf8 -B scripts/magos_guard.py <command> [options]` (`python3` on POSIX). Global options anywhere:
`--repo DIR` (default cwd), `--lang zh|en` (default `zh`, environment `MAGOS_LANG`), `--json`. Options are never
abbreviated (every parser is built with `allow_abbrev=False`), so `--rep` is a usage error. Input is read as bytes
(UTF-8, BOM tolerated); output is UTF-8.

Commands an agent may run: `check`, `plan`, `list`, `release`, `doctor`, `version`. Commands only the user runs:
`override`, `arm`, `disarm`, `install`. The host hook recognises a user-only command whatever the global options before
it look like. A guard word is a word ending in `magos_guard` or `magos_guard.py`, or a word whose case-folded base name
(after the last `/` or `\`) is `run-guard.cmd` or `run-guard`, after which a leading `--strict` is skipped. After the
guard word the hook skips a `--opt=value` word, a prefix of `--repo` or `--lang` together with its value, a prefix of
`--json`, and a `--` (the end of the options; from Python 3.13 on argparse takes the word after it as the subcommand),
and tests the first remaining word. The guard word is found wherever it stands in a command, so wrappers that start it
in a new console or process (`start`, `cmd /c start`, `Start-Process`) hide nothing, and the text of a child shell is
read as well.

- `check --branch B (--paths P... | --manifest FILE|-) [--target T]`: read-only verdict, no lock, writes nothing.
- `plan --branch B (--paths P... | --manifest FILE|-) [--worktree PATH] [--amend]`: judges against the resolved
  integration target (the one creation is checked against) and gathers evidence outside the lock, takes the lock,
  re-reads the claims, checks the branch name again against them, judges, writes `claims/B.claim` atomically and appends
  an audit line. Identical entries are a no-op (exit 0). Different entries need `--amend` (exit 14 otherwise); an amend
  is judged with the lane's own claim excluded, and a removal-only amend skips the overlap check. A branch that already
  exists with no open claim is refused (exit 15). A `--worktree` value that contains a control character is refused
  (exit 12). On success it prints the creation command, for example `git worktree add "<path>" -b <B> <target>`.
- `list [--drift] [--json]`: each claim as `planned` (no branch yet), `active` (unmerged work, a workspace, or a fresh
  branch at the target tip or the plan's base) or `idle` (integrated: merged, moved beyond the plan's base and the target
  tip, no worktree). An idle claim stops blocking other lanes. `--drift` reports files in the lane's footprint matched
  by none of its entries; it never denies. Claims the guard cannot use are listed as well: `unreadable claims/<file>`
  for a file that does not parse and `newer-format <branch> (v=N): upgrade this guard` for a claim of a newer format
  (`claims/<file>` in place of the branch when the claim has no `branch` line); `--json` gives them as rows with state
  `unreadable` (with `path`) or `newer-format` (with `branch`, `v` and `path`).
- `release --branch B [--reason R]`: normalises B as a ref spelling (a backslash read as `/`, empty and `.` segments
  dropped, `..` resolved), finds the claim by the folded name of that spelling among the parsed claims and deletes the
  file of the stored canonical branch name after confirming that its real path lies inside `<store>/claims`; the
  refusal for unmerged work therefore holds for every spelling of B. Refused with exit 16 while the branch has unmerged
  work or its worktree has uncommitted changes, with the message "release refused: the branch has unmerged work or its
  worktree has uncommitted changes"; a merged lane whose clean worktree is still there can be released. A claim written
  in a newer format is refused with exit 16. A claim file that cannot be parsed is removed by `release` only when it is
  the claim file of B, appears in the store's list of unreadable files, lies inside `<store>/claims` and does not carry
  a format line this guard cannot read, which may come from a newer MAGOS: a file whose line 1 is `state=active` and
  whose line 2 starts with `v=` in a spelling the format line does not allow (Claim file below) is refused with exit 16
  and kept. Otherwise `release` prints `no open claim for B` and exits 0. A claim whose stored branch name does
  not lead back to its own file inside `<store>/claims` is not deleted: `release` refuses with exit 16 and names the
  file for the user to inspect.
- `override --fingerprint FP --reason R`: exits 2 unless FP is the 12 lowercase hex digits a denial prints; refuses
  (exit 17) unless stdin and stdout are a real console; the user retypes the fingerprint; writes a one-shot record valid
  for one hour. Only `plan` reads override records: the next `plan` whose denial has the same fingerprint consumes the
  record and stores the fingerprint in the claim's `override` field. The host hook honours only that field, so a re-plan
  is required after an override, and the deny text says so.
- `hook <host> pre-tool`: the PreToolUse entry; it also guards `git worktree add --detach` and `<path> <commit>`, whose
  lane is keyed `detached/<directory name>`. Allow is `{}` with exit 0. Deny is exactly one ASCII-escaped JSON object on
  stdout, exit 0:
  `{"decision":"block","reason":MSG,"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":MSG}}`.
  A deny is never an exit code. Stderr stays empty except for one warning line when engagement could not be decided
  (Invariant 3) and the warning of an internal error on a call whose payload matches none of the prefilter words
  (Invariant 8). An auto-named creation (a tool that names the branch or worktree itself) is denied `UNPLANNABLE` with
  the instruction to plan the branch `worktree-<name>` first and then call `EnterWorktree name=<name>`, or to run
  `git worktree add` directly; `EnterWorktree name=N` creates the branch `worktree-N`.
- `arm [--lang L] [--dry-run]`: needs a real console (exit 17 otherwise, except `--dry-run`). Writes
  `<hooks dir>/reference-transaction` (a foreign hook is chained as `.magos-prev`; the backstop runs it, with the
  transaction on its stdin, only when it is executable, as git runs only executable hooks), `<store>/ARMED`, `lang` and `guard`,
  and appends an audit line (`ts`, `by`, `op` `arm`) to `<store>/audit.log`. `guard` holds the command the backstop's deny message
  prints: the command that runs the copy under the guard home (`~/.magos` or `MAGOS_HOME`) when that copy exists and
  declares the same `GUARD_VERSION` as the running guard, else the running script. Before it sets
  `maintenance.pack-refs.enabled` and `gc.packRefs` to `false` for the repository, it records their previous local
  values (or that they were unset) in `<store>/arm-config.json`; an existing record is kept, so a re-run never records
  its own `false`. A repository armed by 1.0.0 or 1.0.1 has no record and already holds `false`, so re-arming it records
  `false` and `disarm` leaves both keys `false`; the documentation gives the commands that restore them
  (`git config --local --unset gc.packRefs` and `git config --local --unset maintenance.pack-refs.enabled`). It can be
  re-run over its own hook. Refuses (exit 3, checked before the console) when `core.hooksPath` is set, hook directories
  differ across worktrees, or `.magos-prev` already exists next to a hook that is not MAGOS's. Idempotent.
- `disarm [--dry-run]`: needs a real console except with `--dry-run` (exit 17 otherwise); removes `ARMED`, deletes the
  hook if it is MAGOS's and restores `.magos-prev`; restores both settings from `arm-config.json` (unsetting a key that
  was unset) and deletes the record; without a record both settings stay as they are, and a record that does not parse
  leaves both settings and the record as they are; keeps claims and audit, and appends an audit line (`ts`, `by`, `op`
  `disarm`).
- Console gate. The gate of `override`, `arm`, `disarm` and `install` refuses a call whose stdin and stdout are not a
  console. A command started in a new console window (`start`, `Start-Process`) passes it, so the gate, like an
  override, is not access control; what keeps agents from running the user-only commands is the host hook's recognition
  of them and the launcher's refusal of every subcommand but `hook`.
- `install --host claude|codex|hermes [--dry-run] [--home DIR] [--allow-downgrade]`: needs a real console except with
  `--dry-run` (exit 17 otherwise). On Windows it refuses (exit 2, nothing written) when the path of the copied launcher
  (`<home>/guard/hooks/run-guard.cmd`) contains a character that cmd.exe reads as an operator, a separator or an
  expansion when it starts the launcher and runs the interpreter through `call` (`&`, `(`, `)`, `^`, `%`, `;`, `,`,
  `=`); the message names the character and the path and asks for a guard home without it (`--home` or `MAGOS_HOME`).
  It compares `scripts/magos_guard.py` and `hooks/run-guard.cmd` with the copies in
  `<home or ~/.magos>/guard/{scripts,hooks}/`. When both copies are byte-identical to the sources it prints
  `guard copy unchanged (<version>)` and copies nothing. A missing source file is an internal error (exit 11). When the
  copy's `GUARD_VERSION` (read from the copy's bytes and compared as a tuple of integers) is newer than the source's, it
  refuses with exit 18 unless `--allow-downgrade` is given. Otherwise it first writes every changed file to a temporary
  name in its destination directory (the launcher with mode `0o755` on POSIX, so the replaced launcher stays
  executable), then moves each into place with `os.replace`; when a move fails it puts back every file it already
  replaced from the previous bytes, removes the temporary files, leaves `VERSION.json` as it was and exits 11, so the
  copy is never a mix of two versions. It prints `did copy <source> -> <destination>` for each changed file and
  `guard copy <old> -> <new>` (`none` when there was no copy, `unversioned` for a copy that declares no
  `GUARD_VERSION`). Every install that is not a dry run then rewrites `guard/VERSION.json` (also when the copy was
  unchanged) with `{version, sha256, source, installed_at}` of the copied guard and appends one JSON line (`ts`, `op`
  `install`, `host`, `from`, `to`, `source`) to `<home>/audit.log`. `--dry-run` prints what it would copy and the snippet
  and writes nothing. It writes the exact host snippet to `guard/generated/<host>.json|yaml` and prints it.
  It never edits `~/.claude/settings.json`, `~/.codex/hooks.json` or Hermes config. The Codex snippet matches
  `Bash|mcp__.*(start_session|worktree|branch|hand_off_to_session)` and runs `sh '<launcher>' hook codex pre-tool`
  (`commandWindows`: `& '<launcher>' hook codex pre-tool; exit $LASTEXITCODE`), timeout 25; the launcher path is quoted
  for each shell, every `'` written `'\''` in the sh form and `''` in the PowerShell form. The Claude snippet, whose
  commands run under bash (`"shell": "bash"`), puts the launcher path in single quotes with every `'` written `'\''`,
  so a `$`, a backtick or a `!` in the path stays literal. The Hermes snippet is valid
  YAML on every platform (matcher `terminal`, timeout 25, `fail_closed: true`); its command parses to
  `"<launcher>" hook hermes pre-tool` on Windows and to `sh '<launcher>' hook hermes pre-tool` elsewhere, where the
  launcher is `<hermes home>/plugins/magos/hooks/run-guard.cmd` when that file exists, the guard script beside it
  declares the installing guard's `GUARD_VERSION` and, on Windows, its path holds none of the characters above
  (Hermes home: `HERMES_HOME`, else `%LOCALAPPDATA%/hermes` on Windows, else `~/.hermes`), else the copied launcher;
  when the Hermes plugin holds another version, install says so, names that version (`unversioned` when it declares
  none) and tells the user to update the Hermes plugin, and when its path holds such a character, install names the
  character and the path. Only Claude's
  EnterWorktree group carries `--strict`; for the other entries `--strict` is a documented opt-in.
- `doctor [--home DIR]`: prints the running guard's version, the first 12 hex digits of its sha256 and its path; checks
  Python (3.9+) and Git, and reports `git X.Y TOO OLD for the lane guard (need 2.36+)` below 2.36. Before it looks for a
  repository it compares the copy under the guard home (`--home`, else `MAGOS_HOME`, else `~/.magos`), when there is
  one, byte for byte with the running guard and its launcher; when the running guard is that copy itself, it compares
  the copy with the guard file that `VERSION.json` names as its `source` and says which file it compared against, and
  when `VERSION.json` is missing or names a file that does not exist it says that it has no source to compare the copy
  with, which is not a problem. It prints the copy's `GUARD_VERSION` (`unversioned` when it declares none), the first
  12 hex digits of its sha256, and the provenance line `guard copy provenance: <version> (<sha256, 12 digits>) from <source>, installed
  <installed_at>` read from `VERSION.json`, with `, which does not match the copy` added when the recorded sha256 differs
  from the copy's; the provenance line is information, not a problem. A difference between the copy and the guard it is
  compared with is a problem, reported with the refresh command (`<guard command> install --host <host>`, where the
  guard command runs the guard the copy was compared with, with `--home <dir>` when doctor was given `--home`, for
  each host that has a generated snippet under `guard/generated/`, for every host when none has). A copy that
  declares a newer `GUARD_VERSION` than the guard it is compared with is reported as newer, with that version and the
  advice to run doctor from that MAGOS (the `source` that `VERSION.json` names, when it names one), and no install
  command is printed, because install would refuse it with exit 18. When
  `guard/generated/hermes.yaml` exists, doctor reads the launcher path from its command and reports, as a problem, a
  launcher that does not exist (the Hermes plugin was removed, and `fail_closed` then blocks every Hermes terminal call)
  and a launcher whose guard script (`../scripts/magos_guard.py` beside it) declares a `GUARD_VERSION` other than the
  running guard's. Outside a repository it then reports that the guard is inert there. In a repository it checks mode,
  hook uniformity, hook content, claim parsing (unreadable and newer-format claims), orphan claims, `core.hooksPath` and
  the backstop command recorded in `<store>/guard`: a recorded script that does not exist is reported as missing with
  the re-arm command, a recorded script that declares an older `GUARD_VERSION` than the running guard, or none, is
  reported as older than this guard with the re-arm command (both count as problems), and a hook that differs from this
  version is reported with the re-arm command (`<guard command> arm`, for the user's own terminal). In an armed repository whose hook equals this version's it proves the backstop by
  trying `git branch __magos_selftest` on a Git budget of its own (not the time the rest of doctor used): only a
  non-zero exit whose stderr holds a line that begins with the backstop's own veto marker (`MAGOS BLOCKED: ` in English,
  `MAGOS 拒绝: ` in Chinese) counts as a veto; any other failure (a ref lock left behind, a repository path that merely
  contains `MAGOS`), a Git timeout or other Git failure of the probe, and a `__magos_selftest` branch or claim that
  already exists, is reported as `self-test inconclusive` with the cause and counts as a problem; a branch that is
  created is deleted and reported as a failed self-test. Exit 1 on any problem, 0 otherwise.
- `version [--json]`: read-only, works inside and outside a repository; prints `GUARD_VERSION`, the sha256 of the
  running file, its path and the Python version; `--json` prints `{version, sha256, path, python}`. Exit 0.

Repository of a creation. Each creation is judged in its own repository: the redirect target when the invocation has
one, else the directory the invocation runs in at that point (after `cd`, `pushd`, `Set-Location`, `git -C`, `env -C`
and `sudo -D`), else the session directory. The mode, engagement, claims and evidence are those of that repository, so a
claim in the session's repository never allows a creation redirected into another repository. A `git push` into a local
repository is judged in that repository (Command detector). Redirect spellings:
`git --git-dir <p>`, `git --git-dir=<p>`, a `GIT_DIR=<p>` prefix assignment, `env GIT_DIR=<p> git`, a standalone
`GIT_DIR=<p>`, `export GIT_DIR=<p>` and `export GIT_DIR` after an assignment, PowerShell `$env:GIT_DIR='<p>'` or
`$env:GIT_DIR = '<p>'`, and cmd `set GIT_DIR=<p>` (also inside `cmd /c`); `GIT_COMMON_DIR` in each of the variable
spellings. A prefix or `env` assignment applies to its own invocation; an exported, PowerShell or cmd assignment applies
to every later git invocation of the command line, each resolving a relative value against the directory it runs in,
until a removal of the variable ends it, as far as the shell that runs the line performs the assignment and the removal
(see Command detector). A standalone POSIX-shell `GIT_DIR=<p>` that is not exported reaches git only when the shell
already exported `GIT_DIR`, which the guard cannot see; a later git invocation is therefore judged in both repositories,
the redirect target and the directory it runs in, and the stricter verdict applies. A creation under `GIT_COMMON_DIR` is
judged in the `GIT_COMMON_DIR` repository and in the repository the invocation would use without it, and the stricter
verdict applies. A definite directory or redirect change (the first command of a list, or a command joined to the
creation by `&&` alone) replaces the state the creation is judged in; after a possible change (one the shell may not
make before the creation: after `&&` or `||` across a later list or `||`, inside a compound command or a brace block,
made by `eval`, `iex`, `source`, `.` or a PowerShell script, and, outside bash, inside a group, a background list, a
pipeline command or substituted text) the creation is judged in every state before and after it, and the stricter
verdict applies; in bash a change inside a group, a background list, a pipeline command other than the last or
substituted text changes nothing after it. A creation that several states lead to is judged once in each distinct
repository. A `cd` behind a program wrapper (`env cd`) changes nothing. A creation whose redirect is dynamic, does not
open as a repository or follows a `GIT_DIR` / `GIT_COMMON_DIR` change the walker does not model is denied `UNPARSEABLE`
whatever the mode and engagement of the session repository, with the message "the repository is redirected by
--git-dir/GIT_DIR and cannot be resolved; use git -C <repo>". A `cd` or `-C` whose target is dynamic leaves the
repository unknown as well: the creation is judged in the session directory's repository, and so does a dynamic
`env -C` or `sudo -D` directory. A creation left in a prior directory by a `cd` to a missing directory or by a `cd` the
shell refuses is judged in that prior directory and marked unresolved, except for the later elements of an `&&` chain
whose earlier element creates the target (Command detector); when the prior directory is not a repository nothing is
judged. In both cases an engaged creation is denied `UNPARSEABLE` (`UNPLANNABLE` for an auto-named creation). A line the
overflow rule refuses (one that creates something or reads a relative script beyond the state caps, or exceeds the
walking budget) is denied `UNPARSEABLE` unless the session directory's repository is off or `MAGOS_GUARD=off` is set;
outside a repository it is denied.

Errors. In every command except `hook`, a Git failure writes `MAGOS guard: <code>: <text>` and an internal error
writes `MAGOS guard internal error: <exception type>: <text>` to stderr; both exit 11 (`doctor` reports a Git that
cannot run its version probe as a problem and exits 1); with `--json` it also prints
`{"decision":"deny","code":"UNKNOWN","unknowns":[{"code":<GIT_MISSING|GIT_FAILED|BUDGET_EXCEEDED|INTERNAL_ERROR>,"text":...}],"message":...,"exit_code":11}`
on stdout.

Exit codes: 0 allow, registered, ok or unchanged; 1 `doctor` found a problem, or a usage error of `hook` (a failure the
launcher maps, never a deny); 2 usage error of any other command, not a git repository, a malformed fingerprint, or a
guard home whose launcher path `install` refuses on Windows; 3 arm refused; 10 CONFLICT, NO_MANIFEST, UNPLANNABLE,
UNPARSEABLE or PROTECTED; 11 UNKNOWN (also any engine exception, an exhausted budget, a claim in a newer format or a
failed install: plan and check fail closed); 12 INVALID_MANIFEST (also an invalid branch name or a `--worktree` with a
control character); 13 LOCK_TIMEOUT (30 s); 14 LANE_EXISTS; 15 BRANCH_EXISTS; 16 BLOCKED (release);
17 CONSOLE_REQUIRED (`override`, `arm`, `disarm`, `install`); 18 DOWNGRADE_REFUSED (`install`). The launcher's refusal
of a subcommand other than `hook` is its own exit 2; the guard is not started.

Claim file (LF; the git layer reads only line 1, which is exactly `state=active` in every format): `state=active`,
`v=<format>`, `branch`, `worktree`, `target`, `base`, `created`, `by`, `override`, then one `entry=<raw entry>` line per
manifest entry; a missing optional field reads as empty and a missing `v` reads as 1. The format line is `v=` followed
by one or more of the ASCII digits `0` to `9` and nothing else, read as a decimal integer whatever its length and
leading zeros (`v=01` is 1, `v=1000000` is 1,000,000); a value of at most `CLAIM_FORMAT` (0 included) is read as this
guard's format and a greater value is a newer format (below). A line 2 that starts with `v=` in any other spelling
(`v=`, `v=1.0`, `v=+1`, `v=1_0`, `v= 1`, a digit outside ASCII) makes the file unreadable. The reader keeps the known keys; a key it does not know is kept aside and
written back unchanged when a claim of the same format is amended; a key line never replaces the entry list, the state
or the format, and a repeated scalar key makes the file unreadable. A claim whose `v` is greater than `CLAIM_FORMAT` is
too new: every judgement reports `UNKNOWN` `CLAIM_NEWER_FORMAT` ("<branch> was written by a newer MAGOS (v=N); upgrade
this guard", naming the file when it has no `branch` line), `release` refuses it with exit 16, and `plan` and
`plan --amend` never overwrite it. Within one format only additive keys are allowed; a change an older reader must not
ignore raises `CLAIM_FORMAT`. Values never carry a control character: a branch, worktree or entry with one is refused,
and each control character in `by` (the Git user name, e-mail and login) is replaced with a space. A claim file is
written only where no file exists or where the claim of the same folded branch is, and a failed write leaves no
temporary file behind. Branch names that would share a claim file on Windows are refused: a path component ending in
`.` or a space, or ending in `.claim` (the Windows alias rule). A claim an earlier guard stored under such a name stays
readable and keeps allowing the creation of its own branch: the host hook judges that stored claim and skips only the
Windows alias rule for it, while `plan` and `plan --amend` refuse the name. `list` names such a claim (JSON field
`refused_name`, the reason; text ` (name refused by plan: ...)`) and `doctor` prints one line naming every such claim,
so the user can release it and plan the lane under another name. A worktree path is
compared case- and separator-insensitively where the platform is. Store layout:
`<git-common-dir>/magos/{ARMED,lang,guard,arm-config.json,claims/,override/,audit.log,lock}`; the guard home holds
`guard/{scripts,hooks,generated}/`, `guard/VERSION.json` and `audit.log`.

Verdict (`--json`): `{decision, code, conflicts:[{key, branch, worktrees, planned, evidence:[{kind committed|uncommitted|declared,
files, matched, theirs}]}], unknowns, warnings, target:{name,sha,confidence}, fingerprint, overridden, message, exit_code}`.
The fingerprint is the first 12 hex digits of SHA-256 over the canonical denial (the planned lane's key, claimant keys,
evidence kinds and files, the other lanes' declared entries that overlap, unknown codes, target sha); the planned lane's
own manifest entries are not part of it, so changing the repository voids an override. A denial whose every unknown is
`CLAIM_NEWER_FORMAT` names the claim and says to upgrade this guard; it offers no other option (no shrink, wait,
release or override text), because only a guard that reads that format can act on the claim.

Invariants:

1. Creation is denied before it happens; a denial leaves no branch, worktree directory or administrative directory.
2. Existing lanes are never stopped, modified, stashed, merged or moved; the guard only reads them.
3. Unknown is not safe: an ambiguous target (or a `--target` that does not resolve), `git am`, unreadable operation
   metadata, a locked worktree missing on disk, more than 120 unmerged local branches, an unreadable claim, a claim in a
   newer format, a Git failure or an exhausted budget (18 s per command or hook call, 30 s per Git call) deny creation
   in `plan`, `check`, an armed repository and for a named worktree. In auto mode a snapshot that hides lanes (more
   than 120 unmerged local branches, or more unmerged remote-tracking branches than the 300 it analyses) counts as
   engaged. When the engagement check itself fails (an uncertain integration target, a Git failure, an exhausted
   budget), the host hook treats a branch-only creation as engaged only when the repository holds an open claim (then
   it is judged) and allows it otherwise, and it denies an auto-named creation (`UNPLANNABLE`, with the failure as the
   reason) only when a lane signal that needs no integration target exists: an open claim (also one of a newer format),
   a local branch other than the one checked out in the worktree the creation runs from, or a second worktree;
   otherwise it allows the auto-named creation. In each of these cases it writes a warning on stderr that names the
   failure and the outcome. Opening the repository is the one step that does not fail closed: a failure of `rev-parse`
   there, other than a missing Git or an exhausted budget, reads as "not a repository".
4. Hard overlap is a direct path, directory prefix, glob, rename side, case or Unicode collision, or a declared manifest
   against a manifest. Warnings never deny: inferred target, remote freshness, operation in progress, repository not armed.
5. The only writes are claim and audit files (under the lock), override records, the files `arm` (including
   `arm-config.json`), `disarm` and `install` (including `VERSION.json` and the generated snippet) print, and the audit
   lines `arm` and `disarm` append to `<store>/audit.log` and `install` appends to `<guard home>/audit.log`. `check`,
   `list`, `hook`, `version` and every `--dry-run` never write.
6. Engagement: ARMED (marker file) guards every new branch and worktree; AUTO (default) always guards named worktree
   creation and guards branch-only or auto-named creation only when another lane exists; OFF
   (`git config --local magos.guard off`) silences the host hooks of that repository: its own creations, and a line the
   overflow rule refuses when it is the session directory's repository. Mode and engagement are read from the
   creation's own repository, so OFF never silences a creation judged in another repository. `MAGOS_GUARD=off` is read
   from the host process environment only; it silences the creation checks and the overflow rule everywhere.
7. Tamper protection is best-effort matching of words and common writer commands. User-only subcommands (whatever the
   spelling of the global options before them, `--` included, and whether the guard script or its launcher
   `run-guard.cmd` is named, also behind `start`, `cmd /c start` or `Start-Process`) and `git config magos.*` writes are
   denied by the host hook in every repository and outside any repository, and so is a git invocation that carries a
   word beginning with `magos.` beside an alias it defines with `-c alias.<name>=` or a subcommand that is not a
   built-in git command, because an alias can run `config`. Edits of the guard's state are denied once
   the session directory's repository is armed or holds a claim: `core.hooksPath`, `GIT_CONFIG_*`, worktree config, and
   writers or redirects aimed at `.git/hooks`, `.git/refs`, `.git/HEAD`, `.git/config`, `packed-refs`, `.git/magos`,
   `.magos`, the absolute path of the session repository's `<git-common-dir>/magos` (in any separator or case spelling
   the platform folds), the absolute path of the guard home (`~/.magos` or `MAGOS_HOME`) and the Hermes plugin
   directory `<hermes home>/plugins/magos` when it holds a launcher. The writers include the PowerShell cmdlets
   `Rename-Item` (alias `rni`) and `Move-Item` (alias `mi`) and the `Remove-Item` alias `ri`, and the text of a child
   shell (`bash -c`, `sh -c`, the other POSIX shells' `-c`, `cmd /c` and `/k`, `powershell` and `pwsh` `-Command` or
   `-c`) is read with every check, to depth 3, as is a quoted word that names the guard script or its launcher (the
   argument list of `Start-Process`); any other quoted word is not read as a command, so a commit message or a search
   pattern that names these words passes. Each keyword test and the
   state-path test read every word twice, as written and with every backslash, backtick, caret, `'` and `"` removed,
   and match when either reading matches, so the escapes of bash (`ma\gos.guard`, `conf\ig`, `ar\m`,
   `rm .git/ma\gos/ARMED`), PowerShell (``ma`gos.guard``) and cmd (`ma^gos.guard`) hide nothing, and
   `rm .git\magos\ARMED` and `Remove-Item .git\magos\ARMED` stay denied. A plain copy (`cp` without a link option
   `-l`, `--link`, `-s`, `--symbolic-link`; `Copy-Item`, `copy`, `cpi`) is tested on its destination only: `-t` /
   `--target-directory`, or `-Destination` (also written `-Destination:<path>`), else every positional argument after
   the first, so an option value after the operands (`-ErrorAction Stop`, `-S .bak`) hides no destination, and copying
   from the guard home is allowed; every other writer (`rm`, `mv`, `move`, `ln` and `ln -s`, `cp` with a link option,
   `mklink`, `del`, `unlink`, `truncate`, `shred`, `rmdir`, PowerShell's `sc`, `ac`, `ni`, `clc` and the rest) is
   tested on every argument, because a link to a guard file lets a later write change the guard. The repository is opened to learn the
   store's absolute path only when a tested write target or redirect target is an absolute path with a path segment
   named `magos`. Other spellings, interpreters and file tools are the limit stated in `references/lane-split.md`
   section 12.
8. Failure handling: a payload the hook cannot decode (invalid JSON, or any exception while decoding, `RecursionError`
   and `MemoryError` included) is denied when its raw bytes match the prefilter (`git`, `worktree`, `isolation`,
   `start_session`, `EnterWorktree`, `magos`, `hookspath`, `gh`, `claude`, `eval`, `iex`, as substrings in any case).
   An exception while deciding a decoded payload denies the call when the call is recognised as a lane creation or a
   protected command; when recognising it raises as well, the call is denied when the command text of `tool_input`
   (or, for a tool without a command, its `tool_input` serialised) matches the prefilter. Path fields such as `cwd`
   and `transcript_path` never decide it. Otherwise the hook prints `{}` and a warning on stderr. The launcher turns a missing script, missing
   Python or a non-zero guard exit into exit 2 for the strict group (EnterWorktree) and a warning with exit 0 for all
   other tools and hosts, Hermes included; Hermes' `fail_closed: true` blocks only a launcher that cannot be started or
   that times out. The warning names the absolute guard path and says how to stop the guard on any host
   (`MAGOS_GUARD=off` in the host environment or removing the MAGOS hook entry; for Claude, `claude plugin disable
   magos`).

## Change Notes

Version 1.0.2 is a security release of the guard. Relative to the 1.0.1 product it:

- judges a creation in the repository that a `--git-dir` or `GIT_DIR` redirect names (resolved per invocation, as Git
  resolves it, and ended by a removal of the variable), and denies a redirect it cannot resolve with its own message;
  `--work-tree` and `GIT_WORK_TREE` alone leave the judged repository unchanged; judges a creation under
  `GIT_COMMON_DIR` in both repositories Git splits it between; treats a `GIT_DIR` or `GIT_COMMON_DIR` change in a
  spelling the walker does not model (`read`, `printf -v`, `+=`, `builtin export`, `Set-Content Env:`) as an unknown
  repository;
- treats a directory or redirect change as definite only when the shell certainly makes it before the later command
  (the first command of a list, or a chain of `&&`) and judges the commands after every other change in every state
  before and after it, following bash's subshell rules (a group, a background list, a pipeline command other than
  the last and substituted text change nothing after them) and keeping both states where the shell is PowerShell, cmd
  or not known; judges a creation once per distinct repository and gathers each repository's evidence once per hook
  call; bounds the walk of a line by a budget, lets the state caps deny only a line that creates something or reads a
  relative script, and lets the overflow denial follow the session repository's OFF switch and `MAGOS_GUARD=off`;
- ignores a builtin started through a program wrapper (`env cd`), judges git under `env -C` and `sudo -D` in that
  directory, and follows a `cd` the shell refuses or cmd's `cd /d` as the shell does;
- reads text piped into a shell behind prefix assignments, wrappers and their options, unwraps `doas` like `sudo`,
  splits `env -S`, and reads the PowerShell `$name = <command>` and PowerShell `( .. )` and `@( .. )`;
- reads the escapes of the shell that runs the text: POSIX backslash quoting in text a POSIX shell runs and cmd's caret
  in detection, a backslash in a git subcommand or branch name of a shell it cannot name as dynamic, and the escape
  characters of bash, PowerShell and cmd in the tamper filter;
- judges the commands after a `cd` to a missing directory in the prior directory, on every platform and for every
  target spelling, and follows a `cd` into a directory an earlier element of the same `&&` chain creates;
- recognises `git branch` rename and copy in every option spelling, options with their value attached (`claude -w<name>`
  and `claude --worktree=<name>` included), a push into a local repository, glob refspecs, the git global options
  that take a separate value, aliases in every git invocation of a line, and the commands `git rebase --exec` and
  `git bisect run` run;
- inspects the `Monitor` tool and every hooked or MCP tool with a string command, besides the judgement the tool's own
  name calls for, routes MCP tools by command-like names and substrings, answers an MCP tool without a command without
  parsing, reads `tool_input.cwd`, expands `~` in the session directory and joins a relative tool directory to the
  payload's `cwd`, and builds the Claude matcher from the same constant;
- never resolves `git`, `py` or `python` from the hook's working directory on Windows (guard and launcher);
- recognises user-only commands whatever their global option spelling (`--` included) and when they are run through
  the launcher or a wrapper that opens a new console, rejects abbreviated options, gates `install` behind a real console, and
  records `arm`, `disarm` and `install` in audit logs;
- decides an auto-named creation whose engagement cannot be decided by lane signals that need no integration target,
  with a stderr warning, and counts a snapshot that hides lanes as engaged;
- denies a lane-looking payload on any exception while decoding or deciding;
- applies an override only through `plan`;
- prints a JSON deny object for Git and internal errors under `--json`, and names Git's exit code in a silent failure;
- hardens the claim store: canonical `release`, Windows alias names, control characters, key whitelist, name check under
  the lock, the claim format gate (every integer spelling of the format line, and `release` keeps an unreadable claim
  whose format line may come from a newer MAGOS) and visible unusable claims in `list`; a denial caused by a
  newer-format claim says to upgrade and nothing else;
- adds `version`, the version-aware `install` that replaces both copied files or neither, keeps the launcher
  executable, rewrites `VERSION.json` every time, quotes the Codex entry for sh and PowerShell and the Claude entry for
  bash, refuses a Windows guard home with cmd metacharacters, and exits 18 on a downgrade; points the Hermes entry at
  the Hermes plugin launcher only while that plugin holds the same guard version under a path cmd can start; and writes
  valid Hermes YAML on every platform;
- extends `doctor` with the running version, the copy comparison (`--home`, and from the copy against its recorded
  source; for a newer copy it names the newer MAGOS instead of an install command), the `VERSION.json` provenance line,
  the Hermes entry check, the Git 2.36 check, the self-test on its own budget that counts only the backstop's veto
  line, and the recorded backstop path and version; `arm` records the copy only at the running version and records the
  pack-refs settings that `disarm` restores;
- matches the absolute paths of the store, the guard home and the Hermes plugin directory in the tamper filter, reads
  child-shell text and the rename cmdlets there, denies a `magos.` word beside a git alias, allows copying from the
  guard home, opens the repository only for a write target that may be the store, tells an agent denied an auto-named
  worktree to plan `worktree-<name>` before `EnterWorktree name=<name>`, and gives uncommitted changes as the release
  refusal reason;
- looks the cmd half's interpreter up on PATH and runs it through `call`, passes the guard's stderr to the host, gives
  a Windows Python the Windows spelling of the guard path in the sh half, and runs only the `hook` subcommand.

Version 1.0.3 is a hardening release of the guard (`GUARD_VERSION` 1.0.3). Relative to the 1.0.2 product it:

- reads an `update-ref --stdin` name up to a backslash, takes `\0`, `\n`, `\t` and `\r` after it as separators, and
  makes the record dynamic for any other escape, an empty name or a name git refuses;
- reads a program word with a backslash, a backtick or a caret in a shell it cannot name as the program it spells
  without them, with dynamic creations and possible changes;
- reads `git rebase --ex` and `--exe`, `git --shallow-file <v>`, `git update-ref -m <v>` and `--std`, and `heads` in
  any case under `refs/` (host hook and git layer);
- finds the subcommand of every `git` word after the values of the global options for the alias check, in one pass;
- runs `Start-Process` git in its `-WorkingDirectory`, and reads the `-ArgumentList` and `-WorkingDirectory` prefixes
  and colon forms;
- reads every `powershell` and `pwsh` spelling of `-Command`, `-CommandWithArgs` and `-EncodedCommand` (`-e`, `-ec`,
  `-EncodedC`, `-Co`, `-Comm`, `-cwa`) in the walk, the tamper filter and a Codex argv, and joins the words after a
  PowerShell or cmd command option of a Codex argv into the text it runs;
- reads PowerShell's backtick escape with its special sequences;
- gates a line and its inner texts on their text without escapes and quotes, and on a word that runs a script or a
  shell;
- keeps records and inner-text states that differ only in a missing directory's prior directory or followed chain;
- lets the launcher pass on from `py.exe` exiting 103 or 112 in both halves;
- honours a claim stored under a name the Windows alias rule refuses when its branch is created, and names such
  claims in `list` and `doctor`.

Compatibility: claim files of format 1 written by 1.0.0 and 1.0.1 are read unchanged, and line 1 of every claim stays
`state=active`, so the git layer reads old and new claims alike; a claim stored under a name the Windows alias rule
refuses allows the creation of its branch. The git-layer hook reads `heads` in any case, so `doctor` reports an armed
repository as different from this version until `arm` runs again. The Codex and Hermes copies under `~/.magos/guard`
receive 1.0.3 only when the user re-runs `install`; `doctor` reports a stale copy with the refresh command, and armed
repositories are refreshed by re-running `arm`. Exit code 18 is new. A Hermes entry points at the Hermes plugin
launcher only while the plugin's guard declares the installing guard's version; after the plugin moves to another
version, `doctor` reports the difference and `install` points the entry at the copy until the versions agree again.
`references/lane-split.md` is a flat reference shipped to Codex and Hermes by the `references/*.md` glob.
`hooks/hooks.json` and `hooks/run-guard.cmd` sit at the repository root, outside `.claude-plugin/`. The root
`description` is 1017 characters. The git layer is opt-in per repository (`arm`) and the Codex and Hermes entries are
generated, never merged automatically.

Known limits, stated in `references/lane-split.md` section 12:

- Hooks read the text of one command line and follow the directory and redirect changes the Command detector names.
  Not followed: state an earlier tool call left in a shell that keeps it, a relative `cd` that a loop or a repeated
  function call applies more than once, a `cd` resolved through `CDPATH`, a computed `cd` target (the session
  directory's repository decides), a `.git` file the same command line writes, and changes made by a script or an
  interpreter the hook cannot read.
- Tools whose shell the hook cannot name judge the commands after a group, a background list, a pipeline command or
  substituted text in every state.
- PowerShell's typographic quotes (`‘ ’ ‚ ‛` and `“ ” „`), which PowerShell reads as quote characters, are read as
  ordinary characters of a word.
- `Start-Process` is recognised by that name only (not `saps` or `start`), its `-ArgumentList` only by that name, a
  prefix or the colon form (not the alias `-Args`, not as the second positional argument), and its program among its
  words; a creation written in another binding runs unjudged.
- A push to a remote name is not judged, also when the remote's configured URL is a local path.
- The git layer cannot see `-c core.hooksPath`, a `GIT_COMMON_DIR` that names another repository (Git runs that
  repository's hooks), direct `.git/refs` writes, libgit2, clones or a branch rename or copy (`git branch -m/-c`),
  which the host hooks deny in every option spelling. Harness-created worktrees are covered only by the git layer.
- The backstop's denial names the guard command `arm` recorded; once that guard is removed, the denial names a command
  that cannot run until the repository is re-armed, which `doctor` reports.
- A claim file whose `branch` line names another branch than its file name is read by the guard under its `branch`
  line and by the git layer under its file name.
- Input sent to a running shell through Hermes `process_manage` and edits made with file tools are not inspected.
- The tamper filter is best-effort. Not matched: relative spellings other than those Invariant 7 names, the hooks,
  refs, `packed-refs` and config of a bare repository's git directory written by an absolute path, the Claude plugin
  directory the Claude hooks run from, a guard home chosen with `--home` that `MAGOS_HOME` does not name,
  interpreters and file tools.
- `doctor` run from the copy compares it with the file `VERSION.json` names as its `source`; a plugin that installs
  each version into a directory of its own leaves that file at the copy's own version, so a newer plugin is not seen
  from the copy.
- A plugin directory whose Windows path holds a cmd metacharacter breaks the plugin's own Windows hook entry, which
  `install` cannot choose.
- Claims are per clone, and neither an override nor the console gate is access control.
