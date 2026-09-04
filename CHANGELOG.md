# Changelog

All notable changes to the CRAP Metric skill are documented in this file.

## [Unreleased]

## [0.2.0] - 2026-09-04

### Added

- **Multi-format XML coverage parsing** in the analyzer's `CoverageDatabase`, covering the
  three dominant line-coverage schemas, auto-detected by structure:
  - **JaCoCo** (Java) — reads `<sourcefile>/<line nr ci>`; a line counts as covered when
    covered-instructions (`ci`) `> 0`.
  - **Cobertura** (Python and others) — reads `<class filename>/<line number hits>`.
  - **Clover** (PHP) — reads `<file>/<line num count>`.
- Extension-based coverage dispatch (`load_auto`): `--lcov <path>` now accepts `.xml`
  (JaCoCo/Cobertura/Clover), `.out` (Go cover), and LCOV files interchangeably.
- Auto-discovery now scans a dedicated **XML bucket** for standard report locations:
  `target/site/jacoco/jacoco.xml`, `build/reports/jacoco/test/jacocoTestReport.xml`,
  `build/reports/jacoco/test/jacoco.xml`, `coverage.xml`, `coverage/cobertura.xml`,
  `build/logs/clover.xml`, and `clover.xml`.
- Auto-discovery now **loads and merges every matching report** in each bucket
  (LCOV, XML, Go) instead of stopping at the first match, so polyglot repositories with
  multiple coverage files are fully accounted for.
- Unit tests for all three XML schemas, extension dispatch, multi-bucket discovery,
  cross-report merging, LCOV max-merge semantics, and negative cases (unrecognized schema,
  missing file). Added 12 tests, bringing the suite from 78 to 90.

### Fixed

- **Java coverage was silently broken.** JaCoCo XML was discovered but routed to the LCOV
  text parser, which recognized none of its records — every Java function silently fell back
  to the worst-case 0% coverage assumption with no error. JaCoCo XML is now parsed correctly.
- **PHP (Clover) and Python (Cobertura) coverage** were documented but had no parser; both
  now work end-to-end.
- Auto-discovery paths now match the documentation. Previously the code only checked a subset
  and omitted the Maven JaCoCo path, Cobertura, and Clover locations entirely.
- **LCOV records now max-merge** line and function hit counts instead of overwriting, so
  loading multiple reports can never lower an already-observed hit count. This aligns LCOV
  with the XML and Go parsers, all of which merge by taking the maximum hit count per
  file+line.

### Changed

- Coverage merge semantics are now uniform across every parser: records are keyed by
  normalized file path and combined by maximum hit count, giving correct union coverage when
  several reports are loaded.
- Documentation updated to reflect real, verified support:
  - `references/coverage-mapping.md` — discovery table rewritten with a per-language parser
    column, accurate paths, and an XML schema-detection note.
  - `SKILL.md` — Step 2 now lists the LCOV / XML / Go inputs and auto-detection.
  - `README.md` — the Coverage section's "Supported inputs" now lists LCOV, JaCoCo/Cobertura/
    Clover XML, and Go cover profiles.

### Notes

- Coverage remains optional; without a report, analysis proceeds with the worst-case 0%
  assumption. PHP and Python still require exporting to a supported format (Clover, Cobertura,
  or LCOV) via the test runner — but those formats are now parsed and auto-discovered.

[Unreleased]: https://github.com/matinho-dev/crap-metric-kiro-skill/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/matinho-dev/crap-metric-kiro-skill/releases/tag/v0.2.0
