# Action Recommendation Engine & AI Agent Directives

This guide defines how to determine concrete, actionable steps based on Cyclomatic Complexity ($CC$), Test Coverage ($cov$), and the resulting CRAP score, and how to format machine-actionable instructions for AI agents.

---

## 1. The Core Decision Matrix

$$\text{CRAP}(m) = \text{CC}^2 \times (1 - \text{cov})^3 + \text{CC}$$

| Condition | Category | Severity | Primary Remedy | Target Goal |
|:---|:---|:---:|:---|:---|
| **$CC > 30$** | `MANDATORY_REFACTOR` | 🔴 **Critical** | **Code Decomposition** | Reduce $CC \le 15$ |
| **$CC \le 30$ and $\text{CRAP} > 30$** | `ADD_UNIT_TESTS` | 🟠 **High** | **Targeted Unit Tests** | Reach $cov \ge cov_{\text{target}}$ |
| **$CC \ge 15$ and $\text{CRAP} \le 30$** | `PREVENTIVE_MAINTENANCE` | 🟡 **Medium** | **Complexity Safeguards** | Avoid adding more branches |
| **$CC < 15$ and $\text{CRAP} \le 30$** | `HEALTHY` | 🟢 **Low** | **Maintain Existing Tests** | Keep current test suites |

---

## 2. Mathematical Target Coverage Formula

When $CC \le \text{threshold}$, test coverage alone can reduce the function's CRAP score to an acceptable level. The minimum required coverage is calculated by:

$$\text{CC}^2 \times (1 - cov)^3 + \text{CC} \le \text{Threshold}$$

$$(1 - cov)^3 \le \frac{\text{Threshold} - \text{CC}}{\text{CC}^2}$$

$$cov_{\text{target}} \ge 1 - \sqrt[3]{\frac{\text{Threshold} - \text{CC}}{\text{CC}^2}}$$

### Quick Lookup Table ($\text{Threshold} = 30$)

| Complexity ($CC$) | Untested CRAP ($0\%$ cov) | Minimum Required Coverage | Resulting CRAP |
|:---:|:---:|:---:|:---:|
| **6** | $42.0$ | **$29.3\%$** | $30.0$ |
| **8** | $72.0$ | **$30.0\%$** | $30.0$ |
| **10** | $110.0$ | **$41.5\%$** | $30.0$ |
| **12** | $156.0$ | **$50.0\%$** | $30.0$ |
| **15** | $240.0$ | **$59.5\%$** | $30.0$ |
| **18** | $342.0$ | **$66.9\%$** | $30.0$ |
| **20** | $420.0$ | **$70.8\%$** | $30.0$ |
| **25** | $650.0$ | **$80.0\%$** | $30.0$ |
| **28** | $812.0$ | **$86.0\%$** | $30.0$ |
| **30** | $930.0$ | **$100.0\%$** | $30.0$ |
| **> 30** | $> 930.0$ | **Impossible (Tests cannot salvage)** | $> 30.0$ |

---

## 3. Prescriptive Refactoring Strategies

### Strategy A: Method Decomposition (When $CC > 30$)
Because 100% test coverage yields $\text{CRAP} = 0 + CC = CC$, any method with $CC > 30$ **cannot pass by testing alone**.

1. **Extract Method / Helper Functions:**
   - Identify discrete responsibilities inside the method (e.g. data validation, payload formatting, error handling).
   - Extract them into pure private functions.
2. **Replace Nested Conditionals with Guard Clauses:**
   - Invert `if` checks and return early (`return`, `continue`, `break`, `throw`).
   - Eliminate deep indentation ladders.
3. **Replace Switch / Multi-branch If-Else:**
   - In TypeScript/JavaScript & PHP: Replace with map/object lookups or handler dictionaries.
   - In Java & Go: Replace with Strategy Pattern, Polymorphism, or command dispatchers.
4. **Pipeline / Functional Combinators:**
   - Convert manual `for` / `while` iteration with nested condition filters into `map`, `filter`, `reduce` (JS/TS), Streams (Java), or collection utilities.

### Strategy B: Targeted Branch Testing (When $CC \le 30$ & $\text{CRAP} > 30$)
When a method has manageable complexity but is flagged as high-risk, testing the uncovered lines is the fastest route to safety.

1. **Inspect Uncovered Line Numbers:**
   - Check the `uncovered_lines` list reported by the skill.
2. **Test Boundary & Edge Conditions:**
   - If lines in an `else` branch or `catch` block are uncovered, write test fixtures that trigger error scenarios or invalid inputs.
3. **Compound Boolean Assertions:**
   - If conditions use `&&` or `||`, write tests exercising both the true-short-circuit and false-short-circuit branches.
4. **Complementary Quick-Win:**
   - Reducing $CC$ by even 2 points (e.g. simplifying compound conditionals) significantly reduces the required test coverage percentage.

---

## 4. AI Agent Directive Generation

For every analyzed function exceeding the threshold, the skill generates a dedicated **AI Agent Directive**. This enables automated agents (Kiro, Antigravity, CI bots) to consume the report and self-heal the codebase without requiring human translation.

### Refactor Directive Structure:
```text
TASK: Refactor function `{FUNCTION}` in `{FILE}` (lines {START}-{END}).
CONTEXT: Cyclomatic Complexity is {CC} (exceeds threshold of {THRESHOLD}). Testing alone cannot reduce CRAP <= {THRESHOLD}.
DIRECTIVES:
1. Read lines {START} to {END} of `{FILE}`.
2. Decompose `{FUNCTION}` by extracting isolated logic into helper functions.
3. Invert nested conditionals to apply early return guard clauses.
4. Replace multi-branch conditionals with dispatch tables or polymorphism.
5. Maintain exact function signature, return types, and external behavior.
6. Validate refactoring: Run `.kiro/skills/crap-metric/scripts/analyze.sh --path {FILE}` to confirm CC <= 15 and CRAP <= {THRESHOLD}.
```

### Test Generation Directive Structure:
```text
TASK: Generate unit tests for `{FUNCTION}` in `{FILE}` (lines {START}-{END}) using {FRAMEWORK}.
CONTEXT: Function has Cyclomatic Complexity {CC} with only {COVERAGE}% test coverage. Minimum coverage needed is {TARGET_COV}%.
DIRECTIVES:
1. Inspect `{FILE}:{START}-{END}`. Untested lines: `{UNCOVERED_LINES}`.
2. Create test cases exercising: normal paths, edge conditions on untested lines, and error states.
3. Run test runner and export coverage to LCOV.
4. Validate fix: Run `.kiro/skills/crap-metric/scripts/analyze.sh --path {FILE} --lcov <coverage-file>` to confirm CRAP <= {THRESHOLD}.
```
