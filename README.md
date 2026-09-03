# CRAP Metric — Complexity, Coverage & Change-Risk Analyzer

A Kiro skill that analyzes source code to compute **Cyclomatic Complexity (CC)**,
map **test coverage**, calculate **CRAP (Change Risk Anti-Patterns)** scores, and
emit **prescriptive, agent-executable action plans** for reducing risk.

It works across **Java, Go, TypeScript/JavaScript, PHP, Vue SFCs, Python, and C/C++**,
requires no project build, and can generate coverage data from LLVM-instrumented
binaries via `llvm-cov`.

---

## What is CRAP?

CRAP quantifies how risky a function is to change, combining complexity with test coverage:

```
CRAP(m) = CC² × (1 − cov)³ + CC
```

- **CC** — Cyclomatic Complexity (base 1 + decision points)
- **cov** — test coverage fraction (0.0–1.0)

The intuition: complex code is risky, but thorough tests mitigate that risk. A
simple function is always safe; a complex, untested one is a change hazard.

### Thresholds

| Gate | Default | Meaning |
|---|---|---|
| **CRAP threshold** | `30` | Functions with `CRAP > 30` are high-risk anti-patterns. |
| **Max complexity** | `6` | Per Robert C. Martin's *Clean Code* guidance, functions (especially agentic-generated ones) should keep `CC ≤ 6`. `CC > 6` is flagged for decomposition even when CRAP passes. Configurable via `--max-complexity`; **treated as a guideline — decompose only where it improves readability.** |

---

## What it produces

For every function, the analyzer classifies it into one of these action paths:

- 🔴 **MANDATORY REFACTOR** (`CC > 30`) — even 100% coverage can't clear CRAP; the code must be decomposed.
- 🟠 **ADD UNIT TESTS** (`CC ≤ 30`, `CRAP > 30`) — manageable complexity but insufficient coverage; the report gives the exact target coverage % and uncovered lines.
- 🟡 **REDUCE COMPLEXITY** (`CRAP ≤ 30`, `CC > 6`) — within CRAP threshold but above the Clean Code complexity ceiling.
- ✅ **HEALTHY** — clean, low-risk.

Each flagged function comes with a ready-to-execute **AI Agent Directive** — a
self-contained prompt an agent can consume to write the tests or perform the
refactor, then validate the fix.

---

## Usage

The entry point is `scripts/analyze.sh` (a thin wrapper over `analyze.py`; requires `python3`).

```bash
# Analyze a directory, save a timestamped report to the project root
.kiro/skills/crap-metric/scripts/analyze.sh --path src/ --save-report .

# Analyze a single file with an existing coverage file
.kiro/skills/crap-metric/scripts/analyze.sh --path src/app.py --lcov coverage/lcov.info --save-report .

# Only analyze git-modified files/lines (great for pre-commit / PR gates)
.kiro/skills/crap-metric/scripts/analyze.sh --diff --base main --save-report .

# Fail the build if anything exceeds threshold (CI gate)
.kiro/skills/crap-metric/scripts/analyze.sh --path src/ --strict
```

### Key options

| Flag | Description |
|---|---|
| `--path, -p` | File or directory to analyze (default: `.`). |
| `--diff` | Analyze only git-modified files and lines. |
| `--base` | Base commit/branch for the diff (e.g. `main`, `HEAD~1`). |
| `--lcov` | Path to an existing LCOV coverage file. |
| `--llvm-binary` | Instrumented binary — generates LCOV via `llvm-cov` automatically. |
| `--llvm-profdata` | Optional `.profdata` / `.profraw` for `llvm-cov`. |
| `--threshold` | CRAP threshold (default: `30.0`). |
| `--max-complexity` | Max CC before flagging for decomposition (default: `6`). |
| `--format` | `markdown` (default), `json`, or `table`. |
| `--save-report [PATH]` | Persist the report. With `.`/a directory, it archives to `<dir>/reports/{dd-mm-yyyy-hh-mm-ss}-report.md` and refreshes a `latest.md` symlink in `<dir>`. `<file>.md` writes to that exact path (no archive/symlink); bare = current directory. |
| `--strict` | Exit code `1` if any function exceeds threshold. |

> **Reporting convention:** always pass `--save-report .` so each run archives a
> timestamped snapshot under `reports/` and refreshes the root `latest.md` symlink
> (see `SKILL.md`).

---

## Coverage

Coverage is optional — without it, analysis proceeds with a worst-case 0%
assumption, surfacing functions that lack automated protection.

Supported inputs (auto-discovered or via `--lcov`): **LCOV** (`lcov.info`),
**Go cover** profiles (`coverage.out`), and other standard reports.

### Generating LCOV from native binaries

For C/C++/Rust/Swift/Zig instrumented with LLVM coverage, use the helper:

```bash
.kiro/skills/crap-metric/scripts/generate_llvm_lcov.sh \
  --binary ./path/to/instrumented-binary \
  --output coverage/lcov.info
```

It resolves `llvm-cov`/`llvm-profdata` (PATH → `xcrun` on macOS → common
Homebrew/Linux locations), discovers/merges `.profraw`/`.profdata` files, and
exports LCOV.

---

## Project layout

```
README.md                         # This file (project root)
latest.md                         # Symlink → newest report in reports/
reports/                          # Archived {dd-mm-yyyy-hh-mm-ss}-report.md snapshots

.kiro/skills/crap-metric/
├── SKILL.md                      # Agent-facing workflow & activation guidance
├── assets/
│   └── report-template.md        # Report layout template
├── references/
│   ├── action-recommendations.md # Decision matrix & refactoring patterns
│   ├── complexity-rules.md       # McCabe decision points per language
│   ├── crap-formula.md           # Formula derivation & threshold tables
│   └── coverage-mapping.md       # LCOV parsing & llvm-cov export details
└── scripts/
    ├── analyze.sh / analyze.py           # Main analyzer & recommendation engine
    ├── generate_llvm_lcov.sh / .py       # LLVM → LCOV coverage generator
    ├── self_test.py                      # End-to-end pipeline self-test
    ├── test_main.py                      # Unit tests (analyze.py)
    ├── test_generate_llvm_lcov.py        # Unit tests (generate_llvm_lcov.py)
    ├── pyrightconfig.json                # basedpyright config (strict + CC policy) — local, gitignored
    └── coverage/                         # Generated LCOV output
```

---

## Development

### Setup

The analyzer itself only needs **Python 3** — no third-party runtime dependencies.
The quality tooling is dev-only and best installed in a virtualenv:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install basedpyright ruff        # type checker + linter
```

`pyrightconfig.json` (in `scripts/`) pins the type-checking bar — `typeCheckingMode: "all"`,
`pythonVersion: "3.12"`, and an `executionEnvironments`/`extraPaths` entry so the
sibling `analyze` / `generate_llvm_lcov` modules resolve. **It is developer-local
and gitignored**, so recreate `scripts/pyrightconfig.json` after a fresh clone if
you want the same strict IDE/CLI behavior:

```json
{
  "typeCheckingMode": "all",
  "pythonVersion": "3.12",
  "extraPaths": ["."],
  "executionEnvironments": [{ "root": ".", "extraPaths": ["."] }]
}
```

The scripts are held to a strict quality bar:

- **Type checking:** `basedpyright` in `all` mode — zero errors/warnings.
- **Linting:** `ruff` — clean.
- **Tests:** `python3 scripts/test_main.py` runs the full suite and regenerates
  the combined coverage LCOV used to validate the analyzer against itself.
- **Complexity:** every function is kept at `CC ≤ 6` (the standard this skill enforces).

```bash
# Run the unit test suite (also regenerates scripts/coverage/main_coverage.lcov)
python3 .kiro/skills/crap-metric/scripts/test_main.py

# Dogfood: analyze the skill's own scripts with real coverage
.kiro/skills/crap-metric/scripts/analyze.sh \
  --path .kiro/skills/crap-metric/scripts \
  --lcov .kiro/skills/crap-metric/scripts/coverage/main_coverage.lcov \
  --save-report .
```

---

## Supported languages

Java · Go · TypeScript (`.ts`/`.tsx`) · JavaScript (`.js`/`.jsx`/`.mjs`/`.cjs`) ·
PHP · Vue SFC · Python · C (`.c`/`.h`) · C++ (`.cpp`/`.cc`/`.hpp`)

---

## License

Copyright © 2026 Hugo Matinho.

Licensed under the **Creative Commons Attribution-NonCommercial 4.0 International
License (CC BY-NC 4.0)**. You are free to use, share, and adapt this skill —
including extending it — **for non-commercial purposes**, with attribution. You
**may not sell it or use it primarily for commercial advantage or monetary
compensation**. See the [`LICENSE`](LICENSE) file for full terms.
