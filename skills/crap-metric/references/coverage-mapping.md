# Test Coverage Discovery & Mapping

## Coverage Extraction in Kiro

To calculate the CRAP score, code coverage must be mapped down to the individual function level.

$$\text{CRAP}(m) = \text{CC}^2 \times (1 - \text{cov})^3 + \text{CC}$$

---

## 1. Auto-Discovery Locations

When invoked without an explicit `--lcov` flag, the analyzer checks the workspace for standard coverage artifacts:

| Language / Tool | Frameworks | Common Coverage Paths |
|:---|:---|:---|
| **TypeScript / JS** | Jest, Vitest, c8, Istanbul | `coverage/lcov.info`<br>`coverage/lcov-report/index.html`<br>`.nyc_output/` |
| **Go** | `go test -coverprofile` | `coverage.out`<br>`c.out`<br>`cover.out` |
| **Java** | JaCoCo, Maven, Gradle | `target/site/jacoco/jacoco.xml`<br>`build/reports/jacoco/test/jacocoTestReport.xml`<br>`build/reports/jacoco/test/jacoco.csv` |
| **PHP** | PHPUnit, Pest | `coverage/coverage.lcov`<br>`coverage/lcov.info`<br>`build/logs/clover.xml`<br>`coverage.xml` |
| **LLVM / Clang / Rust / Swift** | `llvm-cov`, `cargo-llvm-cov`, `swift test` | `coverage/lcov.info`<br>`coverage.lcov`<br>`*.profdata`<br>`*.profraw` |

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

For a function spanning lines $[\text{startLine}, \text{endLine}]$ in file $F$:

1. Find all `DA` records in file $F$ where $\text{startLine} \le \text{line} \le \text{endLine}$.
2. If executable lines are found in this range:
   $$\text{cov}(m) = \frac{|\{\text{line} \in [\text{startLine}, \text{endLine}] \mid \text{hitCount} > 0\}|}{|\{\text{line} \in [\text{startLine}, \text{endLine}]\}|}$$
3. If no line records match, check `FNDA` (function execution count):
   - Hit count $> 0 \implies 1.0$ (or fallback based on file average)
   - Hit count $= 0 \implies 0.0$
4. If no coverage data exists for file $F$, coverage defaults to $0.0$ (worst-case assumption: unverified code).

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
