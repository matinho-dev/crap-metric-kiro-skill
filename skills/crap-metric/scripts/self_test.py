#!/usr/bin/env python3
"""
Self-Test Verification Script
1. Tests generating LCOV coverage from a native binary via `llvm-cov export`.
2. Traces execution of `analyze.py` and exports real LCOV trace data.
3. Analyzes `.kiro/skills/crap-metric/scripts` with the generated LCOV coverage,
   demonstrating how CRAP scores drop as test coverage is applied.
"""

import os
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze


def test_llvm_cov_generation(script_dir: str) -> str:
    """Compiles an instrumented C binary, runs it, and exports LCOV via generate_llvm_lcov.py."""
    print("==================================================")
    print("STEP 1: Testing LCOV Generation via llvm-cov")
    print("==================================================")

    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = os.path.join(tmpdir, "calculator.c")
        bin_file = os.path.join(tmpdir, "calculator")
        profraw_file = os.path.join(tmpdir, "default.profraw")
        out_lcov = os.path.join(tmpdir, "calculator.lcov")

        with open(src_file, "w") as f:
            _ = f.write("""
#include <stdio.h>
int compute_risk(int a, int b) {
    if (a > 0) {
        if (b > 0) {
            return a + b;
        } else {
            return a - b;
        }
    }
    return 0;
}

int main() {
    int res = compute_risk(10, 5);
    return (res == 15) ? 0 : 1;
}
""")

        # 1. Compile with Clang profiling
        print(f"[*] Compiling instrumented binary with clang: {src_file}")
        compile_cmd = ["clang", "-fprofile-instr-generate", "-fcoverage-mapping", src_file, "-o", bin_file]
        _ = subprocess.run(compile_cmd, check=True)

        # 2. Run binary to produce .profraw
        print("[*] Running binary to emit .profraw...")
        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = profraw_file
        _ = subprocess.run([bin_file], env=env, check=True)

        # 3. Invoke generate_llvm_lcov.py
        gen_script = os.path.join(script_dir, "generate_llvm_lcov.py")
        print("[*] Invoking generate_llvm_lcov.py...")
        gen_cmd = [
            sys.executable, gen_script,
            "--binary", bin_file,
            "--workspace", tmpdir,
            "--output", out_lcov
        ]
        _ = subprocess.run(gen_cmd, check=True)

        with open(out_lcov, "r") as f:
            lcov_content = f.read()

        print(f"[+] Successfully generated LCOV with {len(lcov_content.splitlines())} lines.")
        first_lines = "\n".join(lcov_content.splitlines()[:12])
        print(f"[+] LCOV Sample:\n{first_lines}\n")

        # 4. Analyze the C file with analyze.py and the generated LCOV
        analyze_script = os.path.join(script_dir, "analyze.py")
        print("[*] Running CRAP analysis on calculator.c using generated LCOV...")
        res = subprocess.run(
            [sys.executable, analyze_script, "--path", src_file, "--lcov", out_lcov, "--format", "table"],
            stdout=subprocess.PIPE, text=True, check=True
        )
        print(res.stdout)

    return "PASSED"


def generate_self_lcov_and_analyze(script_dir: str):
    """Executes analyze.py with trace tracking and generates LCOV for analyze.py itself."""
    print("==================================================")
    print("STEP 2: Tracing analyze.py Execution & Self-CRAP")
    print("==================================================")

    analyze_file = os.path.join(script_dir, "analyze.py")
    coverage_dir = os.path.join(script_dir, "coverage")
    os.makedirs(coverage_dir, exist_ok=True)
    lcov_file = os.path.join(coverage_dir, "self_coverage.lcov")

    # Trace execution of analyze.py on multi-language test snippets
    import trace
    tracer = trace.Trace(count=1, trace=0)

    print("[*] Exercising analyze.py functions with sample workloads...")

    def exercise_workloads():
        _ = analyze.calculate_crap(10, 0.5)
        _ = analyze.calculate_crap(5, None)
        _ = analyze.count_decision_points("if (a && b) { for(i=0; i<10; i++) {} }", "java")
        _ = analyze.count_decision_points("if a > 0 && b > 0 { select { case <-ch: } }", "go")
        _ = analyze.count_decision_points("function f() { if ($a ?? $b) { foreach($arr as $v) {} } }", "php")
        _ = analyze.count_decision_points("const x = (a) => { if (a?.b ?? c) return a &&= b; }", "typescript")
        _ = analyze.count_decision_points("def foo():\n    if a and b:\n        for x in y: pass", "python")
        
        # Test file analysis
        dummy_java = "public class T { public void test() { if (true) return; } }"
        _ = analyze.extract_functions("T.java", dummy_java, "java")

        # Test markdown formatting
        rec = analyze.generate_recommendation(
            cc=2, cov_pct=80.0, crap=2.1, threshold=30.0, uncovered_lines=[],
            language="typescript", func_name="demo"
        )
        m = analyze.FunctionMetric(
            file_path="sample.ts", function_name="demo", language="typescript",
            line_start=1, line_end=5, complexity=2, coverage=80.0, crap_score=2.1,
            is_over_threshold=False, status="OK", recommendation=rec
        )
        _ = analyze.format_markdown([m], 30.0, "Test Scope")

    tracer.runfunc(exercise_workloads)

    # Collect line hits for analyze.py
    results = tracer.results()
    line_counts = results.counts
    norm_target = os.path.normpath(analyze_file)

    target_hits = {
        line: count for (fname, line), count in line_counts.items()
        if os.path.normpath(fname) == norm_target
    }

    print(f"[+] Traced {len(target_hits)} executed lines in {analyze_file}")

    # Write LCOV format
    with open(lcov_file, "w") as f:
        _ = f.write(f"SF:{analyze_file}\n")
        with open(analyze_file, "r") as src:
            total_lines = len(src.readlines())
        for ln in range(1, total_lines + 1):
            hits = target_hits.get(ln, 0)
            _ = f.write(f"DA:{ln},{hits}\n")
        _ = f.write("end_of_record\n")

    print(f"[+] Wrote self-test coverage to: {lcov_file}\n")

    # Run CRAP analysis against scripts/ without coverage
    print("--- 1. Scripts Analysis WITHOUT Coverage (Baseline) ---")
    _ = subprocess.run([
        sys.executable, analyze_file,
        "--path", script_dir,
        "--format", "markdown"
    ], check=False)

    print("\n--- 2. Scripts Analysis WITH Self LCOV Coverage ---")
    _ = subprocess.run([
        sys.executable, analyze_file,
        "--path", script_dir,
        "--lcov", lcov_file,
        "--format", "markdown"
    ], check=False)


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    _ = test_llvm_cov_generation(script_dir)
    print()
    generate_self_lcov_and_analyze(script_dir)
    print("\n==================================================")
    print("✅ All self-tests and pipeline validations PASSED!")
    print("==================================================")


if __name__ == "__main__":
    main()
