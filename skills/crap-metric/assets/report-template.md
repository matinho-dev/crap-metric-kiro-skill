# CRAP Score Analysis Report

**Scope:** {SCOPE}  
**Threshold:** {THRESHOLD}  
**Analyzed Functions:** {TOTAL_FUNCTIONS}  
**High-Risk Anti-Patterns (> {THRESHOLD}):** {OVER_THRESHOLD_COUNT}

---

## High-Risk Functions (CRAP > {THRESHOLD})

| File | Function | Lines | CC | Coverage | Target Cov | CRAP Score | Status |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| `{FILE}` | `{FUNCTION}` | `{START}-{END}` | `{CC}` | `{COVERAGE}%` | `{TARGET_COV}%` | **`{CRAP}`** | ⚠️ HIGH RISK |

---

## Within Threshold Functions

| File | Function | Lines | CC | Coverage | CRAP Score | Status |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| `{FILE}` | `{FUNCTION}` | `{START}-{END}` | `{CC}` | `{COVERAGE}%` | `{CRAP}` | ✅ OK |

---

## 🎯 Prescriptive Action Plan & AI Agent Directives

> [!TIP]
> **For AI Agents:** Each action item includes an executable directive block that can be directly executed to refactor code or generate tests.

### 1. `{FUNCTION}` in `{FILE}:{START}-{END}` — 🔴 MANDATORY REFACTOR
> **Diagnosis:** Complexity is `{CC}` (> {THRESHOLD}). Even 100% test coverage yields CRAP `{CC}`, which cannot clear the threshold. Must be refactored.

- **Complexity:** `{CC}` | **Current Coverage:** `{COVERAGE}%` | **CRAP:** `{CRAP}`
- **Recommended Actions:**
  * Decompose `{FUNCTION}`: Extract discrete logic into smaller helper functions.
  * Replace nested condition ladders with early return guard clauses.
  * Target: Reduce Cyclomatic Complexity down to <= 15.

#### 🤖 AI Agent Directive (Prompt to Execute Fix)
```text
TASK: Refactor function `{FUNCTION}` in `{FILE}` (lines {START}-{END}).
CONTEXT: Cyclomatic Complexity is {CC} (exceeds threshold of {THRESHOLD}). Testing alone cannot reduce CRAP <= {THRESHOLD}. Code decomposition is required.
DIRECTIVES:
1. Read lines {START} to {END} of `{FILE}`.
2. Decompose `{FUNCTION}` by extracting isolated logic, inner loops, or distinct validation steps into helper functions.
3. Invert nested conditionals to apply early return guard clauses.
4. Replace multi-branch switch/case or cascading if/else with lookup dictionaries or polymorphism.
5. Maintain exact function signature, return types, and external behavior to preserve compatibility.
6. Validate refactoring: Run `.kiro/skills/crap-metric/scripts/analyze.sh --path {FILE}` to confirm CC <= 15 and CRAP <= {THRESHOLD}.
```

---

### 2. `{FUNCTION}` in `{FILE}:{START}-{END}` — 🟠 ADD UNIT TESTS
> **Diagnosis:** Function has manageable complexity (`{CC}`), but current coverage (`{COVERAGE}%`) is below the `{TARGET_COV}%` needed to clear threshold.

- **Complexity:** `{CC}` | **Current Coverage:** `{COVERAGE}%` | **CRAP:** `{CRAP}`
- **Target Coverage:** **`{TARGET_COV}%`** *(Minimum needed to bring CRAP <= {THRESHOLD})*
- **Uncovered Lines:** `{UNCOVERED_LINES}`
- **Recommended Actions:**
  * Coverage Goal: Increase unit test coverage from `{COVERAGE}%` to at least `{TARGET_COV}%`.
  * Write unit tests targeting branches at lines `{UNCOVERED_LINES}`.

#### 🤖 AI Agent Directive (Prompt to Execute Fix)
```text
TASK: Generate unit tests for `{FUNCTION}` in `{FILE}` (lines {START}-{END}) using standard test framework.
CONTEXT: Function has Cyclomatic Complexity {CC} with only {COVERAGE}% test coverage. Minimum coverage needed to bring CRAP <= {THRESHOLD} is {TARGET_COV}%.
DIRECTIVES:
1. Inspect `{FILE}:{START}-{END}` to understand inputs, outputs, and branches.
- Untested lines: `{UNCOVERED_LINES}`
2. Create or extend test cases exercising:
   a. Main successful execution paths.
   b. Edge cases and boundary conditions corresponding to untested lines.
   c. Error states and exception handling branches.
3. Run the test suite and export coverage to LCOV.
4. Validate fix: Run `.kiro/skills/crap-metric/scripts/analyze.sh --path {FILE}` to confirm CRAP <= {THRESHOLD}.
```
