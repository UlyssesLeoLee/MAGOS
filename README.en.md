# Multi-Agent Git Orchestrator Skills

[English](README.en.md) | [中文](README.md)

> **Let multiple AI agents safely develop the same Git repository in parallel.**

A Git workflow skill for coding agents — Claude Code, Codex, Cursor, OpenCode, Hermes, and any host that supports the Agent Skills format.

It actively inspects the current repository's **branch / worktree / commit / ahead-behind / dependency** state, then helps the agent decide:

- Which tasks can safely run in parallel
- Which worktrees can be reused or reclaimed
- Which branches should be rebased vs merged
- Which commits are worth cherry-picking
- Which branches are now safe to delete
- How to stop several agents from destroying `main`

![MAGOS](https://github.com/user-attachments/assets/4d450361-25b5-4d35-90d8-d5656bd496cb)

---

## Plain-language primer (start here if you are new to Git)

> No Git background needed. Think of several people editing the same important document.

| Word you will see | In plain words | Office analogy |
|---|---|---|
| repository | The folder that holds the whole project and its full history | A filing cabinet of documents and every revision |
| commit | One recorded change, with an ID | A saved version of the document |
| branch | An independent line of changes; lines do not disturb each other | Each person's own revised draft |
| `main` | Usually the "official, stable" line | The finished, published version |
| merge | Bring the changes of one branch into another | Fold several drafts into the master copy |
| worktree | The folder where one branch is being edited | Each person's own desk |
| remote | The copy stored online (for example on GitHub) | The company's shared-drive backup |
| preview / apply | Look at the plan first, then decide to really do it | Read the renovation plan, then say "go" |

**Every command follows one rule: look first, act only when told.** The four commands that can change your repository (`/GitIntegrate`, `/GitCleanup`, `/GitConverge`, `/GitSweep`) act only when you explicitly ask, and they stop and explain whenever they are unsure instead of pushing on.

### How do I write a command?

Type the command in Claude Code, followed by optional "arguments" separated by spaces:

```text
/CommandName  required-thing  --switch  --switch-with-a-value value
```

- Things in `<angle brackets>` are **required**. Replace them with your own value, for example `<branch>` becomes `agent/release`.
- Things in `[square brackets]` are **optional**.
- Anything starting with `--` is a "switch". Some work on their own (`--apply`); some need a value after them (`--lang English`).
- If a value contains a space, put it in quotes: `--lang "Brazilian Portuguese"`.
- The order of switches does not matter.
- `--help` is always safe: it **only shows the instructions and never reads or changes your repository**.

---

## Three arguments that work everywhere

These three work the same way in every command that supports them. Learn them once and every command below gets easier.

### `--help`: just show the instructions

**How to write it**: `/CommandName --help`. It can go anywhere after the command and can be combined with other arguments; as soon as `--help` is present, only the instructions are shown.

```text
/GitConverge --help
/GitIntegrate agent/auth --strategy squash --help      ← other arguments are ignored; only the help is shown
/GitRecon --help --lang English                         ← show the help in English
```

| Item | Explanation |
|---|---|
| What it does | Shows how to write the command, what every argument means, what happens when you leave them out, and a few examples, then stops |
| What it never does | Never reads your repository, never runs Git, never changes anything |
| When to use it | You forgot the syntax, you are unsure what an argument means, or it is your first time with a command |
| Which commands | All seven |

> **When in doubt, add `--help` first. It is completely safe.**

---

### `--remote`: ask the internet for the latest state first

**How to write it**: `/CommandName --remote`. It is a plain switch; no value follows it.

```text
/GitRecon --remote
/GitAnalyze agent/auth --remote
/GitRecommend which branches should merge first --remote
```

**What is the difference with and without it?** Suppose your computer noted yesterday that "online `main` is at change #100", and today a colleague uploaded 3 more changes.

| Written as | How it judges | Likely consequence |
|---|---|---|
| Without `--remote` (default) | Uses only the records **already on your computer**: "online `main` is at #100" | Fast and needs no network, but the conclusion may be stale |
| With `--remote` | First updates the records, learns "online `main` is now at #103", then concludes | A fresher conclusion; needs the network and takes a little longer |

**What exactly does it do?** It asks Git to refresh the list of online branches and their latest positions (for example `git fetch --prune`), and to drop old records of branches that were deleted online.
**What it never does**: it never merges online changes into your branches, never changes your local branches or files, and never uploads anything.

| Item | Explanation |
|---|---|
| Which commands | Only the three read-only ones: `/GitRecon`, `/GitAnalyze`, `/GitRecommend`. `/GitSweep` has a different option with the same name, `--remote <name>`: it must be followed by a remote name, only selects which remote to sweep, and never refreshes anything. After any other command it counts as an unknown option, and you get an error and the help |
| No network or no access | It says the refresh failed and notes that its conclusions are based on the records already on your computer |
| When to add it | You just heard a colleague uploaded something, or you must decide based on how the online copy looks right now |

---

### `--lang <language>`: choose the language of the reply

**How to write it**: `--lang language`. A language **must** follow `--lang`, separated by a space.

```text
/GitRecon --lang English
/GitAnalyze agent/auth --lang 日本語
/GitConverge agent/release --lang "Brazilian Portuguese"
/GitRecommend which branches should merge first --lang en
```

**Which languages can I write?** A name or a common code; almost any language the model can write works:

| Language you want | Write it as |
|---|---|
| Chinese | `中文`, `简体中文`, `zh` (also the default when you write nothing) |
| English | `English`, `en` |
| Japanese | `日本語`, `ja` |
| Korean | `한국어`, `ko` |
| French / German / Spanish | `Français` / `fr`, `Deutsch` / `de`, `Español` / `es` |
| A name with a space | Put it in quotes: `"Brazilian Portuguese"` |

**What does it control?** All the text it writes back to you: explanations, reports, questions to you, error messages, and the text of `--help`.

**What is never translated?** Command names, option names, branch names, file paths, commit IDs, Git commands, and status codes such as `BLOCKED_DIRTY` or `MERGE`, because you may need to copy or search for them exactly. It may add a short gloss in your language next to them, for example `BLOCKED_DIRTY` (unsaved edits in its worktree).

| Item | Explanation |
|---|---|
| If you leave it out | **The reply is in Chinese**, even if you asked in English |
| Where to put it | Anywhere after the command. In `/GitRecommend which branches should merge first --lang English`, `--lang English` is taken out first, so your question is "which branches should merge first" |
| If you write it wrongly | If nothing follows `--lang`, or what follows is not a language (for example `--lang xyz123`), it tells you what is wrong in Chinese and shows the usage, **without running the command** |
| Does it change the result? | No. Only the language of the reply changes; the checks and judgments are identical |
| Which commands | All seven |

---

## Why

Multi-agent development usually collapses into this:

```text
Agent A ─┐
Agent B ─┼── one shared directory ── conflicts / overwrites / tangled history
Agent C ─┘
```

This skill turns it into this:

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

The core principle:

> **One Agent Lane = One Branch + One Worktree**

---

## Capabilities

| Capability | What it does |
|---|---|
| Repository Recon | Actively inspects branches, worktrees, HEAD, dirty state, ahead/behind |
| Dependency DAG | Works out which agent tasks block which |
| Worktree Isolation | Stops multiple agents from mutating the same checkout |
| Rewrite Safety | Decides when a rebase is allowed and when history is frozen |
| Selective Integration | Picks merge / squash / cherry-pick based on actual state |
| Freshness Gate | Blocks integration when `main` moved after your review |
| Merge Queue | Serializes writes into the shared integration branch |
| Safe Cleanup | Identifies completed branches and worktrees safely |
| Safe Rollback | `reset` for private history, `revert` for shared history |
| Branch Strategy | Identifies the branching model a repository actually follows, audits it against a parallel-agent safety checklist, proposes only the smallest change, and never edits branches as advice |

---

## The seven commands

| Command | In one sentence | Does it change your repository? |
|---|---|---|
| `/GitRecon` | A health check of the whole repository | No, look only |
| `/GitAnalyze` | A deep look at one branch or worktree | No, look only |
| `/GitRecommend` | Suggests what to do next, from real state | No, advice only |
| `/GitIntegrate` | Lands one agent's work behind a safety gate | Yes, after a series of checks |
| `/GitCleanup` | Removes finished branches and worktrees | Not by default; only with `--apply` |
| `/GitConverge` | Folds every branch into one and keeps only `main` and it | Not by default; only with `--apply` |
| `/GitSweep` | Runs `/GitConverge`, then also deletes merged remote branches | Not by default; only with `--apply` (includes remote deletion) |

Every command accepts `--lang <language>` (reply language, Chinese by default) and `--help` (instructions only); the three read-only commands also accept `--remote` (`/GitSweep`'s `--remote <name>` is a different option; see its section). Their details are in "Three arguments that work everywhere" above, so each command below describes only the arguments **it alone** has.

> **Not sure which branches and worktrees you have?** Run `/GitRecon` first and it lists them. In a terminal, `git branch` lists the branches and `git worktree list` lists the worktrees.

---

### `/GitRecon` — read the room

**A health check of the whole repository. Look only.**

Use it when you have just taken over a project, several agents are editing at once, or you do not know which branches and worktrees exist.

```text
/GitRecon
/GitRecon --remote
/GitRecon --lang English
```

It reports on:

```text
Worktrees        how many, and which branch each one is on
Branches         their latest positions, and whether an online branch exists for each
HEAD             where you are standing right now
Dirty            which worktrees hold half-edited files
Ahead / Behind   how many changes more or fewer than the main line
Detached         which worktrees are not attached to any branch
Remote tracking  which online branch each local branch follows
Merge candidates which branches are already part of the main line
Risk             things you should look at
```

#### The arguments in detail

`/GitRecon` has no required argument; just type it. Optional arguments:

| Argument | How to write it | What it does |
|---|---|---|
| `--remote` | `/GitRecon --remote` | Refresh the online reference data first; see "Three arguments that work everywhere" |
| `--lang <language>` | `/GitRecon --lang English` | Reply in that language; Chinese if omitted |
| `--help` | `/GitRecon --help` | Show the instructions only |

---

### `/GitAnalyze <target>` — understand one lane

**A deep look at one branch or one worktree. Look only.** Use it to answer "can I merge or delete this?".

```text
/GitAnalyze agent/auth
/GitAnalyze ../wt-auth --remote
```

#### The arguments in detail

**`<branch or worktree path>` (required): what to inspect**

| Item | Explanation |
|---|---|
| What to write | Either works: a **branch name** (as `git branch` shows it, for example `agent/auth`) or the **folder path of a worktree** (for example `../wt-auth`; a full path is fine too) |
| Where to find names | Run `/GitRecon`; the list has every branch name and worktree path |
| If you leave it out | It does not guess; it asks which one to inspect and shows the help |
| If you get it wrong | It says it cannot find that branch or path and asks you to confirm; it does not inspect something else |
| A branch and a path share a name | It decides from the facts of the repository; if the answer would change the conclusion, it tells you about the ambiguity instead of picking one |

**`--remote` (optional)**: refresh the online reference data first; see "Three arguments that work everywhere". **`--lang <language>` (optional)**: reply language, Chinese by default.

#### What it checks, and how to read the report

It finds the common starting point with the main line, how far ahead or behind the branch is, its unique changes, the files it touches, whether other branches depend on it, and whether its history may be rewritten. It ends with a verdict for each of merge, rebase, cherry-pick, squash, and cleanup/delete: safe or not. Illustrative:

```text
agent/auth

Ahead:     3          ← 3 changes more than the main line
Behind:    2          ← 2 changes fewer (the main line has new changes it does not have yet)
State:     DIVERGED   ← each side has changes the other lacks: the lines have "forked"
Depends:   agent/core ← it is built on top of agent/core
Rewrite:   FROZEN     ← do not rewrite its history; branches that depend on it would break

Recommendation:
Do not rebase directly (that rewrites history)
Bring the main line in first, then validate again
```

---

### `/GitRecommend [goal]` — decide what happens next

**Advice from the real state of the repository. Advice only.**

Use it when you are unsure what to do next, for example "how should I split work between 3 agents?".

```text
/GitRecommend
/GitRecommend how should I arrange 3 agents
/GitRecommend which branches should merge first --remote
```

#### The arguments in detail

**`[goal]` (optional): your question or what you want to achieve**

| Item | Explanation |
|---|---|
| How to write it | Just write it in your own words after the command; **no quotes needed**, any length |
| If you leave it out | You get general next-step advice covering every branch and worktree |
| How to write a good one | **The more specific, the better**: say what you want to achieve, how many agents there are, and which branches matter most |
| Mixing with other arguments | Fine. `--remote` and `--lang English` are taken out first; the remaining text is your question |

Examples:

```text
/GitRecommend                                                ← general advice
/GitRecommend how should I arrange 3 agents                  ← work split
/GitRecommend agent/auth is done, how do I wrap it up        ← about one branch
/GitRecommend find the best worktree for a new task --lang ja ← reply in Japanese
```

**`--remote` (optional)**: refresh the online reference data first. **`--lang <language>` (optional)**: reply language, Chinese by default.

#### What the report looks like

It investigates first, then answers in this order: observed facts, the biggest risks, recommendations in order, the reason for each, and what could not be determined. Illustrative:

```text
Agent A → can keep going in parallel
Agent B → edits mostly the same files as A; queue it behind A
Agent C → depends on A; wait for A

agent/old-ui → looks safe to clean up
agent/auth   → others depend on it; do not rewrite it yet
```

---

### `/GitIntegrate <lane>` — land the work behind a gate

**Bring one agent's work (one "lane") into the main line safely.** An agent saying "Done" is never enough.

```text
/GitIntegrate agent/auth
/GitIntegrate agent/auth --strategy squash
/GitIntegrate agent/auth --strategy cherry-pick --lang English
```

#### The arguments in detail

**`<lane or branch>` (required): the branch to bring into the main line**

| Item | Explanation |
|---|---|
| What to write | A branch name such as `agent/auth` (`/GitRecon` shows every branch name) |
| If you leave it out | It asks which one to integrate; **it never picks one for you** |
| Where it lands | The repository's "integration branch", usually `main`; it works this out from the repository's conventions and tells you if it cannot, rather than guessing |

**`--strategy <how>` (optional): how to bring it in**

Write one of the four values after `--strategy`. Leaving it out is the same as `--strategy auto`.

| Value | Plain meaning | Good for |
|---|---|---|
| `auto` (default) | Pick the best way from the repository's habits and your review | When you are not sure which to choose |
| `merge` | Bring everything in and **keep** every change record, plus one extra "merge record" | You want the full history of how it was built |
| `squash` | Bring everything in as **one** combined record (only if the repository's rules allow it) | The changes are fiddly and you want a tidy main line |
| `cherry-pick` | Bring in **only the changes already confirmed safe** and leave the rest | Only part of the work is acceptable |

How the three differ in history (`A, B` are the main line's existing records; `C, D` are the branch's two changes):

```text
merge          A──B──────M       M is a new merge record; C and D stay as they were
                  \     /
                   C──D

squash         A──B──S           S is one new record holding all of C and D; they do not enter the main line separately

cherry-pick    A──B──C'          only C is copied over; D does not enter the main line
```

| If… | It will… |
|---|---|
| The value is wrong, for example `--strategy rebase` | Say only `auto`, `merge`, `squash`, `cherry-pick` are supported, show the help, and **not continue** |
| You write `--strategy` with no value | Same: it asks you to add one |
| You pick `cherry-pick` but it does not know which changes you approved | **Stop and ask**; you must say which changes passed review, and it will not guess |
| The way you chose breaks the repository's rules or is unsafe | Refuse and explain, even if you asked for it explicitly |

**`--lang <language>` (optional)**: reply language, Chinese by default.

#### What it checks before acting

It checks, one by one: is there evidence that the work was reviewed and accepted, are there unfinished dependencies, did the main line change after your review, did this branch gain new changes after your review, and do the repository's rules allow it. **If any check fails it stops and tells you; it never forces it.** After integrating, it validates the main line again.

```mermaid
flowchart TD
    A["Agent Lane"] --> B["Refresh"]
    B --> C["Validation"]
    C --> D["Review"]
    D --> E["Freshness Check"]
    E --> F{"Scope accepted"}
    F -->|"all"| G["Merge / Squash"]
    F -->|"part"| H["Cherry-pick"]
    G --> I["Validate main"]
    H --> I
```

---

### `/GitCleanup` — reclaim branches safely

**Find old branches and worktrees that are safe to remove.**

Use it when finished branches have piled up and you want to tidy up without deleting the wrong thing.

```text
/GitCleanup              # list candidates only; deletes nothing
/GitCleanup --apply      # actually delete
/GitCleanup --lang English
```

#### The arguments in detail

`/GitCleanup` has no required argument.

**`--apply` (optional): really clean up**

| Item | Explanation |
|---|---|
| How to write it | `/GitCleanup --apply`; a plain switch, no value |
| If you leave it out | **Preview only**: lists the objects that can be cleaned and the ones that cannot (with reasons); deletes nothing |
| What it does with it | For each object marked "can be cleaned", it **checks the current state again** and deletes only if it is still safe: first removes its worktree, then deletes the branch |
| An object changed between preview and apply | For example the branch got a new change after the preview: it **skips** that one and tells you, rather than deleting from the old list |
| What it never does | Force-delete; clean a worktree with unsaved edits, an operation half-way through, or ignored files; delete a branch that holds work found nowhere else; run a repository-wide `git worktree prune`; delete `main`, the target, or the worktree you are standing in; delete online (remote) branches unless you explicitly ask |

Suggested habit: **read the list without `--apply` first; add it only when you are happy.**

**`--lang <language>` (optional)**: reply language, Chinese by default.

#### The status of each object in the preview

| Status | Plain meaning | Cleaned? |
|---|---|---|
| `SAFE_CANDIDATE` | All seven conditions hold; safe to clean | Only with `--apply` |
| `BLOCKED_DIRTY` | Its worktree has unsaved edits | No |
| `BLOCKED_UNIQUE_WORK` | It holds work that exists nowhere else | No |
| `BLOCKED_ACTIVE_OWNER` | Someone (or some agent) is using it right now | No |
| `BLOCKED_DEPENDENCY` | Another branch depends on it | No |
| `BLOCKED_NOT_INTEGRATED` | Its content is not fully in the main line yet | No |
| `BLOCKED_IN_PROGRESS` | Its worktree is half-way through an operation (for example a rebase stopped mid-way); it looks clean but is not | No |
| `BLOCKED_IGNORED_FILES` | Its worktree holds files Git ignores (such as a `.env` with passwords); removing the worktree would delete them | No (move or delete those files yourself, then run `/GitCleanup` again) |
| `UNKNOWN` | A key fact could not be established: for example a worktree with no recorded owner (someone may still be using it), or two branch names that differ only in case | No (no confidence, no action) |

A branch becomes a `SAFE_CANDIDATE` only when **all** seven hold:

```text
✓ fully integrated
✓ worktree clean
✓ nothing half-way through in its worktree
✓ no ignored files in its worktree
✓ no active owner (a worktree it has needs a recorded owner)
✓ no downstream dependents
✓ no unique unsaved work
```

`main`, the target, and the worktree you are standing in (with its branch) never go on the list.

**Note: "untouched for a long time" does not mean safe to delete.** Age alone never puts a branch on the cleanup list.

---

### `/GitConverge <branch>` — fold every lane into one branch

**Collect the work of every branch into the branch you choose, then keep only `main` and that branch.**

Use it when several agents finished their branches and you want to "close the net": gather everything in one place and clear away the used branches.

#### An example

Suppose the repository has:

```text
main           the stable version (1 new change)
agent/release  where you want everything collected
agent/a        Ann made 2 changes
agent/b        Bob made 1 change (his worktree is ../wt-b, nothing unsaved)
agent/c        its content is already included; nothing new
```

After `/GitConverge agent/release --apply`:

```text
Before:  main  agent/release  agent/a  agent/b  agent/c      (5 branches)
After:   main  agent/release                                  (2 branches)
         └─ agent/release now contains the work of main, a, and b
         └─ a, b, c are deleted; Bob's worktree ../wt-b is cleaned up too
```

#### Before you start: check three things

1. **Run it from the folder that holds the target branch.** Whichever folder currently has the target (for example `agent/release`) checked out is where you open Claude Code. If another folder is using the target, it refuses and tells you to run it from there.
2. **That folder must have no unsaved edits and must not be "half-way through" something** (merging, rewriting history). Otherwise it refuses and explains.
3. **The target cannot be `main`.** To bring work into `main`, use `/GitIntegrate`.

#### How to use it: three steps

**Step 1: preview (changes nothing)**

```text
/GitConverge agent/release
```

You get a plan: which branches will be merged and in what order, which will be deleted, which will be **kept** and why, and what will be left at the end. Illustrative:

```text
Plan (preview; nothing was changed)
Target branch: agent/release

To merge (in this order)
  1. main        1 new change
  2. agent/a     2 new changes
  3. agent/b     1 new change (worktree ../wt-b is clean; deleted after merging)
Already included, delete only: agent/c

Branches that stay: none
After this only: main, agent/release
Untouched: online branches, tags, worktrees other people are using
```

**Step 2: read the plan**

Each branch in the preview has a status. In plain words:

| Status | Plain meaning | Merged? | Deleted? |
|---|---|---|---|
| `MERGE` | Has new changes to bring in | Yes | Deleted after merging |
| `CONTAINED` | Its changes are already in the target | Not needed | Deleted |
| `BLOCKED_UNRELATED_HISTORY` | Shares no history with the target (for example a separate `gh-pages`) | No | Kept |
| `BLOCKED_IN_PROGRESS` | Someone is half-way through something (rewriting history, cherry-picking); its position is unreliable | No | Kept |
| `BLOCKED_DIRTY` | Its worktree has unsaved edits | Yes (saved part only) | Kept |
| `BLOCKED_LOCKED` | Its worktree is locked (someone or something is using it) | Yes | Kept |
| `BLOCKED_ACTIVE_OWNER` | The worktree belongs to another agent or tool, or is the main worktree | Yes | Kept |
| `BLOCKED_IGNORED_FILES` | The worktree holds files Git ignores (for example a `.env` with secrets) | Yes | Kept (deleted only with `--discard-ignored`) |
| `BLOCKED_SUBMODULE` | The worktree contains a sub-project; Git refuses to delete it directly | Yes | Kept |
| `BLOCKED_UPSTREAM_OF_KEPT` | Another branch that stays depends on it | Yes | Kept |
| `UNKNOWN` | A key fact could not be established, or its name equals another branch's except for case (both stay untouched; the report says how to rename one safely) | Untouched | Untouched |

If any branch is kept, the plan says plainly that you will **not** end up with only `main` and the target, with the reason and the next step.

**Step 3: happy with it? Run it**

```text
/GitConverge agent/release --apply
```

It re-checks the current state, records the plan it will act on, merges the sources one by one, deletes the merged branches and their clean worktrees, and ends with a report. The report has: the plan it acted on, what it did, what it skipped (and why), the target's start and end IDs, and the original ID of every deleted branch.

#### The arguments in detail

**`<branch>` (required): the branch that collects everything**

| Item | Explanation |
|---|---|
| What to write | The name of an existing **local** branch, for example `agent/release`. `/GitRecon` or `git branch` shows the names |
| It must match **exactly** | **Case matters.** `agent/release` is right; `Agent/Release` is rejected, and the right name is suggested |
| What you cannot write | `main` (it is never moved), a branch that does not exist, an online branch name such as `origin/xxx`, or a folder path |
| If you leave it out | It asks you and shows the help |
| Reminder | The target must already exist as a local branch; it will not create one for you |

**`--apply` (optional): really merge and delete**

| Item | Explanation |
|---|---|
| How to write it | `/GitConverge agent/release --apply`; a plain switch, no value |
| If you leave it out | **Preview only**; nothing changes. This is the default |
| What it does with it | Re-check the current state → record the plan → switch to the target branch (if you are not on it) → merge one by one in order → validate → delete one by one after re-checking → report |
| Merge order | `main` first; then the others, the one with the most new changes first, ties by name. So if A contains B, merging A already brings B along, and B is not merged twice |
| On a conflict | It undoes that merge right away and **stops completely, deleting nothing**; merges that already succeeded stay |
| Before each deletion | It re-confirms that the branch has no new changes, its content really is in the target, and its worktree is still clean |
| You previewed earlier | In the same conversation, it compares with that preview: if any branch has moved, it stops and gives you a new preview; branches or worktrees that appeared since the preview are left alone |

**`--discard-ignored` (optional): allow cleaning worktrees that hold "ignored files"**

What are "ignored files"? Some files (for example a `.env` holding passwords and keys, or a `node_modules/` folder) are not recorded by Git, so **once deleted they cannot be recovered**.

| Item | Explanation |
|---|---|
| How to write it | `/GitConverge agent/release --apply --discard-ignored`; a switch, no value |
| If you leave it out | A worktree that holds any ignored file is **kept** together with its branch (status `BLOCKED_IGNORED_FILES`), and the preview lists those files one by one |
| What it does with it | Such worktrees are cleaned up, and **the ignored files inside are gone for good** |
| Useful on its own? | No. It only matters together with `--apply` |
| When to use it | You have read the ignored files listed in the preview and none are needed (for example only temporary files that can be regenerated) |

> It **never** overwrites ignored files that already sit in your current folder: if a branch would bring files that overwrite them, the whole command stops before merging and tells you. This has nothing to do with `--discard-ignored`.

**`--lang <language>` (optional)**: reply language, Chinese by default. **`--help` (optional)**: instructions only.

Examples:

```text
/GitConverge agent/release                              just the plan
/GitConverge agent/release --apply                      run the plan
/GitConverge agent/release --apply --lang English       run it, reply in English
/GitConverge agent/release --apply --discard-ignored    also clear worktrees that hold .env
```

#### Situations where it refuses

In these cases it stops **before doing anything** and explains why; the repository is not changed:

| Situation | What it says | What you do |
|---|---|---|
| The target does not exist, or the case is wrong | It cannot find the branch; if only the case differs, it tells you the right name | Use the exact name |
| The target is `main` | `main` cannot be a target | Use `/GitIntegrate`, or pick another branch |
| There is no local `main` | `main` is missing | Create `main` in the repository first |
| The target or `main` has the same name as another branch except for case | The names collide, so it cannot tell them apart | Run `git pack-refs --all` first, then rename one with `git branch -m`, then check both tips (renaming without packing first can give the new name the other branch's tip and delete both) |
| Another folder is using the target | Run it from that folder | Go to the folder it names and run it there |
| The current folder has unsaved edits, is not on a branch, or is half-way through something | The current folder is not safe | Save or finish what is pending, then run it again |
| The target or `main` exists only in the record of a folder that was deleted | The record is broken and cannot be switched to | Clear that broken record as it explains, then run again |

#### Rules it always follows

```text
✓ Preview by default: without --apply nothing changes
✓ main is only read: never moved, reset, or deleted
✓ Online branches, tags, and detached worktrees are never touched; nothing is uploaded for you
✓ On a merge conflict it undoes that merge and stops, deleting no branch; finished merges stay
✓ Worktrees with unsaved edits, locks, work in progress, or another owner keep their branch
✓ Ignored files (such as .env) are never overwritten; worktrees holding them are kept by default
✓ No forced deletion, no forced worktree removal, no repository-wide pruning
✓ Before deleting each branch it re-checks: unchanged, and its content really is in the target
```

#### If something goes wrong

- **"Merge conflict"**: two branches changed the same place in different ways, and a machine cannot choose for you. It undoes that merge, stops, and **deletes nothing**, and tells you which branch conflicts. Resolve it (or delete the branch you do not need) and run the same command again; branches that already merged count as "included" and are only deleted.
- **Get a deleted branch back**: the report lists each deleted branch's original ID (a short string such as `8eccc62`). With the ID you can restore it any time:

  ```text
  git branch agent/a 8eccc62
  ```

- **Undo the whole thing**: the report has the target's "start ID". Someone with Git experience can reset the target to it; if that is not you, send the report to a colleague or an AI who knows Git.
- **Not sure whether to go ahead**: you can always leave `--apply` off and just read the plan.

#### FAQ

- **Could it delete my unsaved edits?** No. A worktree with unsaved edits is kept together with its branch.
- **Does it affect branches on GitHub?** No. It uploads nothing and deletes nothing online. Whether to push afterwards is up to you.
- **Why was a branch not deleted?** Look at its status in the plan; every kept branch has a reason and a next step.
- **What if it was interrupted?** Run the same command again. It re-checks the current state first; branches already merged are only deleted, never merged twice.
- **I want the reply in English.** Add `--lang English` at the end of the command.

```mermaid
flowchart TD
    A["Preview the plan"] --> B["merge --no-ff, one by one"]
    B -->|"conflict"| X["abort, stop, delete nothing"]
    B --> C["Validate"]
    C --> D["Re-check each: tip unchanged + already an ancestor of the target"]
    D --> E["worktree remove → branch -d"]
```

---

### `/GitSweep <branch>` — converge, then clear merged remote branches

**`/GitConverge` plus a guarded sweep of the remote branches that are already merged.**

Two phases, and nothing happens without `--apply`:

1. **Local converge**: identical to `/GitConverge` (same gates, same merge order). A conflict or failed check stops everything; nothing is deleted locally or remotely.
2. **Remote sweep**: deletes only remote branches whose tip is already contained in a branch the remote keeps: its default branch or its own `<branch>`. A branch merged only on your machine is `PENDING_PUSH` and stays until you push `<branch>` and run `/GitSweep` again.

```text
/GitSweep agent/release                              just the plan (no network)
/GitSweep agent/release --apply                      run the plan
/GitSweep agent/release --apply --remote upstream    sweep upstream instead of origin
```

**Arguments**: `<branch>` (required, the local branch that receives everything), `--apply` (actually run), `--discard-ignored` (passed to phase 1: also clear worktrees that hold `.env`), `--remote <name>` (the remote to sweep, `origin` by default; unlike the read-only commands' `--remote` switch it takes a value and never fetches).

**What stays on the remote** (each one is reported with its reason):

| Status | Meaning |
|---|---|
| `PENDING_PUSH` | Merged only locally; push `<branch>` and rerun to delete it |
| `KEPT_NOT_MERGED` | Holds commits the remote does not keep elsewhere |
| `KEPT_LOCAL` | The local branch of the same name was kept (blocked), so the remote one stays too |
| `STALE` | The live remote branch moved since the plan; skipped |
| Protected | The remote default, `main`, `<branch>`, and any branch with evidence of a long-lived role (integration, staging, release, archive) |

At apply time it first checks the live remote's default branch and branch tips and stops if they differ from what it recorded; run `git fetch` and retry.

It never pushes commits or tags, never force-pushes, and never deletes the remote default branch, `main`, or `<branch>` itself. Each remote branch is deleted on its own with a lease on its recorded SHA, so the remote refuses if the branch moved meanwhile. Deleting a remote branch closes open pull requests that use it as their head. The report lists every deleted branch with its SHA (`git push <remote> <sha>:refs/heads/<name>` restores it).

---

## Agent lane lifecycle

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

Every lane tracks: task, owner, branch, worktree, base branch, base SHA, current HEAD, dependencies, validation evidence, integration decision.

---

## Git decision rules

```text
whole agent result needed
        ↓
      Merge

only some commits needed
        ↓
   Cherry-pick

agent's private branch fell behind main
        ↓
  Rewrite-safe?
    ↓       ↓
   YES      NO
 Rebase    Merge target into lane

private history went wrong
        ↓
      Reset

error already in shared history
        ↓
      Revert
```

---

## Safety principles

```text
Observe first.
Advise second.
Mutate only when needed.
```

Denied by default:

- Multiple agents mutating the same checkout
- Concrete branch/worktree advice without inspecting the repository first
- Rebasing a branch other agents depend on
- Destructive reset on shared history
- Force push by default
- Cherry-picking without a dependency check
- Continuing integration after review has gone stale
- Deleting a branch just because it is old

---

## Lane guard

MAGOS ships a lane guard (`scripts/magos_guard.py`). Before a branch or worktree is created, the files the new lane will change must be registered as a manifest (`plan`); a creation whose planned files overlap another branch, worktree or registered lane is denied, and every conflicting lane is named. Existing lanes are only read: no hook stops a write, commit or merge inside one. The contract agents follow is `references/lane-split.md`; installing, upgrading and the known limits are in `references/installation.md`.

- **Where it runs.** The Claude Code plugin turns on PreToolUse hooks (`hooks/hooks.json`, which runs `hooks/run-guard.cmd`, which runs `scripts/magos_guard.py`) in every repository you open in Claude Code. The Codex and Hermes plugin installs do not: in your own terminal, run `py -3 scripts/magos_guard.py install --host codex` (or `--host hermes`; `python3` on macOS and Linux) and merge the entry it prints into the host's configuration. In one repository, `arm` adds a Git `reference-transaction` backstop that vetoes an unclaimed new branch whatever tool runs git.
- **Modes.** AUTO (the default): a named worktree creation always needs a manifest, a branch-only creation only when another lane exists, so a repository with one worktree and nothing unmerged is unaffected. ARMED (after `arm`): every new branch needs one, in the hooks and in Git. OFF: `git config --local magos.guard off`.
- **Opting out.** `git config --local magos.guard off` (one repository), `claude plugin disable magos` (the whole Claude Code plugin), or `MAGOS_GUARD=off` in the environment of the host process.
- **Requirements.** Python 3.9+ (`py -3`, `python3` or `python`) and Git 2.36+ (the other MAGOS commands need Git 2.30+); `magos_guard.py doctor` checks both, and `magos_guard.py version` prints the running guard's version.
- **Only you** run `override`, `arm`, `disarm` and `install`, from a real terminal; the hooks deny an agent that tries, and the hook launcher runs nothing but the hook. A command started in a new console window passes the console check, so neither that check nor an override is access control.
- **After every upgrade.** Restart the running Claude Code sessions, and re-run `install` for Codex and Hermes (`doctor` prints the exact command; for a copy installed with `install --home <dir>`, run `doctor --home <dir>`).
- **Limits.** The hooks read command text, and they let a call through when Python or the guard script is missing; the Git backstop does not see a branch rename or copy (`git branch -m/-c`), which the hooks deny in every option spelling. `references/lane-split.md` section 12 lists every limit.

---

## Install

Copy the directory into your agent's skills path:

```text
multi-agent-git-orchestrator/
├── SKILL.md              # root skill — triggers semantically
├── plugin.json           # Agent Plugins manifest, used when the whole repository is imported as a plugin
├── .claude-plugin/
│   ├── plugin.json       # Claude Code plugin manifest
│   └── marketplace.json  # plugin marketplace for Claude Code and Codex
├── plugin.yaml + __init__.py  # Hermes native plugin manifest: registers /magos:git-*
├── CHANGELOG.md          # every version, with security notes and upgrade steps
├── commands/             # Claude Code slash commands
├── skills/               # Codex / Hermes command adapters, plus the plugin entry git-orchestrator
├── hooks/
│   ├── hooks.json        # Claude Code plugin hooks: the lane guard
│   └── run-guard.cmd     # launcher (cmd and sh) that runs the guard with Python
├── scripts/
│   ├── magos_guard.py    # the lane guard
│   └── sync_hosts.py     # copies the skill package to Codex and Hermes, or the commands to Claude Code
└── references/
    ├── commands.md
    ├── reconnaissance.md
    ├── branch-strategy.md
    ├── decision-matrix.md
    ├── handoff-and-state.md
    ├── design-rationale.md
    ├── pressure-tests.md
    ├── lane-split.md     # the lane guard contract
    └── installation.md   # install, pin, upgrade and roll back per host; the lane guard
```

The root skill triggers on its own through semantic matching. The seven commands are optional explicit entry points. Besides multi-agent coordination and symptoms such as agents overwriting each other or branch sprawl, it also triggers when you choose, audit, or change the branch strategy (分支策略, ブランチ戦略) of a specific repository, above all one that agents, worktrees, or several developers share. A pure concept question such as "gitflow vs trunk-based" does not trigger it. It only advises: execution still goes through the matching `/Git...` command with its gates, and **Strategy Changes** in `references/branch-strategy.md` says which command does what. No command renames a branch, so a rename stays a manual step after dependents are coordinated. Note that with the sync-script install Hermes shows only about the first 57 characters of a skill description in its index, so there load the skill by name (or use `/git-recommend`) for branch-strategy advice; the Hermes plugin install passes its own index line, which names branch strategy.

### Cross-host install (recommended)

```bash
python -X utf8 scripts/sync_hosts.py --host codex --host hermes --apply --create-roots
python -X utf8 scripts/sync_hosts.py --host codex --host hermes --verify
```

`--verify` checks that every file the adapters reference actually exists, without starting an AI host. The script never deletes files.

### Install from a plugin marketplace (recommended, all three hosts)

All three hosts install the plugin `magos` straight from this repository, with no files to copy and no script to run:

| Host | Install | Update |
|---|---|---|
| Claude Code | in a session: `/plugin marketplace add UlyssesLeoLee/MAGOS`, then `/plugin install magos@magos` | `/plugin marketplace update magos`, then `/plugin update magos@magos`, then restart every running Claude Code session |
| Codex | `codex plugin marketplace add UlyssesLeoLee/MAGOS`, then `codex plugin add magos@magos` | `codex plugin marketplace upgrade magos`, then `codex plugin add magos@magos` again, then restart Codex and refresh the guard copy (`install --host codex`) |
| Hermes | `hermes plugins install UlyssesLeoLee/MAGOS --enable` | `hermes plugins update magos` (when its security scan asks for confirmation: `hermes plugins install UlyssesLeoLee/MAGOS --force --enable`; a pinned install moves its pin instead, see Pin a version), then restart Hermes |

Claude Code also works from a shell: `claude plugin marketplace add UlyssesLeoLee/MAGOS && claude plugin install magos@magos`.

After a new session the names line up across hosts:

| Purpose | Claude Code | Codex | Hermes |
|---|---|---|---|
| The seven commands | `/magos:GitRecon` … `/magos:GitSweep` | `$magos:git-recon` … `$magos:git-sweep` | `/magos:git-recon` … `/magos:git-sweep` |
| The orchestrator (triggers when you describe a problem) | `magos:git-orchestrator` | `magos:git-orchestrator` | `magos:git-orchestrator` (Hermes lists it in the system prompt's `<available_skills>`; the model loads it from the description) |

- Claude Code also lists the seven lowercase `/magos:git-recon` and so on. They are the cross-host adapters and do the same as `/magos:GitXxx`; use the latter.
- Plugin hosts load only the skills under `skills/`, never the root `SKILL.md`, so the plugin carries an entry skill, `git-orchestrator`, that reads the root `SKILL.md`. Skills-directory installs (the sync script, or a clone into a skills folder) do not need it, and the sync script does not copy it.
- The manifests pin a version, so Claude Code updates an installed plugin only when the version changes. A running session keeps the hooks of the version it started with, so restart every session after an update.
- The Claude Code install also turns on the lane guard hooks; the Codex and Hermes installs do not (see Lane guard). Upgrade details per host, including the guard copy and rollback, are in `references/installation.md`; what changed in each version is in `CHANGELOG.md`.
- Hermes warns "custom (unreviewed) source": MAGOS is not in the official Hermes plugin catalog. Listing it takes a pull request to NousResearch/hermes-agent by the repository owner, pinned to a commit SHA; a listed plugin installs with `hermes plugins install magos`.
- If you installed an older way, remove it first so each command exists once: `~/.claude/commands/Git*.md`, `~/.claude/skills/magos`, Codex `~/.agents/skills/MAGOS`, Hermes `skills/multi-agent-git-orchestrator`.

### Pin a version

Every release is tagged `v<version>` (`CHANGELOG.md`). The commands above follow the default branch; to stay on one release:

```bash
claude plugin marketplace add UlyssesLeoLee/MAGOS@v1.0.2    # then: claude plugin install magos@magos
git clone --branch v1.0.2 https://github.com/UlyssesLeoLee/MAGOS ~/.claude/skills/magos
hermes plugins install UlyssesLeoLee/MAGOS --ref <40-character commit SHA of v1.0.2> --enable    # add --force when MAGOS is already installed
```

A pinned install receives no later fixes, guard security fixes included: follow `CHANGELOG.md` and move the pin. The commit SHA of a tag is the `refs/tags/v1.0.2^{}` line of `git ls-remote https://github.com/UlyssesLeoLee/MAGOS refs/tags/v1.0.2 "refs/tags/v1.0.2^{}"` (the `refs/tags/v1.0.2` line when there is no `^{}` line). Hermes records a `--ref` install as pinned: `hermes plugins update magos` refuses it, and `hermes plugins install UlyssesLeoLee/MAGOS --force` without `--ref` reinstalls the pinned commit. Move the pin with `--ref <new SHA> --force --enable`; to follow the default branch again, run `hermes plugins remove magos` and then `hermes plugins install UlyssesLeoLee/MAGOS --enable`. `references/installation.md` has the details, including how to pin Codex and the sync-script installs.

### Claude Code (clone into the skills folder)

Without the marketplace, clone the repository straight into Claude Code's skills directory. It works the same and updates with `git pull`:

```bash
git clone https://github.com/UlyssesLeoLee/MAGOS ~/.claude/skills/magos
```

```powershell
git clone https://github.com/UlyssesLeoLee/MAGOS "$HOME\.claude\skills\magos"
```

The repository root carries `.claude-plugin/plugin.json`, so Claude Code loads the folder as the plugin `magos@skills-dir` in every session, with no `/plugin install` step. Start a new session and you get:

- the seven commands `/magos:GitRecon`, `/magos:GitAnalyze`, `/magos:GitRecommend`, `/magos:GitIntegrate`, `/magos:GitCleanup`, `/magos:GitConverge`, `/magos:GitSweep` (type `/magos:` to complete);
- the orchestrator entry `magos:git-orchestrator`, which triggers on its own;
- the seven cross-host adapters from `skills/`, listed as `/magos:git-recon` and so on. They do the same as the commands above; in Claude Code use `/magos:GitXxx`.

To update, run `git pull` in that folder, then start new sessions; commands, rules and the lane guard update together. `claude plugin list` should show `magos@skills-dir` as loaded.

If you copied `~/.claude/commands/Git*.md` the old way, delete those seven files, or you keep a second, older set of `/GitXxx` commands.

### Claude Code (copied commands, older way)

Without the plugin, copy the command files to `~/.claude/commands/` (all projects) or a project's `.claude/commands/`; the commands are then named `/GitRecon` without a prefix. From the repository root:

```bash
python -X utf8 scripts/sync_hosts.py --host claude --apply --create-roots
python -X utf8 scripts/sync_hosts.py --host claude --verify
```

Or copy the files by hand:

```bash
mkdir -p ~/.claude/commands && cp commands/Git*.md ~/.claude/commands/
```

```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\commands"; Copy-Item commands\Git*.md "$HOME\.claude\commands\"
```

The copies do not follow later updates. After every `git pull` or new version, run the sync (or the copy) again; `--verify` reports copies that are missing or out of date. `--host claude` covers only `~/.claude/commands`; the skill the commands load (for example `~/.claude/skills/MAGOS`) must be updated separately. When the plugin is already installed, the sync script prints a `NOTE` and the copies are not needed. Start a new session, then type `/Git`.

### Codex

```bash
python -X utf8 scripts/sync_hosts.py --host codex --apply --create-roots
```

```powershell
$codexPackage = Join-Path $HOME ".agents\skills\MAGOS"
New-Item -ItemType Directory -Force $codexPackage | Out-Null
Copy-Item -Path .\SKILL.md, .\references, .\skills -Destination $codexPackage -Recurse -Force
```

Restart Codex, press `$` to pick a command skill, or call `$git-recon`, `$git-analyze`, `$git-recommend`, `$git-integrate`, `$git-cleanup`, `$git-converge`, `$git-sweep` directly. `/skills` opens the skill browser. Arguments go after the skill name, e.g. `$git-analyze agent/auth --remote`; `--help` prints full usage.

> Codex's `/` menu only contains built-in commands, so custom `/git-*` slash commands cannot be registered. The skill selector (`$` / `/skills`) is the entry point on Codex.

### Hermes

```bash
python -X utf8 scripts/sync_hosts.py --host hermes --apply --create-roots
```

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/skills/multi-agent-git-orchestrator"
cp -R SKILL.md references skills "${HERMES_HOME:-$HOME/.hermes}/skills/multi-agent-git-orchestrator/"
```

Restart Hermes, then `hermes skills list`, then `/git-recon`, `/git-analyze`, `/git-recommend`, `/git-integrate`, `/git-cleanup`, `/git-converge`, `/git-sweep`. Hermes has no per-skill auto-invoke switch, so the adapter layer specifies that `/git-integrate`, `/git-cleanup`, `/git-converge`, and `/git-sweep` never write to the repository unless you invoke them explicitly.

### Hosts without custom slash commands

Just type the command name:

```text
GitRecon
GitAnalyze agent/auth
GitRecommend
```

### Import as an Agent Plugin

`plugin.json` at the repository root is a plugin manifest that follows the [Agent Plugins 1.0.0 specification](https://agent-plugins.org/specification). A tool that supports it (for example a Codex plugin install) can import the whole repository as one plugin named `magos`; the Codex marketplace install above goes through it.

| Question | Answer |
|---|---|
| Which commands do I get? | The seven command skills under `skills/`: `git-recon`, `git-analyze`, `git-recommend`, `git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, plus the entry skill `git-orchestrator`. Some tools add the plugin name as a prefix; Codex shows `magos:git-recon`. |
| What about the root `SKILL.md` (the shared rules)? | It is not a plugin skill, because the specification only looks inside `skills/`. That is why the plugin has the entry skill `git-orchestrator`: it carries the same description (so it triggers on its own) and reads the root `SKILL.md`; the seven commands read it and `references/` too. Verified in Claude Code, Codex, and Hermes: the plugin installs and enables, with the skill names in the table above; running each command end to end in each host has not been tested one by one. |
| Does Claude Code use it? | No. Claude Code reads `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`; install it from the marketplace as described above. |
| Which way for Hermes? | Either. `hermes plugins install UlyssesLeoLee/MAGOS --enable` reads the Hermes native manifest `plugin.yaml` (not this `plugin.json`), names the commands `/magos:git-recon` and so on, and passes the `[Skill directory: …]` path hint. Every plugin skill is listed in the system prompt's `<available_skills>` with the line from `INDEX_DESCRIPTIONS` in `__init__.py` (Hermes does not read a plugin skill's SKILL.md description, so without this line the model would see only the bare name): the orchestrator line names the situations that should trigger it, and the lines of the commands that write to a repository tell the model to leave them to the user. The four commands that modify the repository act only on an explicit `/magos:git-*`, `/git-*`, or `$git-*` invocation typed by the user. |

The repository root carries `.claude-plugin/` (the Claude Code `plugin.json` and the `marketplace.json` that Claude Code and Codex share) and the Hermes `plugin.yaml` and `__init__.py`, and deliberately no `.codex-plugin/` or `.cursor-plugin/`. Codex treats any of those folders as a plugin root and prefixes the skill names, so **a `git clone` straight into a Codex skills directory gives `$magos:git-recon` instead of `$git-recon`**. Install Codex and Hermes with the sync script: it copies only `SKILL.md`, `references/`, and `skills/`, never `.claude-plugin/`, so the names stay `$git-recon` and `/git-recon`. A root `plugin.json` alone does not trigger the prefix.

One known deviation: section 8 of the specification asks for files meant for a single tool to live in a reverse-domain folder (such as `com.example.client/`). `commands/` serves only Claude Code, and `plugin.yaml` and `__init__.py` only Hermes, but they sit at the top level. Plugin tools ignore them, so importing is unaffected; the install script and the tests address them at the top level.

When you change the version, update together `version` in `plugin.json`, `.claude-plugin/plugin.json` and `plugin.yaml`, `metadata.version` in `SKILL.md` and `skills/git-orchestrator/SKILL.md`, `GUARD_VERSION` in `scripts/magos_guard.py`, and line 3 of `references/commands.md` (the source contracts and the guard suite check that they agree), and add the version's section to `CHANGELOG.md`. The release gate:

```bash
python -X utf8 tests/codex/contracts/run_contract_cases.py --check
python -X utf8 tests/claude/scripts/run_claude_contracts.py --check
python -X utf8 tests/codex/contracts/test_agent_plugin.py
python -m pytest tests/codex/guard -q -p no:cacheprovider
```

The first two run every source-contract case (including `package/agent-plugin`, the plugin format) and write nothing; they exit 1 on any failure. The third plants many kinds of defects (a wrong manifest, mismatched versions, a stray link, and more) and confirms the checks catch each one. The fourth runs the lane guard suite. `.github/workflows/test.yml` runs all four on Windows and Linux with Python 3.9, 3.12 and 3.14, runs the coverage commands of `.quality/qguard.json` on Windows with Python 3.12 and fails when a source file or the whole project has 90 percent line coverage or less, and checks that a release tag `v<version>` names the package version.

---

## Command matrix

| Command | Claude Code | Hermes | Codex | Purpose |
|---|---|---|---|---|
| GitRecon | `/GitRecon` | `/git-recon` | `$git-recon` | Inspect branch/worktree state, produce a snapshot |
| GitAnalyze | `/GitAnalyze` | `/git-analyze` | `$git-analyze` | Analyze diffs, dependencies, and rewrite risk for a target |
| GitRecommend | `/GitRecommend` | `/git-recommend` | `$git-recommend` | Recommend the next Git/multi-agent move from real state |
| GitIntegrate | `/GitIntegrate` | `/git-integrate` | `$git-integrate` | Integrate a lane through safety gates |
| GitCleanup | `/GitCleanup` | `/git-cleanup` | `$git-cleanup` | Preview cleanups; `--apply` required to delete |
| GitConverge | `/GitConverge` | `/git-converge` | `$git-converge` | Merge every local branch into one and keep only `main` and it; preview by default, `--apply` to run |
| GitSweep | `/GitSweep` | `/git-sweep` | `$git-sweep` | `/GitConverge`, then delete merged remote branches; preview by default (no network), `--apply` to run |

```bash
python -X utf8 tests/codex/contracts/run_contract_cases.py
```

Runs the source contract checks and records each case's inputs and results in `tests/codex/contracts/cases/<group>/<case>/evidence/`; with `--check` it runs them without writing anything. No AI host is started. The `package/install-layout` case installs the Codex and Hermes packages into a temporary home and confirms every file the adapters reference exists, and that each skill is discovered exactly once under each host's discovery rules, also for a `git clone` straight into a skills directory. The `package/agent-plugin` case checks the Agent Plugins 1.0.0 package format (see Import as an Agent Plugin).

---

## Who it's for

- Multi-agent development in Claude Code / Codex / Cursor
- Parallel development across git worktrees
- AI-assisted task decomposition
- Managing a large number of agent branches
- Human-in-the-loop review
- Agent worktree visualization
- Automated merge queues
- Selective integration of AI-generated code

---

## Philosophy

Git is not only version control. In multi-agent software engineering it also becomes:

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

**Let agents develop boldly. Keep the main branch under control.**

---

## License

Apache-2.0
