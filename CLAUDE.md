# CLAUDE.md — standing instructions for FordScope

FordScope is a hardware-abstracted **Ford OBD-II diagnostic + As-Built coding** tool
(Python, macOS), built **simulator-first** and **test-driven**.

**Before doing anything in this repo, follow the `fordscope-build` skill**
(`.claude/skills/fordscope-build/SKILL.md`). It defines the iteration loop, the canonical
green check, the layered architecture, and the hard boundaries. Quick summary:

- **Verify by running:** `./run_tests.sh` → `Ran N tests … OK` is the only green check. Never
  claim behavior without it.
- **Loop:** read `PROGRESS.md` → next unchecked box → test-first → run suite green → update
  `PROGRESS.md` → commit. One green suite + one commit per iteration.
- **Committing on the sandbox mount — `unlink` is BLOCKED (host-side FUSE limit):** git
  cannot delete its own `.git/index.lock`, so a stale lock makes `git add`/`git commit`
  fail with `Unable to create '.git/index.lock': File exists` (exit 128). **Never `rm` a
  `.git` lock here — it's blocked.** Commit via **`tools/safe-commit.sh -F <msgfile>`**
  (add `--push` to push), which clears stale locks by RENAME first. By hand, clear with
  `mv .git/index.lock .git/.orphan-locks/…` (rename), never `rm`. This is a WORKAROUND;
  the real fix is host-side (a filesystem where unlink works). See the script header.
- **Honesty:** no car is in the loop; simulation passing ≠ works on a vehicle. Label
  hardware-only behavior `NEEDS ON-CAR CHECK`. Fixtures are hand-derived from the SAE/ISO
  specs, never from the code under test; never fix a contract test by editing the assertion.
- **Never build:** emissions-defeat coding, anti-theft/immobilizer bypass, or reflashing that
  cracks SecurityAccess / ships OEM calibrations. As-Built writes require backup-before-write.

## Standing owner directives — applied cross-project from the owner's Opus/Fable sessions (2026-07-04)
The owner's general working rules (distilled from the Salehman `opus-operating` skill + the
`owner-decision-style` / `fordscope-work-expectations` memories). The Salehman-domain specifics
don't apply here, but the DISCIPLINE does — run FordScope to the same bar.

**Decisions & interaction:**
- **Do NOT use the `AskUserQuestion` tool with this owner.** Default to picking the best option and
  proceeding ("do all"). If you genuinely need a steer, ask in ONE short line of plain prose — even
  inside a Q&A skill (e.g. `/brainstorming`), keep it natural conversation, not the formal picker.
- For a fork, take the **conservative, reversible, correctness-by-default** option, state it plainly
  as a decision you're taking (interruptible, not blocking), and proceed. Reserve a real BLOCK+STOP
  only for **irreversible / safety-critical** forks with no conservative default — here that = the
  never-build list, or writing to a real car unverified. **"Never stop"** the autonomous loop.

**Proof discipline (each blocks a real past failure the owner hit):**
- **Done = the run OUTPUT is pasted and the POSITIVE path fired** — never "it passes." A test can go
  green while asserting nothing; assert the concrete positive behavior, then show `Ran N … OK`.
- **The diff is the fact; reports (including your own) are claims** — trust `git diff` / pasted output
  over narration.
- **Expected test values come from the SAE/ISO spec or a standalone hand-derivation, NEVER from the
  code under test; boundary pins must genuinely straddle; never edit an assertion to match the code.**
- **PROGRESS/log entries describe the FINAL committed tree, re-verified by reading it** before writing.
- Every claim carries its basis; unknowns stay labeled (`NEEDS ON-CAR CHECK`, "no definition on file");
  a nil/None = unknown, never a fabricated value.

**Thoroughness & economy (ultracode bar):**
- Exhaustive sweeps + adversarial self-review + verify by MEASUREMENT (exit codes, test counts,
  probes), never by claim. Use multi-agent **Workflows** for substantive/parallelizable work (audits,
  reviews, research) — orchestrator Opus 4.8, fan-out subagents **Sonnet 5 / max** (`workflow-model-config`
  memory). Serialize big fan-outs; don't overlap them (overlap tripped a rate-limit on 2026-07-04).
- Token discipline: don't Read huge/generated files; verdict-first log reading; concise entries.
- **Research memory:** every research run appends a dated verdict to a durable `docs/RESEARCH_*` file
  and NEVER re-researches an indexed item — extend it. Keep `PROGRESS.md` / `docs/ROADMAP.md` /
  `docs/DESIGN.md` true when structure changes.
