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
- **Honesty:** no car is in the loop; simulation passing ≠ works on a vehicle. Label
  hardware-only behavior `NEEDS ON-CAR CHECK`. Fixtures are hand-derived from the SAE/ISO
  specs, never from the code under test; never fix a contract test by editing the assertion.
- **Never build:** emissions-defeat coding, anti-theft/immobilizer bypass, or reflashing that
  cracks SecurityAccess / ships OEM calibrations. As-Built writes require backup-before-write.
