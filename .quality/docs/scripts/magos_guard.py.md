# Technical Design: `scripts/magos_guard.py`

Source: `scripts/magos_guard.py`

Source-SHA256: `7c8a55b6cf76a939d1a4d06593110a7f01703e8aae068f427868dbb343961a2c`

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

The file holds ten cooperating parts.

1. **Manifest and overlap engine.** Entries are normalised (NFC, case-folded, separators unified, trailing dots and
   spaces stripped) and compared with an exact glob-intersection dynamic programme at character level and at path level.
   A `**` segment matches any number of directories; `*` and `?` never cross `/`; brackets are ordinary characters.
   Entry-versus-path and entry-versus-entry use the same function, so declared manifests of lanes that do not exist yet
   collide with each other.
2. **Evidence gatherer.** A Git runner (argv lists, scrubbed environment, pinned options that turn off the fsmonitor,
   the untracked cache and `diff.relative` (so `diff` and `log` name every path from the top of the work tree, whatever
   directory below it the call starts in: the hook's session directory or a `--repo` below the top), `-z` machine
   formats, `--ignore-submodules=none` right after the subcommand of every `diff`, `log` and `status` call (so a changed
   gitlink is a changed path, and a submodule checkout whose commit differs from its gitlink or that holds modified or
   untracked files is an uncommitted change of that path, whatever `diff.ignoreSubmodules`, `submodule.<name>.ignore` or
   the `ignore` of `.gitmodules` says: the option on the command line overrides all three, and the pinned
   `-c diff.ignoreSubmodules=none`, which Git passes on to the `status` it runs inside each submodule checkout, keeps a
   setting of the user or of a submodule from hiding a nested submodule's changes there), per-call timeout and a total deadline that every Git
   call of one hook
   invocation shares) enumerates claimants: every non-bare worktree, every local branch not merged into the target,
   every unmerged remote-tracking branch, and every open claim except the integration claim of a set (Sets,
   Integration claim). The runner runs only the local subcommands
   `--version`, `branch`, `check-ref-format`, `config`, `diff`, `for-each-ref`, `log`, `merge-base`, `rev-list`,
   `rev-parse`, `status` and `worktree` (`LOCAL_GIT`), read after any leading `--git-dir=` or `--work-tree=` argument;
   for any other first argument (another subcommand, an option such as `-c` or `--config-env`, or none) it raises
   `GitFail` `GIT_FAILED` before git starts.
   Committed evidence is the three-dot diff against each merge base minus content the target already holds; a detached
   worktree contributes the commits of its own HEAD, and a detached worktree at the lane's own registered path is the
   lane itself and is not compared. Uncommitted evidence is `status --ignore-submodules=none --porcelain=v2 -z --untracked-files=all` (a rename
   claims both names). A merge, rebase, cherry-pick or revert in progress is a warning; `git am`, unreadable operation
   metadata or a locked worktree that is missing on disk is unknown; a branch with no history in common with the target
   is ignored with a warning because a merge could not collide. Bare repositories and submodules are opened like any
   other repository. A Git call that exits non-zero without writing to stderr is reported with its exit code
   (`git <args>: exit code N`). Within one hook call the evidence of a repository (its opening, mode, refs, claims,
   engagement and gathered claimant evidence) is collected at most once, whatever number of directory or redirect
   states of the command line lead to it.
3. **Claim store.** `<git-common-dir>/magos/claims/<branch>.claim` files, written under an OS file lock with a
   temporary file and `os.replace`, plus an append-only `audit.log` and, from 1.0.4, the set records
   `<git-common-dir>/magos/sets/<set>.json` (part 8). The store is shared by all worktrees, is never part
   of a work tree and is not carried by fetch, push, clone, bundle or mirror. Every claim carries a format number; the
   guard reads format `CLAIM_FORMAT = 1` and refuses to act on a claim written in a newer format instead of misreading
   it; a set record carries its own format number (`SET_FORMAT = 1`) with the same rule.
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
   neither. bash, sh, zsh, dash and ksh read `-c` and bundled short options that hold a `c` (`-lc`, `-ec`, `-ce`); cmd reads
   `/c` and `/k`. `Start-Process` runs git with its `-ArgumentList` value in its `-WorkingDirectory`, each named in
   full, by a unique prefix (`-a`, `-wo`) or in the colon form (`-WorkingDirectory:<dir>`, and `-WorkingDirectory: <dir>`
   with the value in the next word); a list written with commas
   (`'switch', '-c', 'x'`) is one `-ArgumentList` value; the directory is resolved
   against the directory the shell is in, and a dynamic value makes the repository unknown (the session directory's
   repository decides, as for any computed directory). In PowerShell the command on the right of `$name =` runs (`$out = git switch -c x` is a creation), and the
   text of `( .. )` and `@( .. )` inside a command is judged like `$( .. )`; text inside a quoted string is not. Dynamic
   words (`$x`, backticks, `%x%`) in a lane-creating position are treated as unparseable. The script a shell runs is the
   `-File` value or the first readable file among the first four candidates after option values. Text echoed or quoted
   into a shell through a pipe is inspected also when prefix assignments, wrappers (`env`, `command`, `builtin`, `exec`,
   `nohup`, `nice`, `time`, `setsid`, `stdbuf`, `sudo`, `doas`) and their options stand between the pipe and the shell
   (`FOO=1 sh`, `env FOO=1 bash`, `sudo -E sh`, `command sh`, `doas -u <user> sh`). Command text longer than 200,000
   characters is not inspected: it counts as an unparseable creation and, once claims or the git layer exist, as a
   protected command; when it names MAGOS (`magos` or `run-guard`, read with every backslash, backtick, caret and quote
   removed) every host's hook denies it in every repository with the `protected_long` text, since what it runs cannot be
   read (Approval routes (version 1.0.8), The subcommand of a guard run). Every pattern runs in time linear in the command length: each word a pattern reads excludes `|`,
   `;` and `&`, and has one reading; the lexer reads each character once. A directory spelling longer than 4,096
   characters is an unknown directory: a chain of relative `-C` values or `cd` targets never grows a path past that
   length, so a line of 200,000 characters of `git -C a/b -C a/b ...` costs time linear in its length (the creation after
   it is judged against an unknown directory and denied `UNPARSEABLE` where lanes exist). The walker counts the open
   groups, brace blocks and compound commands per kind, so a closer finds its opener in constant time and a line of
   98,000 nested parentheses or braces is walked in linear time, in bash and in PowerShell. The walk of one command line, nested text and
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
     removes itself and makes the next character literal (``g`it`` is `git`, ``ma`gos`` is `magos`), except that
     `` `0 ``, `` `a ``, `` `b ``, `` `e ``, `` `f ``, `` `n ``, `` `r ``, `` `t `` and `` `v ``
     stand for NUL, bell, backspace, escape, form feed, newline, carriage return, tab and vertical tab (``gi`t`` is `gi`
     followed by a tab, which is no git). A bell in a branch or worktree name is a character git refuses; a creation
     named with one is judged under the name with the letter a in its place, the stricter reading (``git switch -c fe`at``
     is judged as the creation of `feat`). In cmd text a caret outside double quotes removes itself and makes the
     next character literal, as cmd reads it (`git switch -c feat^ure` creates `feature`). In text whose shell is not
     known, a git subcommand or a branch name that holds a backslash is dynamic, because the shell may remove it;
     paths keep their backslashes there (a `cd` target, a `-C` value, a `--git-dir` value, a worktree directory),
     because a Windows shell reads them as separators. A program word there that holds a backslash, a backtick or a
     caret and is no program the detector knows, but names one once the backtick and caret, or all three characters,
     are removed (`g\it`, `g^it`, ``g`it``), is read as that program: every creation it makes is dynamic, and every
     directory or redirect change it makes is possible (the commands after it are judged in the states before and after
     it), because the shell may or may not remove the escape. The programs so read are those the detector reads, the
     commands that change the directory or the environment (`cd`, `export`, `unset`, ...) and the wrappers (`env`,
     `sudo`, ...), so `env g\it switch -c x` finds git behind the wrapper. A word that spells no such program is none.
     In text a POSIX shell runs, a backslash-newline is removed and
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
     `pwsh`, `cmd`, also with `.exe` and behind a path) standing where a command may start: first in a command, after
     prefix assignments, redirections, keywords (`then`, `do`, ...) and a PowerShell `$name =`, or anywhere after a wrapper (`env`,
     `sudo`, `timeout 5`, `xargs`, ...), whose program follows its options, or right after the `-exec` or `-execdir` of
     `find`. A runner's name in the arguments of another
     command (`ls .`, `echo sh`) is no gate. So `. ./mk`, `bash ./mk`, `$(. ./mk)`, `$(bash ./mk)` and a here-document
     that runs `. ./mk` are walked, and the script they run is read. The words are found in one pass over the text
     (a quoted string is one word, a quote that never closes belongs to no word) and in one more pass over the text with
     its quotes removed, so that a quote the shell reads as a literal (`echo \"; bash ./mk`) hides no word; a text longer
     than 200,000 characters is walked, and the walk refuses it as too long to inspect.
   - Redirections. The lexer reads a redirection of the shell as a word of its own, marked as such, in bash, PowerShell,
     cmd and a shell the hook cannot name: an operator written outside quotes and escapes, with an optional file
     descriptor in front (`2>`, `3>&1`; in bash and a shell the hook cannot name a variable name in braces, `{fd}>f`;
     in PowerShell the stream `*>`), among `>`, `>>`, `>|`, `<`, `<<`,
     `<<-`, `<<<`, `<>`, `>&`, `<&`, `&>` and `&>>` (the `&` of `>&` and `<&` ends no command in any shell, and the `&`
     of `&>` and the `|` of `>|` end none in bash and in a shell the hook cannot name, so `2>&1`, `>&2`, `&>f` and
     `>|f` stay in one word, while `|&` and `&&` still end a command), followed by its target in the same word (`>f`,
     `2>&1`, `<<EOF`, `<<<text`, `>$null`) or
     else in the next word (`> f`, `>& 2`, `<< EOF`, `<<< text`). An operator written inside a word without a blank
     before it ends the word there (`git>/dev/null switch` is `git`, `>/dev/null`, `switch`), except right after a
     number that makes the whole word so far (`2>f`), inside `${..}`, `$(..)` and `(..)` of a word, and for `<(` and `>(`,
     which are substituted text and no redirection. A quoted or escaped word (`'>x'`, `\>x`, `">"`) is no redirection.
     A redirection is no word of the command it stands in: it is skipped, with its target when that is the next word,
     before the program word of a command (after prefix assignments, keywords and wrappers as well: `>/dev/null git
     switch -c x`, `2>&1 bash ./mk`, `FOO=1 >f git ...`, `time >f git ...`), between `git`, `gh`, `gt` or `claude` and its
     subcommand and between the global options of git and their values (`git -C . >/dev/null switch -c x`, `git -C
     >/dev/null . switch -c x`), and among the words of every git invocation, so the subcommand, the options and the
     names are those git is handed (`git branch -m old new >/dev/null` creates `new`; `git update-ref >/dev/null
     refs/heads/x HEAD` and `git symbolic-ref 2>/dev/null HEAD refs/heads/x` create `x`; `git switch -c >/dev/null x`
     creates `x`). A word that is no redirection is never skipped, so `git -C '>' switch -c x` still reads `>` as the value
     of `-C`, and `git branch '>x'` creates `>x`. The input redirections of an `update-ref --stdin` stay readable as its
     sources. The text a shell is told to run is read behind redirections as well (`bash -c >/dev/null 'git switch -c
     x'`, `sh 2>&1 -c ...`). The word gate skips the same words (`>/dev/null bash ./mk`, `2>&1 . ./mk` are walked), the
     alias check finds the subcommand behind them (`git 2>/dev/null nb x`), and the tamper filter finds the program behind
     them (`2>/dev/null rm .git/hooks/reference-transaction`).
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
     rename); the last positional word is then the new branch, whatever other option stands beside it (`-mr a b`,
     `-m -r a b`, `-m -a a b` and `-c -r a b` create `b`). The letters of a short-option word are read from left to
     right, and at the first letter that takes a value (`u`, and `t`, whose tracking mode is the rest of its word) the rest of the
     word is that value (`-tdirect b main` creates `b`, `-uorigin/main` sets an upstream). `git branch` creates nothing
     when it does not rename or copy and a short-option word holds `d`, `D`, `l`, `r`, `a` or `u` before any other letter
     that takes a value (`-d`, `-df`, `-Dr`, `-rd`, `-fd`, `-qd`, `-vd`, `-vvd`, `-vu <upstream>`, `-lr`), or a long option
     lists, deletes or sets an upstream (`--delete`, `--list`, `--show-current`, `--contains`, `--merged`, `--no-merged`,
     `--unset-upstream`, `--points-at`, `--edit-description`, `--set-upstream-to`); a word that holds only
     letters that take no value and are none of these (`-f`, `-q`, `-v`) leaves the invocation a creation. The creating long options of `git switch` (`--create`,
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
     word), and the words after `git bisect run`. A ref under `refs/heads/` names a branch whatever the case of `refs` and `heads`
     (`refs/HEADS/x`, `REFS/heads/x`, `Refs/Heads/x`), on every platform, because the case-insensitive file systems of
     Windows and macOS store such a ref as the branch. One pattern of ASCII letters reads it, shared by the host hook
     and the git-layer hook (a letter outside ASCII is no part of it: `refs/headſ/x` is no branch), for `git
     update-ref`, `git symbolic-ref`, the destination of a fetch, pull or push refspec and an `update-ref --stdin`
     instruction. The destination of a refspec is read on its raw text: `refs/heads/<name>` (in any case) names the
     branch `<name>` even when `<name>` begins with `refs/` (`HEAD:refs/heads/refs/x` creates `refs/x`), any other
     destination that begins with `refs/` is a non-branch ref (`refs/tags/t`, `refs/refs/x`, `refs/notes/x`) that
     creates no branch, and a bare destination is a branch. A push refspec with an empty source (`:refs/heads/x`,
     `+:x`) deletes its destination and creates nothing; a fetch or pull refspec with an empty source reads it as `HEAD`
     and creates the destination. A name is dropped from a record only when git certainly refuses it: an ASCII space or
     control character, `~`, `^`, `:`, `?`, `*`, `[`, `\`, `..`, a leading or trailing `/`, a `.lock` suffix.
     Whitespace and letters outside ASCII (U+00A0, U+2003, U+3000, U+0085) belong to a name git accepts. A leading dash
     refuses a name for `git branch`, `git switch`, `git checkout`, `git worktree add -b` and `git stash branch` (git
     reads it as an option or refuses it), but not for `update-ref`, `symbolic-ref`, `fetch`, `pull` and `push`, whose
     operand is a full ref (`refs/heads/-x`, `main:-x`): those names are creations. `git update-ref` reads its options
     as git does: `-m` takes the rest of its word, or else the next word, as its value (`-m -d` writes the message
     `-d` and deletes nothing), a short-option word deletes when it holds `d` before any `m` (`-d`, `-zd`, `-dm <msg>`),
     `--stdin` is also written as a unique prefix (`--s`, `--std`), and the first positional word is the ref it
     writes. A first positional word that is dynamic (`$ref`, `"$REF"`, `${R}`, `$(..)`) and may name a branch makes
     the creation dynamic, as every other creating verb does with a dynamic name; only a word that begins with a
     literal `refs/` namespace other than `heads` (`refs/tags/$T`) names no branch. Behind `xargs` the words that the
     input supplies may stand in any position, so there every positional word that is not a literal ref outside
     `refs/heads/` or `HEAD` makes the creation dynamic (`xargs -I{} git update-ref {} HEAD`). A delete never creates.
     `git symbolic-ref` reads `-m` the same way (it takes the rest of its word, or else the next word, as the reason;
     `-qm <reason>` too) and `--` ends its options, so `git symbolic-ref -m why HEAD refs/heads/z` creates `z`.
     `git symbolic-ref HEAD <target>` creates the branch a target under `refs/heads/` names, and `git symbolic-ref
     refs/heads/<name> <target>` creates `<name>`; with two positional words, a first word that is dynamic and may name
     a branch, or `HEAD` followed by a dynamic target that may name one (`git symbolic-ref HEAD $B`), is a dynamic
     creation. Aliases: when any git invocation of the line names a subcommand that is not a built-in git
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
     input the hook cannot see counts as a dynamic creation. The instructions of an `update-ref --stdin` are read only
     from the sources of that invocation that the hook can see, as the words the shell hands over (quotes removed,
     `printf 'update refs/heads/main''x HEAD'` is `update refs/heads/mainx HEAD`): a here-string (`<<< word`,
     `<<<word`); the bodies of the here-documents of the line (`<<EOF`); and, when a pipe feeds the invocation, the
     words of the command directly before the pipe if that is `echo`, `printf`, `Write-Output` or `Write-Host`, joined
     with spaces (also a single string word that holds a blank, the text a PowerShell string expression writes), or a
     `cat` whose only operands are here-documents or here-strings. Every other source is unreadable and makes the
     creation dynamic: a `<` redirect (`< file`, `<file`, `0< file`, `<&3`, `< <(..)`, also glued to the option:
     `--stdin<file`), a pipe from any other command (`cat file |`), from a group, a loop or a substitution, and no input
     at all. A readable source that holds an expansion is unreadable as well: a word with `$`, a backtick, `%`, `(` or
     `)` (a `printf` format with `%s`), a here-document body with `$` or a backtick. The text that remains is accounted
     for by plainly read names, or the record is dynamic. At least one instruction word (`create`, `update`, `delete`,
     `verify`, `option`, `start`, `prepare`, `commit`, `abort`, also the end of `symref-create` and `symref-update`)
     must stand in it. Every backslash must begin one of the separators `printf` writes (`\n`, `\t`, `\r`, and `\0` not
     followed by an octal digit: `printf 'create refs/heads/x\0HEAD\0'` creates `x`); any other escape (`\x62`,
     `\142`, `\\`) lets `printf` or `echo -e` write another text. Every `create` and `update` word (a verb ends at a
     character that is no letter, digit, `_` or `-`, so `refs/heads/update-docs` holds none) must be followed by blanks
     and one of: `refs/heads/<name>`, in any case of `refs` and `heads`, whose non-empty name git accepts and ends at a
     blank, a newline, the end of the text or one of those separators, which creates `<name>`; a literal ref outside
     `refs/heads/` (`refs/tags/v1`, `refs/notes/x`); `HEAD` or another pseudo-ref of capital letters and underscores.
     Anything else is not plainly read and makes the record dynamic: a quote (a C-quoted name `update "refs/heads/q"
     HEAD`), `$`, `%`, a brace or parenthesis, a backslash, an empty name, a name git refuses, a word that is no ref.
     So a verb, a prefix or a name written with escapes or `printf` formats, and a name that a quote continues, never
     pass as a plain name, and no other verb counts for one that is not plainly read. A git invocation the walk cannot
     name, `$g update-ref --stdin` (a dynamic or `git` program word in command position, behind prefix assignments and
     wrappers written with or without a path, then git's global options, then `update-ref`, and a `--stdin` word after
     it; also the program `git-update-ref` with a `--stdin` word), is read in the same way in every directory and
     redirect state of the line. A command that only mentions `update-ref --stdin` and an instruction (a commit message, an `echo` operand,
     a `git grep` pattern, a here-document written to a file, documentation) runs no `update-ref` and is not read.
     `popd` and `Pop-Location` return to the directory the
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
5. **Host hook entry.** `hook <claude|codex|hermes> pre-tool` reads one PreToolUse payload from stdin and prints
   `{}` (allow), one deny object that carries the full conflict message, or, for exactly one direct invocation of a
   user-only guard subcommand, the ask or allow of part 9 in Claude Code and, when the MAGOS Hermes plugin runs it
   (`--hermes-gate`), the modify and approve of part 9 in Hermes; the Codex hook's denial of a user-only command names
   the MCP route of part 10. The hooked tools are named in one constant:
   the shell tools `Bash`, `PowerShell`, `Monitor`, `terminal`, `shell` and `local_shell`; the worktree-creating tools
   (`EnterWorktree`, `Agent`, `Task` and `Workflow` with worktree isolation); the MCP session tools, whose name contains
   `start_session`, `worktree`, `branch` or `hand_off_to_session`; and the names and substrings that route an MCP tool
   that may run a command, in this order: `run_in_terminal`, `terminal`, `shell`, `exec_command`, `execute_command`,
   `start_process`, `command`, `run_command`, `exec`, `execute`, `process`, `bash`, `powershell` and `cmd`. Every hooked
   tool and every MCP tool whose `tool_input.command` is a string is inspected as a command line. An argv list from
   Codex is turned into one command line: when its program is a shell (`bash`, `sh`, `zsh`, `dash`, `ksh`,
   `powershell`, `pwsh`, `cmd`) and it carries a script after `-c`, `-Command`, `-CommandWithArgs`, `-EncodedCommand`
   or `/c` (in every spelling the shell reads), that script, read in that shell's dialect (the words after a PowerShell
   or cmd option are joined with spaces into the text it runs, an encoded value is decoded, and one that does not
   decode counts as a dynamic creation); otherwise its words joined with POSIX quoting (a word holding a space, a quote, a backslash or a
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
   and a HEAD set to such a ref (an unborn or orphan branch), with `refs` and `heads` matched in any case (`refs/HEADS/x`
   and `REFS/heads/x` are the branch `x` on a case-insensitive file system; elsewhere they need a claim for `x` as well;
   the arms are written from the same pattern the host hook reads). A branch
   rename or copy (`git branch -m/-M/-c/-C`) writes the new ref outside a reference transaction, so the git layer does
   not see it; the host hook denies it in every option spelling (bundled short options and abbreviated long options
   included).
7. **Version, installer and doctor.** `GUARD_VERSION` is the single version constant of the guard (1.0.9) and equals
   the package version. `version` reports the running guard; `install` keeps the user-level copy that the Codex hook
   (and the Hermes hook when it cannot run the Hermes plugin's own launcher) runs, records where the copy came from in
   `VERSION.json` on every install and appends to `<guard home>/audit.log`; `doctor` checks the interpreter, Git, the
   copy, the Hermes entry, the Hermes route, the MCP approval server, the Codex entry and the plugin's `mcp.json`,
   the repository, the backstop, the sets and the approval level.
8. **Sets.** `set-plan`, `set-show`, `set-update` and `set-release` register, read, update and retire a set: one task
   divided into lanes with exclusive file ownership, merged back as one whole. They reuse the manifest engine for the
   disjointness proof, the evidence gatherer and the judge for the comparison with every other claimant, the claim store
   for the lane claims and the claim lock for every write, and add the set record, the revision compare-and-swap and the
   lane state machine. A set also states what the task asks for and what each lane delivers: the requirements of the
   task, the requirements every lane serves and its outcome (the guard proves that every requirement is served and
   every lane serves one), names that show the topic of the change (a lane id that is a topic slug, the branch
   `agent/<set>/<id>` and a worktree directory ending with `-<set>-<id>`), and, when a lane is recorded `integrated`, an
   objective summary of what it changed computed from git. The section Sets (version 1.0.4) states them.
9. **Approval.** The user-only subcommands (`override`, `arm`, `disarm`, `install`) run after the user's approval: in a
   real terminal on every host, or, in Claude Code, by a click in Claude Code's own permission dialog. The host hook
   opens that dialog for exactly one direct invocation of this guard and hands the host a rewritten command that
   carries a one-time token, which the command verifies and consumes instead of asking the console. The repository's
   `magos.approval` sets the level. The section Approval (version 1.0.7) states it. In Hermes the MAGOS Hermes plugin
   runs the guard and Hermes asks the same question in its own approval prompt; the section Hermes approval (version
   1.0.8) states it. The section Approval routes (version 1.0.8) compares the routes of the three hosts.
10. **MCP approval server.** `mcp` is an MCP server over stdio that the host starts (Codex, from the root `mcp.json`
    of the MAGOS plugin or from its own configuration); no tool command may start it. Its one tool, `magos_approve`,
    asks the user in the host's own dialog (MCP elicitation) to approve one user-only command, then records the
    approval of part 9 and runs this guard's command with it in its own process. The section Codex approval (version
    1.0.8) states it.

## Dependencies

Upstream: Python 3.9+ standard library only (`argparse`, `base64`, `collections`, `contextlib`, `functools`, `getpass`,
`hashlib`, `io`, `json`, `os`, `queue`, `re`, `secrets`, `shlex`, `shutil`, `subprocess`, `sys`, `threading`, `time`,
`unicodedata`, `concurrent.futures`, `msvcrt` or
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
- Codex starts `mcp`, the MCP approval server, from the root `mcp.json` of the MAGOS plugin or from the
  `[mcp_servers.magos]` entry that `install --host codex` prints, and the agent calls its tool `magos_approve` (Codex
  approval (version 1.0.8)). `mcp.json` is an Agent Plugins MCP file (schema 1.0.0) with one stdio server, `magos`:
  `type` `stdio`, `command` `git`, `args` `-c`, `alias.magos-mcp=!<sh script>` and `magos-mcp`, and `cwd` `./`, the
  plugin root. Git runs the alias with its own `sh`, on Windows as well. The script returns to the plugin root through
  `GIT_PREFIX`, exports `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1` and `NoDefaultCurrentDirectoryInExePath=1`, and
  runs `scripts/magos_guard.py mcp` with `-X utf8 -B` under the first of `python3`, `py -3` and `python` that is
  Python 3.9 or later (each probed with all its output discarded); without one it prints `MAGOS guard: no Python 3.9
  or later found (tried python3, py -3, python)` on stderr and exits 127. Only the guard writes to stdout. Codex
  accepts only the keys `type`, `command`, `args`, `env` and `cwd` in this file and drops a server that holds any
  other, so the file names neither `env_vars` nor a timeout: Codex sets `PLUGIN_ROOT` and `PLUGIN_DATA` for the
  server, allows it 30 s to start and ends a tool call after 300 s (Codex 0.163). The Git runner's scrubbed
  environment (part 2) removes the `GIT_CONFIG_PARAMETERS` and `GIT_PREFIX` that the launch leaves. Claude Code does
  not read the file, and Hermes reads an `mcp.json` only for a plugin without `plugin.yaml`; MAGOS ships
  `plugin.yaml`, so Hermes never starts the server.
- The MAGOS Hermes plugin entry (`__init__.py`) registers, besides the skills, two `pre_tool_call` callbacks for the
  Hermes `terminal` tool. They run the plugin's own guard as `hook hermes pre-tool --hermes-gate <ask|bypass|absent>`
  without a shell (Hermes approval (version 1.0.8)). The Hermes entry under `hooks:` runs `hook hermes pre-tool`
  without that option and denies every user-only command.
- `references/lane-split.md` and `SKILL.md` tell agents to run `check`, `plan`, `list` and `release`, and, for sets,
  `set-plan`, `set-show`, `set-update` and `set-release`; `version` is read-only and agents may run it as well.
- `/GitIntegrate`, `/GitRecon`, `/GitCleanup`, `/GitConverge` and `/GitSweep` read or release claims through `list` and
  `release` as `references/commands.md` describes; the read-only commands never write claims.
- `/GitPlan` (`references/commands.md` section 8, `commands/GitPlan.md`, `skills/git-plan/`) checks that `version` is
  at least 1.0.4, registers a set with `set-plan`, reads it with `set-show`, records the state of the lanes with
  `set-update` and retires the set with `set-release`; its read-only forms (the plan and amend previews, `--status` and
  `--converge` without `--apply`) call only `version`, `list`, `set-show` and `set-plan --dry-run`, which never write.
  The tables of requirements, outcomes and lanes that it prints, and the changes it prints after the merge, are
  rendered from the JSON of `set-plan --dry-run`, `set-plan` and `set-show` (the requirements and lanes of the record and
  the `changes` of every integrated lane), never from memory.
- Package manifests: `plugin.json`, `.claude-plugin/plugin.json`, `plugin.yaml`, `SKILL.md` (`metadata.version`),
  `skills/git-orchestrator/SKILL.md` (when it states a version) and line 3 of `references/commands.md` carry the same
  version as `GUARD_VERSION`; a contract test reads all of them. `__init__.py` registers the skills and the two Hermes
  `pre_tool_call` callbacks (Hermes approval (version 1.0.8)).
  `scripts/sync_hosts.py` copies `SKILL.md`, `references/*.md` and the skill adapters, never the guard, so `install`
  copies the guard to `~/.magos/guard/` for the hosts that run it outside the plugin directory.

## Public Contract

Invocation: `py -3 -X utf8 -B scripts/magos_guard.py <command> [options]` (`python3` on POSIX). Global options anywhere:
`--repo DIR` (default cwd), `--lang zh|en` (default `zh`, environment `MAGOS_LANG`), `--json`. Options are never
abbreviated (every parser is built with `allow_abbrev=False`), so `--rep` is a usage error. Input is read as bytes
(UTF-8, BOM tolerated); output is UTF-8.

Commands an agent may run: `check`, `plan`, `list`, `release`, `doctor`, `version`, `set-plan`, `set-show`,
`set-update`, `set-release`. Commands only the user runs:
`override`, `arm`, `disarm`, `install`: the user runs them in a real terminal or approves them by a click: in Claude Code
in Claude Code's own dialog (Approval (version 1.0.7)), in Codex in Codex's own dialog through the MCP tool
`magos_approve` (Codex approval (version 1.0.8)), and in Hermes with the MAGOS Hermes plugin in Hermes's own approval
prompt (Hermes approval (version 1.0.8)). Only the host starts the hidden `mcp`, the MCP approval server; a tool command
never does. The set subcommands are not user-only: the host hook lets them through like
`plan`, `release` and `list` (Sets, Hook). The host hook recognises a user-only command whatever the global options before
it look like. A guard word is a word ending in `magos_guard` or `magos_guard.py`, or a word whose case-folded base name
(after the last `/` or `\`) is `run-guard.cmd` or `run-guard`, after which a leading `--strict` is skipped. After the
guard word the hook skips a `--opt=value` word, a prefix of `--repo` or `--lang` together with its value, a prefix of
`--json`, and a `--` (the end of the options; from Python 3.13 on argparse takes the word after it as the subcommand),
and tests the first remaining word. The guard word is found wherever it stands in a command, so wrappers that start it
in a new console or process (`start`, `cmd /c start`, `Start-Process` and its alias `saps`, `conhost.exe`, `wt`) hide
nothing, and the text of a child shell is read as well. Every word is also cut at PowerShell's comma, which separates
the elements of an array that a native command and `Start-Process` receive as separate arguments: a guard piece and
the pieces and words after it are read as the guard word and its arguments (`Start-Process py <guard>,disarm`,
`-ArgumentList '<guard>','disarm'`, `<guard>, disarm`, `<guard> ,disarm`, `py '<guard>','disarm'`). A piece loses a
`.Name(...)` method call at its end that holds no `/` or `\` (`"<guard>,disarm".Split(',')`) and every `@`, `(` and `)`
at its ends (`@('<guard>','disarm')`, `('<guard>') disarm`); an empty piece (a lone comma, a comma that starts or ends a
word) is no word. A command without a guard word is not affected by the cut (`git commit -m "a, b"`, `echo a,b`, a path
that holds a comma).

- `check --branch B (--paths P... | --manifest FILE|-) [--target T]`: read-only verdict, no lock, writes nothing.
- `plan --branch B (--paths P... | --manifest FILE|-) [--worktree PATH] [--amend]`: judges against the resolved
  integration target (the one creation is checked against) and gathers evidence outside the lock, takes the lock,
  re-reads the claims, checks the branch name again against them, judges, writes `claims/B.claim` atomically and appends
  an audit line. Identical entries are a no-op (exit 0), except for the re-plan that consumes an override record, which
  writes the claim with the override (`override`). Different entries need `--amend` (exit 14 otherwise); an amend
  is judged with the lane's own claim excluded, and a removal-only amend skips the overlap check. A branch that already
  exists with no open claim is refused (exit 15). A `--worktree` value that contains a control character is refused
  (exit 12). Without `--worktree` the written claim keeps the worktree path the existing claim registers (a new claim
  registers none). A branch of a set is a branch whose claim carries `set=<name>` of a set that has a record, and a
  branch that a record names, compared folded, as the branch of one of its lanes or as its integration branch, whatever
  its claim says (missing, without a `set=` line, or naming a set that has no record); of a record that cannot be read
  (`SET_UNREADABLE`, `SET_NEWER_FORMAT`) only the integration branch `agent/<set>/integration` is known, so its lanes
  count only through the `set=` line of their claims. A claim of a newer format on such a branch is the claim gate's:
  `plan` reports UNKNOWN `CLAIM_NEWER_FORMAT` (exit 11), as for any branch, before the set gate is asked. For a branch
  of a set, identical entries without an override
  record are still a no-op (its creation command names the path the claim stores, whatever spelling `--worktree` was
  typed in), and every `plan` that would write its claim (a new claim, other entries or another
  `--worktree`, with or without `--amend`, and the re-plan that would store an override) is refused with exit 14 and
  the message that names the set (`lane_in_set`), before the test for an existing branch (exit 15), the override
  record left unconsumed, because the claims of a set are written only by `set-plan` (`set-plan --amend` writes a
  missing or set-less claim of the record again: Sets, set-plan step 8). On success it prints the creation command
  with the worktree path the claim registers, absolute with `/` separators as `plan` writes it, which the host hook
  compares with the path of the creation (`<path>` when the claim registers none), for example
  `git worktree add "C:/work/app-one" -b <B> <target>`; the path is no key of the `--json` verdict.
- `list [--drift] [--json]`: each claim as `planned` (no branch yet), `active` (unmerged work, a workspace, or a fresh
  branch at the target tip or the plan's base) or `idle` (integrated: merged, moved beyond the plan's base and the target
  tip, no worktree). An idle claim stops blocking other lanes. `--drift` reports files in the lane's footprint matched
  by none of its entries; it never denies. Claims the guard cannot use are listed as well: `unreadable claims/<file>`
  for a file that does not parse and `newer-format <branch> (v=N): upgrade this guard` for a claim of a newer format
  (`claims/<file>` in place of the branch when the claim has no `branch` line); `--json` gives them as rows with state
  `unreadable` (with `path`) or `newer-format` (with `branch`, `v` and `path`). A claim that carries `set=` shows its
  set and lane (text ` set <name>/<lane>` after the state, ` set <name>/integration` for the integration claim; JSON
  fields `set`, `lane` and, for the integration claim, `role` `integration` with `lane` null); the rows of every other
  claim are unchanged. The state of an integration claim is computed like that of every claim and is information only,
  because the claim blocks nothing; `--drift` skips it, because it claims no files (Sets, Integration claim).
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
  file for the user to inspect. A claim that carries `set=<name>` of a set that has a record (a lane or the
  integration claim of that set) is refused with exit 16 and the message that names the set (`blocked_set`): the
  claims of a set are released only by `set-release`; the claim of a set that has no record (a registration that was
  interrupted) is released like any other.
- `override --fingerprint FP --reason R [--approval TOKEN]`: exits 2 unless FP is the 12 lowercase hex digits a denial
  prints; then, without `--approval`, refuses (exit 17) unless stdin and stdout are a real console and the user retypes
  the fingerprint, and with `--approval` verifies and consumes the token instead (exit 25 to 28 when it does not
  verify; Approval (version 1.0.7)); writes a one-shot record valid for one hour (`fp`, `reason`, `by`, `at`,
  `expires`, `via`, `reason_by`) and appends an audit line (`ts`, `by`, `op` `override`, `fingerprint`, `reason`,
  `reason_by`, `via`, `host` `cli`, `tool_use_id` for a run approved with a token (null through the MCP approval
  server), and `route` for one approved through the MCP approval server (`mcp`, with `client`) or in Hermes
  (`hermes`)). Only `plan` reads override
  records: the next `plan` whose denial has the same fingerprint consumes the
  record and stores the fingerprint in the claim's `override` field. The host hook honours only that field, so a re-plan
  is required after an override, and the deny text says so. A lane of a set that has a record is not overridden this
  way: its re-plan is refused (exit 14, `lane_in_set`; see `plan`) and leaves the record unconsumed.
- `hook <host> pre-tool`: the PreToolUse entry; it also guards `git worktree add --detach` and `<path> <commit>`, whose
  lane is keyed `detached/<directory name>`. Allow is `{}` with exit 0. For a user-only subcommand the Claude Code hook
  (`hook claude`) answers with the ask or allow of Approval (version 1.0.7), or denies; the Codex hook denies it with
  the text that names the MCP tool `magos_approve`, its exact arguments and the command for a real terminal (Codex
  approval (version 1.0.8)); the Hermes hook that the MAGOS Hermes plugin runs (`hook hermes pre-tool --hermes-gate
  <gate>`) answers with the modify and approve of Hermes approval (version 1.0.8), or denies, and the Hermes entry under
  `hooks:` denies it. Every hook denies a command that starts `mcp` with the `protected_mcp` text, and a command that
  runs this guard with a subcommand that is no plain word an agent may run (`hook` among them) with the
  `protected_slot` text, and a command whose text nested deeper than three levels names MAGOS with the `protected_deep`
  text (Approval routes (version 1.0.8), The subcommand of a guard run). Deny is exactly one
  ASCII-escaped JSON object on
  stdout, exit 0:
  `{"decision":"block","reason":MSG,"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":MSG}}`.
  A deny is never an exit code. Stderr stays empty except for one warning line when engagement could not be decided
  (Invariant 3) and the warning of an internal error on a call whose payload matches none of the prefilter words
  (Invariant 8). An auto-named creation (a tool that names the branch or worktree itself) is denied `UNPLANNABLE` with
  the instruction to plan the branch `worktree-<name>` first and then call `EnterWorktree name=<name>`, or to run
  `git worktree add` directly; `EnterWorktree name=N` creates the branch `worktree-N`.
- `mcp [--lang L]`: the MCP approval server (Codex approval (version 1.0.8)), started by the host and hidden from the
  help. It reads JSON-RPC 2.0 from stdin and writes it to stdout, asks for every approval in the host's dialog, and on
  Accept runs the approved user-only command in its own process with a one-time token. Exit 0 when stdin ends, 1 when
  stdout cannot be written or the server fails outside a request.
- `arm [--lang L] [--dry-run] [--approval TOKEN]`: needs a real console or an approval token that verifies (exit 17
  without either, except with `--dry-run`; Approval (version 1.0.7)). Writes
  `<hooks dir>/reference-transaction` (a foreign hook is chained as `.magos-prev`; the backstop runs it, with the
  transaction on its stdin, only when it is executable, as git runs only executable hooks), `<store>/ARMED`, `lang` and `guard`,
  and appends an audit line (`ts`, `by`, `op` `arm`, `lang`, `via`, `tool_use_id` for a run approved with a token (null through the MCP approval server), and `route` for one approved through the MCP approval server (`mcp`, with `client`) or in Hermes (`hermes`)) to `<store>/audit.log`. `guard` holds the command the backstop's deny message
  prints: the command that runs the copy under the guard home (`~/.magos` or `MAGOS_HOME`) when that copy exists and
  declares the same `GUARD_VERSION` as the running guard, else the running script. Before it sets
  `maintenance.pack-refs.enabled` and `gc.packRefs` to `false` for the repository, it records their previous local
  values (or that they were unset) in `<store>/arm-config.json`; an existing record is kept, so a re-run never records
  its own `false`. A repository armed by 1.0.0 or 1.0.1 has no record and already holds `false`, so re-arming it records
  `false` and `disarm` leaves both keys `false`; the documentation gives the commands that restore them
  (`git config --local --unset gc.packRefs` and `git config --local --unset maintenance.pack-refs.enabled`). It can be
  re-run over its own hook. Refuses (exit 3, checked before the console) when `core.hooksPath` is set, hook directories
  differ across worktrees, or `.magos-prev` already exists next to a hook that is not MAGOS's. Idempotent.
- `disarm [--dry-run] [--approval TOKEN]`: needs a real console or an approval token that verifies, except with
  `--dry-run` (exit 17 otherwise; Approval (version 1.0.7)); removes `ARMED`, deletes the
  hook if it is MAGOS's and restores `.magos-prev`; restores both settings from `arm-config.json` (unsetting a key that
  was unset) and deletes the record; without a record both settings stay as they are, and a record that does not parse
  leaves both settings and the record as they are; keeps claims and audit, and appends an audit line (`ts`, `by`, `op`
  `disarm`, `via`, `tool_use_id` for a run approved with a token (null through the MCP approval server), and `route`
  for one approved through the MCP approval server (`mcp`, with `client`) or in Hermes (`hermes`)).
- Console gate. The gate of `override`, `arm`, `disarm` and `install` refuses a call whose stdin and stdout are not a
  console, unless the call carries `--approval` with a token that verifies (Approval (version 1.0.7)): such a call never
  asks the console, and a token that does not verify ends it with exit 25 to 28. A command started in a new console
  window (`start`, `Start-Process`) passes the console gate, so the gate, like an
  override, is not access control; what keeps agents from running the user-only commands is the host hook's recognition
  of them and the launcher's refusal of every subcommand but `hook`.
- `install --host claude|codex|hermes [--dry-run] [--home DIR] [--allow-downgrade] [--approval TOKEN]`: needs a real
  console or an approval token that verifies, except with `--dry-run` (exit 17 otherwise; Approval (version 1.0.7)),
  checked after the guard-home check below. On Windows it refuses (exit 2, nothing written) when the path of the copied launcher
  (`<home>/guard/hooks/run-guard.cmd`) contains a character that cmd.exe reads as an operator, a separator or an
  expansion when it starts the launcher and runs the interpreter through `call` (`&`, `(`, `)`, `^`, `%`, `;`, `,`,
  `=`); the message names the character and the path and asks for a guard home without it (`--home` or `MAGOS_HOME`).
  It compares `scripts/magos_guard.py` and `hooks/run-guard.cmd` with the copies in
  `<home or ~/.magos>/guard/{scripts,hooks}/`. The guard home is the absolute path of `--home`, else `MAGOS_HOME`, else
  `~/.magos`, written with `/` on Windows, where a backslash is a separator; on POSIX a backslash is a character of a
  file name and stays (the generated entries quote such a path for sh and TOML). When both copies are byte-identical to the sources it prints
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
  `install`, `host`, `from`, `to`, `source`, `via`, `tool_use_id` for a run approved with a token (null through the MCP approval server), and `route` for one approved through the MCP approval server (`mcp`, with `client`) or in Hermes (`hermes`)) to `<home>/audit.log`. `--dry-run` prints what it would copy and the snippet
  and writes nothing. It writes the exact host snippet to `guard/generated/<host>.json|yaml` and prints it; with
  `--host codex` it also writes `guard/generated/codex-mcp.toml`, the `[mcp_servers.magos]` entry of the MCP approval
  server, and prints it with the `codex mcp add` line (Codex approval (version 1.0.8)).
  It never edits `~/.claude/settings.json`, `~/.codex/hooks.json` or Hermes config, nor the Codex configuration file the user
  merges the printed MCP entry into. The Codex snippet matches
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
  character and the path. For `--host hermes` install also prints one `NOTE:` line on the Hermes route (Hermes approval
  (version 1.0.8)): when the Hermes plugin runs the guard of this version, that the plugin asks in Hermes's approval
  prompt and that a MAGOS entry under `hooks:` would deny every user-only command before Hermes can ask; otherwise that
  the entry runs the guard once Hermes has approved it (an entry that is not approved is skipped without a word) and
  user-only commands run in the user's own terminal, and how the plugin is installed or updated. Only Claude's
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
  running guard's. It then prints the Codex lines of Codex approval (version 1.0.8): the approval server's answer to an
  in-process `initialize` and `tools/list`, the entry that `install --host codex` generated, and the sha256 of the
  plugin's `mcp.json` beside the running guard; and, when the Hermes home is a directory, the Hermes route, entry and
  approvals lines of Hermes approval (version 1.0.8). Outside a repository it then reports that the guard is inert there and prints `approval: prompt (no
  repository): ...`. In a repository it prints the approval line of Approval (version 1.0.7) after the repository line,
  a problem when `magos.approval` holds a value that is no level, and checks mode,
  hook uniformity, hook content, claim parsing (unreadable and newer-format claims), orphan claims, the sets (the
  `sets:` line and the set problems of Sets, Hook, list, doctor and the plain commands), `core.hooksPath` and
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
- `set-plan --set NAME --target BRANCH --spec FILE|- [--dry-run] [--amend --expect-revision N]`: validates a set spec
  (the requirements, the coverage of every requirement by a lane, the topic names of lane ids, branches and worktrees)
  and, unless `--dry-run`, registers the lane claims, the integration claim and the set record as one operation under
  the lock (Sets, set-plan). Exit 0 registered, previewed or unchanged; 2 usage; 10 overlap or conflict; 11 unknown;
  12 name or worktree clash with the repository; 13 lock; 14, 15 lane or branch exists; 16 amend refused; 19 stale;
  20 set exists; 21 set unknown (`--amend`); 23 newer format; 24 invalid spec.
- `set-show --set NAME [--drift]`: read-only, no lock; prints the record and the derived view (Sets, set-show). Exit 0;
  2 usage; 11, 21, 23 as above; 24 an invalid `--set`. `--json` carries the requirements of the set and the `changes` of
  every lane.
- `set-update --set NAME --expect-revision N --lane ID --state active|ready|integrated|blocked [--head SHA] [--note
  TEXT] [--integration BRANCH]`: one lane transition under the lock with a revision compare-and-swap (Sets,
  set-update); `--state integrated` also stores the summary of what the lane changed (Sets, The changes summary). Exit 0;
  2 usage; 11 (also a missing target branch or a failed Git call of that summary); 13; 16 refused by the repository state
  (also no common history for the summary); 19 stale; 21; 22 OUT_OF_LANE; 23; 24.
- `set-release --set NAME [--reason R] [--abandon]`: retires a set and releases its claims (Sets, set-release). Exit 0;
  2 usage; 11; 13; 16 blocked; 21; 23; 24 an invalid `--set` or an invalid `--reason` (more than 200 characters, a
  lone surrogate or a control character).

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

Exit codes: 0 allow, registered, ok or unchanged, and the end of `mcp`'s input; 1 `doctor` found a problem, a usage
error of `hook` (a failure the launcher maps, never a deny), or `mcp` could not write to the host or failed outside a
request; 2 usage error of any other command, not a git repository, a malformed fingerprint, or a
guard home whose launcher path `install` refuses on Windows; 3 arm refused; 10 CONFLICT, NO_MANIFEST, UNPLANNABLE,
UNPARSEABLE or PROTECTED; 11 UNKNOWN (also any engine exception, an exhausted budget, a claim in a newer format, a set
record that cannot be read or a failed install: plan and check fail closed); 12 INVALID_MANIFEST (also an invalid
branch name or a `--worktree` with a control character, and for `set-plan` a branch name or worktree path that clashes
with the repository); 13 LOCK_TIMEOUT (30 s); 14 LANE_EXISTS; 15 BRANCH_EXISTS; 16 BLOCKED (`release`, `set-release`,
and the refusals of `set-update` and `set-plan --amend` that the repository state causes);
17 CONSOLE_REQUIRED (`override`, `arm`, `disarm`, `install`); 18 DOWNGRADE_REFUSED (`install`); 19 STALE (the plan or
the revision a set command was made against is not the current one); 20 SET_EXISTS; 21 SET_UNKNOWN; 22 OUT_OF_LANE
(`set-update --state ready` with files outside the lane's manifest); 23 SET_NEWER_FORMAT (a set record of a newer
format); 24 INVALID_SPEC (a spec or option value that is invalid in itself; the message names the field); 25
APPROVAL_UNKNOWN, 26 APPROVAL_EXPIRED, 27 APPROVAL_USED and 28 APPROVAL_MISMATCH (`override`, `arm`, `disarm` and
`install` with an `--approval` token that does not verify; Approval (version 1.0.7)). The
launcher's refusal of a subcommand other than `hook` is its own exit 2; the guard is not started.

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
compared case- and separator-insensitively where the platform is. The claims of a set carry the additive keys
`set=<name>` and `lane=<id>` (the integration claim `set=<name>` and `role=integration`) after the standard keys: they
are kept in the claim's `extra` list, not in `CLAIM_KEYS`, so claims without a set are byte-identical to those of
1.0.3, the format stays `CLAIM_FORMAT = 1`, and a guard of 1.0.3 reads and writes these claims like any claim with
keys it does not know. Only `set-plan` writes `role=integration`; `plan` writes no extra key, and `role=integration`
is read only as one part of the shape of the integration claim (Sets, Integration claim), so the key alone exempts
nothing. Store layout:
`<git-common-dir>/magos/{ARMED,lang,guard,arm-config.json,claims/,sets/,override/,approvals/,denials/,audit.log,lock}`;
the guard home holds `guard/{scripts,hooks,generated}/`, `guard/VERSION.json`, `approvals/` and `audit.log`.

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
   in `plan`, `check`, `set-plan`, an armed repository and for a named worktree. The one creation no unknown of the
   judgement denies is that of the branch of an integration claim, which is judged for the branch name and the claim
   only (Sets, Integration claim): an uncertain target, an unreadable claim elsewhere and the cap of unmerged branches do
   not deny it, and only a Git failure of its name check fails closed. In auto mode a snapshot that hides lanes (more
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
   against a manifest; the integration claim of a set takes part in none of them (Sets, Integration claim). Warnings
   never deny: inferred target, remote freshness, operation in progress, repository not armed.
5. The only writes are claim, set-record and audit files (under the lock), override records, the files `arm` (including
   `arm-config.json`), `disarm` and `install` (including `VERSION.json` and the generated snippet) print, the audit
   lines `arm` and `disarm` append to `<store>/audit.log` and `install` appends to `<guard home>/audit.log`, the
   approval records the Claude Code hook writes and a verifying command renames, and the denial records `plan` and the
   host hook write (Approval (version 1.0.7)), and the approval records the MCP approval server writes on an Accept
   (Codex approval (version 1.0.8)). `check`, `list`, `version` and `set-show` never write, every `--dry-run` writes
   nothing but the consumption of its `--approval` token, the host hook writes nothing but approval and denial records,
   and `mcp` writes nothing but approval records and what the command it runs writes; `set-plan`, `set-update` and `set-release`
   write only the claim and set-record files of their own set and an audit line, and never a branch, a ref, a worktree or
   the index.
6. Engagement: ARMED (marker file) guards every new branch and worktree; AUTO (default) always guards named worktree
   creation and guards branch-only or auto-named creation only when another lane exists; OFF
   (`git config --local magos.guard off`) silences the host hooks of that repository: its own creations, and a line the
   overflow rule refuses when it is the session directory's repository. Mode and engagement are read from the
   creation's own repository, so OFF never silences a creation judged in another repository. `MAGOS_GUARD=off` is read
   from the host process environment only; it silences the creation checks and the overflow rule everywhere.
7. Tamper protection is best-effort matching of words and common writer commands. User-only subcommands (whatever the
   spelling of the global options before them, `--` included, and whether the guard script or its launcher
   `run-guard.cmd` is named, also behind `start`, `cmd /c start` or `Start-Process`, and also as an element of a
   PowerShell comma or array list such as `Start-Process py <guard>,disarm`) and `git config magos.*` writes are
   denied by the host hook in every repository and outside any repository, and so is a git invocation that carries a
   word beginning with `magos.` beside an alias it defines with `-c alias.<name>=` or a subcommand that is not a
   built-in git command, because an alias can run `config`. `mcp`, the MCP approval server that only the host starts,
   is denied in the same spellings and places, on every host, with the `protected_mcp` text (Codex approval (version
   1.0.8)). A command that runs the guard with a subcommand the hook cannot read as one plain word of `AGENT_SUBS`
   (a dynamic word, a brace expansion or glob, `hook`, an empty slot, a word xargs feeds) is denied on every host with
   the `protected_slot` text, and a text nested deeper than three child shells, here-documents, quoted guard words or
   alias values that names MAGOS with the `protected_deep` text (Approval routes (version 1.0.8), The subcommand of a
   guard run). The value of a `-c alias.<name>=<value>` is read like the text of a child shell. The one exception is the ask or allow of the Claude Code
   hook for exactly one direct invocation of this guard (Approval (version 1.0.7)). A writer or a redirect aimed at an
   approval store (`.git/magos/approvals`, `.magos/approvals`, the absolute `<git-common-dir>/magos/approvals` or
   `<guard home>/approvals`) is denied in every repository and outside any repository. Edits of the guard's state are denied once
   the session directory's repository is armed or holds a claim: `core.hooksPath`, `GIT_CONFIG_*`, worktree config, and
   writers or redirects aimed at `.git/hooks`, `.git/refs`, `.git/HEAD`, `.git/config`, `packed-refs`, `.git/magos`
   (the claims, the set records under `.git/magos/sets` and every other file of the store),
   `.magos`, the absolute path of the session repository's `<git-common-dir>/magos` (in any separator or case spelling
   the platform folds), the absolute path of the guard home (`~/.magos` or `MAGOS_HOME`) and the Hermes plugin
   directory `<hermes home>/plugins/magos` when it holds a launcher. The writers include the PowerShell cmdlets
   `Rename-Item` (alias `rni`) and `Move-Item` (alias `mi`) and the `Remove-Item` alias `ri`, and the text of a child
   shell (`bash -c`, `sh -c`, the other POSIX shells' `-c`, `cmd /c` and `/k`, `powershell` and `pwsh` `-Command`,
   `-CommandWithArgs` and `-EncodedCommand` in every spelling the shell reads) is read with every check, to depth 3, as is a quoted word that names the guard script or its launcher (the
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

## Sets (version 1.0.4)

A set is one task divided into lanes (sub-agent worktrees), named by the topic of their change, that are merged back as one whole. `/GitPlan`
(`references/commands.md` section 8) investigates the repository and the code before any sub-agent starts, divides the
work with exclusive file ownership and registers the division through the four set subcommands; the guard proves every
rule that the spec and the repository allow it to prove, registers the claims of all lanes and the plan record as one
operation, and records the state of every lane afterwards. The plan lists the requirements of the task, the lanes that
serve each requirement and the outcome each lane delivers; the guard stores them with the plan and proves that every
requirement is served by a lane and that every lane serves a requirement, so the command can show them as tables. The
names show the topic of the change: a lane id is a topic slug, the lane branch is `agent/<set>/<id>` and the lane
worktree directory ends with `-<set>-<id>`, so `git branch` and `git worktree list` read as a list of topics. When a lane
is recorded `integrated` the guard stores, computed from git at that moment, a summary of what the lane changed
(`changes`), so the command can print the original list again with the result of the merge added to it. The plan is
optimistically locked: nobody holds a lock while working. Every change to a registered set compares a `revision` and
increments it, the plan carries the target tip it was made against (`base`), and a lane records the head it was marked
ready at. A stale plan is detected and refused, never overwritten. The guard changes no branch, ref, worktree or index
and runs no `merge`, `merge-tree`, `switch` or `worktree add`: the merging of the lanes is done by the command in the
user's repository, through the host hook like any other git command, and the guard checks and records. The set
subcommands run only subcommands of part 2, among them `rev-list` (the number of commits a lane is ahead of the plan's
base, and the non-merge commits of an integrated lane), `log` (the subjects of an integrated lane, and the files of the
target's commits in the drift view of `set-show`) and `diff` (the files of an integrated lane), and they run `worktree`
only as `worktree list`; `rev-list`, `log`, `diff` and `merge-base` are members of `LOCAL_GIT`, which holds no network
subcommand.

### Subcommands and shared rules

```
set-plan    --set NAME --target BRANCH --spec FILE|- [--dry-run] [--amend --expect-revision N]
set-show    --set NAME [--drift]
set-update  --set NAME --expect-revision N --lane ID --state active|ready|integrated|blocked
            [--head SHA] [--note TEXT] [--integration BRANCH]
set-release --set NAME [--reason R] [--abandon]
```

- Global options `--repo`, `--lang` and `--json` work anywhere, and options are never abbreviated, as for every
  subcommand. A directory that is not a git repository is exit 2.
- A set name is `[a-z0-9][a-z0-9-]{0,23}` and not one of the Windows device names `con`, `prn`, `aux`, `nul`, `com1` to
  `com9`, `lpt1` to `lpt9` (the record is the file `sets/<set>.json`, and a device name with any extension is a device on
  Windows); anything else is exit 24 with the field `--set` and the code `FORMAT`, whose text is an entry of the table
  `M` in the language of the call: `set_err_set_name` for a name that does not match the slug, `set_err_set_device` for
  a device name. A set name has the form of a lane id (the slug of Data model, Lane id rules, which names the topic of
  the task), and unlike a lane id it is not refused as an ordinal or generic name.
- The frame of an exit 24 (and of an exit 12) names what was refused. `set-plan` prints its exit 24 and exit 12 in the
  frame `set_invalid` (the set plan is invalid, nothing registered or created). `set-show`, `set-update` and `set-release`
  print every exit 24 of theirs (an invalid `--set`, an option value, an unknown `--lane`, a refused transition) in the
  neutral frame `set_invalid_args` (invalid arguments, nothing changed), which speaks of no plan: an invalid `--set`
  and an invalid `--head` or `--reason` of one call are lines of one denial, so the frame is the subcommand's and not
  the field's.
- None of the four is user-only (Public Contract). They run through the host hook like `plan`, `release` and `list`
  (Hook below).
- `set-plan` (without `--dry-run`), `set-update` and `set-release` take the claim `Lock` (exit 13 after 30 s) and read
  the repository, the claims and the record inside it; the budget of their git calls (18 s) starts when the lock is held,
  so a long wait for the lock does not shorten it. `set-show` and every `--dry-run` take no lock, create nothing (not
  even the store directory or the `lock` file, which the first locked call creates) and run on a budget that starts when
  the repository is opened.
- Every outcome prints one result on stdout: the message (text) or, with `--json`, one object with at least `decision`
  (`allow` or `deny`), `code`, `message` and `exit_code` that equals the exit code of the process. Stderr stays empty,
  except for a usage error (exit 2) and the generic Git-failure and internal-error lines of Errors (exit 11, with the
  deny object under `--json`). A set command that stops writes nothing: no claim, no record, no temporary file.
- Every write of a call is one transaction (Atomic write below). Every call that changes the store appends one audit
  line (the audit lines are listed under Compatibility, limits and cost); a refusal, a preview, `--dry-run` and
  `set-show` append none.

### Data model

**Spec** (the input of `set-plan`; JSON, UTF-8 with or without a BOM, or UTF-16 with a BOM as PowerShell 5.1 writes it,
decoded by `decode_manifest`; a file outside every worktree, or `-` for stdin):

```
{"v": 1, "title": str,
 "requirements": [{"id": rid, "text": str}],
 "base": "<full object name of the target tip>", "sheet": str, "notes": [str],
 "shared": [{"path": str, "owner": id}],
 "lanes": [{"id": id, "title": str, "branch": "agent/<set>/<id>", "worktree": str, "paths": [manifest entry],
            "depends_on": [id], "serves": [rid], "outcome": str, "acceptance": str}]}
```

`rid` is a requirement id. Every key shown is required (`notes`, `shared` and `depends_on` may be empty lists) except the
lane's `acceptance`, which may be omitted, and a key that is not shown is invalid at every level (`UNKNOWN_KEY`). The
limits:

| Field | Rule |
| --- | --- |
| whole spec | at most 4,194,304 bytes (reading stops at 4,194,305 bytes), a JSON object, no duplicate key at any depth, no `NaN`, `Infinity` or `-Infinity` and no number beyond the range of a float (a literal such as `1e400`), nesting the JSON parser can read; no string holds a control character (the `sheet` may hold newline and tab) or a lone surrogate; the text is parsed with an integer hook that keeps a run of more than 4,000 digits as text, as `format_number` does for claims, so the result does not depend on the interpreter's integer-size limit |
| `v` | the integer 1 (a boolean, a float or a string is invalid; every other integer, a run of digits of any length included, is an unsupported spec version, `UNSUPPORTED_VERSION`) |
| `title` | 1 to 120 characters |
| `requirements` | 1 to 12 objects, each with exactly the keys `id` and `text`: the requirements of the task as the planner understood them |
| requirement `id` | `[A-Za-z0-9_-]{1,8}`, unique ignoring case (`FORMAT` and `DUPLICATE`, field `requirements[i].id`) |
| requirement `text` | 1 to 200 characters |
| `base` | 40 or 64 hexadecimal digits in any case, stored in lower case; an abbreviation is invalid |
| `sheet` | 1 to 8,192 characters (code points); stored verbatim, never parsed |
| `notes` | at most 5 strings of 1 to 200 characters |
| `shared` | at most 64 objects; `path` is a file path that passes `parse_entry` with no `*` or `?` and no trailing `/`, unique after folding; `owner` names a lane id of the spec, and the path lies inside the owner's manifest: `segs_overlap(alt, fpath(path))` is true for an alternative `alt` of an entry of the owner (the exact glob intersection of the entry with the file, so a directory entry covers the files below it), and the literal-directory clause of `path_hit` does not apply, so `src/c` is not inside `src/c/x.py` |
| `lanes` | 1 to 12 objects |
| lane `id` | a topic slug: the lane id rules below (the form, the generic names, the reserved names), unique |
| lane `title` | 1 to 80 characters |
| lane `branch` | exactly `agent/<set>/<id>`: the branch rules below |
| lane `worktree` | the worktree rules below, its directory name ending with `-<set>-<id>` |
| lane `paths` | 1 to 200 strings; each is one manifest entry read by `parse_entry` (at most 1,024 characters, normalised, with every refusal of the manifest syntax: empty, magic, absolute, `..`, `.git`, a `**` inside a segment, too broad); there is no comment syntax, so a `#` starts a path; no two entries of one lane are equal after normalisation (the same tuple of normalised alternatives: separators, `./`, repeated `/`, a trailing `/`, case, Unicode normalisation and the blanks at the ends fold): every later equal entry is `DUPLICATE` on its own field `lanes[i].paths[j]`, with the English text `the entry equals lanes[i].paths[k] after normalisation` naming the first one, as for `shared` paths; so the record and the claim store one entry per entry of the spec, in its order, each its raw spelling with the blanks at its ends removed |
| lane `depends_on` | at most 11 ids of other lanes of the spec, spelled as the lane's `id`, no duplicate, no self |
| lane `serves` | 1 to 12 requirement ids, each spelled exactly as the `id` of a requirement of the spec, no duplicate: the coverage rules below |
| lane `outcome` | 1 to 300 characters: the result the lane delivers |
| lane `acceptance` | optional, 0 to 300 characters: how the outcome is checked; an omitted key and the empty string are the same and are stored as the empty string |

*Lane id rules.* A lane id is a topic slug: one to three words that name the subject of the change in kebab-case
(`claim-store`, `sweep-readiness`, `launcher-exit-codes`, `readme-gitplan`). The exact expressions, each matched against
the whole id (they are listed outside the table because the alternation holds a vertical bar):

```
slug      [a-z0-9][a-z0-9-]{0,23}
digits    [0-9]+
letter    [a-z]
ordinal   (l|lane|task|agent|worker|wt|t|n|w|work|part|step|item)-?[0-9]+
device    con|prn|aux|nul|com[1-9]|lpt[1-9]
```

The tests run in this order and the first one that fails gives the one error of the id (exit 24, field `lanes[i].id`):

1. the id is a string (`TYPE`);
2. generic: the lower-cased id matches `digits`, `letter` or `ordinal` (`GENERIC_ID`): an ordinal or generic name such as
   `L1`, `lane-2`, `Task3`, `7`, `a` or `A` says nothing about the change, and the case is folded so that these ids get
   this message and not the form message;
3. reserved: the lower-cased id is `integration` or matches `device` (`RESERVED`): `integration` is the name of the
   integration branch `agent/<set>/integration` and the name `list` shows for the integration claim (` set
   <name>/integration`), which a lane of that id would read as, and a Windows device name as the last component of the
   branch `agent/<set>/<id>` is refused by `check_name`; the id is refused here once, so that one bad id never yields an id
   error and a branch error;
4. the form: the id as written matches `slug` (`FORMAT`): uppercase, `_`, a `.`, a space, a non-ASCII character, an empty
   id, a leading hyphen and an id of more than 24 characters fail it;
5. uniqueness among the ids that passed 1 to 4 (`DUPLICATE`; ids are lower case, so equality is exact).

The set name has the form `slug` and is not tested against `digits`, `letter`, `ordinal` or `integration`. The text of
each of these lane id errors is an entry of the table `M` in the language of the call (`set_err_generic_id`,
`set_err_reserved_id`, `set_err_id_form`). The generic and the form texts name the rule, ask for the topic of the change
in one to three words and give examples; the reserved text names the reserved names and what they belong to and asks
for another topic slug that names what the lane changes, with no example name (no fixed name fits the topic of every
lane). For the form error, when the lower-cased id with every `_` replaced by `-` matches `slug` and is neither
generic nor reserved, the message adds that slug as the suggestion (`Claim-Store` and `claim_store` give `claim-store`).
A lane whose id is invalid is left out of the uniqueness test and of the rules derived from the id (the branch and the
worktree name), and a `depends_on` entry or a `shared` owner that names that id exactly is not reported a second time;
its other fields are validated and its `serves` takes part in the coverage rules.

*Branch rules.* A lane branch is exactly `agent/<set>/<id>`, compared exactly, case included (`BRANCH_FORM`, exit 24, field
`lanes[i].branch`; the text is `set_err_branch_form` and names the compliant branch). The integration branch is
`agent/<set>/integration`. Consequences, none of them a separate check: the lane branches are pairwise distinct, never
collide ignoring case or Unicode normalisation (they are lower-case ASCII) and never clash as a ref that would be both a
file and a directory (`agent/<set>/<id>` has no further `/`, and `agent/<set>` is never a lane branch); none equals or
clashes with the integration branch (`integration` is no lane id). A lane branch that equals the target (ignoring case)
is exit 24, `BRANCH_NAME`, `lanes[i].branch`. The intrinsic rules of `check_name` (a valid branch name by
`check-ref-format --branch`, at most 100 characters, none of `< > | "`, no Windows reserved device name in a path
component, and the Windows alias rule: no component ending in `.` or a space or in `.claim`) hold for `agent/<set>/<id>`
by construction: a slug holds none of those characters, the longest branch has 6 + 24 + 1 + 24 = 55 characters, and a
device name can be a component only through the set name or the id, which their own rules refuse. The rules that need the
repository are the existing ones of `check_name` against the refs and claims of the repository (a ref that would be both
a file and a directory, for example an existing branch `agent/<set>`; a collision with an existing branch ignoring case
and Unicode normalisation, for example `Agent/Demo/Api`), refused with exit 12 and `[BRANCH_NAME]`, and the existence of
the branch (exit 15) or of a claim for it that is not the set's own (exit 14).

*Worktree rules.* A lane worktree is an absolute path, classified by the guard's own rule and never by `os.path.isabs`
(whose Windows result for a rooted path without a drive differs from Python 3.13 on): after `_norm_path` (Git Bash
drive spellings such as `/c/x` map to drive paths on Windows) it is a drive path (`C:/x`, `C:\x`) or a UNC path on
Windows and a path with a leading `/` on POSIX; a leading `~`, a `..` segment, a control character, a backslash on
POSIX, a Win32 namespace path on Windows (`\\?\` or `\\.\`, which `pkey` would never fold to the drive spelling it
names), on Windows the spellings that Win32 path resolution reads as another directory than the one `pkey` compares
(the rules judge the `os.path.normpath` form, which holds no `.` segment): a segment that ends in `.` or a space (Win32
can drop those characters, so `C:/x/repo./wt` names `C:/x/repo/wt`), `~` followed by a digit (the form of an 8.3 short
name, as the alias rule of manifest entries refuses `git~1`; `C:/x/REPOSI~1/wt` can name `C:/x/repository/wt`) and a
`:` other than the one of the drive (NTFS stream syntax; `C:/x/repo::$INDEX_ALLOCATION/wt` names `C:/x/repo/wt`), or a
length over `MAX_DIR` (4,096) is invalid (exit 24, field `lanes[i].worktree`, the text naming the reason). It is stored as
`os.path.normpath` with `/` as the separator (the spelling `plan --worktree` stores), on POSIX with its leading run of
slashes written as one (`os.path.normpath` keeps exactly two, which the kernel reads as one, so `//home/u/x` is stored
as `/home/u/x` and is compared as the directory it names), and compared with `pkey`, so case and separators fold where
the platform folds them. Two lane worktrees are never equal and never one inside the other
(exit 24). Against the repository, a lane worktree is never inside a worktree of the repository (the main one
included) or inside the git common directory, and no existing worktree lies inside it (exit 12, `[WORKTREE]`), except
the lane's own worktree: the worktree that is already checked out on the lane's own branch at the lane's path (an
amend of a lane whose worktree exists) and, in an amend only, the worktree on a detached HEAD at the path that the
record registers for the same lane id (an owner's rebase or bisect detaches it); a fresh plan still clashes with a
detached worktree at a planned path. The guard
validates the spelling and the position, not whether the directory is free: `git worktree add` decides that. The
position rules compare the spellings the spelling rules admit, with `pkey`, and resolve no link: a directory reached
through a junction, a symbolic link, a `subst` drive or another share of the same disk (`//localhost/C$/x`) is another
directory to them. The spec file is refused (exit 24, `SPEC_IN_WORKTREE`) when the `os.path.abspath` spelling of
`--spec` lies inside a worktree of the repository or inside a lane worktree of the spec, so a spec file named through
an 8.3 short name or a stream suffix is not caught.

*Worktree name.* The directory name of a lane worktree (the last component of the stored path, without a trailing
separator; the root of a drive has none), judged only for a path whose spelling is valid, is `<prefix>-<set>-<id>` with
a non-empty prefix: it ends with `-<set>-<id>` (`WORKTREE_FORM`, exit 24, field `lanes[i].worktree`; the text is
`set_err_worktree_form` and names the default path). The default is `<parent of the main worktree>/<repo dir name>-<set>-<id>`, where the main worktree is the first entry of
`git worktree list` and `<repo dir name>` is its directory name, so `git worktree list` reads as a list of topics next to
the main worktree. The default is absolute: for a main worktree directly below the root of the filesystem or of a drive
the parent is that root (`/repo` gives `/repo-<set>-<id>`, `C:/repo` gives `C:/repo-<set>-<id>`). A main worktree at a
root (`/`, `C:/`, and on Windows the root of a UNC share, `//server/share`, whose share is its drive) has no directory
name and contains every path of that root, so its default, `repo-<set>-<id>` on that root (`//server/share` gives
`//server/share/repo-<set>-<id>`, never the sibling share `//server/share-<set>-<id>`), is refused like any path inside
the main worktree (exit 12, `[WORKTREE]`). A spec that names the default meets the rules of any other path: on Windows
a main worktree below a directory whose name holds `~` followed by a digit gives a default that the spelling rule
refuses.
The comparison of the name with the spec's own `set` and `id` is exact on every platform, case
included (`pkey` compares two paths with each other and does not take part), so a spec means the same everywhere. On
Windows the spelling rule refuses a segment that ends in `.` or a space before the name is judged, and the name ends
with a letter, a digit or a hyphen, so the aliases of a trailing `.` or space cannot occur; a
device name can occur through the prefix only: when the text of the name before its first `.`, folded, matches `device`,
the lane is refused on every platform (`WORKTREE`, same field; `aux.x-demo-api` is the device AUX on Windows).

*Coverage rules (exit 24).* The requirements and the lanes cover each other. Every `serves` id holds no lone surrogate (`ENCODING`, field `lanes[i].serves[j]`, tested before the other rules of the id), names a requirement of
the spec, matched exactly like a `depends_on` id (`UNKNOWN_REQUIREMENT`, field `lanes[i].serves[j]`; an id in another
case is unknown), appears once in its lane (`DUPLICATE`), and `serves` holds 1 to 12 ids (`RANGE`, field
`lanes[i].serves`, an empty list included: a lane that serves nothing; a missing key is `MISSING`). Every requirement is
served by at least one lane (`UNSERVED`, field `requirements[i]`, one error per unserved requirement with its id and
text, `set_err_unserved`). The rules read the `serves` of every lane whose `serves` is a valid list, a lane with an
invalid id included. The coverage is derived from the `serves` of the lanes and never stored separately: wherever a
result lists `lanes` of a requirement, it is the ids of the lanes that serve it, in lane order. The texts of the
coverage errors are entries of the table `M` in the language of the call (`set_err_unserved`, `set_err_serves_unknown`,
`set_err_serves_count`).

*Other cross-field rules (exit 24).* `depends_on` names existing ids and forms a directed acyclic graph (a cycle is
reported with the lanes on it, `CYCLE`); the merge order is the topological order of the graph in which, at every step,
the first lane of the `lanes` array whose dependencies are all placed comes next, so it is deterministic. Errors are
collected across fields and reported together (at most 20 lines, then `... and N more`), each as `[CODE] field: text`
with `field` a path such as `lanes[2].paths[7]`, `lanes[1].worktree`, `shared[0].owner`, `requirements[1]`, `sheet` or
`base`. They come in this order, and the 20 printed lines (and the `errors` of `--json`) are the first 20 of it: the
keys of the top-level object (repeated, unknown, missing); the top-level fields in the order of the schema above except
`shared` (`v`, `title`, `requirements`, `base`, `sheet`, `notes`, then `lanes`), where a list's type and size come before
its items in array order, an object's keys before its fields and the fields of a lane in schema order; then the rules
across fields: the `depends_on` ids lane by lane, each lane's ids in array order, each id with the first of unknown,
repeated, self that applies (an id equal to the lane's own id is a self dependency each time it appears, never a
repeated one), then the cycles; then `shared`, its type and
size and then each entry in array order with its keys, its `path`, its `owner` and the containment of the path in the
owner's manifest (reported on `shared[j].path`); then the unserved requirements, the nesting of lane worktrees and the
position of the spec file. A repeated key that none of these checks reports is one error (`spec`, `DUPLICATE`), given
only when there is no other. The text of the naming errors
(the `--set` name included) and of the coverage errors is in the language of the call (zh by default, also in
`errors[].text` under `--json`); the text of every other error is English in both languages, as the codes and the
field paths are identifiers. The codes are `TOO_LARGE`,
`ENCODING`, `JSON`, `MISSING`, `UNKNOWN_KEY`, `TYPE`, `RANGE`, `FORMAT`, `DUPLICATE`, `UNSUPPORTED_VERSION`,
`UNKNOWN_LANE`, `UNKNOWN_REQUIREMENT`, `UNSERVED`, `GENERIC_ID`, `RESERVED`, `CYCLE`, `NOT_IN_OWNER`, `BRANCH_NAME`,
`BRANCH_FORM`, `WORKTREE`, `WORKTREE_FORM`, `SPEC_IN_WORKTREE`, `STATE` and the codes of the manifest syntax (`EMPTY`,
`TOO_LONG`, `MAGIC`, `ABSOLUTE`, `DOTDOT`, `BAD_SEGMENT`, `GITDIR`, `BAD_GLOB`, `UNIVERSAL`, `TOO_MANY`).

**Set record** `<git-common-dir>/magos/sets/<set>.json`: one JSON object, UTF-8 without a BOM, LF, with no `NaN` and no infinity (the serialiser `record_bytes` refuses a non-finite number), written only by the
guard (the tamper filter denies agent writes under the store). Fields, in this order: `v` (`SET_FORMAT` = 1), `set`,
`target` (the branch name the set lands on), `base` (the target tip the plan was made against, lower case), `revision`
(1 at registration, +1 on every change), `created`, `updated` (UTC `YYYY-MM-DDTHH:MM:SSZ`), `by` (the user of the last
write, as claims write it), `title`, `requirements` (the spec's `{id, text}` objects in the spec's order), `sheet`,
`notes`, `shared`, `integration` (null until the first `integrated` update records the branch), and `lanes`, each with
`id`, `title`, `branch`, `worktree`, `paths` (the raw entries), `depends_on`, `serves`, `outcome`, `acceptance` (the empty
string when the spec omitted it), `state` (`planned`, `active`, `ready`, `integrated` or `blocked`; `planned` at
registration), `head` (null until `ready`), `ready_target` (null until `ready`: the commit the last `ready` measured
the lane against, a full object name: the tip of the local target branch, or the plan's `base` when that branch did
not exist), `changes` (null until the lane is recorded `integrated`: the summary of The
changes summary; null again when the lane leaves `integrated`), `note` (empty until set) and `updated`. A key this guard
does not know, in the record object or in a lane object of a record of format 1, is kept and written back unchanged, with
one limit: a number that is not an integer is read as a double and written back as Python's `repr` writes that double
(the fewest digits that read back as it: `1e5` is written as `100000.0`), so a literal with more digits than a double
holds is rounded (`0.12345678901234567890123` is written as `0.12345678901234568`) and an underflow such as `2.5e-400`
is written as `0.0`. The `set` field equals the file name; a record that does not is unreadable.

**Lane claims.** Every lane has one claim of the existing format written like a claim of `plan`: `branch`, `worktree`
(the normalised spelling above), `target` (the target's name), `base` (the plan's base), `created`, `by`, empty
`override`, one `entry=` line per path, then the extra keys `set=<name>` and `lane=<id>`; `v=1` and `state=active`.

**Integration claim.** Creating `agent/<set>/integration` (the branch the convergence merges the lanes into) must pass
the host hook and the git layer like the creation of any branch, so the set registers a claim for it as well: branch
`agent/<set>/integration`, empty `worktree`, `target` and `base` as the lanes', the single entry
`.magos/integration/<set>/` (the marker entry: a claim needs a non-empty manifest, and the marker names no file of the
work tree), and the extra keys `set=<name>` and `role=integration` (no `lane=`). Only `set-plan` writes `role=integration`
(`plan` writes no extra key of its own, and the tamper filter denies agent writes to the claim store, Invariant 7), so
an agent cannot request the exemption below. The command creates the branch with a plain `git switch -c agent/<set>/integration <target
tip>`, and a denial of that creation is the host hook's, never worked around. The set refuses to register when the
integration branch already exists (exit 15, naming it) or has a claim that is not the set's own (exit 14).

*The integration claim is exempt from overlap judgement, in both directions.* The integration branch is the whole,
assembled by merging the lanes, so its claim claims no files and restricts no lane manifest: entries such as
`docs/**/*.md`, `**/*.md` and `*.md` are valid in a lane, and the marker takes no part in the pairwise proof of
`set-plan` (step 4). The exemption belongs to the claim that has exactly the shape `set-plan` writes
(`is_integration_claim`): `role=integration` exactly, `set=<S>`, the branch `agent/<S>/integration` and the single entry
`.magos/integration/<S>/`, the last three compared folded. A claim that carries `role=integration` in any other shape (for
example the remainder of an interrupted registration whose entries a plain `plan --amend`, or a guard of 1.0.3, changed,
since an amend keeps the extra keys of the claim) is an ordinary claim: its entries are declared evidence and its
creation is judged in full. A set-plan amend writes the claim again in its shape (step 12). The exemption is decided by
the claim alone: the set record is not read, so the claim of an interrupted registration is exempt as well until
`release --branch` frees it.

- *As a claimant (the judgement).* The claimant list of the judgement is built from two sources: `gather` reads git
  only (branches, worktrees, commits, uncommitted files) and knows no claim; `judge` then adds the declared entries of
  the open claims in `with_declared` (`set-plan` calls it once for all its lanes and hands its result to `judge`, step 11). `with_declared` skips an integration claim, so its marker entry never reaches
  `evaluate` and it is never a claimant of `plan`, `check`, `set-plan` (step 11) or the creation check of any other
  branch, of its own set or of another one. A skipped claim is not parsed, so it yields no `CLAIM_UNPARSEABLE`.
  The exemption concerns the claim only: the real branch `agent/<S>/integration`, once it exists, and a worktree on it
  are gathered like any branch, and the commits merged into it are evidence like those of any unmerged branch; only
  `set-plan` leaves them out of its own snapshot as members of the set (step 9).
- *As a creation (`check_creation`).* The creation of the branch of an integration claim is judged for the claim and the
  name only. The checks that precede the judgement stay: a claim of a newer format is UNKNOWN `CLAIM_NEWER_FORMAT`, a
  branch without a claim is `NO_MANIFEST`, and the claim's registered worktree is compared with the path of the
  creation (the integration claim has none, so there is no `path_mismatch`). Then the branch name passes `check_name`
  against the refs and the other claims with `stored` true, as for the claim of any branch (`INVALID_MANIFEST`,
  `[BRANCH_NAME]` on failure), and the creation is allowed: `plan_core` is not called, so nothing is gathered or
  evaluated, and no lane's manifest, no commit of a lane and no unknown of the judgement (an unreadable claim elsewhere,
  an uncertain target, more unmerged branches than the cap) denies it; only a Git failure of the name check
  (`check-ref-format`, the refs) fails closed, as for every creation. The git layer reads line 1 of the claim file of the
  name, so the claim is all its backstop needs. Any other branch is judged in full: an unclaimed one is `NO_MANIFEST`, a claimed one by its entries.
- *What `list`, `doctor` and the release show of it.* `list` prints ` set <name>/integration` (JSON `role`
  `integration`, `lane` null) and its state as for any claim, and `list --drift` skips it; it prints them only for a claim
  that `is_integration_claim` accepts, so a claim that carries `role=integration` in another shape shows its `set` alone
  (text ` set <name>`, no lane and no `role`) and reads as missing to a reader that looks for the integration claim
  (`/GitPlan` then writes it again with `set-plan --amend`, step 12). `doctor` leaves it out of the
  orphan-claims line while the set has a record and names it in `claims of set <s> without a record` when the record is
  gone; it prints nothing else for the exemption. `release --branch` refuses it while the record exists (`blocked_set`),
  and `set-release` removes it in the transaction with the lane claims (each only when it exists, lies inside the store,
  carries `set=<name>` and is the claim of the reserved branch name).

**Format gate.** A set record whose `v` is an integer (not a boolean) greater than `SET_FORMAT` is never read as if it
were this format, never overwritten and never removed: every set command that names it (`set-plan` with or without
`--amend`, `set-show`, `set-update`, `set-release`) refuses with exit 23 (`set_newer`: "set X was written by a newer
MAGOS (v=N); upgrade this guard (doctor shows its version, install refreshes the copy), or run this command with the
MAGOS that wrote it"); the check precedes every other field, so no field of a newer record is interpreted. The record
is parsed with the hooks of the spec (a run of more than 4,000 digits stays text; `NaN`, `Infinity` and a number beyond the range of a float, such as `1e400` under a key this guard does not know, are not valid JSON), so an integer `v` above
`SET_FORMAT` of any length is a newer format on every interpreter, as `format_number` treats a long format line of a
claim. A record that is not a JSON object, has no integer `v`, has `v` below 1 or is not valid JSON is
unreadable, and so is a record of this format whose fields do not have their shape, among them a `base` that is not a
full object name (40 or 64 hexadecimal digits) and a lane `head` or `ready_target` that is neither null nor one: the set commands pass
these values to Git as revisions, so a value shaped like an option never reaches Git. A number of more than 4,000 digits anywhere but `v` makes a record of this format unreadable as well: the parser keeps it as text, so a write would put it back as a string. So does a lone surrogate (a code point from U+D800 to U+DFFF that is not half of a pair, which only a JSON escape can spell) in a string or in a key at any depth (`holds a lone surrogate`): it has no UTF-8 form, so a write of the record or a `--json` output of it would fail. One walk of the record after the check of `v` finds both. The command refuses with exit 11 (UNKNOWN, code `SET_UNREADABLE`, naming the file, `set_unreadable`), the
file is never overwritten or removed by this guard, and the user inspects it. Readers list only `*.json` files of
`sets/`, so a temporary file (`*.tmp`) never reads as a record. A claim of a newer format among the claims of the set is
handled by the claim gate (UNKNOWN `CLAIM_NEWER_FORMAT`, never overwritten, never released).

**Atomic write.** The text of every claim a set writes is produced by the validation and serialisation part of
`write_claim` (the control-character refusal, the match of the folded branch with the name, the refusal when the claim
file holds another branch's claim or cannot be read, the refusal to overwrite a newer-format claim), so a claim written
by a set is exactly a claim `plan` could write; a refusal ends the call before anything is written (a name or
control-character refusal exit 12, a newer-format claim exit 11). The call then builds the complete list of writes
(claim files, then the record last) and deletions (claims of removed lanes), reads the previous bytes of every file it
will touch inside the lock, and applies the writes with `replace_files` (every new content staged in a temporary file
beside its destination, every file moved into place
with `os.replace`, a failed move puts every file already moved back from its previous bytes and removes the temporary
files), then the deletions; when a deletion fails, every deletion and write already made is undone from the previous
bytes (a file that had none is removed) and the error is raised, so the store never holds a mixture of two versions.
Readers take no lock (the host hook reads the claims, `set-show` the record), and Windows refuses to replace or remove
a file that a reader holds open: every move into place and every removal of the transaction, those of an undo
included, is retried on `PermissionError`, the error Windows gives for such a busy file (40 tries, 0.05 s apart), and
a file still refused after the last try is a failed move or deletion.
When an undo itself fails (`NotRestored`), the call exits 11 and names the files that could not be put back, which
`doctor` then reports. The record is the last write, so a reader that sees a new record sees every claim it needs. A
process that is killed between two moves leaves either claims of a set without a record or a record whose claims are
missing: `doctor` reports both directions, `release --branch` frees the claims of a set that has no record, and
`set-release --abandon` retires a record whose claims are gone.

### set-plan

`set-plan --set NAME --target BRANCH --spec FILE|- [--dry-run] [--amend --expect-revision N]`. Steps, in this order; the
first failing step ends the call, and a failure at any step writes nothing:

1. **Usage (exit 2).** `--amend` without `--expect-revision`, `--expect-revision` without `--amend`, and an
   `--expect-revision` that is not `[1-9][0-9]{0,8}`. `--set`, `--target` and `--spec` are required (a missing one is a
   usage error); an invalid `--set` is exit 24.
2. **Read the spec.** Bytes are read from the file or from stdin up to the size limit; a missing file, a directory or an
   unreadable file is exit 24 on `--spec`; a file inside a worktree is `SPEC_IN_WORKTREE` (write it outside every
   worktree, or pass `-`). The text is decoded (`decode_manifest`) and parsed with duplicate keys, `NaN`/`Infinity`, a number beyond the range of a float and
   over-deep nesting refused.
3. **Validate every field and the cross-field rules** of Data model, collecting all errors in the order stated there:
   the fields, the lane id rules (generic, reserved, form), the requirements, `serves` and `outcome`, the branch and
   worktree names (`agent/<set>/<id>`, the directory name ending with `-<set>-<id>`), the manifests (every entry valid,
   no two entries of one lane equal after normalisation), `depends_on`, the `shared` owners, the coverage (every
   requirement served, every lane serving one), the nesting of lane worktrees and
   the position of the spec file; any error is exit 24. No claim, record or ref has been read at this point (only the
   worktree list, for the position of the spec file and for the default worktree path of the naming messages).
4. **Pairwise disjointness (exit 10).** Only the lanes of the spec take part: the integration claim claims no files and
   its marker entry is not compared (Integration claim), so a lane entry whose first segment is a wildcard is valid. The
   entries of every lane are indexed by the literal prefix of each of their alternatives: its folded leading segments
   up to the first one that holds `*` or `?` or is `**` (empty for an alternative that starts with one). A path matches
   an alternative only when its leading segments are that prefix, so two alternatives can match a common path only when
   the literal prefix of one is a prefix of the other's (equal included). An entry of one lane is compared by
   `entries_overlap` (the exact glob intersection that `plan` uses) only with the entries of the other lanes that have
   an alternative whose prefix is a prefix of one of its own, or has one of its own as a prefix, so an entry with an
   empty prefix is compared with every entry of the other lanes, and the work is near-linear when lanes own distinct
   directories, also below one shared top directory (`src/<lane>/...`). The call's deadline is
   ticked between entries: when it runs out, the call ends with exit 11 (UNKNOWN, `BUDGET_EXCEEDED`) and nothing is
   written, never with a partial proof. Every overlapping pair is reported with both lane ids and both raw entries (at
   most 20 pairs, in lane order and entry order, then `... and N more`); the verdict is CONFLICT (exit 10) with the
   pairs in `overlaps`. Entries equal after normalisation, a glob and a file it matches, a directory and a file below it,
   two globs that can match one path, and entries that differ only in case or Unicode normalisation all overlap.
5. **Lock** (not with `--dry-run`): exit 13 on timeout. Inside it the claims, the record and the refs are read afresh.
6. **The record.** Without `--amend`: a record of the set (readable, any revision) is exit 20 (`set_exists`, naming the
   revision and the two ways forward), a newer-format one exit 23, an unreadable one exit 11. With `--amend`: no record
   is exit 21 (`set_unknown`), a newer one exit 23, an unreadable one exit 11, a `--target` that is not the record's
   target (folded) exit 24 (a target never changes; release the set and plan a new one), and an `--expect-revision` that
   is not the record's revision exit 19 (`set_stale_revision`, naming both revisions).
7. **The live base (exit 19).** The target must exist as the local branch `refs/heads/<target>`; the guard's own
   resolution of the target (`resolve_target` with `--target`, the one the judgement uses) must give the same sha, else
   the call ends with exit 11 (UNKNOWN, `TARGET_UNCERTAIN`, with the `--target` value as messages show a value of the spec: the target does not resolve to a local branch, or the local
   branch is behind or diverged from its remote-tracking copy, where lanes cut from the local branch would never
   descend from the sha the plan names). The spec's `base` must equal that sha read inside the lock, else STALE
   (exit 19, `set_stale_base`, naming both): the planner investigated another tip. Nothing is fetched.
8. **Names against the repository.** The claims of the set are, in an amend, the claims whose `set=` value is the set's
   name and the claims without a `set=` line whose branch is spelled exactly as the record spells the branch of one of
   its lanes or its integration branch, which step 12 writes again from the record (a set-less claim of such a branch in
   another spelling, another letter case for example, is a claim file of its own where case matters and no claim of the
   set: it clashes with the branch, exit 12 `[BRANCH_NAME]`); in a fresh registration no claim is the set's own (a claim that carries `set=<name>` while no record exists is
   the remainder of an interrupted registration and is refused like any other claim until `release --branch` frees it).
   For every lane in spec order and then the integration branch: `check_name` against the refs and the claims of the
   repository that are not the set's own (the branches of the spec never clash with each other, by the branch rules,
   so only existing refs and claims can: a ref that would be both a file and a directory, a collision ignoring case or
   Unicode normalisation; exit 12, `[BRANCH_NAME]` naming the lane); a claim of the branch
   that is not the set's own (exit 14, `set_lane_exists`); a branch that exists with no claim of the set and is no
   branch of the record (exit 15, `set_branch_exists`; in an amend the existing branch of a lane of the record or the
   integration branch passes when its claim is missing, and step 12 writes the claim). The kinds are checked in this order, every offending lane of the first failing kind is named,
   and the first failing kind decides the exit code. The worktree rules against the repository are checked here
   (exit 12, `[WORKTREE]`). In an amend, a claim of a newer format on the branch of a lane of the record or on the
   integration branch is not foreign: it is the claim gate's (the judgement of step 11 and the write of step 13 refuse
   it as UNKNOWN `CLAIM_NEWER_FORMAT`, exit 11), and it is never overwritten.
9. **One snapshot.** `gather(g, None, <target>)` runs once for the whole call (not once per lane) and the claimants that
   are members of the set are left out of it: the branches of the record's lanes and of the spec's lanes and the
   integration branch `agent/<set>/integration` by `lane_key`, their worktrees by their `wt:` key and the claims of the
   set. The lanes were proven pairwise disjoint by step 4, so they are not compared with each other, and the commits of
   the lanes already merged into the integration branch never conflict with the set's own lanes; the evidence of the
   members is kept aside for step 10.
10. **Amend only: lanes that were already started.** The evidence of a lane of the record is that of its branch and
    that of its registered worktree when that worktree is on a detached HEAD (its `wt:` key of the snapshot), joined. For
    every lane of the record, matched by id: a lane absent from the
    spec is removed, and it is refused with exit 16 (BLOCKED, reason `UNMERGED_WORK` or `DIRTY_WORKTREE`, naming the lane;
    the text of `UNMERGED_WORK` names the lane's branch as the record spells it, whatever the case of the existing branch)
    when its branch exists with commits that are not in the target (`refs/heads/<b>` is not merged into the target), when
    its detached worktree holds commits that are not in the target (`UNMERGED_WORK` with their files), or when
    its worktree has uncommitted changes; a lane that survives keeps its branch and worktree when either exists (a
    changed `worktree` of a lane that has a branch or a worktree on disk is exit 24; its `branch` is fixed by its id), and it is refused with
    exit 16 (reason `SHRINK`, naming the lane and the files) when a file it already changed (committed over every merge
    base with the target, or uncommitted in its worktree, a rename counting both names) is no longer inside its new
    manifest. The files are tested against the new manifest through the index of the lane manifests that `set-show` uses
    (`ManifestIndex`, whose answer is exactly that of `path_hit`) on the budget of the call: an exhausted budget ends the
    call with exit 11 (`BUDGET_EXCEEDED`) and nothing is written. A lane whose id is new is registered `planned`.
11. **Judgement against every other claimant.** `with_declared` adds the declared entries of the claims outside the set
    to the snapshot once for the whole call (it skips the integration claim of any other set as well, so it is never a
    claimant). For each lane in spec order, `judge` runs on that list without the lane's own claim and with the lane's
    entries: the committed and uncommitted files of every claimant are first narrowed to those the index of the lane's
    manifest (`ManifestIndex`, on the budget of the call) matches, and `evaluate` compares the lane's entries with those
    files and with the declared entries of every claimant that is not a member. The index answers exactly as `path_hit`
    does, so a file it does not match is no evidence against the lane, and every lane gets the verdict `judge` gives it
    alone, as for `plan`. A conflict or an unknown denies the whole set and names
    the lane (`set_lane_item`) and the claimants as `render` names them, without the override paragraph of `options`,
    which is replaced by the set's own (`set_options`): `set-plan` never reads or consumes an override. Every lane is
    judged, so every offending lane is named. The code is CONFLICT (exit 10) when any lane has a conflict and UNKNOWN
    (exit 11) when the lanes have only unknowns (an unreadable or newer-format claim anywhere denies, as for `plan`).
    The warnings of the snapshot and `NOT_ARMED` and `HOOK_BYPASSED` are printed with the success (not with a denial):
    `backstop_warnings` computes the two, as it does for `plan`, and the lanes of the set count as parallel lanes, so
    `NOT_ARMED` shows whenever the git backstop is not installed.
12. **Build and compare.** The new record (`base` the spec's, `target` the record's, `revision` 1, or the old revision + 1
    for an amend, `requirements` and every lane's `serves`, `outcome` and `acceptance` the spec's, the lane states, heads,
    `ready_target`, `changes` and notes carried over for the ids that survive, `planned`, a null `head`, a null
    `ready_target` and a null `changes` for new
    ones, `integration` kept, `created` kept) and the claims (a lane
    claim is rewritten when it is missing, or its entries, worktree, target, base, override fingerprint or set keys (`set=`, `lane=`) differ; its `created` is kept; the
    claims of survivors get the new `base` when the amend moves it; claims of removed lanes are deleted; the
    integration claim is written when it is missing or does not have the shape `set-plan` writes, its `created` kept).
    When an amend changes nothing (every record field except `revision`, `updated` and `by`, and every claim, equals
    what exists) the call ends with exit 0 and `unchanged: true`, the revision stays, and nothing is written.
13. **Write** (not with `--dry-run`) with the transaction of Atomic write, then append the audit line (built before the
    write, Compatibility, limits and cost) and print the result. `--dry-run` runs steps 1 to 12 against the same snapshot logic without the lock and prints the verdict the
    registration would give, with `dry_run: true` and the same exit code; it writes nothing and appends nothing. Its
    success text is `set_ok_check`, for a new plan and for an amend alike: the preview passed and, as a dry run,
    wrote nothing.

Result (`--json`): success `{decision: "allow", code: "OK", set, target: {name, sha}, base, revision, dry_run, unchanged,
integration_branch, order, requirements: [{id, text, lanes}], lanes: [{id, title, branch, worktree, entries, depends_on,
serves, outcome, acceptance, state, create}], written, warnings, message, exit_code}` where `create` is `git worktree
add "<worktree>" -b <branch> <target>`, `entries` the manifest entries of the lane as the record's `paths` stores them
(each raw spelling with the blanks at its ends removed, in the spec's order), `requirements[].lanes` the ids of the lanes
that serve the requirement (Coverage rules) and `written` lists the claim and
record files the call wrote (empty for `--dry-run` and `unchanged`); `revision` is the revision the record has after the
call (the one a `--dry-run` would write, the current one for `unchanged`) and `warnings` is a list of `{code, text}`; the
requirements, outcomes and lanes of a preview are therefore the guard's own reading of the spec;
denial `{decision: "deny", code, errors: [{field, code, text}], overlaps: [{a, b, entries: [[entry of a, entry of
b]]}], lanes: [{id, branch, code, conflicts, unknowns}], unknowns: [{code, text}], blocked: [{lane, reason, files}],
expected, current, kind, message, exit_code}` with only the keys of the denial present (`errors` for exits 12, 14, 15
and 24, `overlaps` for the pairwise exit 10, `lanes` for the judgement of exits 10 and 11, `unknowns` for an exit 11 of
the call itself (`TARGET_UNCERTAIN`, `SET_UNREADABLE`, `BUDGET_EXCEEDED`, `GIT_FAILED`, `INTERNAL_ERROR`), `blocked` for
exit 16, `kind` `base` or `revision` with `expected` and `current` for exit 19, `current` the record's revision for exit
20). `conflicts` and `unknowns` of a lane have the shape of the verdict of `plan`. The text of a success is `set_ok_plan` (or `set_ok_amend`, `set_ok_check`,
`set_unchanged`), one line per lane (id, branch, worktree, entry count), the line of the integration branch and the
`(CODE) text` warning lines. The `{example}` of `set_ok_plan` is the creation of the first lane of the spec from the
recorded base, `git worktree add '<worktree>' -b '<branch>' '<base>'`, with `<worktree>` the stored worktree, `<branch>`
`agent/<set>/<id>` and `<base>` the full object name the record stores as `base`, each argument one POSIX
single-quoted word (`sh_quote`: an apostrophe inside it is written `'\''`), so that the example cuts the lane from the
commit the plan was proven against even after the target moved. The `create` key of each lane is a separate value,
`git worktree add "<worktree>" -b <branch> <target>` as above.

### set-update

`set-update --set NAME --expect-revision N --lane ID --state STATE [--head SHA] [--note TEXT] [--integration BRANCH]`
changes one lane of a registered set. `--expect-revision` is required and is `[1-9][0-9]{0,8}`, `--state` takes only
`active`, `ready`, `integrated` or `blocked`, `--lane` is required (another value or a missing option is a usage error,
exit 2). Under the lock: the record is read (exit 21 unknown, 23 newer, 11 unreadable); the revision is compared (exit 19, `set_stale_revision`);
`--lane` must be a lane of the record (exit 24, field `--lane`, code `UNKNOWN_LANE`, naming the ids); then the transition and its conditions. The option
values that need no repository are checked before the lock (exit 24, the field named): `--set`, `--head` (a full object name, given
with `ready` and `integrated` only and required there), `--note` (any state, at most 200 characters, no control character) and
`--integration` (given with `integrated` only, and only the reserved name):

| From | planned | active | ready | integrated | blocked |
| --- | --- | --- | --- | --- | --- |
| planned | not a target state | allowed | refused | refused | allowed |
| active | not a target state | allowed (note) | allowed | refused | allowed |
| ready | not a target state | allowed (rework) | allowed (new head) | allowed | allowed |
| integrated | not a target state | refused | refused | allowed (note) | allowed |
| blocked | not a target state | allowed (resume) | refused | refused | allowed (note) |

A refused transition is exit 24, field `--state`, `STATE`, naming the lane's state; `planned` is the initial state
and never a `--state` value. `--note` is at most 200 characters without a control character and replaces the lane's note
(an empty value clears it). `--head` is a full object name (40 or 64 hexadecimal digits) and is accepted only with
`ready` and `integrated`, where it is required; `--integration` is accepted only with `integrated`; any other
combination is exit 24 on the option.

- **ready.** The lane's branch must exist (else exit 16, `BRANCH_MISSING`) and `--head` must equal its tip (else exit 16,
  `HEAD_MISMATCH`, naming both). Every worktree of the lane (at its registered path or on its branch) must be clean
  (`DIRTY_WORKTREE`) and in no rebase, merge, cherry-pick, revert or sequencer operation (`OPERATION_IN_PROGRESS`),
  because uncommitted work is not in the recorded head and would be left behind by a merge of it; both are exit 16, and
  a worktree that fails both names both reasons. A worktree of the lane whose directory is missing (prunable: a locked
  worktree on an unmounted drive, or a directory removed without `git worktree remove`) cannot be read, so it counts as
  dirty (`DIRTY_WORKTREE`, `set_why_wt_missing` naming its path). The files the lane changed, measured
  by `committed_paths(g, <target tip>, <tip>)` (the evidence function the guard uses everywhere, so a lane that merged
  the target into itself is not charged with the target's files; the plan's `base` stands in for the target tip when the
  target branch no longer exists), must all lie inside the lane's manifest by the exact glob intersection (`path_hit`); a
  file outside it is exit 22 (OUT_OF_LANE, `set_out_of_lane`, naming the lane and the files, at most 200 in `files`
  with `truncated`, and the two ways forward: revert those files in the lane, or amend the plan with `/GitPlan <set>
  --amend`, the command that changes a set), and no common history with the target is exit 16 (`NO_MERGE_BASE`).
  Success records the head and, as the lane's `ready_target`, the commit the files were measured against (the target
  tip, or the plan's `base` when the target branch does not exist).
- **integrated.** The lane is `ready` (the first record) or already `integrated` (a repeated update, which replaces
  the note only). `--head` must equal the head recorded at ready (else exit 16, `HEAD_MISMATCH`), and it must be an
  ancestor of the target's tip or of the tip of the integration branch (else exit 16, `NOT_MERGED`,
  `set_why_ancestor`). `--integration` must be the reserved name `agent/<set>/integration` and the branch must exist
  (`BRANCH_MISSING`, `set_why_integration`); it is required while the record's `integration` is null and must equal it
  afterwards, and success stores it. Nothing else about the merge is checked: the command performed it. When the lane
  was `ready`, the guard then computes the summary of what the lane changed and stores it as the lane's `changes`
  (The changes summary); a repeated update keeps the stored `changes` and runs none of the Git commands of the summary.
- **active, blocked.** No condition; `--head` is refused (exit 24). A lane that is `ready` and returns to `active`
  keeps its head and its `ready_target` until it is marked ready again. A lane that leaves `integrated` for
  `blocked` has its `changes` set to null: the record no longer states that it was merged.

Success writes the record only (the lane's `state`, `head`, `ready_target`, `changes`, `note`, `updated`, the record's `integration`,
`revision` + 1, `updated`, `by`), as one atomic replace; every other byte of the record is unchanged. Result (`--json`):
`{decision, code, set, lane, state, head, changes, note, integration, revision, warnings, message, exit_code}` where
`changes` is the lane's stored summary after the call (null unless the lane is `integrated`); a refusal
carries the keys of its exit as Result keys below lists them (`blocked: [{lane, reason, files}]` for exit 16 (each `files` empty: no reason of `set-update` names a file), `lane`, `files`
and `truncated` for exit 22, `errors` for exit 24, `kind`, `expected` and `current` for exit 19, `unknowns` for exit 11).
Every exit 24 of `set-update`, before the lock and under it, is printed in the neutral frame `set_invalid_args`.

### The changes summary

When `set-update --state integrated` records a lane that was `ready`, the guard stores in the lane's `changes` an
objective summary of what the lane changed, computed from git at that moment inside the call (under the lock, on the
budget of the call, after every condition of `integrated` holds), so that after the merge the command can print the
original list again with the result added to it. The summary is stored when the lane becomes `integrated` and kept until
the lane leaves that state (Lifecycle below).

*What is measured.* The compare tip `ref` is the current tip of the local branch `refs/heads/<target>` of the record,
resolved once to a full object name; the lane tip is the head recorded at ready (equal to `--head`). When that head is
already an ancestor of `ref` (the lane was landed before it was recorded, so `ref..head` would be empty; the answer is
the one the ancestry condition of `integrated` already gave, which asks the target's tip first and the tip of the
integration branch second, so the summary runs no further command for it), the lane's `ready_target` (the commit its `ready` was measured against; the plan's `base` when it is null) is the
compare tip instead, so that the summary describes the lane's work and not an empty range: `integrated` requires the
head recorded at that `ready`, so `<ready_target>..<head>` holds the lane's own commits, and a commit the target held
at that `ready`, which the lane took in by merging the target tip (the remedy of a stale plan and of a predicted
conflict) or by a fast-forward to it, is no lane commit and its files are no lane files. Four commands,
all read-only members of `LOCAL_GIT`, with `<ref>` and `<head>` full object names, so that every command sees one state:

```
git merge-base <ref> <head>
git rev-list --count --no-merges <ref>..<head>
git log --ignore-submodules=none --no-show-signature --encoding=UTF-8 --format=%s --reverse --no-merges --skip=<max(commits - 8, 0)> --max-count=8 <ref>..<head>
git diff --ignore-submodules=none --numstat -z --find-renames --no-ext-diff --no-textconv <ref>...<head> --
```

The first command only asks whether the two share history (the command `committed_paths` uses: exit 1 means none, see
Failure). The second gives the number of commits of the lane: its non-merge commits only, because a merge commit is no
lane work (the lane owner's merge of the target tip into the lane, which the remedy of a stale plan asks for, and any
other merge are left out of the count and of the subjects). The third reads the eight oldest of those commits, oldest
first: `--no-merges` filters before `--skip` and `--max-count` count, and both apply before `--reverse`, so a skip of
`commits - 8` selects the oldest eight non-merge commits (a lane of at most eight non-merge commits is read whole, and
the command is not run when `commits` is 0, also for a range that holds only merges). The fourth compares the head
with the merge base of `ref` and the head, so a lane that merged the target into itself is not charged with the
target's files (with several merge bases Git uses one and warns on stderr, which is ignored); it is the net change of
the lane, merges included, so a
change made in a merge commit itself counts as a file and as lines. Besides `--no-merges`, `--skip` and `--max-count`,
which select the commits, the flags beyond the bare `git log --format=%s --reverse` and `git diff --numstat` make the
result independent of the user's configuration:
`--no-show-signature` and `--encoding=UTF-8` of `log.showSignature` and `i18n.logOutputEncoding`, `-z` of
`core.quotepath` (a path with spaces, quotes or non-ASCII characters is read exactly), `--find-renames` of
`diff.renames`, `--ignore-submodules=none` (as on every `diff`, `log` and `status` call of the guard, part 2) of
`diff.ignoreSubmodules`, `submodule.<name>.ignore` and the `ignore` of `.gitmodules`, so a changed gitlink is a file of the
summary (one line added for a new gitlink, one added and one removed for a moved one), and `--no-ext-diff --no-textconv`
start no helper program. The `-c diff.relative=false` that every guard
call carries (part 2) reads every path from the top of the work tree, so `files`, `insertions`, `deletions` and `paths`
describe the whole lane whatever directory below the top `--repo` names.

*The object* (keys in this order, no other key):

```
{"commits": int, "subjects": [str], "more": int, "files": int, "insertions": int, "deletions": int,
 "paths": [str], "paths_more": int}
```

- `commits` is the output of `rev-list --count --no-merges`: the non-merge commits of `<ref>..<head>`.
- `subjects` holds at most 8 commit subjects (`%s`: the first paragraph of the message with its line breaks folded
  into spaces, which is its first line for a message that follows the convention), oldest first, each at most 100
  characters (a longer subject is cut to 99 characters followed by `…`); every control character in a subject is
  replaced by a space, blanks at its ends are removed and a subject that is empty after that is stored as `(no subject)`.
  `more` is `commits - len(subjects)`: the non-merge commits not listed (a merge commit is neither listed nor counted
  in `more`).
- `files`, `insertions` and `deletions` are the net change from the merge base to the head (the `diff`), not a sum over
  the commits: a file added and then edited is one new file with its final lines. `files` is the number of records of the
  `diff`: a rename or a copy is one record and one file, named by its new name, and a file with only a mode change is one
  file with no line. `insertions` and `deletions` are the sums of the numstat columns; a binary file shows `-` in both,
  counts as one file and adds no line.
- `paths` holds at most 12 distinct keys in the order of the first changed file that has them (Git lists the files in
  path order). The key of a file is its first two path segments joined by `/` (`src/api/x.py` gives `src/api`, `src/x.py`
  gives `src/x.py`), and a file in the repository root is its own key (`README.md`). `paths_more` is the number of
  distinct keys beyond those listed. Names are decoded as UTF-8 with replacement and every control character is replaced
  by a space.
- A lane that changed nothing (no commit, no file) stores zeros, empty lists and `paths_more` 0. A lane whose commits in
  the range are all merges stores `commits` 0 and no subject, and its `files`, `insertions` and `deletions` are still
  the net change (zero for a plain merge of the target tip, the merge's own change otherwise).

*Failure (fail closed).* The call writes nothing (no record, no audit line) and the lane stays `ready`, so the same
call can be repeated once the cause is removed: exit 11 UNKNOWN `TARGET_UNCERTAIN` (`set_why_changes_target`) when the
local branch `refs/heads/<target>` does not exist, because there is nothing to measure against and the plan's `base`
does not stand in for it here; exit 11 `GIT_FAILED` when one of the commands fails, and `BUDGET_EXCEEDED` when the
budget runs out; exit 16 `NO_MERGE_BASE` (`set_why_changes_history`) when `merge-base` finds that the compare tip and the
head share no history.

*Lifecycle.* Only the transition from `ready` to `integrated` computes the summary. A repeated `integrated` update keeps
the stored `changes` byte for byte whatever the repository looks like by then, even when the target branch is gone, and
replaces the note. `integrated` to `blocked` sets `changes` to null; a lane that comes back through `active`, `ready` and
`integrated` gets a new summary. An amend carries `changes` over with the state and the head of a surviving lane.

*Where it shows.* The summary is part of the record (`lanes[].changes`), of the result of the update (`changes`), of
`set-show --json` (`record.lanes[].changes` and `view.lanes[].changes`, the same object or null), of the text view of
`set-show` (one line per integrated lane with `changes`) and, as counts, of the audit line of the update.

### set-show

`set-show --set NAME [--drift]` is read-only, takes no lock and exits 0 with the record and its derived view (exit 21
unknown, 23 newer, 11 unreadable, 24 an invalid `--set` in the neutral frame `set_invalid_args`). `--json` prints `{decision, code, record, view, warnings, message, exit_code}`, where
`record` is the stored record as read and `view` is:

- `target_tip` (the tip of the local target branch, null when it no longer exists) and `target_moved` (the tip differs
  from `base`; null when the branch is missing);
- `lanes`, in the record's order, each with `id` and: `branch_exists`, `tip` (null without a branch), `ahead`
  (`rev-list --count <base>..<tip>`; null without a branch), `descends_from_base` (the base is an ancestor of the tip;
  informational, since a lane need not descend from the base: an amendment moves the base and no command gates on it),
  `worktree_present` (a worktree at the lane's path or on its branch that is not prunable), `worktree_clean` (null when
  there is none; false when any of those worktrees has uncommitted changes or a `git status` of it exits non-zero),
  `operation` (the operations in progress of every one of those worktrees as `operation` reads them, each named once,
  with `unreadable` when the metadata of one cannot be read), `state`, `head` (as recorded), `claim` (`ok`, `missing`, or `mismatch` when the claim of
  the branch lacks `set=<name>` or `lane=<id>`, its entries differ from the record's `paths`, its worktree is empty or another path than the
  record's (compared with `pkey`), it carries an override fingerprint, or it cannot be read or comes from a newer MAGOS)
  and `changes` (the lane's stored summary of The changes summary, the same object as `record.lanes[].changes`, or null
  until the lane is recorded `integrated`; it is read from the record, never recomputed);
- `requirements`, in the record's order: `{id, text, lanes}` with `lanes` the ids of the lanes that serve the requirement,
  in lane order (Coverage rules), so a caller renders the table of requirements and lanes from one object;
- with `--drift` the lanes also carry `changed` (the files the lane changed, measured as `set-update` measures them,
  sorted: committed changes only, the uncommitted ones are shown by `worktree_clean`; null without a branch, and null
  when there is no common history with the target, which adds the warning `UNRELATED_HISTORY`), `out_of_lane` (the files of
  `changed` that no entry of the lane's manifest matches) and `moved_since_ready` (true when the state is `ready` and the
  tip is not the recorded head, false otherwise, null without a branch), and `view` carries the object `drift` with the
  fields `shared_changes` (a list of `{path, lanes}`: every file that two or more lanes changed, with those lane ids),
  `target_overlap` (a list of `{path, lanes}`, in path order: the files changed by the target's commits since the plan's
  base that the set's own work does not hold, measured as *The target's own changes* below, that fall inside the
  manifest of at least one lane, with those lane ids; empty when the target did not move or is missing), `stale` (true
  when the target moved and `target_overlap` is not empty: the plan must be amended; false otherwise, null when the
  target branch is missing) and `merge_order` (the topological order of the lane ids, as defined under Other cross-field
  rules). `target_moved` states only that the tip differs from `base`, whatever commits moved it, so after the set's
  own land `target_moved` is true while `target_overlap` is empty and `stale` false. `warnings` is a list of `{code,
  text}`; `moved_since_ready`, `out_of_lane`, `changed` and `drift` exist only with `--drift`. A lane with no branch has
  `out_of_lane` empty and `changed` null.

*The target's own changes.* When the local target branch exists and its tip differs from `base`, the drift view runs one
Git command, a read-only member of `LOCAL_GIT`, with full object names:

```
git log --ignore-submodules=none --no-show-signature -z --format= --name-only --no-renames --diff-merges=dense-combined --ignore-missing <target tip> --not <base> <integration tip> <head>...
```

- The commits it lists are those of the target that are not in the plan's `base` and not reachable from the set's own
  work: the negative revisions after `--not` are `base`, the tip of the local branch `agent/<set>/integration` when that
  branch exists (read from the refs, whether or not the record names it yet; left out when it does not exist) and the
  recorded `head` of every lane in state `ready` or `integrated`, in the record's lane order (a lane in another state
  adds none, also when it keeps a head from an earlier `ready`). `<target tip> --not <base>` is the range
  `<base>..<target tip>`, written with `base` among the negative revisions so that `--ignore-missing` treats a base
  that no longer names an object like a missing head (it excludes nothing) and never drops the range as a whole.
- So the set's own land adds nothing: a fast-forward of the target to the integration branch brings only commits the
  integration tip holds, and a land merge is listed by its own changes alone. The integration branch is cut from the
  target tip at the start of the convergence and the lanes are merged on top of it, so the target commits it holds
  are left out too, and so are the target commits that a lane owner merged into the lane before recording `ready`. The
  exclusion is by reachability from the set's work as a whole, not per lane: a target commit that one lane head or the
  integration branch holds is left out for every lane, also for a lane whose own branch does not contain it.
- Each listed commit names the files it changed against its parent. A merge commit is listed by its own changes only
  (`--diff-merges=dense-combined`: the files whose merge result differs from every parent, such as a conflict
  resolution or a change made in the merge itself): the merge of another branch into the target adds nothing beyond
  that, and the commits of the merged branch are listed by themselves. A rename names both paths (`--no-renames`).
- The output is the NUL-separated paths (`-z`: every name exactly as Git stores it, never quoted, with `core.quotepath`
  and `diff.relative` off as on every guard call, so every name is the path from the top of the work tree whatever
  directory below it `--repo` names); the distinct non-empty names are tested against the lane manifests in sorted order.
  `--no-show-signature` keeps `log.showSignature` from adding lines to the output, and `--ignore-submodules=none` lists
  every gitlink a commit changed, whatever `diff.ignoreSubmodules`, `submodule.<name>.ignore` or the `ignore` of
  `.gitmodules` says.
- `--ignore-missing` makes a negative revision that no longer names an object (a recorded head pruned after its branch
  was reset or deleted, a base gone with a replaced target history) exclude nothing, so the call succeeds and the
  answer can only grow: a base that no longer exists counts the target's history down to the set's own work, never an
  empty listing. The target tip and the integration tip are read from the refs of the same call.
- A failure of the command ends the call with exit 11 (`GIT_FAILED`), and an exhausted budget with exit 11
  (`BUDGET_EXCEEDED`), as for every Git command of `set-show`; nothing is written either way.

Paths are tested against the lane manifests through an index, so a drift
view over thousands of files stays within the budget (exhausted: exit 11, `BUDGET_EXCEEDED`): an entry that names a literal file
or directory is a lookup of the prefixes of the path, every other entry is indexed by the folded literal first segment of each
alternative (an alternative that starts with a wildcard goes to a group that every path is tested against), and a path without
`*` or `?` is matched by a greedy glob walk of the size of the glob and the path; the result is exactly that of `path_hit`, and a
path that holds `*` or `?` is compared by the exact intersection. The text view prints the
header `show_head`, the stored sheet verbatim, one line per lane (`show_lane`: `[x]` for `ready` and `integrated`, `[ ]`
otherwise, the state, the recorded head and the tip abbreviated to 7 digits, the commits ahead, the worktree as `clean`,
`dirty`, an operation, `absent` or `unreadable`, the branch), directly below the line of every `integrated` lane whose
`changes` is not null the line `show_changes` (the commits, the files, `+<insertions>/-<deletions>`, the paths and the
subjects of the summary; a list that was cut ends with `show_more`, `+<n> more`, with the number of the commits or of the
paths not listed, and an empty list reads `-`) and, with `--drift`, the lines that are not empty:
`show_out`, `show_shared`, `show_moved` (with the overlap files), `show_moved_ready` and `show_order`. The text view
prints no table of requirements; the tables are the command's, built from the JSON.

### set-release

`set-release --set NAME [--reason R] [--abandon]` retires a set. Under the lock the record is read (exit 21, 23, 11),
then for every lane, and for the integration branch `agent/<set>/integration` (named `integration`), the guard
evaluates the same predicate `release` uses for a claim, against the record's target, with and without `--abandon`:
a lane or the integration branch has **unmerged work** when its branch exists and is not merged into the tip of the
local branch `target` of the record (when that branch no longer exists, no existing branch counts as merged), and a
**dirty worktree** when a worktree on that branch or, for a lane, at the registered path, a prunable one included,
has uncommitted changes (a `git status`
that exits non-zero counts as dirty, and a worktree whose directory is missing, such as a locked worktree on an
unmounted drive, is dirty with the text `set_why_wt_missing`; a Git that cannot run at all, a working directory that is
gone or an exhausted budget ends the call with exit 11). Without `--abandon` every lane must also be in
state `integrated`; with `--abandon` the state does not matter. Each failing lane is named with its reason
(`NOT_INTEGRATED`, `UNMERGED_WORK`, `DIRTY_WORKTREE`, `CLAIM_UNUSABLE` for a lane claim, or the integration claim (named `integration`), that is unreadable or of a newer
format) and any of them is exit 16 (BLOCKED, `set_blocked`) with nothing written. The items
come lane by lane in record order, then those of the integration branch (the texts `set_why_unmerged`,
`set_why_dirty` and `set_why_wt_missing` with `{l}` `integration`), and the `CLAIM_UNUSABLE` items last. A lane branch
or an integration branch that no longer exists has no unmerged work. So a set whose lanes were integrated and landed
releases, a lane that changed nothing is "not needed", and `--abandon` drops a plan whose branches, the integration
branch included, hold nothing that is not in the target: an integration branch with merges that never reached the
target keeps the set until it is landed or the user deletes it.

When nothing blocks, one transaction deletes the claim of every lane and the integration claim (each only when it
exists, lies inside `<store>/claims`, carries `set=<name>` and is the claim of the stored branch, as `release` checks; a
claim of that branch that belongs to another set or to none is left alone and reported as a warning) and then the record.
The call prints `set_released` with the number of claims it removed, and appends the audit line with `--reason`.
`--reason` is at most 200 characters (`RANGE`) with no lone surrogate (`ENCODING`) and no control character (`FORMAT`),
the rules of `--note`, so the audit line can always be written; an invalid `--set` and an invalid `--reason` are checked
before the lock and are exit 24 in the neutral frame `set_invalid_args`, as one denial when both fail. The guard never removes a branch, a
worktree or a file of the work tree. The claims
of a set that is released stop blocking `/GitCleanup`, `/GitConverge` and `/GitSweep`; while the set is open they block
them as `BLOCKED_ACTIVE_OWNER`, as every open lane claim does. Result (`--json`): `{decision, code, set, abandoned,
released: [branch], warnings, blocked: [{lane, reason, files}], message, exit_code}`, each `files` of `blocked` empty: no reason of `set-release` names a file.

### Exit codes and messages

The exit table `EXIT` gains `STALE` 19, `SET_EXISTS` 20, `SET_UNKNOWN` 21, `OUT_OF_LANE` 22, `SET_NEWER_FORMAT` 23 and
`INVALID_SPEC` 24; `CONFLICT` 10, `UNKNOWN` 11, `LOCK_TIMEOUT` 13, `LANE_EXISTS` 14, `BRANCH_EXISTS` 15 and `BLOCKED` 16
keep their meaning, and `INVALID_MANIFEST` 12 is used for a branch name or worktree path that clashes with the
repository. The rule: a spec or option value that is invalid in itself is 24 and names the field; a failure that the
repository or the record causes keeps the existing code. The verdict `code` and the process exit code agree.

**Result keys (`--json`).** Every result of a set command carries `decision`, `code`, `message` and `exit_code`, where
`code` is the `EXIT` name of the exit code (`OK` for 0, then `CONFLICT`, `UNKNOWN`, `INVALID_MANIFEST`, `LOCK_TIMEOUT`,
`LANE_EXISTS`, `BRANCH_EXISTS`, `BLOCKED`, `STALE`, `SET_EXISTS`, `SET_UNKNOWN`, `OUT_OF_LANE`, `SET_NEWER_FORMAT`,
`INVALID_SPEC`); a denial adds only the keys of its exit, and a caller reads nothing else of it:

| Exit | Extra keys |
| --- | --- |
| 10 | `overlaps` (two lanes of the plan) or `lanes` (per lane `id`, `branch`, `code`, `conflicts`, `unknowns` of the judgement against other claimants) |
| 11 | `unknowns: [{code, text}]` of the call itself (`TARGET_UNCERTAIN` also when `set-update --state integrated` finds no target branch to measure the changes against, `SET_UNREADABLE`, `BUDGET_EXCEEDED`, `GIT_FAILED`, `INTERNAL_ERROR`), or `lanes` when the judgement found only unknowns |
| 12, 14, 15, 24 | `errors: [{field, code, text}]` (`field` a path such as `lanes[2].branch` or `requirements[1]`; `code` `BRANCH_NAME`, `WORKTREE`, `LANE_EXISTS`, `BRANCH_EXISTS` or a code of Other cross-field rules, among them `GENERIC_ID`, `RESERVED`, `BRANCH_FORM`, `WORKTREE_FORM`, `UNKNOWN_REQUIREMENT`, `UNSERVED` and `DUPLICATE` (also for an entry of a lane manifest, `lanes[i].paths[j]`); `text` in the language of the call for the naming codes, the `FORMAT` of `--set` included, and the coverage codes) |
| 16 | `blocked: [{lane, reason, files}]`, one shape for every exit 16 of `set-plan --amend`, `set-update` and `set-release`, built by the one function `refuse16` from the items (lane, reason, the text of the reason and, when it names files, those files): `reason` is one of `UNMERGED_WORK`, `DIRTY_WORKTREE`, `SHRINK`, `BRANCH_MISSING`, `HEAD_MISMATCH`, `OPERATION_IN_PROGRESS`, `NO_MERGE_BASE` (at `ready`, and at `integrated` when the changes cannot be measured), `NOT_MERGED`, `NOT_INTEGRATED`, `CLAIM_UNUSABLE`, and `files` is a list, empty when the reason names no file; only `set-plan --amend` names files: the uncommitted files for `DIRTY_WORKTREE` and the files of the commits of a detached lane worktree for `UNMERGED_WORK` (at most 20 each), and the files outside the new manifest for `SHRINK` (at most 200) |
| 19 | `kind` (`base` or `revision`), `expected`, `current` |
| 20 | `current` (the record's revision) |
| 22 | `lane`, `files`, `truncated` |
| 21, 23 | none beyond the common keys |

The messages are entries of the table `M` (`T(lang, key, **fields)`), zh first and en second:

| Key | zh | en |
| --- | --- | --- |
| `set_invalid` | MAGOS：set 规划无效，未登记也未创建任何东西：\n{errors} | MAGOS: the set plan is invalid, nothing registered or created:\n{errors} |
| `set_invalid_args` | MAGOS：参数无效，未做任何修改：\n{errors} | MAGOS: invalid arguments, nothing was changed:\n{errors} |
| `set_stale_base` | MAGOS：计划已过期，未写入任何东西：目标 {t} 现在位于 {live}，而计划基于 {base}。请重新调查仓库后再规划。 | MAGOS: the plan is stale, nothing was written: target {t} is now at {live}, but the plan was made against {base}. Investigate the repository again and re-plan. |
| `set_stale_revision` | MAGOS：计划已过期，未写入任何东西：set「{s}」现在是修订 {cur}，而你基于修订 {exp}。请先用 set-show 重新读取。 | MAGOS: the plan is stale, nothing was written: set '{s}' is at revision {cur}, not {exp}. Read it again with set-show. |
| `set_exists` | MAGOS：set「{s}」已存在（修订 {rev}）。用 --amend --expect-revision {rev} 修改，或先 set-release。 | MAGOS: set '{s}' already exists (revision {rev}). Change it with --amend --expect-revision {rev}, or release it first with set-release. |
| `set_unknown` | MAGOS：没有名为「{s}」的 set。 | MAGOS: there is no set named '{s}'. |
| `set_out_of_lane` | MAGOS：拒绝把 lane {l} 标记为 ready：下列文件在它的 manifest 之外：{files}。请在该 lane 中撤销这些改动，或用 /GitPlan {s} --amend 修改计划。 | MAGOS: refused to mark lane {l} ready: these files lie outside its manifest: {files}. Revert them in the lane, or amend the plan with /GitPlan {s} --amend. |
| `set_newer` | MAGOS：set「{s}」由更新版本的 MAGOS 写入（v={v}）：请升级本守卫（doctor 显示版本，install 刷新副本），或用写入它的那个 MAGOS 执行这条命令。 | MAGOS: set '{s}' was written by a newer MAGOS (v={v}): upgrade this guard (doctor shows its version, install refreshes the copy), or run this command with the MAGOS that wrote it. |
| `set_unreadable` | MAGOS：set 记录 {f} 无法读取，未做任何修改；请用户检查该文件。 | MAGOS: the set record {f} cannot be read; nothing was changed. The user must inspect the file. |
| `set_conflict` | MAGOS 拒绝登记 set「{s}」：下列 lane 的 manifest 与其他 lane 或已有分支重叠，或无法分析。没有登记也没有创建任何东西。 | MAGOS DENIES registering set '{s}': the manifests of the lanes below overlap other lanes or existing branches, or could not be analysed. Nothing was registered or created. |
| `set_overlap` | lane {a} 与 lane {b} 的 manifest 重叠：{pairs} | lane {a} and lane {b} overlap: {pairs} |
| `set_lane_item` | lane {l}（分支 {b}）： | lane {l} (branch {b}): |
| `set_options` | 可选处理：① 缩小或拆分重叠的 lane；② 等对方合入 {target} 后再规划；③ 对方若已合并或已放弃，用 release 释放它的登记（未合并的工作不会被释放）。set-plan 不读取也不消耗用户覆盖（override）。 | Options: (1) shrink or split the overlapping lanes; (2) wait until the others are merged into {target}; (3) if the other lane is merged or abandoned, release its claim with release (unmerged work is never released). set-plan neither reads nor consumes an override. |
| `set_branch_exists` | MAGOS：lane {l} 的分支「{b}」已经存在且没有有效登记，不能事后补登记。请换一个新分支名。 | MAGOS: the branch '{b}' of lane {l} already exists without a claim; it cannot be registered after the fact. Choose a new branch name. |
| `set_lane_exists` | MAGOS：lane {l} 的分支「{b}」已有一份不属于这个 set 的登记。请先 release 它，或换一个分支名。 | MAGOS: the branch '{b}' of lane {l} already has a claim that is not this set's. Release it first, or choose another branch name. |
| `set_ok_plan` | MAGOS：已登记 set「{s}」：{n} 个 lane，目标 {t}，基线 {base}，修订 {rev}。现在可以从基线逐个创建 lane，例如：{example} | MAGOS: registered set '{s}': {n} lanes, target {t}, base {base}, revision {rev}. You may now create the lanes from the base, e.g.: {example} |
| `set_ok_amend` | MAGOS：已修改 set「{s}」：修订 {old} → {rev}，{n} 个 lane。 | MAGOS: amended set '{s}': revision {old} -> {rev}, {n} lanes. |
| `set_ok_check` | MAGOS：set「{s}」的预览通过，没有发现重叠；这是 --dry-run，未写入任何东西。 | MAGOS: the preview of set '{s}' passed, no overlap found; this was a --dry-run and nothing was written. |
| `set_unchanged` | MAGOS：set「{s}」没有变化（修订 {rev}），未写入任何东西。 | MAGOS: set '{s}' is unchanged (revision {rev}); nothing was written. |
| `set_line` | lane {l}  分支 {b}  工作树 {w}  {n} 条路径 | lane {l}  branch {b}  worktree {w}  {n} entries |
| `set_line_integration` | 集成分支 {b} | integration branch {b} |
| `set_ok_update` | MAGOS：set「{s}」的 lane {l} 现在是 {st}，修订 {rev}。 | MAGOS: lane {l} of set '{s}' is now {st}, revision {rev}. |
| `set_released` | MAGOS：已释放 set「{s}」及其 {n} 份登记。 | MAGOS: released set '{s}' and its {n} claims. |
| `set_blocked` | MAGOS：拒绝 {op}：{why} | MAGOS: {op} refused: {why} |
| `set_why_state` | lane {l} 的状态是 {st}，不是 integrated | lane {l} is {st}, not integrated |
| `set_why_unmerged` | lane {l} 的分支 {b} 有未合并的工作 | the branch {b} of lane {l} has unmerged work |
| `set_why_dirty` | lane {l} 的工作树有未提交的修改 | the worktree of lane {l} has uncommitted changes |
| `set_why_wt_missing` | lane {l} 的工作树 {w} 在磁盘上缺失（例如已锁定但所在驱动器未挂载），无法确认其中没有未提交的工作 | the worktree {w} of lane {l} is missing on disk (for example locked on an unmounted drive), so it cannot be known to hold no uncommitted work |
| `set_why_operation` | lane {l} 的工作树正在进行 {op} | the worktree of lane {l} has a {op} in progress |
| `set_why_missing` | lane {l} 的分支 {b} 不存在 | the branch {b} of lane {l} does not exist |
| `set_why_head_tip` | --head {head} 不是分支 {b} 的当前提交 {tip} | --head {head} is not the tip {tip} of branch {b} |
| `set_why_head_recorded` | --head {head} 不是 lane {l} 在 ready 时记录的 head {rec} | --head {head} is not the head {rec} recorded for lane {l} at ready |
| `set_why_ancestor` | 提交 {head} 既不在 {t} 中，也不在集成分支中 | commit {head} is in neither {t} nor the integration branch |
| `set_why_shrink` | lane {l} 已经改动了新 manifest 之外的文件：{files} | lane {l} already changed files outside its new manifest: {files} |
| `set_why_claim` | lane {l} 的登记无法读取或来自更新版本的 MAGOS | the claim of lane {l} cannot be read or comes from a newer MAGOS |
| `set_why_integration` | 集成分支 {b} 不存在 | the integration branch {b} does not exist |
| `set_why_base` | lane {l} 与计划的基线没有共同历史 | lane {l} shares no history with the plan's base |
| `set_why_changes_target` | 目标分支 {t} 不存在，无法计算 lane {l} 的改动摘要 | the target branch {t} does not exist, so the summary of the changes of lane {l} cannot be computed |
| `set_why_changes_history` | lane {l} 与 {ref} 没有共同历史，无法计算改动摘要 | lane {l} shares no history with {ref}, so the summary of its changes cannot be computed |
| `set_err_generic_id` | lane id「{id}」是序号或泛称，看不出改动的主题。请改用 1 到 3 个单词的主题 slug（小写，连字符连接），例如 claim-store、sweep-readiness、readme-gitplan。 | lane id '{id}' is an ordinal or generic name and does not show the topic of the change. Name the topic with 1 to 3 words in kebab-case, for example claim-store, sweep-readiness, readme-gitplan. |
| `set_err_reserved_id` | lane id「{id}」是保留名：integration 属于集成分支 agent/<set>/integration，con、prn、aux、nul、com1 至 com9、lpt1 至 lpt9 是 Windows 设备名。请另选一个说明这个 lane 改动内容的主题 slug。 | lane id '{id}' is reserved: integration belongs to the integration branch agent/<set>/integration, and con, prn, aux, nul, com1 to com9 and lpt1 to lpt9 are Windows device names. Choose another topic slug that names what the lane changes. |
| `set_err_id_form` | lane id「{id}」不是主题 slug：必须匹配 {rule}（小写字母、数字、连字符，1 到 24 个字符，不以连字符开头），并用 1 到 3 个单词说明改动的主题，例如 claim-store。{hint} | lane id '{id}' is not a topic slug: it must match {rule} (lowercase letters, digits and hyphens, 1 to 24 characters, not starting with a hyphen) and name the topic of the change in 1 to 3 words, for example claim-store.{hint} |
| `set_hint_slug` | 建议：{slug}。 | Suggestion: {slug}. |
| `set_err_branch_form` | lane {l} 的分支必须是 {want}（agent/<set>/<lane id>），而不是「{got}」。请改用 {want}。 | the branch of lane {l} must be {want} (agent/<set>/<lane id>), not '{got}'. Use {want}. |
| `set_err_worktree_form` | lane {l} 的工作树目录名必须以 -{s}-{l} 结尾，而「{got}」不是。请改用，例如：{want}。 | the worktree directory of lane {l} must have a name ending with -{s}-{l}, which '{got}' does not. Use, for example: {want}. |
| `set_err_worktree_device` | lane {l} 的工作树目录名「{got}」在第一个点之前是 Windows 设备名 {dev}。请改用，例如：{want}。 | the worktree directory name '{got}' of lane {l} is the Windows device name {dev} before its first dot. Use, for example: {want}. |
| `set_err_unserved` | 需求 {r}（{t}）没有任何 lane 负责。请用一个 lane 负责它：把 {r} 加入某个 lane 的 serves，或为它新增一个 lane。不要删除用户提出的需求。 | requirement {r} ({t}) is served by no lane. Serve it with a lane: add {r} to the serves of a lane, or add a lane for it. Never drop a requirement the user stated. |
| `set_err_serves_unknown` | serves 里的「{r}」不是本规划 requirements 中的编号（已有：{ids}；编号逐字匹配，区分大小写）。 | '{r}' in serves is no requirement id of this spec (known: {ids}; ids are matched exactly, case included). |
| `set_err_serves_count` | lane {l} 的 serves 需要 1 到 12 个需求编号（现在 {n} 个）。 | the serves of lane {l} needs 1 to 12 requirement ids ({n} given). |
| `set_err_set_name` | set 名称「{s}」无效：必须匹配 {rule}（小写字母、数字、连字符，1 到 24 个字符，不以连字符开头），并说明任务的主题。 | the set name '{s}' is invalid: it must match {rule} (lowercase letters, digits and hyphens, 1 to 24 characters, not starting with a hyphen) and name the topic of the task. |
| `set_err_set_device` | set 名称「{s}」是 Windows 设备名，不能用作记录文件 sets/{s}.json 的名称。请另选一个说明任务主题的名称。 | the set name '{s}' is a Windows device name and cannot name the record file sets/{s}.json. Choose another name that names the topic of the task. |
| `lane_in_set` | MAGOS：分支「{b}」是 set「{s}」的 lane，不能单独修改它的登记。用 set-plan --amend 修改，或先 set-release。 | MAGOS: branch '{b}' is a lane of set '{s}'; its claim cannot be changed on its own. Use set-plan --amend, or set-release first. |
| `blocked_set` | MAGOS：拒绝 release：「{b}」是 set「{s}」的登记。请用 set-release 一并释放。 | MAGOS: release refused: '{b}' belongs to set '{s}'. Retire the whole set with set-release. |
| `show_head` | set「{s}」→ {t}　基线 {base}　修订 {rev}　集成分支 {i} | set '{s}' -> {t}  base {base}  revision {rev}  integration {i} |
| `show_lane` | {box} {l}　{st}　记录 {head}　当前 {tip}　领先 {n}　工作树 {wt}　分支 {b} | {box} {l}  {st}  head {head}  tip {tip}  ahead {n}  worktree {wt}  branch {b} |
| `show_out` | 越界文件（{l}）：{files} | outside the manifest ({l}): {files} |
| `show_shared` | 多个 lane 改动的文件：{files} | changed by more than one lane: {files} |
| `show_moved` | 目标已从 {base} 移到 {tip}；与 lane 重叠的文件：{files} | the target moved from {base} to {tip}; files that overlap lanes: {files} |
| `show_moved_ready` | ready 之后分支又移动：{lanes} | moved since ready: {lanes} |
| `show_order` | 合并顺序：{order} | merge order: {order} |
| `show_changes` | 改动 {l}：{commits} 个提交，{files} 个文件，+{ins}/-{del}；路径 {paths}；{subjects} | changes {l}: {commits} commits, {files} files, +{ins}/-{del}; paths {paths}; {subjects} |
| `show_more` | 另有 {n} 项 | +{n} more |

The words of `show_lane` that stand for the worktree are `干净`/`clean`, `有未提交修改`/`dirty`, `{op} 进行中`/`{op} in
progress`, `缺失`/`absent` and `无法读取`/`unreadable`; the lane states are the identifiers `planned`, `active`, `ready`,
`integrated` and `blocked` in both languages. The lines of `set_line` and `set_line_integration` are indented by two spaces
and the line of `show_changes` by four. A usage error is argparse's own text and exit 2. The generic Git-failure
and internal-error lines of Errors (exit 11) apply to every set subcommand.

The messages with a name to correct state the compliant form, except `set_err_reserved_id`, which asks for another
topic slug that names what the lane changes and names no example, and `set_err_set_device`, which asks for another
name. `T` formats with `str.format`, so an entry holds no literal brace: `set_err_id_form` and `set_err_set_name` take
the parameter `{rule}` for the text `[a-z0-9][a-z0-9-]{0,23}`, and `set_err_id_form` also `{hint}`, which is empty or
one space followed by the text of `set_hint_slug` (the slug that lower-casing the id and replacing `_` by `-` gives,
when it is valid). In `set_err_set_name` and `set_err_set_device` `{s}` is the `--set` value as messages show a value
of the spec (control characters as spaces, a lone surrogate as U+FFFD, cut to 80 characters). In `set_ok_plan` `{base}` is the full base and
`{example}` the creation command of set-plan (Result); in `set_ok_check` and `set_out_of_lane` `{s}` is the set name.
`set_invalid` frames the exit 24 and exit 12 of `set-plan` and `set_invalid_args` every exit 24 of `set-show`,
`set-update` and `set-release`; `{errors}` is the `[CODE] field: text` lines in both. In `set_err_branch_form` `{want}` is `agent/<set>/<id>` of the lane and `{got}` the
branch of the spec; in `set_err_worktree_form` and `set_err_worktree_device` `{got}` is the directory name of the spec
(`{dev}`, in the second, is its text before the first `.`) and `{want}` the default path `<parent of the main worktree>/<repo dir name>-<set>-<id>` with `/` separators; in
`set_err_unserved` `{t}` is the text of the requirement cut to 60 characters; in `set_err_serves_unknown` `{ids}` are the
requirement ids of the spec; in `set_err_serves_count` `{n}` is the number of ids given. The texts of the errors `GENERIC_ID`, `RESERVED`, `FORMAT` (of an id, and of `--set`), `BRANCH_FORM`,
`WORKTREE_FORM`, `WORKTREE` (of a device name), `UNSERVED`, `UNKNOWN_REQUIREMENT` and `RANGE` of `serves` are these
entries, in the language of the call; `set_why_changes_target` is the text of the unknown `TARGET_UNCERTAIN` of a missing
target at `integrated` (the message of that exit 11 is the text), and `set_why_changes_history` is the reason of the
exit 16 `NO_MERGE_BASE` at `integrated` (`set_blocked` with the operation `set-update`).

### Hook, list, doctor and the plain commands

- **Hook.** `_USER_ONLY` is unchanged: `set-plan`, `set-show`, `set-update` and `set-release` are no user-only
  subcommand, so `protected()` lets a guard word followed by them through, in every spelling of the global options, behind
  the launcher or a wrapper. A spec passed on stdin by a here-document or an echo pipe (its text may hold `->`, `.git/magos`
  or a branch command) is not a write to the guard's state and creates nothing. Direct writes stay denied: a writer or a
  redirect aimed at `.git/magos/sets/<set>.json` (relative or the absolute store path in any separator or case spelling) is
  `PROTECTED` once the repository is armed or holds a claim, like a write to a claim file. The creation of a lane branch
  or worktree after `set-plan` is judged by the existing creation check against the lane's claim, its registered
  worktree path (`path_mismatch` for another path) and the set's target: for a claim that carries `set=`, the judgement
  resolves the target stored in the claim (`target=`, the target `set-plan` proved the lanes against) instead of the
  repository's default target, and a stored target that no longer resolves denies as UNKNOWN; a claim without `set=`
  is judged against the default target as before. The creation of `agent/<set>/integration` is judged for its name and
  the existence of the integration claim only, in an AUTO-engaged and in an armed repository alike, whatever the
  manifests of the lanes (Integration claim); the git layer finds the claim file of each name. An overlapping creation
  of an unrelated branch, and the creation of a branch that has no claim, is still denied.
- **list.** The `set` and `lane` (or `role`) of a claim as listed under Public Contract: the text row is the state padded to eight
  characters, then ` set <name>/<lane>` (or ` set <name>/integration`, or ` set <name>`), then the branch and the entries, for example
  `active   set demo/api agent/demo/api  [src/api/]`; with `--drift` the integration claim has an empty `drift`.
- **doctor.** When `sets/` holds any file or any claim carries `set=`, doctor prints `sets: <n>, unreadable: <n>,
  newer-format: <n>` after the claim line and then one line per problem, each a problem for the exit code: a set whose
  lane claim is missing or whose `set=`, `lane=`, entries or worktree differ from the record or that carries an override
  fingerprint (`set <s> lane <l>: claim missing` or `claim differs`, the `missing` and `mismatch` of set-show); a lane in state `active` or `ready` whose branch no longer exists (`branch vanished`; a `planned`,
  `integrated` or `blocked` lane without a branch is no problem); a set whose target branch no longer exists; claims that
  carry `set=<s>` while no record file `<s>` exists (`claims of set <s> without a record: <branches>`, the interrupted
  registration; a record that exists but cannot be read has a line of its own, and `release --branch` refuses its claims); a
  newer-format or unreadable record (`set record sets/<s>.json was written by a newer MAGOS (v=N): upgrade this guard (doctor shows
  its version, install refreshes the copy)` and `unreadable set record sets/<s>.json`; the name of the file is shown as
  messages show a value of the spec, control characters as spaces and a lone surrogate as U+FFFD, with a limit of 255
  characters, so no file name is cut). A problem line is indented by two spaces; the
  target line reads `set <s>: the target branch <t> no longer exists`. The line of orphan
  claims (`claims without a branch or planned worktree`) leaves out the integration claim of a set that has a record. A
  repository without sets prints what 1.0.3 printed, the version aside.
- **plan and release** refuse the claims of a set as Public Contract says; `check` is unchanged.

### Compatibility, limits and cost

- A claim of a set is an ordinary claim of format 1: a guard of 1.0.3 reads it, judges its entries as declared
  manifests for every other lane, keeps `set=`, `lane=` and `role=` when it amends the claim, and the git layer reads line 1
  as before. A guard of 1.0.3 has no set subcommand (a usage error, exit 2), does not show sets in `list` or `doctor`, and
  cannot refuse `release` or `plan --amend` of a set claim, or its re-plan after an override, so a set whose claims an
  older guard changed shows `mismatch` or `missing` in `set-show` and in `doctor` (a worktree emptied by a 1.0.3 amend
  or re-plan without `--worktree` and a stored override fingerprint included). A guard of 1.0.3 also has no exemption: it judges the marker entry of an
  integration claim as the declared manifest of a lane, so a hook that runs it denies the creation of a lane whose
  entries can match a path under the marker (`**/*.md`) and judges the creation of the integration branch against the
  lanes. `/GitPlan` checks `version` first and stops below 1.0.4, and `install` refreshes the Codex and Hermes copies.
- Limits: 12 lanes, 12 requirements of 8 characters of id and 200 of text, 12 requirement ids in `serves`, a lane id of
  24 characters, an outcome of 300 characters, 200 entries per lane, 1,024 characters per entry, 64 shared paths, 5
  notes, a sheet of 8,192 characters, a spec of 4 MiB, 20 error lines, 20 overlap pairs, 200 files in an OUT_OF_LANE
  listing, a summary of changes of at most 8 subjects of 100 characters and 12 paths, revisions of 1 to 999,999,999 as
  an option. A set of 12 lanes with 200 entries each registers within the 18 s budget when the lanes own distinct
  directories, also when they all sit below one top directory: validation and the pairwise proof are indexed, the snapshot is gathered once, the claims outside the set are parsed once, and the judgement is one
  `evaluate` per lane over the files of the claimants that the lane's manifest index matches, so an unmerged branch of
  thousands of files outside the lanes costs one index test per file and lane for the literal entries (no wildcard and
  no `[...]` group), while a glob entry, or one that holds a `[...]` group (indexed like a glob through the alternative
  that reads the group as `?`), is tested against every such file under its literal first segment and an entry whose first segment holds a
  wildcard or is `**` against every such file; an amend tests the files a started lane changed against its new
  manifest through the same index. Glob entries whose literal first segment holds many such files, and a spec whose
  entries all start with a wildcard, need that many comparisons and may exhaust the budget, which ends the call with
  exit 11 and no write. The summary of the changes of a lane costs four read-only Git
  calls of that call's budget; the output of `diff` grows with the number of changed files and is read whole, so an
  exhausted budget ends the call with exit 11 (`BUDGET_EXCEEDED`) and no write. The drift of the target costs one `log`
  call, whose output grows with the target's commits since the base that the set's work does not hold, and is read
  whole on the budget of `set-show`.
- Audit lines (one JSON line each, appended to `<store>/audit.log` under the lock after the write, with `ts`, `by` and
  `host` `cli` as for `plan`): `set-plan` (`set`, `target`, `base`, `revision`, `requirements` as the ids, `lanes` as
  `{id, branch, worktree, entries, serves}`, `integration`), `set-amend` (the same with `revision` the new one,
  `previous_revision` and `removed` lane ids), `set-update` (`set`, `lane`, `state`, `head`, `note`, `integration`,
  `revision`, and `changes`: `{commits, files, insertions, deletions}` of the stored summary, null unless the lane is
  `integrated`; the subjects and paths are in the record) and `set-release` (`set`, `revision` (the record's),
  `reason`, `abandon`, `lanes` as ids, `claims` as the removed branches). A refusal, among them every fail-closed
  refusal of the changes summary, appends none. A set command builds its audit line, `by` and the UTF-8 bytes included,
  before its write, so a field that cannot be encoded or a Git failure while reading the user ends the call before
  anything is written; once the write is made, a failure to append the line leaves the change in place and adds the
  warning `AUDIT_NOT_WRITTEN` (naming the error) to the success, which therefore never reads as a failed call.
- Known limits are below and in `references/lane-split.md`: sets live in one clone; semantic coupling between files is
  not detected; the claims of an older guard cannot see the set.

## Approval (version 1.0.7)

The user-only subcommands (`override`, `arm`, `disarm`, `install`) run only when the user approves them. The user
approves a run in one of two ways. In a real terminal: the console gate, and for `override` the retyped fingerprint, on
every host and at every level. Or, in Claude Code, by a click in Claude Code's own permission dialog: the host hook
opens it for exactly one direct invocation of this guard, and the host then runs a command that carries a one-time
approval token. In Codex the user approves by a click in Codex's own dialog through the MCP approval server, and the
Codex hook names that route when it denies (Codex approval (version 1.0.8)). In Hermes the MAGOS Hermes plugin hands the
same command and a guard-written question to Hermes's own approval prompt (Hermes approval (version 1.0.8)); the Hermes
entry under `hooks:` denies every user-only command with the `protected` text.

### Registry and levels

- `USER_ONLY` is the one table of the user-only subcommands, one row (`name`, `auto_safe`, `scope`) each: `override`
  (no, `repo`), `arm` (yes, `repo`), `disarm` (no, `repo`) and `install` (yes, `home`). The tamper filter reads its
  names (`_USER_ONLY`), the argument parser gives each of them the hidden option `--approval`, and `user_only_row` maps
  a parsed invocation to its row. `auto_safe` marks a subcommand that adds protection or copies the guard and weakens
  nothing; `scope` names its approval store.
- `magos.approval` is read like `magos.guard`: from the repository's own config (`git config --local`; `-c`,
  `GIT_CONFIG_*` and the global and system files cannot set it), its last value when the key has several, compared
  without regard to case and surrounding blanks. `terminal`: the hook denies, and the user runs the command in their
  own terminal. `prompt`, also when the key is unset: the hook asks. `auto-safe`: the hook allows `arm`, and `install`
  when its destination is the default guard home and it carries no `--allow-downgrade`, and asks for every other subcommand. Any other value counts as
  `terminal`, and `doctor` reports it as a problem. The value that applies is that of the repository the guard command
  names: its `--repo` joined to the session directory, else the session directory; where that is no repository
  (`install` outside a repository) the level is `prompt`. No guard command writes the key, and the tamper filter
  denies an agent's `git config magos.*` (Invariant 7), so only the user sets it. No level runs `override` or `disarm`
  without a click, and the MCP approval server runs nothing without a click at any level (Codex approval (version
  1.0.8)).
- `doctor` prints the level after the repository line: `approval: <level> (magos.approval <value>): <what it means>`,
  or `(magos.approval unset)`; outside a repository `approval: prompt (no repository): ...`. A value that is no level
  prints `approval: terminal (magos.approval is "<value>", which is not terminal, prompt or auto-safe, so the guard fails
  closed; set it in your own terminal: git config --local magos.approval prompt)`, and a value that cannot be read
  `approval: terminal (magos.approval cannot be read: <error>)`; both are problems (exit 1).

### Recognition

The Claude Code hook (`hook claude pre-tool`) takes the approval path only for a command in which the tamper filter
finds a user-only subcommand (scope `always`, reason `override / arm / disarm / install are user-only`). It denies with
the `protected_shape` text, which ends with one cause code on a line of its own, every such command that is not all of
the following:

1. A call of the `Bash` or `PowerShell` tool (`APPROVAL_TOOL` otherwise: `Monitor`, MCP tools and every tool whose
   shell the hook cannot name).
2. Exactly one command in the tool's dialect. With the leading and trailing blanks and line breaks of the text cut, it
   holds no control character but the tab and no lone surrogate, and the lexer reads it as one command with nothing around it: no list,
   pipe, background `&`, group, brace block, compound command, substituted text, redirection or here-document, and it
   creates nothing (`APPROVAL_SHAPE`). No word is dynamic (`$`, a backtick, `%`, an open parenthesis;
   `APPROVAL_DYNAMIC`).
3. Its first word is a Python interpreter (`APPROVAL_SHAPE` otherwise; a prefix assignment, a wrapper, the guard
   script itself and the launcher are none). It is either a bare name `py`, `python`, `python3` or `python3.<n>`, optionally with `.exe`,
   which the shell finds on PATH and which on Windows resolves to an `.exe` (not a `.bat` or `.cmd` shim, which would
   hand the arguments to cmd.exe); or a path to the same file as the interpreter that runs the hook
   (`APPROVAL_INTERPRETER` for any other path, a word that starts with `~`, or a name that resolves to a shim). Only
   these interpreter options follow it: `-3`, `-3.<n>` and their `-32` or `-64` forms, `-B`, `-E`, `-I`, `-s`, `-u`,
   `-X utf8` and `-Xutf8`. Then comes a word ending in `magos_guard.py` or `magos_guard`.
4. That word, with a Git Bash drive spelling mapped and joined to the session directory when it is relative, names
   this guard: the running file, or a file whose bytes equal it, such as the copy under the guard home
   (`APPROVAL_SCRIPT`). An older guard, a changed copy and a file of the same name elsewhere are never offered.
   For `install` the word must name the running file itself (`APPROVAL_SCRIPT` otherwise, at every level): `install`
   copies the launcher `hooks/run-guard.cmd` from beside the script it runs as, so a byte-equal copy of the guard
   next to another launcher would install that launcher.
5. No argument of the guard is `--` (`APPROVAL_SHAPE`): argparse from Python 3.13 on reads the word after it as the
   subcommand and earlier versions read it otherwise, so the command could fail on another interpreter than the hook's.
   The guard's own argument parser (`build_parser`, the parser the command uses, with `--repo` unset) reads the words
   after it, with `--approval=<43 characters>` appended, without a usage error. They must name a subcommand that has a
   `USER_ONLY` row, and the parser must read the appended word as its approval option (`APPROVAL_ARGS`).
6. Every word reaches the guard unchanged through the tool's shell.
   - PowerShell (`APPROVAL_POWERSHELL`): no empty word, no word that holds `"`, no word that ends with `\`, and no
     `--%`. When Windows PowerShell 5.1 starts a program it drops the first, splits or rejoins the next two, and reads
     the last as its stop-parsing token.
   - Bash on Windows (`APPROVAL_PATHCONV`): no argument of the guard that starts with `/`, holds `=/` or `@/`, starts
     with `-<letter>/`, or holds two backslashes in a row. Git Bash rewrites such a word when it starts a Windows program:
     the first four as a Windows path (`@/tmp/x` reaches Python as `@C:/...`), a backslash pair as one backslash.
7. A subcommand of scope `repo` names a repository the hook opens (`APPROVAL_REPO`).

A command in which the tamper filter finds a user-only subcommand and which names `--approval` is denied with the
`approval_given` text, whatever its shape. The hook looks for that name in the whole text, also after a `--` (which
argparse from Python 3.13 on reads as the end of the global options), as written and with every backslash, backtick,
caret, `'` and `"` removed. The one exception is the hook's own rewritten command of the same tool call: the token's record is live,
carries the payload's `tool_use_id`, and holds the SHA-256 of exactly this command text. That command is answered `{}`,
so a host that runs its hooks again on the rewritten input runs it. When such a record (not yet consumed, same
`tool_use_id`, same SHA-256) has expired, the hook denies with the `approval_expired` text: the click came too late,
nothing runs, and the record stays for the command or a prune. At level `terminal` the hook denies with the
`protected_level` text.

### The answer

- `ask`, or `allow` where level `auto-safe` allows the subcommand, as one ASCII-escaped JSON object on stdout, exit 0,
  stderr empty. Its only key is `hookSpecificOutput`, an object of exactly four keys: `hookEventName` `PreToolUse`,
  `permissionDecision` `ask` or `allow`, `permissionDecisionReason` TEXT and `updatedInput` INPUT.
  It carries no legacy `decision` field: that field has no ask, and its `approve` would skip the dialog. Claude Code
  applies the strictest answer of its hooks (deny, then defer, then ask, then allow), and an ask holds in every
  permission mode.
- `INPUT` is the whole `tool_input`, with `command` replaced by the rewritten command and `description` by the
  guard's own (`MAGOS user-only command: <subcommand> (approval)`). For an `allow` it holds no
  `dangerouslyDisableSandbox`.
- The rewritten command is built from the words the hook read, never by appending to the agent's text. It is the
  interpreter, its options, the absolute path of the script and the guard's arguments, each quoted for the tool's
  shell, then `--approval=<token>`. That is one word, so a token that starts with `-` stays the option's value.
  - Bash: a word made only of letters, digits and `_ @ % + = : , . / -` stays bare; every other word is single-quoted,
    with `'` written `'\''`.
  - PowerShell: the line starts with `& ` and every word is single-quoted, with `'` and the typographic single quotes
    doubled.

  The host shows this command in its dialog and runs it after the click. A comment, a dropped call operator or any text
  the lexer reads otherwise than the shell is not part of it.
- `TEXT` says what is approved and that the click is the approval.
  - Every subcommand: its name and a dry run.
  - `arm`, `disarm` and `override`: the repository.
  - `install`: the host, the directory it copies the guard and its launcher from (the directory of the running
    guard), the destination `<home>/guard`, and with `--allow-downgrade` that it replaces a newer guard copy.
  - `override`: also the fingerprint, the lane its denial record names (the lane the click lets through) with its
    target (`-` when the record names none), the conflicting branches of that record (or that the lane and the branches
    are not recorded here), and the reason, marked as written by the agent.
  - An `ask` says that the command carries a one-time token valid for 120 s; an `allow` says that the subcommand runs
    without a click under `auto-safe`.
- Every value an agent can choose is shown as a JSON string: the reason, the fingerprint, the lane, the target, branch
  names, and the repository, source and home paths.
  - The value is normalised to NFKC (so a fullwidth `＂` becomes `"`).
  - Every control, format (the bidirectional controls among them), surrogate, and line or paragraph separator character
    is replaced by a space, and so is every quotation mark but the ASCII `"`: the categories Pi and Pf, U+2018 to
    U+201F, the fullwidth `＂` and `＇`, `«` `»` `‹` `›`, the backtick and `´`. Runs of blanks are collapsed.
  - The ASCII `"` is escaped as `\"` by the JSON string.
  - The value is cut to 160 characters (the reason), 80 (a branch), 200 (a path) or 16 (the fingerprint).
  - At most six branches are shown, followed by `+<n> more`.

  So the closing quote of every shown value is the guard's, and no agent text starts a line of its own. A shown value
  can still hold letters that look like the guard's words; the quotes mark where it begins and ends.
- A mint that cannot write its record denies with the `approval_unrecorded` text, which names the error.

### Token and store

- The token is `secrets.token_urlsafe(32)`: 43 characters of `A-Z a-z 0-9 _ -`, shown only in the rewritten command.
  The SHA-256 of the token (64 hex digits) names its record, and the record never holds the token. No message of the
  command and no audit field holds it either: a usage error of the guard's parser shows every value of `--approval`
  it parsed (`--approval=<x>`, or the word after `--approval`) as `<redacted>`, wherever the message names it, and
  every other word as written.
- Store.
  - Scope `repo`: `<git-common-dir>/magos/approvals/` of the repository that `--repo` names (joined to the session
    directory), else that of the session directory.
  - `install`: `<guard home>/approvals/` of the default guard home (`MAGOS_HOME`, else `~/.magos`), whatever `--home`
    says. `--home` names only where `install` copies.
- The hook and the command compute the same directory from the same inputs.
  - A relative `--repo` is joined to the payload's `cwd`, the directory in which the tool's shell runs the command.
  - Git reports one common directory for every worktree and every spelling of a repository.
  - The command compares the record's `where` with its own common directory or default guard home, case- and
    separator-insensitively where the platform is, or as the same directory.
- Record `<sha256>.json`, written to a temporary file and moved into place with `os.replace`:
  `{"v": 1, "sub", "argv", "where", "via", "created", "expires", "tool_use_id", "session_id", "command_sha256",
  "used": false}`. A record of the MCP approval server or of the Hermes hook also holds `route` (Approval routes
  (version 1.0.8)), which the command does not check.
  - `argv`: the guard's arguments as the hook read them, without the approval word.
  - `via`: `prompt` (ask) or `auto-safe` (allow).
  - `created`, `expires`: seconds since the epoch; `expires` is 120 s after `created`, and for a Hermes record that asks
    the lifetime that Hermes approval (version 1.0.8) states.
  - `tool_use_id`, `session_id`: from the payload, at most 200 characters, null when absent.
  - `command_sha256`: the SHA-256 of the rewritten command.
  - A record of the MCP approval server holds `tool_use_id` null, `command_sha256` null and, besides `route`, the key
    `client` (Codex approval (version 1.0.8)).
- Every mint first prunes its store. It removes a record (`.json` or `.used`) whose `expires` passed more than 600 s
  ago, a record that cannot be read and is older than that, and a temporary file older than that; in a repository
  store it also removes a denial record whose `expires` has passed, or that cannot be read and is older than one hour.
  Files of other names stay, and a file that cannot be removed is left. A hook call that mints nothing reads no store.

### Verification in the command

- `override`, `arm`, `disarm` and `install` take `--approval <token>`, hidden from their help.
- The refusals that come before the console gate stay first: not a repository, a malformed fingerprint, `arm`'s
  refusal with exit 3, the guard home `install` refuses on Windows.
- Then, with `--approval`, the command verifies and consumes the token, and asks neither the console nor the
  challenge. A `--dry-run` with `--approval` consumes its token as well. Without `--approval`, the console gate and
  `override`'s challenge run as Public Contract states, and `--dry-run` skips them.
- Consumption first creates the claim `<sha256>.lock.tmp` exclusively (`O_CREAT | O_EXCL`, on Windows `CreateFile` with
  `CREATE_NEW`): of any number of uses at the same moment exactly one creates it, on NTFS as on POSIX file systems. A use
  that finds the claim held is the second use (exit 27) and runs nothing. Holding the claim, the use renames
  `<sha256>.json` to `<sha256>.used` and then releases the claim; a later use finds no record and the `.used` file
  (exit 27). The rename alone does not decide: on NTFS two processes that rename the same file at the same moment can
  both succeed (each opens the file by name, then renames its handle).
- A claim or a rename that Windows keeps busy past its retries counts as used when the record is consumed already (no
  `.json`, a `.used`), and otherwise fails closed: exit 11, nothing ran, the claim is released. A claim left behind by a
  process that died answers 27 for its token until a mint prunes it as a temporary file, 600 s after it was made.
- The renamed record is then read and checked:
  - format 1: `v` 1, `used` false, `via` `prompt` or `auto-safe` and a finite `expires` (else the token is unknown; an
    integer too large for a float is no finite `expires`);
  - not expired;
  - `sub` equal to the subcommand;
  - `where` equal to the command's repository or default guard home;
  - `argv` equal to the command's own argument list without its one approval option.

  The `.used` file stays until a mint prunes it, so a second use is named as such.
- A token that does not verify ends the command before it writes anything, and never falls back to the console. The
  message names the cause and says to run the command again without `--approval`. The exit codes:
  - 25 `APPROVAL_UNKNOWN`: not a token, no record of it in this store (a wrong token, one of another repository or
    guard home, one pruned after it expired), or a record that cannot be read.
  - 26 `APPROVAL_EXPIRED`.
  - 27 `APPROVAL_USED`.
  - 28 `APPROVAL_MISMATCH`: issued for another subcommand, set of arguments, repository or guard home, or an argument
    list that holds more than one approval option. The checks run in that order, so the message names the first that
    fails.

  A guard before 1.0.7 refuses `--approval` as a usage error (exit 2).

### Audit

Every run of a user-only subcommand that is not a dry run records how it was approved:
- `via`: `terminal` (a real console), `prompt` (a click) or `auto-safe` (allowed without a click);
- `tool_use_id`: that of its record, for a run approved in Claude Code (its `tool_use_id`) or in Hermes (its
  `tool_call_id`), and null for a run approved through the MCP approval server;
- `route` `mcp` and `client`: for a run approved through the MCP approval server (Codex approval (version 1.0.8));
- `route` `hermes`: for a run approved in Hermes (Hermes approval (version 1.0.8)).

The lines are those of Public Contract with these fields added: `arm` and `disarm` in `<store>/audit.log`, `install`
in `<home>/audit.log`, and `override` in `<store>/audit.log`. The `override` line also carries `reason_by`: `user` for
a reason typed in a terminal, `agent` for one that came through the dialog. The override record carries `via` and
`reason_by` as well.

### Denial records

`plan` (when it would write and denies with a conflict) and the host hook (when it denies a creation with a conflict)
keep `<store>/denials/<fingerprint>.json`: `{"v": 1, "fp", "lane", "branches", "target", "at", "expires"}`.
`branches` holds the conflicting branches of the verdict (`(detached) <worktrees>` for a detached one); `at` and
`expires` are seconds since the epoch. A record is valid for one hour, like an override record, and only the override
dialog reads it. `check` writes none, and a failure
to write one changes no verdict and no message.

### Tamper filter

A writer or a redirect whose target lies in an approval store (`.git/magos/approvals`, `.magos/approvals`, the
absolute `<git-common-dir>/magos/approvals` or `<guard home>/approvals`) is `PROTECTED` with scope `always`, in every
repository and outside any repository. Reading a store is allowed: it holds no token.

### Limits

- The approval path relies on an agent that runs commands through the hooked tools. Claude Code's file tools (`Write`,
  `Edit`) are not hooked, and the tamper filter does not read interpreters or scripts. So a same-user agent that sets
  out to forge a record, and to call the guard through such a route, can do so. This is the class of the override
  records and of `ARMED` (Known limits): the token, like the console gate, is no access control.
- The token is visible in the dialog and in the command the host runs. Anything that reads the host's record of that
  call before the click can run exactly the approved command, once, within 120 s.
- A click more than 120 s after the hook answered runs nothing: a host that runs its hooks again on the rewritten
  command gets the `approval_expired` deny, and otherwise the command ends with exit 26. The agent runs the command
  again for a new dialog.
- The hook and the command must see the same directory and the same `MAGOS_HOME`. A host whose payload `cwd` differs
  from the directory its shell runs in, or a tool environment with another `MAGOS_HOME`, ends the command with exit 25.
- The PowerShell and Git Bash word rules are those of Recognition. A word that another shell version passes otherwise
  ends the command with exit 28. A PowerShell `''` inside a single-quoted word and the typographic quotes are read as
  Known limits states, and the rewritten command shows the words that run.

## Approval routes (version 1.0.8)

The user approves a user-only subcommand by a click in the host's own dialog on all three hosts, each through a route
of its own; a real terminal stays valid on every host and at every level.

| Host | Route | Who asks | Token minted | `auto-safe` |
| --- | --- | --- | --- | --- |
| Claude Code | `hook claude` answers with an ask or allow (Approval (version 1.0.7)) | Claude Code's permission dialog | by the hook, before the click | runs `arm`, and `install` to the default guard home without `--allow-downgrade`, without a click |
| Codex | the MCP approval server `mcp` and its tool `magos_approve` (Codex approval (version 1.0.8)) | Codex's dialog for the server's elicitation form | by the server, after an Accept with `Approve` ticked | asks like `prompt` |
| Hermes | the MAGOS Hermes plugin's callbacks hand Hermes a modify and an approve (Hermes approval (version 1.0.8)) | Hermes's approval prompt | by the hook that the plugin runs, before the answer | runs `arm`, and `install` to the default guard home without `--allow-downgrade`, without a question |

The routes share the machinery of Approval (version 1.0.7): the `USER_ONLY` table; the level, read from
`magos.approval` of the repository the command names (`prompt` for `install` without one), where `terminal` and every
value that counts as `terminal` refuse on every route; the text that says what is approved, `approval_what` (the
content of `TEXT` in The answer, without the frame of the Claude Code dialog), with its sanitiser; the token, its
store, its record of format 1 and its verification in the command with the exit codes 25 to 28; and the audit field
`via`. Each route adds to it:

- `route`. A record of the MCP approval server holds `route` `mcp` and `client`, and a record of the Hermes hook holds
  `route` `hermes`; a record of the Claude Code hook holds neither. The command does not check them.
  `approval_fields` adds `route`, and `client` for `mcp`, to the audit line of a run whose record holds one of these
  two values, and nothing for any other value, so the records and audit lines of Claude Code and of a real terminal
  stay those of 1.0.7.
- `mcp`. The MCP approval server is no user-only subcommand: only a host starts it, from its own configuration, and
  every host's hook denies a tool command that starts it with the `protected_mcp` text (Codex approval (version
  1.0.8), The approval server and the tamper filter).
- The subcommand. A tool command that runs this guard names its subcommand as one plain word an agent may run, or it
  is denied on every host (The subcommand of a guard run): `mcp` and `hook` run without a human, so a word that the
  shell computes (`x=mcp; python3 <guard> $x`) must not reach them.

### The subcommand of a guard run

The parser's subcommands fall into four tables, which together hold exactly its choices: `AGENT_SUBS` (`plan`,
`check`, `list`, `release`, `doctor`, `version`, `set-plan`, `set-show`, `set-update`, `set-release`), the user-only
subcommands (`USER_ONLY`), `HOST_ONLY` (`mcp`) and `hook`, which only a host runs. The tamper filter reads the
subcommand slot of every guard word: the first word after it that is not the launcher's leading `--strict`, a global
option (`--repo` and `--lang` with their value, `--json`, any `--name=value`, in every spelling argparse takes) or a
`--`. One right-to-left pass over the words of a command gives the slot for every position a guard word's arguments
can start at, so reading a command stays linear in the number of its words however many guard words it holds.

- A guard word is a word whose base name (after the last `/` or `\`) names the guard in one of these readings, in any
  case: as written; with the escape characters and quotes removed; with `$''` and `$""` (empty ANSI-C and locale
  strings) removed and the trailing dots and blanks of the base name dropped (Windows drops them when it opens the
  file). `magos_guard` and `magos_guard.py` name the script, `run-guard` and `run-guard.cmd` the launcher, and so do the
  Windows 8.3 short names `magos_~<n>` and `magos_~<n>.py` (the script) and `run-gu~<n>` and `run-gu~<n>.cmd` (the
  launcher).
- A user-only word or `mcp` in the slot of any guard word keeps its own rule wherever the guard word stands (Approval
  (version 1.0.7), Recognition; Codex approval (version 1.0.8), The approval server and the tamper filter), and its
  reason wins over the one below anywhere in the command.
- A guard word that the shell runs is one that stands as:
  - the program of its command, after assignments, redirections, keywords and the wrappers of the walk with their
    options, option values, numbers and durations (`nohup <guard>`, `timeout 30s <guard>`, `xargs -I X <guard>`), and
    after a tool that runs a program of an environment with its run word (`uv run`, `uvx`, `poetry run`, `pdm run`,
    `hatch run`, `pipenv run`, `rye run`, `pixi run`, `conda run`, `mamba run`, `micromamba run`, `pyenv exec`);
  - the script of a Python interpreter (`py`, `pyw` and every base name that starts with `python` or `pypy`:
    `pythonw`, `python3.<n>`, `python3.14t`, `python3.12-dbg`, `pypy3`, also as a path or with `.exe`) or of a shell (`bash`, `sh`, `zsh`, `dash`, `ksh`) after its options, where `-X`, `-W` and
    `--check-hash-based-pycs` take a value, `-c` ends the reading and `-m <module>` runs a module named like the guard;
    also when an assignment holds the interpreter (`c="python3 <guard>"`, read as a command by the quoted-word rule) or
    a dynamic word or an interpreter named by one stands as the program (`"$PY" <guard>`, `$(command -v python3)
    <guard>`);
  - any argument of `Start-Process` (`saps`) or cmd's `start`;
  - weakly: the script of an interpreter or shell met among the arguments of another program, which the walk does not
    unwrap (`ionice -c3 python3 <guard>`, `flock /tmp/l python3 <guard>`; also `grep -n python3 <guard>`, which runs
    nothing). An `xargs` or `parallel` there feeds such an interpreter after it.

  Any other argument of another program (`git add <guard>`, `grep x <guard>`, `grep -rn xargs <guard>`, `wc -l
  <guard>`, `python -m pytest -k magos_guard`, `python -m py_compile <guard>`) is not run.
- A guard word that the shell runs is denied with the reason `the guard runs with a subcommand that is no plain word an
  agent may run` (scope `always`) when:
  1. a word after it, up to and including its slot, is dynamic: the lexer reads the word as dynamic and its piece holds
     `$`, a backtick, `%` or a parenthesis (a variable, a command substitution, `${X:-mcp}`, `$'mcp'`, `${a[0]}`, a
     PowerShell variable or sub-expression, `G,$a` of a PowerShell array; an unquoted option value word-splits into the
     slot), or its piece holds `{`, `}`, `*`, `?` or `[`, as written or with the escape characters and quotes removed (a
     brace expansion or a glob, which the shell expands into words of its own: `--json{,} mcp`, `-* mcp` beside a file
     named `--json`, `--js[o]n mcp`);
  2. `xargs`, `parallel` or `find -exec`, `-execdir`, `-ok` or `-okdir` stands before it in its command, or before the
     child shell whose text holds it (`xargs -I plan python3 <guard> plan` replaces any word);
  3. the slot is not, as written or with the escape characters and quotes removed, exactly one of `AGENT_SUBS`: `hook`,
     an empty slot (a word that a later expansion, a pipe into xargs or a variable that holds the command supplies would
     land there), a glob (`mc?`), a brace expansion, a PowerShell splat (`@a`, `@args`) and every other word. An option
     the parser refuses, `-h` and `--help` run nothing and pass, except as an argument of `Start-Process` or `start`,
     whose own parameters (`-ArgumentList`, `-RedirectStandardInput`) stand there. Rule 3 does not apply to a guard word
     that is run weakly.
- A quoted word that names the guard and holds a blank is read as a command with the same rules; there rule 3 applies
  only to a guard word that an interpreter, a dynamic program word or `Start-Process` runs, so a commit message that
  starts with the script name passes when its next word is neither `mcp` nor a user-only word nor dynamic: those keep
  their rule in every quoted word (`git commit -m "magos_guard.py mcp notes"` is denied, `git commit -m "magos_guard.py
  hook text"` passes). The text of a child shell takes rule 2 from the command that starts it.
- A here-document starts at a `<<` (not `<<<`) that stands outside quotes (`'..'`, `".."` with its backslash escapes,
  `$'..'`) and outside a comment (a `#` that starts a word) of its line; a `<<` inside quotes or a comment starts none, so
  the lines after `echo "<<E"` are read as commands. A here-document that a shell reads is read as commands with every
  check at the next depth, as the walk reads it: a word of the `<<` line, or of the first line after the body when the
  `<<` line ends with `|`, names a POSIX shell, PowerShell, `source`, `iex` or `Invoke-Expression`, read like a program
  word (the base name with the escape characters, quotes and `.exe` removed: `bash <<E`, `sh -s <<E`, `bash -s <<-E`,
  `/bin/bash <<'E'`, `"bash" <<E`, `cat <<E | bash`, `cat <<E | /bin/sh`, and `cat <<E |` with `bash` on the line after
  the body). A here-document fed to `cat`, to a file, to `git commit -F -` or to an interpreter without a shell is data.
  A PowerShell here-string (`@'..'@`) is a quoted word and is read by the quoted-word rule.
- The value of every `-c alias.<name>=<value>` of a git invocation (the two words `-c` `alias.<name>=<value>` and the one
  word `-calias.<name>=<value>`) is read with every check at the next depth: a value that starts with `!` as a shell
  command, any other value as `git <value>`. So `git -c "alias.c=!git config magos.guard off" c` holds the `magos.*`
  config rule and `git -c "alias.c=!rm .git/magos/ARMED" c` an edit of the guard's state.
- A finding of scope `always` anywhere in the command (a user-only word, `mcp`, this rule, a write into an approval
  store, a `magos.*` config switch, an unread nested text that names MAGOS) wins over every finding of scope `guarded`,
  whatever their order and wherever either stands: in another command of the line, in a quoted word, a child shell, a
  here-document, an alias value, or among the targets of the writers, redirects and environment writes of the same
  command (`rm .git/hooks/x; python3 <guard> mcp`, `env "B=1; rm .git/hooks/x <guard>" python3 <guard> mcp`, `printf r
  >> .git/hooks/x > <store>/approvals/<sha>.json`). An edit of the guard's state counts only once claims or the git
  layer exist. The hook reads the command a second time with the absolute guard home, the Hermes plugin directory and
  the repository's store as roots whenever the first reading found nothing of scope `always`, and keeps the more severe
  of the two findings.
- Child shells, here-documents that a shell reads, quoted words that name the guard and alias values are read to depth
  3. A text that would be read at depth 4 is not read: when it names MAGOS (`magos` or `run-guard`, read with every
  backslash, backtick, caret and quote removed) every host's hook denies the command with the `protected_deep` text
  (scope `always`), in every repository and before any host route; a text that names no MAGOS adds no finding.
- A command longer than 200,000 characters (`MAX_TEXT`) is not read. When it names MAGOS (`magos` or `run-guard`, read
  with every backslash, backtick, caret and quote removed) every host's hook denies it with the `protected_long` text,
  which names the limit, in every repository and before any host route; one that names no MAGOS keeps the rule of
  Responsibility (an unparseable creation, and a protected command once claims or the git layer exist). The
  `protected_deep` text names the depth limit, 3, and says to run the guard command at a shallower level.
- Every host's hook denies such a command with the `protected_slot` text before any route of its own: no ask, no
  modify, no tool name. The text says that the subcommand must be one plain word right after the script and its plain
  options, that the guard must not take its words from xargs, parallel or find -exec, the guard command with the
  subcommands of `AGENT_SUBS`, that `hook` and `mcp` are run by the host and that the user approves the user-only
  subcommands.

## Codex approval (version 1.0.8)

In Codex the user approves a user-only subcommand (`override`, `arm`, `disarm`, `install`) in Codex's own dialog: the
user ticks `Approve`, then accepts. The route is the guard's MCP approval server, the subcommand `mcp`: Codex starts it,
from the root `mcp.json` of the MAGOS plugin or from the `[mcp_servers.magos]` entry that `install --host codex`
prints, and the agent calls its one tool `magos_approve`. The server asks the user through MCP elicitation and, only
on an Accept with `Approve` ticked, records a one-time approval (Approval (version 1.0.7), Token and store) and runs
this guard's command with it. Codex's PreToolUse hooks have no `ask`, so the Codex hook denies every user-only
command; its text names the tool, the exact arguments and the command for a real terminal. A real terminal stays valid
on every host and at every level. The server, its record and its dialog text are host-neutral (Approval routes
(version 1.0.8)); Codex is the host that starts it. The plugin brings the server, not the hook: Codex reads no hooks
from a plugin whose root `plugin.json` is an Agent Plugins manifest, so the Codex hook comes from `install --host
codex`, whose entry the user merges into `~/.codex/hooks.json` and trusts once in Codex's `/hooks`; `magos_approve`
works without that hook.

### The tool

- `tools/list` holds one tool, `magos_approve`, with the title `MAGOS approval` and the annotations `readOnlyHint`,
  `destructiveHint` and `openWorldHint` false. Its input schema has `additionalProperties` false and requires
  `subcommand`:
  - `subcommand`: `override`, `arm`, `disarm` or `install`;
  - `repo`: the absolute path of the repository, required for `override`, `arm` and `disarm`; for `install` it names
    the repository whose `magos.approval` applies, and without it the level is `prompt`;
  - `fingerprint` and `reason` (`override`): the 12 lowercase hex digits a denial prints, and the user's words;
  - `host` (`install`): `claude`, `codex` or `hermes`;
  - `dry_run` (`arm`, `disarm`, `install`): a boolean; `false` is taken by every subcommand.
- The tool takes nothing else: no guard home, no `--allow-downgrade`, no language, no `--json`, no token and no free
  argument list.
- Every result carries one text item and `structuredContent` with `approved` (the user accepted), `exit_code` (the
  command's exit code, null when nothing ran) and `text` (the same text). `isError` is true when nothing ran or the
  command exited non-zero.

### The server

- `mcp [--lang L]` reads newline-delimited JSON-RPC 2.0 from stdin and writes one ASCII-escaped JSON object per line to
  stdout. The language of its texts is `--lang`, else `MAGOS_LANG`, else zh.
- A line holds at most 1 MiB (`MCP_LINE`); a longer line is skipped to its end and answered with error -32600 and id
  null. A line that is not UTF-8 JSON is answered with -32700 and id null. A message that is not an object, has no
  `"jsonrpc": "2.0"`, names a method that is not a string, or carries an id that is neither a string nor an integer is
  answered with -32600. Blank lines are skipped, and a line may end with CR LF.
- Requests: `initialize`, `ping`, `tools/list` and `tools/call`. `initialize` keeps the client's capabilities and
  `clientInfo` and answers with the client's `protocolVersion` when it is a date (`YYYY-MM-DD`), else `2025-06-18`,
  the capability `tools` (an empty object) and `serverInfo` with the name `magos` and the version `GUARD_VERSION`.
  `ping` gets an empty result. Every other request is answered with -32601 (Codex also asks `resources/list` and
  `resources/templates/list` and takes that answer), a `tools/call` of another tool with -32602. A notification gets no
  answer. A response that answers no open request of the server is ignored. A request that fails inside the server is
  answered with -32603, and the session goes on.
- A reader thread reads stdin into a queue; the server answers in arrival order and keeps at most one dialog open. A
  `tools/call` that comes while a dialog is open is answered at once with the `mcp_busy` text and runs nothing.
- The dialog is one `elicitation/create` request with `mode` `form`, the dialog text as `message` and a
  `requestedSchema` of type `object` with one property, `approve`: type `boolean`, title `Approve`, the description
  `mcp_approve_field`, listed in `required`, with no default anywhere. Only an answer with the action `accept` and a
  `content` object whose `approve` is the JSON value `true` approves. An Accept with `content` empty, missing or null,
  with `approve` false, a string, a number or absent gets the `mcp_unticked` text; `decline`, `cancel` and any other
  action get `mcp_refused`; an answer that is no object and an error answer get `mcp_failed`. None of them runs
  anything. Codex does not check an answer against the form, and under the approval policy `never` with full disk
  access it accepts a form without a required field by itself (with empty `content`); a form with a required field it
  declines by itself under `never`.
- The server waits 120 s for the answer (`MCP_CLICK_S`). It then withdraws the dialog with `notifications/cancelled`
  for its own request id (Codex then closes the dialog and forwards no later answer) and answers the call with the
  `mcp_late` text. The deadline is checked before each message is handled, so other messages do not extend it. Codex
  does not count the time a dialog is open against its tool timeout.
- `notifications/cancelled` for the open call withdraws its dialog the same way, and the cancelled call gets no answer.
  Codex sends no cancellation when its own tool timeout ends a call, so no call waits behind an open dialog.
- A client that declares no elicitation form (no `elicitation` capability, or one that names `url` only) gets the
  `mcp_no_form` text. Codex declares `form` and `url`; it declines this form by itself under the approval policy
  `never` (every sandbox) and under a granular policy without MCP elicitations, and shows it to the user under
  `on-request`, `untrusted`, a granular policy with MCP elicitations and an automatic reviewer of tool calls.
- With the annotations of The tool, Codex asks no tool-call approval of its own before `magos_approve`: the form is the
  only question.
- Only the protocol reaches stdout: for the session `sys.stdout` is stderr, and the command the server runs writes into
  buffers of its own. The server exits 0 when stdin ends (an open dialog then runs nothing) and 1 when stdout cannot be
  written or the server fails outside a request.

### The tool call

1. Arguments. Every key is one of the six; a key the subcommand does not take is refused (`dry_run` false is taken by
   every subcommand). A string holds at most 4096 characters (`MCP_FIELD`), no control character but the tab and no
   lone surrogate. `repo` is the absolute path of an existing directory: a drive or UNC path on Windows (a Git Bash
   drive spelling is mapped), a `/`-rooted path elsewhere, never relative, drive-relative or starting with `~`; it is
   normalised and written with `/` on Windows only (on POSIX a backslash is a character of a file name and stays, as for
   the guard home), and the directory tested is the one written; for `override`, `arm` and `disarm` it lies in a Git
   repository. `fingerprint` is 12 lowercase hex digits, `reason`
   holds a character that is not blank, `host` is a host name and `dry_run` a boolean. The text lists every error, and
   nothing runs.
2. The command line is built from these values only, every option one word: `--repo=<repo>` (not for `install`),
   `--lang=<the server's language>`, the subcommand, `--fingerprint=<fp>` and `--reason=<reason>` (`override`),
   `--host=<host>` (`install`) and `--dry-run`. A value that starts with `-` or holds `=` or a blank stays the value of
   its option. The guard's own parser (`build_parser`, `--repo` unset) reads it back with a probe
   `--approval=<43 characters>` appended; the row, the probe and every value must come back as given, else nothing
   runs.
3. The snapshot. Before the dialog the server computes, once, the level, the dialog text, the command line, the
   approval store and `where`, and the ready command. After the click it reads none of them again: not
   `magos.approval`, not the denial record, not the repository's spelling.
4. The level is `magos.approval` of `repo` (Approval (version 1.0.7), Registry and levels), or `prompt` for `install`
   without `repo`. At `terminal`, and at every value that counts as `terminal`, the call is answered with the
   `mcp_terminal` text and no dialog opens. At `prompt` and `auto-safe` the dialog opens: the MCP route never runs a
   command without a click.
5. The dialog text (`mcp_ask`), in the server's language, has four lines: the question with the subcommand; the
   repository and its Git directory, both as real paths, or for `install` the guard home; what is approved, in the
   words of Approval (version 1.0.7), The answer (`approval_what_*`: the fingerprint, the lane, target and branches of
   the denial record, and the reason marked as written by the agent); and `Tick Approve, then Accept: that approves
   exactly this, once. Anything else runs nothing.` Every value the agent chose passes the sanitiser of that section.
6. The run, only on an Accept with `approve` true. The server mints the token (`secrets.token_urlsafe(32)`), prunes the store of the snapshot
   and writes the record there: the record of Approval (version 1.0.7), Token and store, with `via` `prompt`,
   `tool_use_id` null, `session_id` the `_meta.threadId` of the call (at most 200 characters, else null),
   `command_sha256` null, and two more keys: `route` `mcp` and `client`, the client's `clientInfo` `name/version` with
   control characters as spaces, at most 80 characters. It then runs this guard's own command line with
   `--approval=<token>` appended through `main` in its own process, with an empty stdin and its output captured. The
   command verifies and consumes the token as Approval (version 1.0.7), Verification in the command states, and the
   guard starts no program but Git. The result text holds the command's stdout and stderr, every occurrence of the
   token replaced by `<redacted>`, cut to 8000 characters (`MCP_TEXT`).
7. The ready command, in every text that sends the user to a real terminal, is the guard command (`py -3 "<guard>"` on
   Windows, `python3 "<guard>"` elsewhere) and the command line; a word that is not a plain word is single-quoted for
   PowerShell on Windows and for sh elsewhere. On Windows a word that holds `"`, or a blank and a trailing `\`, would
   not reach the guard unchanged: Windows PowerShell 5.1 wraps a word that holds a blank in double quotes without
   escaping the quotes and backslashes inside it, so the program reads other words. Such a word keeps its option name
   and shows the text `ready_own` (`<type your own words here>`) in place of its value; the user types their own
   words there. Every other word reaches the guard exactly as the ready command shows it in Windows PowerShell 5.1.

### The Codex hook

- `hook codex` denies every user-only command: Codex PreToolUse hooks support no `ask` and run the call when a hook
  answers with one, or with an `allow` that carries no command. Codex blocks the call on the guard's deny object (exit
  0), also for a command that a code-mode tool runs (its `tool_name` is `Bash` as well).
- When the payload's `permission_mode` is `bypassPermissions` (Codex's approval policy `never`, under which Codex
  declines the form by itself), the text is `protected_codex_never`: only the command for a real terminal.
- Otherwise the hook reads the command in the dialect of its tool (for an argv, the script of its shell; on Windows a
  string command in the PowerShell dialect, because Codex runs it through `powershell.exe -Command`) and maps it onto
  the tool only when that text is exactly one direct invocation of this guard as the Claude Code hook reads one
  (Approval (version 1.0.7), Recognition 2 to 5: one command with nothing around it, no redirection, no dynamic word, an
  interpreter and its options, then a script word that names this guard, and for `install` the very file the hook
  runs); the guard's parser reads the words after the script word. When that invocation maps onto the tool and its
  arguments pass step 1 of The tool call, the text is `protected_codex`: the tool, its arguments as one JSON object, and
  the ready command. The mapping drops `--lang`, `--json` and an `--approval` value, joins a relative `--repo` to the
  session directory, and takes the session directory as `repo` when no `--repo` is named (for `install` only when that
  directory lies in a repository); `--home` and `--allow-downgrade` do not map. Every other command gets
  `protected_codex_form`, which says what the tool takes: among them a `cd`, `Set-Location`, `pushd` or `env -C` before
  the guard, an environment assignment (`MAGOS_HOME=.. python3 <guard>`, `export`, `$env:`), a script that is not this
  guard, and an `install` through a copy other than the hook's own file.
- The Codex hook entry matches `Bash` and the MCP session tools only, so it does not run for the tool
  `mcp__magos__magos_approve`, and the hook answers an MCP tool without a string `command` with `{}` in any case.

### The approval server and the tamper filter

- `mcp` is no user-only subcommand: the host starts it, and a tool command never does. `HOST_ONLY` holds it. The tamper
  filter reads it after a guard word as it reads the user-only subcommands (the global options and `--` before it,
  both readings of every word, quoted words that name the guard, child shells, PowerShell comma and array lists) and
  returns scope `always` with a reason of its own. Every host's hook denies such a command with the `protected_mcp`
  text, in every repository and outside any repository; the Claude Code hook never answers it with an ask. A guard run
  whose subcommand the shell computes (a variable, a command substitution, a word xargs supplies) or that names `hook`
  is denied by the rule of Approval routes (version 1.0.8), The subcommand of a guard run, with the `protected_slot`
  text.
- The help and the usage list every subcommand but `mcp` (the metavar of the subcommand list); a usage error that
  names the choices of the subcommand lists it.

### install and doctor

- `install --host codex` writes and prints the hook entry of Public Contract, and also writes
  `guard/generated/codex-mcp.toml` and prints it, then the `codex mcp add` line:

  ```toml
  [mcp_servers.magos]
  command = "<the interpreter that runs install>"
  args = ["-I", "-B", "<home>/guard/scripts/magos_guard.py", "mcp"]
  env_vars = ["MAGOS_HOME", "MAGOS_LANG"]
  startup_timeout_sec = 30
  tool_timeout_sec = 600
  ```

  The strings are TOML basic strings: `"` and `\` are escaped and every control character but the tab is written
  `\uXXXX`. Codex starts a stdio server with a short list of environment variables; `env_vars` passes `MAGOS_HOME` and
  `MAGOS_LANG`, so the server uses the guard home and the language of the user's hooks. The `codex mcp add` line
  (`codex mcp add magos -- <interpreter> -I -B <script> mcp`) sets neither `env_vars` nor the timeouts. The guard leaves
  the Codex configuration file that the user merges the printed entry into as it is.
  A server started from the plugin's `mcp.json` gets neither variable: that file cannot name `env_vars` (Dependencies,
  Downstream callers), and Codex passes a stdio server only a short list of environment variables. It then uses the
  guard's defaults: the guard home `~/.magos` in the user's home directory (on Windows from `USERPROFILE`, which Codex
  passes) and Chinese texts. `install` through it copies the guard to `~/.magos/guard`, and `arm` through it records
  the backstop command of the copy under `~/.magos` (Public Contract, `arm`). The printed entry passes both variables.
- `doctor` prints, before the repository part: `mcp server: answers initialize and tools/list (magos_approve)`, from an
  in-process exchange with the server (any other answer is a problem); the entry in `guard/generated/codex-mcp.toml`
  (a problem when its interpreter or its guard script does not exist or the script declares another `GUARD_VERSION`,
  with the refresh command, or, for a newer `GUARD_VERSION`, with `run doctor from that MAGOS`, since install would
  refuse the downgrade), or that none was generated; the first 12 hex digits of the sha256 of the
  plugin's `mcp.json` in the directory above the running guard's `scripts/` directory, when it exists (`codex plugin
  file: mcp.json <12 hex>`); and that only Codex shows whether it runs the server and trusts the MAGOS hooks.

### Limits

- The server cannot tell who started it, so it proves a human only as far as the host does. A same-user agent that runs
  code of its own can start a server of its own (a copy of the guard under another name, the guard imported by
  `python -c`) and answer its own dialog; that is the class of the forged records of Approval (version 1.0.7), Limits.
- The files that start the server (the plugin's root `mcp.json`, whose git alias holds the launch, and the guard
  script it runs, or the user's `config.toml` entry) run whenever Codex starts. Codex trusts hooks by hash, not these
  files; `doctor` prints the sha256 of the plugin's `mcp.json`.
- The denial record the dialog quotes can be forged like the store; its values are sanitised.
- How the Codex desktop app shows the form, and what an interrupted turn does to an open dialog, is Codex's; without an
  Accept with `Approve` ticked nothing runs. A client that ticks and accepts by itself (an automatic answer configured
  outside Codex's approval policies) approves as a human would; the server cannot tell them apart.
- Codex's tool timeout counts the run after the click, not the wait for the answer: the generated entry sets 600 s,
  and Codex ends a tool call to the server of the plugin's `mcp.json`, which cannot set a timeout, after 300 s (Codex
  0.163).
- A server started from the plugin's `mcp.json` sees neither `MAGOS_HOME` nor `MAGOS_LANG` (install and doctor) and
  uses `~/.magos` and Chinese texts; the mint and the verification of its tokens run in its one process, so they
  agree.
- Another client that reads the Agent Plugins `mcp.json` starts the server as well; a client that declares no
  elicitation form gets the `mcp_no_form` text, and nothing runs.

## Hermes approval (version 1.0.8)

In Hermes the user approves a user-only subcommand with one answer in Hermes's own approval prompt (the CLI panel, the
TUI and desktop dialog, or the buttons of a messaging gateway). The MAGOS Hermes plugin entry (`__init__.py`) registers two
`pre_tool_call` callbacks; for exactly one direct invocation of this guard by the `terminal` tool, one run of the guard
hands Hermes the command rebuilt with a one-time token (a `modify` directive) and a guard-written question with a
request-unique rule key (an `approve` directive). Hermes applies every `modify`, lets any `block` win, and otherwise asks
the human with the first `approve` before the command runs; a denial, a timeout and a gate error run nothing. The token,
its store, its verification, the levels and the exit codes 25 to 28 are those of Approval (version 1.0.7). The Hermes
entry under `hooks:` (`install --host hermes`) runs `hook hermes pre-tool` without `--hermes-gate` and denies every
user-only command with the `protected` text. Approval routes (version 1.0.8) compares this route with those of
Claude Code and Codex.

### The plugin callbacks

- `register(ctx)` registers the skills, then `ctx.register_hook("pre_tool_call", <verdict>)` and
  `ctx.register_hook("pre_tool_call", <approval>)`, in this order, and nothing else. `plugin.yaml` declares
  `provides_hooks: [pre_tool_call]`.
- Both callbacks act only for the tool `terminal` and return nothing for every other tool, and both return nothing
  when `MAGOS_GUARD` is `off` (any case, surrounding blanks ignored) in Hermes's environment.
- The verdict callback starts `sys.executable -X utf8 -B <plugin>/scripts/magos_guard.py hook hermes pre-tool
  --hermes-gate <gate>` as an argument list without a shell, with the payload on stdin and a limit of 25 s, below
  Hermes's 30 s callback limit. The payload has the shape of a Hermes shell-hook payload:
  `{"hook_event_name": "pre_tool_call", "tool_name", "tool_input": <args>, "session_id", "tool_use_id": <tool_call_id>,
  "cwd": <Hermes's directory>, "extra": <the other keyword arguments>}`, and the child's `HERMES_HOME` is Hermes's active
  home when Hermes names one.
- The verdict callback maps the guard's answer:
  - `{}`: nothing;
  - a deny object: `{"action": "block", "message": <its reason>}`;
  - `{"hermesApproval": {"modify": {"command": C}, "approve": {"message": M, "rule_key": K}}}`: it keeps the approve part
    for this call and returns `{"action": "modify", "args": {"command": C}}`;
  - `{"hermesApproval": {"modify": {"command": C}}}` (`auto-safe`): `{"action": "modify", "args": {"command": C}}`;
  - anything else, a non-zero exit, a run longer than 25 s or a guard that cannot start: a block that names the cause and
    the off switches. A callback that raises or exceeds Hermes's own limit is a block as well (Hermes's rule for
    `pre_tool_call`).
- The verdict callback keeps a mark for every call it answers, under the `args` object of the call: Hermes hands both
  callbacks of one call the same `args` dict (each callback gets a shallow copy of one keyword dict) and every call a
  dict of its own, so two calls alike in every keyword argument and in the command never share a mark. The mark holds
  the object, so its id is not reused while the mark lives, and it holds the approve part for a question, nothing for
  every other answer. The approval callback takes the mark of its own `args` object once and returns its approve part,
  or nothing. When a call has no mark and its command names `magos_guard` (read with
  every backslash, backtick, caret, `'` and `"` removed, case ignored), it returns a block: an approve that the verdict
  could not hand over never turns into a modify without a question. Marks older than 120 s are dropped.
- The gate value is computed in Hermes's process before the guard runs:
  - `absent` when the plugin runs in a plugin-host process (`HERMES_PLUGIN_HOST_PROCESS` set, `plugins.isolation:
    host`), when `tools.approval.request_tool_approval` has no `rule_key` parameter or `hermes_cli.plugins` has no
    `_PreToolCallDirective` with a `rule_key` field (a Hermes without the plugin approve directive), or when an import or
    any probe below raises;
  - `bypass` when Hermes's approval gate would answer without a human: `tools.approval._yolo_active()` (`--yolo`,
    `HERMES_YOLO_MODE`, a session `/yolo`, `hermes -z`), `tools.approval_context._get_approval_mode()` is `off`
    (configuration or a hosted-room policy), or `tools.approval._presence()` finds neither an interactive CLI, a gateway
    nor an ask bridge (cron, `-q`, unattended platforms);
  - `ask` otherwise.

### Recognition

The Hermes hook takes the click route only with `--hermes-gate` and only for a command in which the tamper filter finds a
user-only subcommand. It denies with the `protected_shape_hermes` text, whose last line is one cause code, every such
command that does not meet Recognition 1 to 7 of Approval (version 1.0.7) read with these differences:

1. The call is of the `terminal` tool, in the foreground and without a pseudo-terminal: `background` and `pty` absent
   or false (`APPROVAL_TOOL` otherwise: the agent drives a background or PTY shell itself). Its dialect is bash, the
   shell Hermes runs every command in (Git Bash on Windows), so the Git Bash word rule (`APPROVAL_PATHCONV`) applies on
   Windows.
2. The directory comes from the call. With `workdir` (an existing directory named by an absolute path: a drive or UNC
   path on Windows, where a drive-less `/x` would name another directory in Git Bash than in Python, a `/`-rooted path
   elsewhere; not starting with `~`, at most 4,096 characters, of the characters Hermes accepts: letters, digits and
   `/ \ : _ - . ~ + @ = ,` and the space) a relative path is joined to it; without `workdir`
   the script word, an interpreter path, `--repo` and `--home` must be absolute (a path starting with `~` is not), and
   `override`, `arm` and `disarm` must name `--repo` (`APPROVAL_DIRECTORY` otherwise). The payload's `cwd` is the
   directory of the Hermes process (its checkout), not the directory the terminal command runs in.
3. A command that names `--approval` is denied with the `approval_given_hermes` text. Hermes runs its hooks once per call,
   so no rewritten command comes back to the hook.
4. The level is that of the repository `--repo` or `workdir` names; `install` without either has level `prompt`.
   `terminal` denies with the `protected_level` text.
5. Under `prompt`, and under `auto-safe` for every subcommand it does not allow, the hook asks only when Hermes would ask
   a human. It denies with the `protected_hermes_noask` text, which names the reason, when `--hermes-gate` is `bypass` or
   `absent`, when `HERMES_YOLO_MODE` is `1`, `true`, `yes` or `on` (any case) in its environment, when `approvals.mode`
   in the Hermes config (`<hermes home>/config.yaml`) reads as off, or when that file exists and cannot be read.

### The answer

- One ASCII-escaped JSON object on stdout, exit 0, stderr empty:
  `{"hermesApproval": {"modify": {"command": C}, "approve": {"message": M, "rule_key": K}}}`; under `auto-safe` for
  `arm` and for `install` to the default guard home without `--allow-downgrade` the `approve` key is absent. This shape is
  no Hermes directive: a Hermes entry under `hooks:` that ran it would contribute nothing, and the command would meet the
  console gate.
- `C` is the rewritten command of Approval (version 1.0.7), The answer, quoted for bash. The plugin hands only `command`
  to Hermes, which merges it over the call's other arguments (`workdir`, `timeout` stay as the agent sent them).
- `M` is `approval_ask_hermes`: the question, the `what` text of Approval (version 1.0.7) (subcommand, repository,
  fingerprint, lane, target, branches, the reason marked as the agent's, the install source and destination, a dry run
  and `--allow-downgrade`), the record's lifetime in seconds, and that `once`, `session` and `always` each approve this
  one request only. It holds neither the token nor the command: Hermes shows the gate target `<terminal> (plugin approval
  rule)` and this text, and passes the text through its redactor.
- `K` is `magos:<subcommand>:<32 hex digits>` from `secrets.token_hex(16)`, new for every request, so no `session` or
  `always` answer can approve a later request.
- The record is that of Approval (version 1.0.7) with `"route": "hermes"`, `tool_use_id` the payload's `tool_use_id`, else
  `extra.tool_call_id`. A record that asks expires `min(max(T, 120), 900) + 30` s after `created`, T being
  `approvals.timeout` as Hermes reads it (Reading the Hermes config; 300 when unset); a record under `auto-safe` expires
  after 120 s.

### Reading the Hermes config

The hook and `doctor` read `<hermes home>/config.yaml` (UTF-8, a byte order mark and CRLF allowed) with a line reader of
the standard library:
- A missing file means Hermes's defaults (`approvals.mode` manual, `approvals.timeout` 300). A file that cannot be read or
  decoded, more than one top-level `approvals:` key, a quoted `approvals` key, an `approvals:` with a value on its own
  line (a flow mapping or a scalar), a tab in its indentation, a line of the block that is no `key:` line, a repeated
  child key, or a `mode` or `timeout` value that is an anchor, an alias, a tag, a block scalar, a flow collection, an
  unclosed quote, text after its closing quote that is no comment, or continued on deeper lines is "cannot be read".
  So is a top-level line that is neither a `key:` line nor a bare document marker (`---` or `...`, alone or with a
  comment): a flow mapping or sequence (a JSON-style file), an explicit `?` key, a sequence item, a merge key `<<`, an
  anchor, alias, tag or directive, and a document marker followed by content. The file is read for certain or not at
  all.
- The child keys are the lines indented exactly as the first non-blank, non-comment line under `approvals:`; deeper lines
  belong to nested values and are skipped. A value loses a trailing ` #` comment when it is not quoted; a quoted value is
  read with `''` standing for `'` (single quotes) and without escapes (double quotes; a backslash makes it unreadable).
- `mode` reads as off when its value, without surrounding blanks and case, is `off`, or, unquoted, `false`, `no` or `n`.
  Hermes reads the YAML 1.1 booleans of PyYAML (`false`, `False`, `FALSE`, `no`, `No`, `NO`) as false, which it treats as
  off, and every other of these spellings (`n`, `nO`, `fAlse`) as a string, which it reads as `manual`: there the guard
  is stricter and refuses the click where Hermes would ask.
- `timeout` is what Hermes reads: Python's `int()` of the value PyYAML gives the scalar, 300 where `int()` raises
  `ValueError` or `TypeError`. Unquoted, YAML 1.1 resolves null (`~`, `null`, an empty value: 300), the booleans (1 and
  0), integers in decimal, octal with a leading `0`, hexadecimal `0x`, binary `0b` and base 60 (`10:00`), with
  underscores, and floats (`1000.5` is 1000, `.nan` is 300); a quoted value and every other text is a string, which
  `int()` reads in decimal with surrounding blanks and single underscores. A value Hermes cannot take at all (an
  infinite float, a number YAML cannot construct) counts as 900, the cap of the record's lifetime.

### doctor

When `<hermes home>` is a directory, after the copy lines:
- `hermes route: the plugin <dir> (guard <v>) runs the guard and asks for a user-only command in Hermes's approval prompt`
  when `<dir>/scripts/magos_guard.py` declares this guard's version, `<dir>/__init__.py` registers the guard callbacks and
  `plugins.enabled` of the Hermes config names `magos` and `plugins.disabled` does not (or the config holds neither list, or
  cannot be read); each list is a flow list `[a, b]` (it ends at its first `]`; a comment may follow) or a block
  sequence of `- name` lines, of plain or quoted names;
- `hermes route: the plugin <dir> holds guard <v>, not <this version>; update it (hermes plugins update magos) and restart Hermes`
  when the plugin holds another guard;
- `hermes route: the plugin <dir> holds guard <v>, but its __init__.py registers no guard callbacks; update it (hermes plugins update magos) and restart Hermes`
  when it holds this guard and its `__init__.py` registers no callbacks;
- `hermes route: magos is not in plugins.enabled of <config>; Hermes loads no MAGOS callbacks`;
- `hermes route: no MAGOS plugin under <hermes home>/plugins; the entry under hooks: (install --host hermes) runs the guard, and user-only commands run in the user's own terminal`;
- `hermes entry: <config> holds the MAGOS entry under hooks:, but <hermes home>/shell-hooks-allowlist.json does not list its command, so Hermes skips it without a word; approve it once (hooks_auto_accept: true, or HERMES_ACCEPT_HOOKS=1 for hermes acp)`
  when a line of the `hooks:` block holds `hook hermes pre-tool` and no allowlist entry of event `pre_tool_call` has that
  exact command: a problem when no plugin route applies (the guard then runs nowhere in Hermes), information otherwise;
- `hermes route: <config> also holds a MAGOS entry under hooks:; it denies every user-only command before Hermes can ask and runs the guard a second time on every terminal call; remove that entry from the Hermes config, the plugin runs the guard`
  when the first line applies and a line of the top-level `hooks:` block holds `hook hermes pre-tool`: a problem (exit 1);
- one approvals line: `hermes approvals: approvals.mode is <v> in <config>: Hermes approves without asking, so the guard refuses the click and user-only commands run in the user's own terminal`,
  `hermes approvals: HERMES_YOLO_MODE is set here: Hermes approves without asking, ...` (same ending),
  `hermes approvals: <config> cannot be read (<error>): the guard refuses the click`, or
  `hermes approvals: Hermes asks (approvals.mode <v>|approvals.mode unset), within <T> s; a session /yolo is not visible here`,
  in this order of precedence: `HERMES_YOLO_MODE`, a config that cannot be read, `approvals.mode` off, the causes and
  the order in which the Hermes hook refuses a question (Recognition 5, from the same function); `<T>` is
  `approvals.timeout` as Hermes reads it (300 when unset).
The double-route line, and the entry line when no plugin route applies, are problems; the others are information. Doctor cannot see what Hermes registered at start, the
shell-hook consent file's effect on a running Hermes, a session `/yolo` or a hosted-room policy.

### Limits

- The click route is as strong as Hermes's approval gate. A same-user agent that can run code outside the hooked tool can
  forge a record (Approval (version 1.0.7), Limits) or replace the plugin's files, which Hermes loads and runs.
- Among several `approve` directives of one call the first wins: a Python plugin loaded before MAGOS that escalates
  `terminal` calls sets the text and the rule key, and a rule key it had approved for the session or always passes the gate
  without the MAGOS question. No plugin shipped with Hermes returns `approve`.
- A session `/yolo` and the other in-process bypasses are seen only by the in-process probe; in a plugin-host process the
  plugin passes `absent`, and the user runs the command in their own terminal. A bypass switched on between the hook and
  the gate (seconds) is not seen.
- `always` makes Hermes write an inert `plugin_rule:magos:<subcommand>:<hex>` line into `command_allowlist` of its config;
  it approves nothing later and may be deleted. A plugin that asks without a rule key gets the key `terminal`, so one
  `always` for it silences its later questions; when such a plugin runs before MAGOS its approve is the one Hermes uses.
- Hermes shows the guard's text and the target `<terminal> (plugin approval rule)`, never the command; once the call runs it
  sends the rewritten command, token included, to every ACP viewer of the session. That command consumes the token at once,
  and the token is good only once, for that subcommand, those arguments and that repository or guard home.
- A click after the record's lifetime ends the command with exit 26; Hermes itself refuses a click after
  `approvals.timeout`.
- The hook and the command must see the same `MAGOS_HOME`; Hermes runs the command in a bash that sources the login
  snapshot, so a `MAGOS_HOME` that only the login shell sets ends `install` with exit 25.
- A MAGOS entry under `hooks:` next to the plugin denies every user-only command before Hermes can ask (`doctor` reports
  it).

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

- reads the instructions of an `update-ref --stdin` only from the sources of that invocation (here-string,
  here-documents, a directly piped `echo`, `printf` or `cat` of a here-document), takes `\0`, `\n`, `\t` and `\r` as
  separators, and makes the record dynamic unless every `create` and `update` instruction is a plainly read name:
  an unreadable source, an expansion, any other escape, a quote, an empty name or a name git refuses make it dynamic;
  a command that only mentions `update-ref --stdin` is not read;
- reads `refs/heads/` in any case of `refs` and `heads` for `update-ref`, `symbolic-ref`, refspec destinations and
  `update-ref --stdin` with one pattern shared by the host hook and the git-layer hook; reads `refs/heads/refs/x` as
  the branch `refs/x`; reads `symbolic-ref -m <reason>` and the dynamic ref words of `update-ref` and `symbolic-ref`
  (also behind `xargs`) as dynamic creations; ignores a push refspec with an empty source; keeps the names git accepts
  (a leading dash for `update-ref`, `symbolic-ref`, `fetch`, `pull` and `push`, whitespace outside ASCII);
- reads a program word with a backslash, a backtick or a caret in a shell it cannot name as the program it spells
  without them, with dynamic creations and possible changes;
- reads `git rebase --ex` and `--exe`, `git --shallow-file <v>`, `git update-ref -m <v>` and `--std`;
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
- reads the redirections of the shell as words of their own and skips them before the program word, between a program
  and its subcommand, among the words of a git invocation, in the word gate, the alias check and the tamper filter, so
  a creation behind `>/dev/null`, `2>&1` or `&>f` is judged; reads `2>&1`, `>&2`, `&>f` and `>|f` as one word;
- reads the bundled short options of `git branch` the way git reads them, so `-df`, `-dr` and `-vd` are deletions and
  `-mr`, `-m -r` and `-c -a` are renames and copies;
- bounds a chain of relative `-C` values and the nesting of groups and brace blocks to time linear in the command length;
- honours a claim stored under a name the Windows alias rule refuses when its branch is created, and names such
  claims in `list` and `doctor`.

Version 1.0.6 of the guard (`GUARD_VERSION` 1.0.6) has the sets for `/GitPlan` that 1.0.4 added. Relative to
the 1.0.3 product it:

- adds the subcommands `set-plan`, `set-show`, `set-update` and `set-release`, none of them user-only, and the exit
  codes 19 (STALE), 20 (SET_EXISTS), 21 (SET_UNKNOWN), 22 (OUT_OF_LANE), 23 (SET_NEWER_FORMAT) and 24 (INVALID_SPEC);
- stores a set as one record `<store>/sets/<set>.json` (format `SET_FORMAT` 1, a record of a newer format is refused
  with exit 23 and never misread) and as one claim per lane plus one claim for the integration branch, written together
  in one transaction with a rollback, claims first and the record last; the integration claim is exempt from overlap
  judgement in both directions (it is never a claimant, and the creation of its branch is judged for the name and the
  claim only), so it restricts no lane manifest;
- validates a spec before anything is written: field limits (at most 12 lanes, 12 requirements, 200 entries per lane, a
  sheet of 8,192 characters, a spec of 4 MiB), the requirements of the task and the coverage (every requirement served
  by a lane, every lane serving existing requirements and delivering an outcome), lane ids that are topic slugs (the
  ordinal, generic and reserved ids are refused), lane branches that are exactly `agent/<set>/<id>` (checked by the
  existing branch-name rules and the Windows alias rule against the repository), absolute worktrees that are distinct,
  nested in nothing and named `<prefix>-<set>-<id>`, the manifest syntax of every entry and no entry listed twice in one
  lane (`DUPLICATE`), a dependency graph without a cycle, shared files inside their owner's manifest, and the pairwise
  disjointness of the lane manifests by the exact glob intersection through a literal-prefix index; the messages that
  refuse a name, the set name included, are in Chinese and English and state the compliant form or ask for another
  topic slug, the refusals of `set-show`, `set-update` and `set-release` are framed as invalid arguments, and a
  registration prints the creation of a lane from the recorded base as its example;
- refuses a plan made against another target tip (STALE, exit 19) and an amend or an update made against another revision
  (the same exit), judges every lane against every claimant outside the set from one snapshot, and never reads or
  consumes an override;
- keeps the lane states of an amended set, refuses the removal of a lane that holds unmerged or uncommitted work (on
  its branch or in its detached worktree) and the shrinking of a manifest below files the lane already changed, and
  checks at `ready` that the recorded head is the branch tip, that every worktree of the lane is clean and idle (one
  missing on disk counts as dirty) and that every changed file lies inside the manifest (OUT_OF_LANE, exit 22), and at
  `integrated` that the head is in the target or in the integration branch;
- stores at `integrated` an objective summary of what the lane changed (`changes`: the non-merge commits, at most 8 of
  their subjects, the files, the lines added and removed, at most 12 path keys) computed from `merge-base`, `rev-list`, `log` and `diff`
  against the current tip of the local target (against the commit its `ready` was measured against when the head is
  already in the target), keeps it on a repeated `integrated` update, clears it when the lane leaves
  `integrated`, and fails closed (exit 11, nothing written) when the target branch is missing or a Git call fails;
- derives a view of a set (`set-show`, with the drift of the lanes, of the target (the files of its commits since the
  base that the set's own work does not hold, so the set's own land never makes the plan stale) and of the files two
  lanes changed, the requirements with their lanes and the `changes` of every lane), retires a set only when its lanes are integrated and
  landed or, with `--abandon`, hold no unmerged work, and its integration branch holds none either, never with a dirty
  or missing worktree of a lane or of the integration branch, and records every
  write in the audit log, with the line built before the write;
- lists the set and lane of a claim in `list`, reports set problems in `doctor`, refuses every `plan` that would write
  the claim of a lane that belongs to a set (an amend, the re-plan of an override) and its `release`, judges the creation of a lane of a set against the target stored in its
  claim, and runs `rev-list`, `log` and `diff` (members of `LOCAL_GIT`) for the
  commits a lane is ahead of the plan's base, for the summary of an integrated lane and, `log` only, for the target's
  commits of the drift view;
- runs every `diff`, `log` and `status` call with `--ignore-submodules=none`, so `plan`, `check`, the hook, plain `release` (a lane
  worktree holding such a change has uncommitted changes) and the set subcommands count a changed gitlink, and a submodule checkout that differs from its gitlink or holds changes, as a
  change of that path whatever `diff.ignoreSubmodules`, `submodule.<name>.ignore` or the `ignore` of `.gitmodules` says.

Version 1.0.7 of the guard (`GUARD_VERSION` 1.0.7). Relative to the 1.0.6 product it:

- lets the user approve a user-only subcommand in Claude Code's own permission dialog. The Claude Code hook answers
  exactly one direct invocation of this guard by the `Bash` or `PowerShell` tool with `ask`, or, under `magos.approval
  auto-safe`, with `allow` for `arm` and for `install` to the default guard home. It hands the host the command rebuilt
  from its words with a one-time `--approval` token, and it denies every other shape with a cause code (Approval
  (version 1.0.7));
- reads `magos.approval` (`terminal`, `prompt`, `auto-safe`; unset is `prompt`, any other value `terminal`) from the
  repository's own config and reports it in `doctor`;
- gives `override`, `arm`, `disarm` and `install` the hidden option `--approval`. The token is verified against a record
  named by its SHA-256 in `<git-common-dir>/magos/approvals/` or `<guard home>/approvals/` and consumed by one rename,
  with the exit codes 25 to 28, and no message names it;
- records `via` in the audit lines of the user-only subcommands, and `reason_by` for `override`;
- keeps the branches of a conflict denial in `<store>/denials/<fp>.json` for the override dialog;
- denies writes into an approval store in every repository, and states the click in the `options` and `need_tty`
  texts, in the denials of a user-only command and in `doctor`'s re-arm and refresh hints.

Its claims, set records and every other command are those of 1.0.6; a guard of 1.0.6 refuses `--approval` as a usage
error.

Version 1.0.8 of the guard (`GUARD_VERSION` 1.0.8). Relative to the 1.0.7 product it:

- adds the hidden subcommand `mcp`, an MCP approval server over stdio with the one tool `magos_approve`: the user
  approves a user-only subcommand in the host's own dialog (an MCP elicitation form: tick `Approve`, then Accept), and
  only on that answer the server records a one-time approval and runs this guard's command with it in its own process,
  at every level but `terminal` and never without the user's answer; the MAGOS plugin for Codex starts it
  from its root `mcp.json` (Codex approval (version 1.0.8));
- has the Codex hook name `magos_approve`, its exact arguments and the command for a real terminal when it denies a
  user-only command;
- denies a tool command that starts `mcp`, on every host, with the `protected_mcp` text;
- denies, on every host with the `protected_slot` text, a tool command that runs this guard with a subcommand that is no
  plain word of `AGENT_SUBS`: a dynamic word (a variable, a command substitution, a parameter expansion, a PowerShell
  variable, sub-expression or splat), a word xargs, parallel or find -exec supplies, an empty slot, `hook` and every
  unknown word, also in a here-document a shell reads; and denies a command longer than 200,000 characters that names
  MAGOS with the `protected_long` text (Approval routes (version 1.0.8), The subcommand of a guard run);
- writes and prints the `[mcp_servers.magos]` entry in `install --host codex`, and reports the approval server, that
  entry and the plugin's `mcp.json` in `doctor`;
- records `route` `mcp` and `client` in the audit lines of the runs the approval server approved;
- lets the user approve a user-only subcommand in Hermes's own approval prompt. The MAGOS Hermes plugin registers two
  `pre_tool_call` callbacks for the `terminal` tool that run the plugin's guard as `hook hermes pre-tool --hermes-gate
  <gate>`; for exactly one direct invocation of this guard (bash, in the foreground, with its directory named by
  `workdir` or absolute paths) one guard run returns the command rebuilt with a one-time token and a question with a
  request-unique rule key, and Hermes asks before it runs the command. Where Hermes would approve without a human (a
  session `/yolo`, `--yolo`, `approvals.mode off`, a run nobody attends) or has no plugin approval request, the hook denies
  with the terminal text (Hermes approval (version 1.0.8));
- gives an approval record of the Hermes hook the field `route` `hermes` and a lifetime that follows Hermes's `approvals.timeout`,
  and records `route` `hermes` in the audit line of a run it approved;
- adds the cause code `APPROVAL_DIRECTORY`, the Hermes texts of the user-only denials and the Hermes question, and the
  Hermes route, entry and approvals lines of `doctor` and the `NOTE:` of `install --host hermes`;
- keeps the Hermes entry under `hooks:`, its snippet and its denial of every user-only command unchanged;
- states the approval routes of all three hosts in the texts that every host shows: `options` (the override option of
  every conflict denial and of `plan` and `check`: Claude Code's dialog, `magos_approve` in Codex, Hermes's approval
  prompt, and the user's own terminal where no such route exists or at `terminal`), `need_tty`, `approval_unknown` (the
  host's dialog), `approval_expired` (the time the request stated, which is no longer 120 s on every route), doctor's
  approval line and the user-only hint of its re-arm and refresh lines (`_USER_RUN`), and the footer of `install` for
  every host (no Hermes entry is needed with the plugin; without it the entry is approved once).

It also consumes an approval token behind an exclusive claim (Approval (version 1.0.7), Verification in the command):
on NTFS two uses of one token at the same moment could both rename its record and both run the command; and on POSIX it
keeps a backslash in the guard home as a character of the name (`--home`, `MAGOS_HOME`), where it wrote under another
directory before.

Its claims, set records, the answers of the Claude Code hook to a user-only command (ask, allow, the denials with a
cause code), its dialog text, its approval records and audit lines, the Hermes entry under `hooks:` and every other
command are those of 1.0.7; in Claude Code only the texts named above differ.

Version 1.0.9 of the guard (`GUARD_VERSION` 1.0.9). Relative to the 1.0.8 product it:

- reads every part of a command before it decides and keeps the most severe finding: a finding of scope `always` in a
  later piece, a later command, a quoted word, a child shell, an alias value or among several targets of one writer or
  redirect wins over a `guarded` one wherever that stands, and the hook reads the command a second time with the
  absolute guard home and store whenever the first reading found nothing of scope `always`;
- starts a here-document only at a `<<` outside quotes and comments, and reads a body as commands when a shell named as
  written, by a path or in quotes stands on its line or, after a line that ends with `|`, on the line after the body;
- denies a guard run whose words up to the subcommand slot hold a brace expansion or a glob, reads the guard word also
  with `$''` and `$""` removed, without trailing dots and blanks and in its Windows 8.3 short names, takes every
  Python build (`python3.14t`, `python3.12-dbg`, `pypy3`) as an interpreter, and reads the value of every `git -c
  alias.<name>=<value>` like the text of a child shell;
- denies a command whose text nested deeper than three levels names MAGOS with the `protected_deep` text, on every host;
- reads the subcommand slots of a command in one pass, so a command of many guard-like words is read in linear time;
- maps a Codex command onto `magos_approve` only when it is exactly one direct invocation of this guard;
- keeps a POSIX backslash in the directories of `magos_approve`, the Hermes plugin and the rewritten command, refuses a
  Hermes `workdir` that is no existing absolute directory, and refuses a `~` interpreter or script word where the call
  names no directory;
- reads a Hermes flow list up to its first `]`.

Its claims, set records, approval records, audit lines and texts are those of 1.0.8, with the `protected_deep` text
added; commands that 1.0.8 allowed and that none of the readings above concerns are allowed alike.

Compatibility: claim files of format 1 written by 1.0.0 to 1.0.3 are read unchanged, and line 1 of every claim stays
`state=active`, so the git layer reads old and new claims alike; a claim stored under a name the Windows alias rule
refuses allows the creation of its branch. The git-layer hook reads `refs/heads/` in any case of `refs` and `heads`, so `doctor` reports an armed
repository as different from this version until `arm` runs again; the text of the git-layer hook is the same in 1.0.4,
so a repository armed by 1.0.3 stays current. The Codex and Hermes copies under `~/.magos/guard`
receive 1.0.4 only when the user re-runs `install`; `doctor` reports a stale copy with the refresh command, and armed
repositories are refreshed by re-running `arm`. Exit code 18 and the exit codes 19 to 24 are new. A Hermes entry points at the Hermes plugin
launcher only while the plugin's guard declares the installing guard's version; after the plugin moves to another
version, `doctor` reports the difference and `install` points the entry at the copy until the versions agree again.
`references/lane-split.md` is a flat reference shipped to Codex and Hermes by the `references/*.md` glob.
`hooks/hooks.json` and `hooks/run-guard.cmd` sit at the repository root, outside `.claude-plugin/`. The root
`description` stays within 1024 characters. The git layer is opt-in per repository (`arm`) and the Codex and Hermes entries are
generated, never merged automatically; the MAGOS plugin for Codex starts the MCP approval server from its root
`mcp.json`, and the MAGOS Hermes plugin runs the guard through its own `pre_tool_call` callbacks, each without any
entry.

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
- PowerShell's backtick escapes that differ between Windows PowerShell 5.1 and PowerShell 7 are read as PowerShell 7
  reads `` `e `` (the escape character; Windows PowerShell 5.1 reads the letter e), and `` `u{<hex>} `` is read as the
  letter u followed by its text (PowerShell 7 reads the character the number names).
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
- The hooks are a best-effort detector of the text of one command line: they judge the words and routes they are written
  to read, and the classes below are the spellings and routes that reading does not cover. The Git backstop does not
  read the command line. In a repository the user has armed (`arm`), it vetoes the creation of a branch (a ref under
  `refs/heads/`, or a `HEAD` set to a branch that does not exist) without a claim whatever tool ran the git binary,
  within its own limits above (a branch rename or copy, a `core.hooksPath` or `GIT_CONFIG_*` override, a
  `GIT_COMMON_DIR` that names another repository, direct `.git/refs` writes, libgit2 and JGit, clones). For every class
  below the user does the same three things: keeps the repositories where lanes live armed, runs the commands that
  matter through a script they have reviewed (the guard cannot read what a script does through the routes below), and
  stays on the lane discipline of the skill (plan before creating, never work around a denial); a class whose remedy
  differs says so.
- Aliases that git reads from a place the hook does not read: `-c alias.<name>=` written in another letter case (git
  folds the name) or naming a built-in (git ignores it, the hook expands it), `--config-env=alias.<name>=<VAR>`,
  `GIT_CONFIG_COUNT` with `GIT_CONFIG_KEY_<n>` and `GIT_CONFIG_VALUE_<n>`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_GLOBAL`
  and `GIT_CONFIG_SYSTEM`, `-c include.path=`, an alias that `git config alias.<name>` defines earlier on the same line,
  the local aliases of a repository other than the session directory's (`git -C <other> <alias>`, `cd <other> && git
  <alias>`, `--git-dir`), and every alias when the session directory is no repository (the aliases are loaded for the
  session directory's repository, with the global aliases git reports there). Also not followed: a chain of more than
  three aliases or nested shells, and a `!` alias that calls another alias; the alias check does not run when git is
  spelled `git.exe`, `Git`, a path to `git.exe` or a variable (`g=git; $g <alias>`), and an alias load that runs out of
  its Git budget lets an alias creation through. The backstop vetoes the ref whatever alias git expanded: keep armed the
  repository the line reaches (for `-C`, `cd` and `--git-dir`, the other repository).
- Command text that git runs from its configuration or environment (`-c core.fsmonitor=`, `core.editor`,
  `sequence.editor`, `diff.external`, `GIT_EDITOR`, `GIT_SEQUENCE_EDITOR`, `GIT_EXTERNAL_DIFF`) and the text of `git
  rebase --exec` or `git bisect run` whose program word is dynamic (`-x "$(echo git branch x)"`) are not inspected. Keep
  the repository armed: the backstop vetoes the branch that text creates.
- Wrappers and program spellings outside the walker's lists are not read: a wrapper the walk does not unwrap (`ionice`,
  `flock`, `taskset`, `chrt`, `fakeroot`, `coproc`, `eatmydata`, `busybox`, ...), a listed wrapper written with a path
  or `.exe` (`/usr/bin/env git ...`, `env.exe`, `/usr/bin/nohup`, `/usr/bin/xargs`, `/usr/bin/sudo`), a program word
  written with ANSI-C or locale quoting (`$'g\x69t'`, `$"git"`), split by a backslash and a newline (`g\<newline>it`, in
  bash and in a tool whose shell is not known), spelled by an empty expansion or a command substitution (`g${x}it`,
  `$(echo git)`), held in a literal variable (`x=gi; ${x}t switch -c y`, `b=bash; $b ../mk`) or computed (`g=$(command
  -v git); $g ...`, `$git = (Get-Command git).Source; & $git ...`), run by a shell outside the named list (`fish`,
  `csh`, `tcsh`, `busybox sh`, `pwsh-preview`), or found through `PATH`. Run the commands that matter through a script
  you have reviewed, and keep the repository armed: only its backstop stops the branch they create.
- In a tool whose shell the hook cannot name (the Codex and Hermes shell tools, MCP command tools), a backslash in the
  program word, the subcommand or the branch name of a git invocation makes the creation dynamic, but a backslash inside
  any other word is compared as written: an option word (`-\C <repo>`, `--git\-dir=<repo>`, `-c al\ias.x=branch`,
  `--cr\eate`), a sub-subcommand (`worktree a\dd`, `stash b\ranch`) or the ref of `update-ref` (`refs/he\ads/x`), so the
  creation, or the repository it reaches, is not judged. Keep the repository armed.
- Text a shell is told to run is not walked in these routes: text inside a process substitution (`cat <(git switch -c
  x)`, `diff <(git status) <(git switch -c x)`), text quoted, echoed or fed by a here-string into a shell when it names
  no git (`printf '. ../mk\n' | sh`, `sh <<< 'bash ../mk'`), a script run directly without a `.sh`, `.bash` or `.ps1`
  name (`./mk`) and a script another command feeds (`cat ../mk | bash`, `. <(cat ../mk)`). Read such a script before it
  runs, and keep the repository armed.
- A `cd` into a directory that an earlier command of the line creates is followed only in a `&&` chain of `mkdir`, `git
  init`, `git clone` and `git worktree add`; after `;`, a newline, `&`, `install -d`, `ln -s` or `cp -r` the commands
  after it are judged where the shell was before the `cd` (`mkdir L/nd; cd L/nd; git switch -c x`, run from a directory
  outside the repository `L`). Create the directory in a call of its own, or chain the commands with `&&`, and keep the
  repository armed.
- A push or fetch whose destination the hook does not read: a fetch that writes `refs/heads/*` through `--refmap` or `-c
  remote.<name>.fetch=` (`git fetch --refmap=refs/heads/b:refs/heads/b <repo> b`), a push into another local repository
  whose refspec has no colon (`git push ../R newb`, `+newb`, `refs/heads/newb`, `HEAD`) or that is `--all`, `--mirror`
  or `--branches`, and a push whose repository argument a bundled short option with a value displaces (`git push -fo x .
  HEAD:b`, `-uo x`); only a refspec with a colon names its destination. A push to a remote name is not judged either
  (above). Arm every repository lanes are made in, the receiving one of a push or fetch included: its backstop vetoes
  the ref.
- A symbolic ref created outside `refs/heads/` that points into it (`git symbolic-ref refs/x/alias refs/heads/z`, then
  `git update-ref refs/x/alias HEAD`) writes the branch through the alias; the host hook does not follow aliases. Keep
  the repository armed: its backstop vetoes the write.
- A substituted text with a group inside it is not read: `$(git switch -c x $(git rev-parse HEAD))` in bash, `( .. ( ..
  ) )`, `@( .. ( .. ) )` and `$( .. $( .. ) )` in PowerShell (also inside a double-quoted string); only a group with no
  parenthesis inside it is judged. Keep the repository armed.
- PowerShell text is read with approximations: a `\"` or a doubled backtick before `"` in a double-quoted string is read
  as an escaped quote (PowerShell ends the string there: `Write-Output "C:\tmp\"; git switch -c x`), a backslash at the
  end of a line joins the next line (PowerShell continues a line only with a backtick), and a here-string whose body
  holds an apostrophe or a double quote and a block comment `<# .. #>` (also one between the words of a command, `git
  <##> switch -c x`) are read as commands and quotes, so the quote tracking is off for the rest of the line and the
  creation after them goes unjudged; a command-shaped line inside a here-string or a block comment is judged as a
  command and denied although nothing runs it. Keep the repository armed.
- PowerShell code built from a string and run through a script block (`& ([scriptblock]::Create('git switch -c x'))`,
  `.Invoke()`, `$ExecutionContext.InvokeCommand.InvokeScript('..')`) and a program called by a dot (`. git switch -c x`)
  are not read (`iex`, `Invoke-Expression`, `{ }` blocks, `Invoke-Command` and `Start-Job` are). Keep the repository
  armed.
- The switches of `cmd` other than a lone `/c` or `/k` (`/r`, `/d/c`, `/q/c`, `/cgit`, `/c"git .."`), also in a Codex
  argv, and cmd's own `start` (`cmd /c start /b git switch -c x`) are not read. Keep the repository armed.
- What `Start-Process` starts is read only when the word `git` itself is among its words: a shell it starts
  (`Start-Process powershell -ArgumentList '-Command "git switch -c x"'`, also `cmd`, `bash` and `pwsh`) and a call
  through splatting (`Start-Process @p`) are not read, and the `-ArgumentList` of `Start-Process git` is cut at its
  commas and read with shell quoting, so a name with a comma or quotes is judged as another name than the one git
  receives (a registered claim for `a` then licenses `a,b`). Keep the repository armed.
- The options of a child shell are read in part: `pwsh -WorkingDirectory <dir>` (also `-wd`) runs its text in `<dir>`,
  which the guard judges in the session directory, `powershell -File <script>` is read only when the script is among the
  first four words that are no option (four option values before it hide it), and `env -S` with bundled short options
  before the `S` (`env -vS`, `env -iS`) or the `\_` separator (`env -S 'git\_switch\_-c\_x'`) is not split. Keep the
  repository armed.
- The tamper filter does not follow these routes: user-only commands (`disarm`, `override`, `arm`, `install`) pass
  through a guard word that no interpreter, wrapper or `Start-Process` runs followed by a variable (`$g = '<guard>'; py
  $g $a`), an argument split by a block comment (`py magos_guard.py <##> disarm`), `env -S` with a guard word that no
  interpreter runs, a program the walk does not unwrap that runs the script without an interpreter word (`ionice -c3
  <guard> $x`, `npx <tool> <guard> $x`), `python -c` and `runpy`, a copy of the guard under another name and a script
  file that runs it; the same routes start `mcp` or `hook`. Writes to the guard's state (`.git/hooks`, refs, config) pass through `cmd
  /r`, `/d/c` and `/cdel`, a shell that `Start-Process` starts, `env -S`, `iex` and `ScriptBlock::Create`, besides the lexer
  approximations above; a command started in a new console also passes the console gate. This is the one class where the
  backstop itself can be removed, so the user runs `doctor` (an armed repository must report `git layer: installed`; the
  audit logs record the `arm`, `disarm` and `install` runs that went through the guard) and re-runs `arm` in their own
  terminal when it does not.
- An MCP command tool whose command is not a string under `command` is allowed without parsing: a list (`{"command":
  ["git", "switch", "-c", "x"]}`), `command` with `args`, or another key (`cmd`, `script`, `argv`, `commandLine`,
  `input`); a Codex or Hermes shell tool with an argv list is read, and an MCP tool named for sessions, worktrees or
  branches is still judged by its name. Keep the repository armed.
- Judged as a creation or a protected command by their text or name, so these calls are denied although they create
  nothing: an `Agent`, `Task` or `Workflow` prompt or script that mentions `isolation: worktree`, quoted text with a git
  creation word beside a here-string or a process substitution (`grep "git switch -c x" <(git log)`, `cat <<< "git
  switch -c x"`), an MCP tool named `get_branch`, `delete_branch` or `get_worktree_status`, the help forms of `gh pr
  checkout`, `gt create` and `claude -w`, the one-argument read `git config magos.<key>`, `git branch` with an
  abbreviated long option for a deletion or a listing (`--del`, `--li`), git options that print and exit (`git --version
  branch x`), and a word that names a program after a wrapper and a redirection operator written alone (`env > git
  switch -c x`). The denial stops only that call: report it, and the user runs the command in their own terminal.
- An `update-ref --stdin` whose input is a file, another command or text with an expansion is denied as a dynamic
  creation even when it only deletes or writes refs outside `refs/heads/`, because the hook cannot read it; it reads the
  instructions only when a here-document, a here-string or an `echo` or `printf` piped into it feeds them.
- The sh half of the launcher (`hooks/run-guard.cmd`) reads its input line by line, so a payload of tens of thousands of
  raw lines costs quadratic time (20,000 lines cost about 18 to 22 s, against the hook's 25 s timeout; the host decides
  what a hook that times out means; section 12 of `references/lane-split.md` lists the hosts that fail open). A Claude
  Code payload carries its command in a JSON string, which cannot hold a raw newline, so an agent cannot cause it; only
  a host that pretty-prints its payload can, and it should send the payload on one line. The cmd half hands its input to
  Python directly.
- `doctor` run from the copy compares it with the file `VERSION.json` names as its `source`; a plugin that installs
  each version into a directory of its own leaves that file at the copy's own version, so a newer plugin is not seen
  from the copy.
- A plugin directory whose Windows path holds a cmd metacharacter breaks the plugin's own Windows hook entry, which
  `install` cannot choose.
- Claims are per clone, and neither an override, the console gate nor an approval token is access control (Approval
  (version 1.0.7), Limits); the MCP approval server proves a human only as far as the host does (Codex approval
  (version 1.0.8), Limits), and the Hermes route only as far as Hermes's approval gate (Hermes approval (version
  1.0.8), Limits).
- Sets live in one clone: the record and the claims are in the clone's store, are shared by its worktrees and are not
  carried by fetch, push, clone, bundle or mirror, so a second clone neither sees nor honours the set, and the set record
  never travels with the integration branch.
- The guard proves the disjointness of the manifests, not the independence of the lanes: semantic coupling between files
  (a changed signature, a shared type, a config key read elsewhere) is not detected, and coupled files belong in one lane.
  A manifest is a declared ownership, not a barrier: nothing stops a lane from editing a file outside it; `ready`
  (OUT_OF_LANE) and `set-show --drift` (`out_of_lane`, `shared_changes`) report it afterwards.
- The claims of an older guard cannot see the set: a guard of 1.0.3 reads the claims of a set as ordinary claims but has no
  set subcommand, does not list or report sets, and can `release` a lane claim of a set, amend it, or re-plan it after
  an override, which `set-show` and `doctor` then report as `missing` or `mismatch`.
- A plan is stale only when it is next compared: the target can move after `set-plan` without any message, and the plan
  learns it at the next `set-plan --amend`, `set-show --drift` (`target_moved`, `target_overlap`, `stale`) or convergence.
  `ready` records a commit: a later reset or force move of the branch shows as `moved_since_ready`, not as a refusal.
- The drift of the target leaves out the set's own work by ancestry, for the set as a whole: a target commit that the
  integration branch or the recorded head of one `ready` or `integrated` lane holds is left out for every lane, also
  for a lane whose branch does not contain it, so `target_overlap` names what the set's work does not yet hold, not
  what each lane holds. A land of the integration branch by squash or rebase creates commits that no head of the set
  holds, so after such a land the files of the lanes count as target changes and `stale` is true.
- `set-release` judges unmerged work by ancestry, like `release`: a lane branch or an integration branch that was
  squash-merged or rebased into the target holds commits the target does not contain by ancestry, so the set cannot be
  released until that branch is deleted or merged. A process killed in the middle of a registration leaves claims without a record or a record without claims,
  which `doctor` reports and `release --branch` and `set-release --abandon` clear.
- Shared files are plain file paths (no glob or directory) and are checked only against the owner's manifest; the
  guard does not read the `sheet`, the notes, the acceptance text, the text of a requirement or the outcome of a lane:
  it proves that every requirement is served by a lane and every lane serves one, not that the lane delivers the
  outcome or that the topic of an id fits the files it owns (a name that is not generic, ordinal or reserved is accepted).
- The summary of the changes is a snapshot of the moment a lane is recorded `integrated`: it counts the non-merge
  commits by ancestry against the then current tip of the local target, so a later commit to the lane branch is not
  added, a merge commit is never a lane commit (its own change still counts among the files), and a squash or
  rebase merge of the lane cannot be recorded as integrated at all, because its head is an ancestor of neither the
  target nor the integration branch. A lane recorded `integrated` after it was landed is measured against its
  `ready_target`, so a lane recorded `ready` only after its work was already in the target stores zeros: the target
  tip of that `ready` already holds the lane's commits, and ancestry cannot tell a lane's own commits in the target
  from target commits it took in by a merge or a fast-forward.
