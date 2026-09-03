# CRAP Metric Formula & Guidelines

## The CRAP Formula

The **CRAP (Change Risk Anti-Patterns)** metric was designed by Alberto Savoia and Bob Evans in 2007. It combines **Cyclomatic Complexity (CC)** and **Test Coverage (cov)** to measure the risk and difficulty of changing code without breaking it.

$$\text{CRAP}(m) = \text{CC}^2 \times (1 - \text{cov})^3 + \text{CC}$$

Where:
- $\text{CC}$: Cyclomatic complexity of function/method $m$ ($\ge 1$).
- $\text{cov}$: Test coverage of $m$ as a fraction between $0.0$ (0%) and $1.0$ (100%).

---

## Metric Behavior & Interpretation

The cubic penalty term $(1 - \text{cov})^3$ heavily penalizes high complexity when test coverage is absent or low:

| Cyclomatic Complexity (CC) | Test Coverage | CRAP Score | Assessment |
|:---|:---|:---|:---|
| **1** (Simple linear code) | 0% | **2.0** | Trivial, negligible risk |
| **5** (Standard helper) | 0% | **30.0** | Acceptable ceiling for untested code |
| **5** (Standard helper) | 50% | **8.1** | Low risk |
| **10** (Moderate logic) | 0% | **110.0** | **CRITICAL RISK** (Dangerous without tests) |
| **10** (Moderate logic) | 42% | **30.0** | Reaches threshold at 42% coverage |
| **10** (Moderate logic) | 80% | **10.8** | Low risk (well covered) |
| **20** (Complex method) | 0% | **420.0** | **EXTREME RISK** |
| **20** (Complex method) | 75% | **26.3** | Acceptable, requires $\ge 75\%$ coverage |
| **30** (Very high complexity)| 100% | **30.0** | **Threshold maximum** |
| **> 30** (Monolithic method)| 100% | **> 30.0** | **Unsalvageable by tests alone; must be refactored** |

---

## Thresholds & Action Plan

| CRAP Range | Risk Level | Recommended Action |
|:---|:---|:---|
| $\le 30$ | **Low / Acceptable** | Code is reasonably simple or sufficiently covered by tests. Maintain coverage. |
| $31 - 75$ | **Medium Risk** | Function has branching logic and insufficient tests. Write unit tests targeting untested branches. |
| $> 75$ | **High / Critical Risk** | High change risk anti-pattern. Refactor first (extract sub-methods, eliminate deep nesting), then add tests. |

> [!NOTE]
> When $\text{CC} > 30$, no amount of test coverage can bring CRAP under the standard threshold of 30. Such functions **must** be broken down into smaller components.
