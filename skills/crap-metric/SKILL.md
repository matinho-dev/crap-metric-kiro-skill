---
name: crap-metric
description: Analyzes codebase at runtime to calculate Cyclomatic Complexity, line coverage, and CRAP (Change Risk Anti-Patterns) scores across Java, Go, PHP, TypeScript/JavaScript, Vue, Python, and C/C++ files. Flags high-risk functions (> 30) and prescribes concrete refactoring and unit testing action plans. Supports LCOV generation via llvm-cov.
triggers:
  - crap
  - crap metric
  - crap score
  - complexity
  - cyclomatic complexity
  - change risk
  - test coverage
  - refactor risk
  - high risk functions
  - llvm-cov
  - lcov
  - recommend actions
  - how to reduce crap
allowed-tools: bash read_file
---

# CRAP Metric Skill & Action Recommendation Engine

This skill allows Kiro to analyze code complexity, map test coverage, compute CRAP scores, and prescribe concrete action plans (refactoring vs. test generation) across **Java**, **Go**, **PHP**, **TypeScript/JavaScript**, **Vue Single File Components (SFC)**, **Python**, and **C/C++**.

Supported file extensions: `.java`, `.go`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.php`, `.vue`, `.py`, `.c`, `.h`, `.cpp`, `.cc`, `.hpp`.

```
CRAP(m) = CC² × (1 − cov)³ + CC
```

- **CC**: Cyclomatic Complexity (base 1 + decision points)
- **cov**: Test coverage fraction (`0.0` to `1.0`)
- **CRAP Threshold**: Standard threshold is **30**. Functions with `CRAP > 30` are high-risk Change Risk Anti-Patterns.
- **Max Complexity (`CC ≤ 6`)**: Per Robert C. Martin's ("Uncle Bob") guidance on coding with AI agents — in which he has agents drive every function's complexity below six ([conversation with Kent Dodds](https://youtu.be/RxxxGkFIUJ0?t=859)) — functions, **especially agentic-generated ones**, should keep Cyclomatic Complexity **at or below 6**. Functions with `CC > 6` are flagged for decomposition (category `REDUCE_COMPLEXITY`) even when their CRAP score is within threshold. This is configurable via `--max-complexity` (default: `6`).
- **Treat 6 as a guideline, not an absolute rule**: decompose only when it improves readability — see the judgment note under Step 4, Path C.

---

## When to Use This Skill

Activate this skill when:
- The user requests a **CRAP score**, **complexity check**, or **risk analysis**.
- The user asks **"what actions should I take?"** or **"how do I lower my CRAP score?"**.
- The user asks to **save or export a report** to `{dd-mm-yyyy-hh-mm-ss}-report.md`.
- The user invokes `/crap-metric [file or directory]`.
- The user asks to evaluate code changes before committing or creating a PR/MR (`git diff`).
- The user asks to generate LCOV coverage data using `llvm-cov` from LLVM instrumented binaries.

---

## Workflow Instructions for Kiro

Follow this execution workflow when invoked. **Every analyzer run must persist a timestamped report to the project root via `--save-report .`** (see Step 3) so results are captured after each run.

### Step 1: Determine the Target Scope
Inspect the user request to determine the scope:
1. **Specific file or directory:** Pass `--path <path>`.
2. **Recent changes / Git diff:** Pass `--diff` (and optionally `--base main` or `--base HEAD~1`).
3. **Entire project:** Run from repository root (`--path .`).

### Step 2: Check for Existing Coverage or Generate with `llvm-cov`
- **Existing Reports:** the analyzer auto-discovers common coverage artifacts, and `--lcov <path>` accepts any of them (dispatched by extension):
  - **LCOV** — `coverage/lcov.info`, `coverage.lcov` (TS/JS/Vue via Jest/Vitest, PHP/Python when exported to LCOV, LLVM languages).
  - **XML** — JaCoCo (`target/site/jacoco/jacoco.xml`, `build/reports/jacoco/test/jacocoTestReport.xml`), Cobertura (`coverage.xml`, Python), and Clover (`build/logs/clover.xml`, PHP). Schema is auto-detected.
  - **Go cover** — `coverage.out`, `c.out`, `cover.out`.
- **Generating via `llvm-cov`:** If working with an instrumented binary, run:
  ```bash
  .kiro/skills/crap-metric/scripts/generate_llvm_lcov.sh --binary ./path/to/binary --output coverage/lcov.info
  ```
  Or supply `--llvm-binary ./path/to/binary` directly to `analyze.sh`.
- If no coverage exists, analysis proceeds with worst-case assumption (0%), identifying methods that lack automated protection.

### Step 3: Run the Analyzer Script

**Always pass `--save-report .` so each run is persisted.** Timestamped reports are **archived under a `reports/` folder** (`reports/{dd-mm-yyyy-hh-mm-ss}-report.md`) so history accumulates in one place, and a **`latest.md` symlink at the project root** always points at the most recent report.

```bash
# Standard analysis with action plan — archives reports/{timestamp}-report.md + updates ./latest.md
.kiro/skills/crap-metric/scripts/analyze.sh --path src/ --save-report .

# Git diff mode (still archives a report + updates latest.md)
.kiro/skills/crap-metric/scripts/analyze.sh --diff --save-report .

# With explicit coverage file
.kiro/skills/crap-metric/scripts/analyze.sh --path src/ --lcov coverage/lcov.info --save-report .
```

Notes:
- `--save-report .` (or a directory) archives the timestamped report under `<dir>/reports/` and refreshes `<dir>/latest.md` to point at it. Bare `--save-report` (no value) behaves the same for the current directory.
- `--save-report <file>.md` writes to that **exact path** instead — no `reports/` archiving and no `latest.md` symlink (use this when you want a single fixed output file).
- When `--format` is `json` or `table`, a `.md` destination still receives the full markdown report, so `--save-report .` always yields a readable report file.
- Include `--lcov <path>` (or `--llvm-binary`) whenever coverage data is available so the saved report reflects real CRAP scores rather than the 0%-coverage worst case.

### Step 4: Interpret Results and Prescribe Actions
The analyzer output categorizes every flagged function into one of three action paths:

#### Path A: 🔴 MANDATORY REFACTOR (`CC > 30`)
- **Cause:** Cyclomatic Complexity exceeds 30. Even with 100% test coverage, `CRAP = CC > 30`. Testing alone **cannot** resolve this.
- **Action for Kiro:** Offer to refactor the function for the user:
  1. Extract nested logic into private helper methods.
  2. Replace nested conditional blocks with early-return guard clauses.
  3. Replace complex switch/case structures with lookup dictionaries or polymorphism.
  4. **Target:** reduce CC to **≤ 6** (Uncle Bob's recommended ceiling for agent-generated code).

#### Path B: 🟠 ADD TARGETED UNIT TESTS (`CC ≤ 30` and `CRAP > 30`)
- **Cause:** Manageable complexity, but insufficient test coverage.
- **Formula for Target Coverage:**

  ```
  cov_target = 1 − ∛((30 − CC) / CC²)
  ```
- **Action for Kiro:** Offer to write the unit tests for the user:
  1. Inspect the reported **Uncovered Lines** (e.g. `L14-16, L22`).
  2. Generate test assertions covering those specific branches and edge conditions.

#### Path C: 🟡 REDUCE COMPLEXITY (`CRAP ≤ 30` but `CC > 6`)
- **Cause:** CRAP is within threshold, but Cyclomatic Complexity exceeds the recommended maximum of **6** (Uncle Bob's ceiling for agent-generated code). Applies especially to agentic-generated code, which should be born simple.
- **Action for Kiro:** Offer to decompose the function (same techniques as Path A) to bring `CC ≤ 6`. No new tests are strictly required, but keep existing coverage intact.
- **Note:** The complexity ceiling is configurable with `--max-complexity N`; the default of `6` reflects Uncle Bob's guidance.

> [!IMPORTANT]
> **CC ≤ 6 is a guideline, not a hard rule — exercise judgment.** The goal of decomposition is *clearer, more maintainable* code, never a lower number for its own sake. Before extracting helpers to hit the target:
> - **Readability first.** If forcing `CC ≤ 6` would fragment cohesive logic into many tiny, hard-to-follow helpers, or scatter tightly-coupled steps across the file, **stop and leave it slightly above 6**. A cohesive CC-7 or CC-8 function is better than five artificial one-line helpers.
> - **Preserve behavior and signatures.** Extractions must be behavior-preserving; keep public signatures stable and verify with tests after each change.
> - **Extract along natural seams.** Pull out genuinely independent concerns (a parse step, a distinct validation, an inner loop), not arbitrary line ranges chosen only to reduce the count.
> - **Name helpers meaningfully.** Each extracted function should have a clear, single responsibility that reads as a step in the parent. If you can't name it well, the seam is probably wrong.
> - **Don't inflate the surface.** Prefer private/module-local helpers over widening the public API just to satisfy the metric.
> - **When you deliberately exceed the ceiling, say so.** Briefly explain to the user why the function is clearer left above the threshold rather than silently ignoring the flag.
>
> In short: treat a `REDUCE_COMPLEXITY` flag as a prompt to *review* the function's design, and reduce complexity only where doing so genuinely improves clarity.

---

## Reference Documentation

- [action-recommendations.md](references/action-recommendations.md): Decision matrix, mathematical target coverage derivation, and refactoring patterns.
- [complexity-rules.md](references/complexity-rules.md): McCabe decision points per language.
- [crap-formula.md](references/crap-formula.md): Formula derivation and threshold tables.
- [coverage-mapping.md](references/coverage-mapping.md): LCOV parsing and `llvm-cov` export details.

---

## License

© 2026 Hugo Matinho. Licensed under **CC BY-NC 4.0** (Creative Commons
Attribution-NonCommercial 4.0 International). Free to use, share, and extend for
**non-commercial** purposes with attribution; selling or commercial use is not
permitted.
