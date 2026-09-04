# Test Coverage Discovery & Mapping

## Coverage Extraction in Kiro

To calculate the CRAP score, code coverage must be mapped down to the individual function level.

```
CRAP(m) = CC² × (1 − cov)³ + CC
```

---

## 1. Auto-Discovery Locations

When invoked without an explicit `--lcov` flag, the analyzer checks the workspace for standard coverage artifacts. Reports are parsed by one of three built-in parsers — **LCOV**, **XML** (JaCoCo / Cobertura / Clover, auto-detected by schema), or **Go cover** — selected by file extension and content.

| Language / Tool | Frameworks | Parser | Auto-Discovered Paths |
|:---|:---|:---|:---|
| **TypeScript / JS / Vue** | Jest, Vitest, c8, Istanbul | LCOV | `coverage/lcov.info`<br>`coverage.lcov`<br>`coverage/lcovonly`<br>`lcov.info` |
| **Go** | `go test -coverprofile` | Go cover | `coverage.out`<br>`c.out`<br>`cover.out` |
| **Java** | JaCoCo (Maven, Gradle) | XML (JaCoCo) | `target/site/jacoco/jacoco.xml`<br>`build/reports/jacoco/test/jacocoTestReport.xml`<br>`build/reports/jacoco/test/jacoco.xml` |
| **Python** | coverage.py, pytest-cov | XML (Cobertura) / LCOV | `coverage.xml`<br>`coverage/cobertura.xml`<br>(or `coverage lcov` → `coverage/lcov.info`) |
| **PHP** | PHPUnit, Pest | XML (Clover) / LCOV | `build/logs/clover.xml`<br>`clover.xml`<br>`coverage/coverage.lcov` |
| **LLVM / Clang / Rust / Swift** | `llvm-cov`, `cargo-llvm-cov`, `swift test` | LCOV | `coverage/lcov.info`<br>`coverage.lcov`<br>(or generate via `--llvm-binary`; see §2) |

Any of these can also be passed explicitly with `--lcov <path>` — the flag dispatches by extension, so `--lcov target/site/jacoco/jacoco.xml`, `--lcov coverage.out`, and `--lcov coverage/lcov.info` all work.

> **XML schema auto-detection:** JaCoCo (`<report>` root or a `<package>` child), Cobertura (`<coverage>` root with `<packages>`), and Clover (`<coverage>` root with `<project>`) are distinguished automatically. Line hits are read from JaCoCo `ci` (covered instructions), Cobertura `hits`, and Clover `count`.

---

## 2. Generating LCOV with `llvm-cov`

When working with LLVM-instrumented code (Clang C/C++, Rust, Swift, or native binaries), LCOV trace data can be generated using `llvm-cov export`:

### Step-by-Step Mechanism
1. **Instrument & Compile:**
   Compile source files with profiling flags:
   ```bash
   clang -fprofile-instr-generate -fcoverage-mapping source.c -o my_test
   ```
2. **Execute Tests:**
   Run the test binary to produce raw execution counters (`.profraw`):
   ```bash
   LLVM_PROFILE_FILE="default.profraw" ./my_test
   ```
3. **Merge Raw Profiles (`llvm-profdata`):**
   ```bash
   llvm-profdata merge -sparse default.profraw -o coverage.profdata
   # On macOS: xcrun llvm-profdata merge -sparse default.profraw -o coverage.profdata
   ```
4. **Export to LCOV Format (`llvm-cov export`):**
   ```bash
   llvm-cov export -format=lcov ./my_test -instr-profile=coverage.profdata > coverage/lcov.info
   # On macOS: xcrun llvm-cov export -format=lcov ./my_test -instr-profile=coverage.profdata > coverage/lcov.info
   ```

### Using the Bundled Helper (`generate_llvm_lcov.sh`)
The skill bundles a self-contained helper script that detects tools (including `xcrun` on macOS and Homebrew), merges `.profraw` files automatically, and exports LCOV:

```bash
# Auto-detects discovered .profraw/.profdata in workspace and writes to coverage/lcov.info
.kiro/skills/crap-metric/scripts/generate_llvm_lcov.sh --binary ./build/test_runner

# Custom profdata and output path
.kiro/skills/crap-metric/scripts/generate_llvm_lcov.sh \
  --binary ./build/test_runner \
  --profdata ./coverage.profdata \
  --output coverage/lcov.info
```

Or invoke directly in the main analyzer:
```bash
.kiro/skills/crap-metric/scripts/analyze.sh --path src/ --llvm-binary ./build/test_runner
```

---

## 3. Line Coverage Mapping Strategy

LCOV data contains file records (`SF:`), line coverage counts (`DA:lineNumber,hitCount`), and optional function records (`FN:`, `FNDA:`).

For a function spanning lines `[startLine, endLine]` in file `F`:

1. Find all `DA` records in file `F` where `startLine ≤ line ≤ endLine`.
2. If executable lines are found in this range:

   ```
   cov(m) = (count of lines in [startLine, endLine] with hitCount > 0)
            ÷ (count of lines in [startLine, endLine])
   ```
3. If no line records match, check `FNDA` (function execution count):
   - Hit count `> 0` ⟹ `1.0` (or fallback based on file average)
   - Hit count `= 0` ⟹ `0.0`
4. If no coverage data exists for file `F`, coverage defaults to `0.0` (worst-case assumption: unverified code).

---

## 4. Running Coverage On-Demand for Other Languages

### Go
```bash
go test -coverprofile=coverage.out ./...
```

### TypeScript / JavaScript
```bash
npm test -- --coverage --coverageReporters="lcovonly"
# or
npx vitest run --coverage
```

### PHP
```bash
vendor/bin/phpunit --coverage-lcov coverage/lcov.info
```

### Java
```bash
./gradlew test jacocoTestReport
# or
mvn test jacoco:report
```
