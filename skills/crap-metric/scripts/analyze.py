#!/usr/bin/env python3
"""
CRAP (Change Risk Anti-Patterns) Analyzer & Recommendation Engine
Calculates Cyclomatic Complexity (CC), maps test coverage (cov), computes CRAP scores,
and generates prescriptive action recommendations and AI agent prompt directives.

Formula: CRAP(m) = CC^2 * (1 - cov)^3 + CC
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

SUPPORTED_EXTENSIONS = {
    ".java": "java",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".php": "php",
    ".vue": "vue",
    ".py": "python",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
}

IGNORED_DIR_NAMES = {
    ".git", "__pycache__", ".nyc_output", ".idea", ".vscode",
    "node_modules", "vendor", "dist", "build", "target"
}

IGNORED_FUNCTION_NAMES = {
    "if", "for", "while", "switch", "catch", "return", "class", "interface", "struct", "type"
}

# Uncle Bob's Clean Code guidance for (agentic-generated) functions: keep Cyclomatic
# Complexity at or below this value. Functions above it are flagged for decomposition
# even when their CRAP score is within threshold.
DEFAULT_MAX_COMPLEXITY = 6

FUNCTION_HEADER_PATTERNS: dict[str, re.Pattern[str]] = {
    "go": re.compile(
        r"(?m)^[ \t]*func\s+(?:\([^\)]+\)\s+)?([A-Za-z0-9_]+)\s*\([^{]*\)[^{]*\{"
    ),
    "php": re.compile(
        r"(?m)^[ \t]*(?:(?:public|protected|private|static|final|abstract)\s+)*"
        + r"function\s+&?\s*([A-Za-z0-9_]+)\s*\([^)]*\)\s*(?::\s*[\w\\|\?]+)?\s*\{"
    ),
    "native": re.compile(
        r"(?m)^[ \t]*(?:@\w+(?:\([^)]*\))?\s*)*"
        + r"(?:(?:public|protected|private|static|final|synchronized|abstract|default|native|inline|virtual)\s+)*"
        + r"(?:<[\w,\s\?]+>\s+)?"
        + r"[\w<>\[\],\s\?*&]+\s+"
        + r"([A-Za-z0-9_]+)\s*"
        + r"\([^)]*\)\s*"
        + r"(?:const\s+)?(?:noexcept\s+)?(?:override\s+)?"
        + r"(?:throws\s+[\w,\s]+)?\s*\{"
    ),
    "typescript": re.compile(
        r"(?m)^[ \t]*(?:export\s+(?:default\s+)?)?"
        + r"(?:"
        + r"(?:async\s+)?function\s*\*?\s*([A-Za-z0-9_$]+)\s*\([^)]*\)[^{]*\{|"
        + r"(?:(?:public|protected|private|static|async|override|readonly)\s+)*([A-Za-z0-9_$]+)\s*\([^)]*\)[^{]*\{|"
        + r"(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_$]+)\s*(?::\s*[^=]+)?=>\s*\{"
        + r")"
    )
}


@dataclass
class FunctionSpan:
    name: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    body: str


@dataclass
class FunctionRecommendation:
    category: str  # MANDATORY_REFACTOR, ADD_UNIT_TESTS, PREVENTIVE_MAINTENANCE, HEALTHY
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    target_coverage_percent: float | None
    uncovered_lines: list[int]
    uncovered_lines_display: str
    summary: str
    actions: list[str]
    ai_agent_directive: str


@dataclass
class FunctionMetric:
    file_path: str
    function_name: str
    language: str
    line_start: int
    line_end: int
    complexity: int
    coverage: float
    crap_score: float
    is_over_threshold: bool
    status: str
    recommendation: FunctionRecommendation


def calculate_crap(cc: int, coverage: float | None) -> float:
    """CRAP(m) = CC^2 * (1 - cov)^3 + CC"""
    cov = 0.0 if coverage is None else max(0.0, min(1.0, coverage))
    return round((cc ** 2) * ((1.0 - cov) ** 3) + cc, 2)


def compute_target_coverage(cc: int, threshold: float) -> float | None:
    """
    Computes minimum test coverage required to bring CRAP <= threshold:
    cov >= 1 - ((threshold - cc) / (cc^2))^(1/3)
    Returns None if cc > threshold (impossible to salvage via tests alone).
    """
    if cc > threshold:
        return None
    if cc <= 1:
        return 0.0
    if cc == threshold:
        return 100.0
    val: float = (threshold - cc) / (cc ** 2)
    min_cov: float = 1.0 - math.pow(val, 1.0 / 3.0)
    return round(max(0.0, min(1.0, min_cov)) * 100, 1)


def format_line_ranges(lines: list[int]) -> str:
    """Formats list of line numbers into concise ranges e.g. '14-16, 20, 22-24'."""
    if not lines:
        return "None"
    sorted_lines = sorted(set(lines))
    ranges: list[str] = []
    start = sorted_lines[0]
    end = start
    for n in sorted_lines[1:]:
        if n == end + 1:
            end = n
        else:
            ranges.append(f"{start}-{end}" if start != end else f"{start}")
            start = end = n
    ranges.append(f"{start}-{end}" if start != end else f"{start}")
    return ", ".join(ranges)


def generate_agent_prompt(
    category: str,
    func_name: str,
    file_path: str,
    line_start: int,
    line_end: int,
    cc: int,
    cov_pct: float,
    target_cov: float | None,
    uncovered_lines_display: str,
    language: str,
    threshold: float,
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
) -> str:
    """Generates machine-actionable instructions for AI agents to self-heal the code."""
    frameworks = {
        "python": "pytest / unittest",
        "typescript": "vitest / jest",
        "javascript": "vitest / jest",
        "java": "JUnit 5",
        "go": "testing package",
        "php": "PHPUnit / Pest",
        "vue": "vitest with vue-test-utils",
        "c": "clang instrumented runner / ctest",
        "cpp": "gtest / catch2"
    }
    fw = frameworks.get(language, "standard test framework")

    if category == "MANDATORY_REFACTOR":
        return (
            f"TASK: Refactor function `{func_name}` in `{file_path}` (lines {line_start}-{line_end}).\n"
            f"CONTEXT: Cyclomatic Complexity is {cc} (exceeds threshold of {threshold}). "
            f"Testing alone cannot reduce CRAP <= {threshold}. Code decomposition is required.\n"
            f"DIRECTIVES:\n"
            f"1. Read lines {line_start} to {line_end} of `{file_path}`.\n"
            f"2. Decompose `{func_name}` by extracting isolated logic, inner loops, or distinct validation steps into helper functions.\n"
            f"3. Invert nested conditionals to apply early return guard clauses.\n"
            f"4. Replace multi-branch switch/case or cascading if/else with lookup dictionaries or polymorphism.\n"
            f"5. Maintain exact function signature, return types, and external behavior to preserve compatibility.\n"
            f"6. Validate refactoring: Run `.kiro/skills/crap-metric/scripts/analyze.sh --path {file_path}` to confirm CC <= {max_complexity} and CRAP <= {threshold}."
        )
    elif category == "ADD_UNIT_TESTS":
        uncovered_info = f"- Untested lines: `{uncovered_lines_display}`\n" if uncovered_lines_display != "None" else ""
        return (
            f"TASK: Generate unit tests for `{func_name}` in `{file_path}` (lines {line_start}-{line_end}) using {fw}.\n"
            f"CONTEXT: Function has Cyclomatic Complexity {cc} with only {cov_pct}% test coverage. "
            f"Minimum coverage needed to bring CRAP <= {threshold} is {target_cov}%.\n"
            f"DIRECTIVES:\n"
            f"1. Inspect `{file_path}:{line_start}-{line_end}` to understand inputs, outputs, and branches.\n"
            f"{uncovered_info}"
            f"2. Create or extend test cases exercising:\n"
            f"   a. Main successful execution paths.\n"
            f"   b. Edge cases and boundary conditions corresponding to untested lines.\n"
            f"   c. Error states and exception handling branches.\n"
            f"3. Run the test suite and export coverage to LCOV.\n"
            f"4. Validate fix: Run `.kiro/skills/crap-metric/scripts/analyze.sh --path {file_path} --lcov <coverage-file>` to confirm CRAP <= {threshold}."
        )
    elif category == "REDUCE_COMPLEXITY":
        return (
            f"TASK: Reduce the Cyclomatic Complexity of `{func_name}` in `{file_path}` (lines {line_start}-{line_end}).\n"
            f"CONTEXT: CRAP is within threshold, but Cyclomatic Complexity is {cc} (exceeds the Clean Code maximum of {max_complexity}).\n"
            f"DIRECTIVES:\n"
            f"1. Read lines {line_start} to {line_end} of `{file_path}`.\n"
            f"2. Extract cohesive logic, inner loops, or distinct steps into small helper functions.\n"
            f"3. Invert nested conditionals into early-return guard clauses.\n"
            f"4. Replace cascading if/elif or switch/case with lookup/dispatch tables.\n"
            f"5. Preserve the function signature, return types, and external behavior.\n"
            f"6. Validate: Run `.kiro/skills/crap-metric/scripts/analyze.sh --path {file_path}` to confirm CC <= {max_complexity}."
        )
    else:
        return f"TASK: Maintain existing tests for `{func_name}` in `{file_path}`. No changes needed."


def generate_recommendation(
    cc: int,
    cov_pct: float,
    crap: float,
    threshold: float,
    uncovered_lines: list[int],
    language: str,
    func_name: str,
    file_path: str = "",
    line_start: int = 1,
    line_end: int = 1,
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
) -> FunctionRecommendation:
    """Generates concrete, actionable advice based on CC, coverage, and CRAP score."""
    target_cov = compute_target_coverage(cc, threshold)
    uncovered_disp = format_line_ranges(uncovered_lines)

    # 1. CC > threshold (MANDATORY REFACTOR)
    if cc > threshold:
        category = "MANDATORY_REFACTOR"
        severity = "CRITICAL"
        summary = (
            f"Complexity is {cc} (> {threshold} threshold). Even 100% test coverage yields "
            f"CRAP {cc:.1f}, which cannot clear the threshold. Must be refactored."
        )
        actions = [
            f"Decompose `{func_name}`: Extract discrete logic chunks into smaller helper functions.",
            "Replace nested condition ladders with early return guard clauses.",
            "Replace multi-branch switch/case statements with dispatch tables, maps, or polymorphism.",
            f"Target: Reduce Cyclomatic Complexity from {cc} down to <= {max_complexity}."
        ]

    # 2. CC <= threshold but CRAP > threshold (ADD UNIT TESTS)
    elif crap > threshold:
        category = "ADD_UNIT_TESTS"
        severity = "HIGH"
        gap = (target_cov or 0.0) - cov_pct
        summary = (
            f"Function has manageable complexity ({cc}), but current coverage ({cov_pct}%) "
            f"is below the {target_cov}% needed to clear the CRAP threshold."
        )
        actions = [
            f"Coverage Goal: Increase unit test coverage from {cov_pct}% to at least {target_cov}% (+{gap:.1f}%).",
        ]
        if uncovered_lines:
            actions.append(f"Write unit tests covering untested execution lines: `{uncovered_disp}`.")
        else:
            actions.append("Generate tests exercising edge branches, error states, and exception handlers.")
        actions.append(
            "Alternative Quick-Win: Simplifying compound logic to reduce CC by 2-3 points will drastically lower the required test coverage."
        )

    # 3. CRAP within threshold but CC exceeds the Clean Code max (REDUCE COMPLEXITY)
    elif cc > max_complexity:
        category = "REDUCE_COMPLEXITY"
        severity = "MEDIUM"
        summary = (
            f"CRAP ({crap}) is within threshold, but Cyclomatic Complexity ({cc}) exceeds the "
            f"Clean Code maximum of {max_complexity}. Decompose to improve readability and testability."
        )
        actions = [
            f"Decompose `{func_name}`: extract cohesive logic into small helper functions.",
            "Prefer early-return guard clauses over nested conditionals.",
            "Replace multi-branch if/elif or switch/case with lookup/dispatch tables.",
            f"Target: Reduce Cyclomatic Complexity from {cc} down to <= {max_complexity}."
        ]

    # 4. Low complexity and safe CRAP
    else:
        category = "HEALTHY"
        severity = "LOW"
        summary = f"Clean, low-risk function (CC: {cc}, CRAP: {crap})."
        actions = ["No immediate action needed. Keep existing test coverage intact."]

    agent_directive = generate_agent_prompt(
        category=category,
        func_name=func_name,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        cc=cc,
        cov_pct=cov_pct,
        target_cov=target_cov,
        uncovered_lines_display=uncovered_disp,
        language=language,
        threshold=threshold,
        max_complexity=max_complexity,
    )

    return FunctionRecommendation(
        category=category,
        severity=severity,
        target_coverage_percent=target_cov,
        uncovered_lines=uncovered_lines,
        uncovered_lines_display=uncovered_disp,
        summary=summary,
        actions=actions,
        ai_agent_directive=agent_directive
    )


def _skip_line_comment(code: str, i: int, n: int) -> int:
    """Advances index past end-of-line comment."""
    while i < n and code[i] != "\n":
        i += 1
    return i


def _skip_block_comment(code: str, i: int, n: int) -> tuple[int, list[str]]:
    """Advances index past block comment, preserving internal newlines."""
    newlines: list[str] = []
    while i < n:
        if code[i] == "\n":
            newlines.append("\n")
        elif code[i] == "*" and i + 1 < n and code[i + 1] == "/":
            return i + 2, newlines
        i += 1
    return i, newlines


def _skip_triple_quote(code: str, i: int, n: int, quote_char: str) -> tuple[int, list[str]]:
    """Advances index past Python triple-quoted string, preserving internal newlines."""
    target = quote_char * 3
    newlines: list[str] = []
    while i < n:
        if code[i] == "\n":
            newlines.append("\n")
        elif code[i:i + 3] == target:
            return i + 3, newlines
        i += 1
    return i, newlines


def _skip_simple_quote(code: str, i: int, n: int, quote_char: str) -> tuple[int, list[str]]:
    """Advances index past quoted string literal, preserving internal newlines (e.g. template literals)."""
    newlines: list[str] = []
    while i < n:
        c = code[i]
        if c == "\\":
            i += 2
            continue
        if c == quote_char:
            return i + 1, newlines
        if c == "\n":
            newlines.append("\n")
        i += 1
    return i, newlines


def _skip_comment_or_string(
    code: str, i: int, n: int, language: str, allow_backticks: bool
) -> tuple[int, list[str]] | None:
    """Attempts to skip a comment or string literal starting at index i.

    Returns (new_index, preserved_newlines) if a comment/string was skipped, or
    None if the character at i does not start one.
    """
    c = code[i]
    next_c = code[i + 1] if i + 1 < n else ""

    # Line comments (// or #)
    if c == "/" and next_c == "/":
        return _skip_line_comment(code, i + 2, n), []
    if language in ("php", "python") and c == "#":
        return _skip_line_comment(code, i + 1, n), []

    # Block comments (/* ... */)
    if c == "/" and next_c == "*":
        return _skip_block_comment(code, i + 2, n)

    # Python triple quotes
    if language == "python" and code[i:i + 3] in ('"""', "'''"):
        return _skip_triple_quote(code, i + 3, n, code[i])

    # Quoted strings or template literals
    if c in ('"', "'") or (c == "`" and allow_backticks):
        return _skip_simple_quote(code, i + 1, n, c)

    return None


def strip_comments_and_strings(code: str, language: str) -> str:
    """Removes comments and string literals to avoid false-positive decision points."""
    result: list[str] = []
    i = 0
    n = len(code)
    allow_backticks = language in ("typescript", "javascript", "go", "vue")

    while i < n:
        skipped = _skip_comment_or_string(code, i, n, language, allow_backticks)
        if skipped is not None:
            i, newlines = skipped
            result.extend(newlines)
            continue
        result.append(code[i])
        i += 1

    return "".join(result)


def count_decision_points(body: str, language: str) -> int:
    """Calculates cyclomatic complexity for the sanitized function body."""
    clean_body = strip_comments_and_strings(body, language)

    common_patterns = [
        r"\bif\b",
        r"\bfor\b",
        r"\bwhile\b",
        r"\bcase\b",
        r"\bcatch\b",
        r"&&",
        r"\|\|",
    ]

    ternary = r"(?<!\?)\?(?!\.|\?|\:)"
    language_patterns: dict[str, list[str]] = {
        "typescript": [r"\?\?", r"&&=", r"\|\|=", r"\?\?=", ternary],
        "javascript": [r"\?\?", r"&&=", r"\|\|=", r"\?\?=", ternary],
        "vue": [r"\?\?", r"&&=", r"\|\|=", r"\?\?=", ternary],
        "php": [r"\belseif\b", r"\bforeach\b", r"\band\b", r"\bor\b", r"\bxor\b", r"\?\?", r"\?\?=", ternary],
        "python": [r"\belif\b", r"\bexcept\b", r"\band\b", r"\bor\b"],
        "java": [ternary],
        "c": [ternary],
        "cpp": [ternary],
    }

    patterns = common_patterns + language_patterns.get(language, [])
    points = sum(len(re.findall(pat, clean_body)) for pat in patterns)
    return 1 + points


def _python_function_end(lines: list[str], start_idx: int, base_indent: int) -> int:
    """Returns the last line index (0-based) of a Python function body by indentation."""
    end_idx = start_idx
    for j in range(start_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("#"):
            continue
        cur_indent = len(lines[j][:len(lines[j]) - len(lines[j].lstrip())].expandtabs(4))
        if cur_indent <= base_indent:
            break
        end_idx = j
    return end_idx


def extract_python_functions(file_path: str, content: str) -> list[FunctionSpan]:
    """Finds Python function declarations and tracks boundaries using indentation."""
    functions: list[FunctionSpan] = []
    lines = content.splitlines()
    fn_header_re: re.Pattern[str] = re.compile(r"^([ \t]*)(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\(")

    for idx, line in enumerate(lines):
        match = fn_header_re.match(line)
        if not match:
            continue
        base_indent = len(match.group(1).expandtabs(4))
        end_idx = _python_function_end(lines, idx, base_indent)
        functions.append(FunctionSpan(
            name=match.group(2),
            file_path=file_path,
            language="python",
            line_start=idx + 1,
            line_end=end_idx + 1,
            body="\n".join(lines[idx:end_idx + 1]),
        ))

    return functions


def extract_functions(file_path: str, content: str, language: str) -> list[FunctionSpan]:
    """Finds all functions/methods and their line boundaries."""
    if language == "python":
        return extract_python_functions(file_path, content)

    if language == "vue":
        functions: list[FunctionSpan] = []
        template_match = re.search(r"<template\b[^>]*>(.*?)</template>", content, re.DOTALL)
        if template_match:
            tmpl_content = template_match.group(1)
            start_pos = template_match.start(1)
            start_line = content[:start_pos].count("\n") + 1
            end_line = start_line + tmpl_content.count("\n")
            
            functions.append(FunctionSpan(
                name="<template>",
                file_path=file_path,
                language=language,
                line_start=start_line,
                line_end=end_line,
                body=tmpl_content
            ))

        script_match = re.search(r"<script\b[^>]*>(.*?)</script>", content, re.DOTALL)
        if script_match:
            script_content = script_match.group(1)
            offset_pos = script_match.start(1)
            offset_line = content[:offset_pos].count("\n")
            script_fns = extract_functions_generic(file_path, script_content, "typescript", offset_line)
            functions.extend(script_fns)

        return functions

    return extract_functions_generic(file_path, content, language, 0)


def _get_function_header_regex(language: str) -> re.Pattern[str]:
    """Returns compiled regex for function declarations based on language."""
    if language in ("java", "c", "cpp"):
        return FUNCTION_HEADER_PATTERNS["native"]
    return FUNCTION_HEADER_PATTERNS.get(language, FUNCTION_HEADER_PATTERNS["typescript"])


def _skip_brace_scan_noise(content: str, curr: int, n: int) -> int | None:
    """If a comment or string starts at curr, returns the index just past it; else None."""
    two = content[curr:curr + 2]
    if two == "//":
        return _skip_line_comment(content, curr + 2, n)
    if two == "/*":
        return _skip_block_comment(content, curr + 2, n)[0]
    if content[curr] in ('"', "'", "`"):
        return _skip_simple_quote(content, curr + 1, n, content[curr])[0]
    return None


def _find_matching_brace(content: str, open_brace_index: int) -> int:
    """Scans forward from open brace to find the corresponding closing brace index."""
    curr = open_brace_index + 1
    n = len(content)
    brace_count = 1

    while curr < n and brace_count > 0:
        skipped = _skip_brace_scan_noise(content, curr, n)
        if skipped is not None:
            curr = skipped
            continue
        c = content[curr]
        if c == "{":
            brace_count += 1
        elif c == "}":
            brace_count -= 1
        curr += 1

    return curr


def extract_functions_generic(file_path: str, content: str, language: str, line_offset: int) -> list[FunctionSpan]:
    """Finds function declarations and their enclosing braces."""
    functions: list[FunctionSpan] = []
    fn_header_re = _get_function_header_regex(language)

    for match in fn_header_re.finditer(content):
        name = next((g for g in match.groups() if g), "anonymous")
        if name in IGNORED_FUNCTION_NAMES:
            continue

        start_index = match.start()
        open_brace_index = match.end() - 1
        end_index = _find_matching_brace(content, open_brace_index)

        line_start = content[:start_index].count("\n") + 1 + line_offset
        line_end = content[:end_index].count("\n") + 1 + line_offset
        body = content[start_index:end_index]

        functions.append(FunctionSpan(
            name=name,
            file_path=file_path,
            language=language,
            line_start=line_start,
            line_end=line_end,
            body=body
        ))

    return functions


class CoverageDatabase:
    """Manages line-level and function-level coverage records parsed from LCOV or cover profiles."""

    def __init__(self):
        self.file_line_hits: dict[str, dict[int, int]] = {}
        self.file_func_hits: dict[str, dict[str, int]] = {}

    def _lcov_begin_file(self, sf_value: str) -> str:
        """Handles an SF: record; registers the file and returns its normalized path."""
        current_file = os.path.normpath(sf_value)
        _ = self.file_line_hits.setdefault(current_file, {})
        _ = self.file_func_hits.setdefault(current_file, {})
        return current_file

    def _lcov_record_line(self, current_file: str, da_value: str) -> None:
        """Handles a DA: record (line_no,hits), max-merging with any existing entry."""
        parts = da_value.split(",")
        if len(parts) >= 2:
            self._record_line_hit(current_file, int(parts[0]), int(parts[1]))

    def _lcov_record_func(self, current_file: str, fnda_value: str) -> None:
        """Handles an FNDA: record (hits,func_name), max-merging with any existing entry."""
        parts = fnda_value.split(",")
        if len(parts) >= 2:
            func_map = self.file_func_hits.setdefault(current_file, {})
            func_map[parts[1]] = max(func_map.get(parts[1], 0), int(parts[0]))

    def _process_lcov_line(self, line: str, current_file: str | None) -> str | None:
        """Dispatches one LCOV line to the right handler; returns the updated current_file."""
        if line.startswith("SF:"):
            return self._lcov_begin_file(line[3:])
        if line == "end_of_record":
            return None
        if current_file is None:
            return current_file
        if line.startswith("DA:"):
            self._lcov_record_line(current_file, line[3:])
        elif line.startswith("FNDA:"):
            self._lcov_record_func(current_file, line[5:])
        return current_file

    def load_lcov(self, lcov_path: str) -> None:
        if not os.path.exists(lcov_path):
            return
        try:
            with open(lcov_path, "r", encoding="utf-8", errors="replace") as f:
                current_file: str | None = None
                for line in f:
                    current_file = self._process_lcov_line(line.strip(), current_file)
        except (OSError, ValueError) as e:
            print(f"Warning: Failed to parse LCOV file {lcov_path}: {e}", file=sys.stderr)

    def _record_go_span(self, file_norm: str, span: str, count: int) -> None:
        """Records a Go coverage span (start.col,end.col) with max-merge of hit counts."""
        line_hits = self.file_line_hits.setdefault(file_norm, {})
        start_end = span.split(",")
        start_line = int(start_end[0].split(".")[0])
        end_line = int(start_end[1].split(".")[0])
        for ln in range(start_line, end_line + 1):
            line_hits[ln] = max(line_hits.get(ln, 0), count)

    def _record_go_cover_line(self, line: str) -> None:
        """Parses and records a single Go coverage profile line (skips non-data lines)."""
        if line.startswith("mode:"):
            return
        parts = line.strip().split()
        if len(parts) < 3:
            return
        loc, count = parts[0], int(parts[2])
        if ":" not in loc:
            return
        file_path, span = loc.split(":", 1)
        self._record_go_span(os.path.normpath(file_path), span, count)

    def load_go_cover(self, cover_path: str) -> None:
        """Parses Go coverage profile (mode: count / mode: set)."""
        if not os.path.exists(cover_path):
            return
        try:
            with open(cover_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    self._record_go_cover_line(line)
        except (OSError, ValueError, IndexError) as e:
            print(f"Warning: Failed to parse Go coverage {cover_path}: {e}", file=sys.stderr)

    def _record_line_hit(self, file_norm: str, line_no: int, hits: int) -> None:
        """Records a single line's hit count, max-merging with any existing entry."""
        line_hits = self.file_line_hits.setdefault(file_norm, {})
        line_hits[line_no] = max(line_hits.get(line_no, 0), hits)

    def _load_jacoco(self, root: "ET.Element") -> None:
        """Parses a JaCoCo report: package/sourcefile/line with nr + ci (covered instructions)."""
        for package in root.iter("package"):
            pkg_name = package.get("name", "")
            for sourcefile in package.iter("sourcefile"):
                fname = sourcefile.get("name", "")
                file_path = f"{pkg_name}/{fname}" if pkg_name else fname
                self._load_jacoco_sourcefile(sourcefile, os.path.normpath(file_path))

    def _load_jacoco_sourcefile(self, sourcefile: "ET.Element", file_norm: str) -> None:
        """Records the line hits for a single JaCoCo <sourcefile> element."""
        for line in sourcefile.iter("line"):
            nr = line.get("nr")
            if nr is None:
                continue
            covered = int(line.get("ci", "0")) > 0
            self._record_line_hit(file_norm, int(nr), 1 if covered else 0)

    def _load_cobertura(self, root: "ET.Element") -> None:
        """Parses a Cobertura report: class[filename]/lines/line with number + hits."""
        for cls in root.iter("class"):
            filename = cls.get("filename")
            if not filename:
                continue
            file_norm = os.path.normpath(filename)
            for line in cls.iter("line"):
                number = line.get("number")
                if number is None:
                    continue
                self._record_line_hit(file_norm, int(number), int(line.get("hits", "0")))

    def _load_clover(self, root: "ET.Element") -> None:
        """Parses a Clover report: file[name/path]/line with num + count (statement lines only)."""
        for file_el in root.iter("file"):
            filename = file_el.get("path") or file_el.get("name")
            if not filename:
                continue
            file_norm = os.path.normpath(filename)
            for line in file_el.iter("line"):
                num = line.get("num")
                if num is None:
                    continue
                self._record_line_hit(file_norm, int(num), int(line.get("count", "0")))

    def _detect_xml_schema(self, root: "ET.Element") -> str | None:
        """Identifies the coverage XML schema from the root element, or None if unrecognized."""
        tag = root.tag.lower()
        if tag == "report" or root.find("package") is not None:
            return "jacoco"
        if tag != "coverage":
            return None
        if root.find("packages") is not None:
            return "cobertura"
        if root.find("project") is not None:
            return "clover"
        return None

    def _dispatch_xml(self, root: "ET.Element") -> bool:
        """Routes a parsed XML root to the matching schema loader. Returns True if recognized."""
        loaders = {
            "jacoco": self._load_jacoco,
            "cobertura": self._load_cobertura,
            "clover": self._load_clover,
        }
        schema = self._detect_xml_schema(root)
        if schema is None:
            return False
        loaders[schema](root)
        return True

    def load_xml(self, xml_path: str) -> None:
        """Parses a JaCoCo, Cobertura, or Clover XML coverage report into line hits."""
        if not os.path.exists(xml_path):
            return
        try:
            # Coverage reports are trusted local build artifacts, not untrusted input.
            root = ET.parse(xml_path).getroot()
            if not self._dispatch_xml(root):
                print(f"Warning: Unrecognized XML coverage schema in {xml_path}", file=sys.stderr)
        except (OSError, ET.ParseError, ValueError) as e:
            print(f"Warning: Failed to parse XML coverage {xml_path}: {e}", file=sys.stderr)

    def load_auto(self, path: str) -> None:
        """Loads a coverage file, dispatching by extension (.xml -> XML, .out -> Go, else LCOV)."""
        lowered = path.lower()
        if lowered.endswith(".xml"):
            self.load_xml(path)
        elif lowered.endswith((".out",)):
            self.load_go_cover(path)
        else:
            self.load_lcov(path)

    def get_function_coverage(
        self, file_path: str, start_line: int, end_line: int, name: str
    ) -> tuple[float | None, list[int]]:
        """
        Finds matching coverage for a given file and function span.
        Returns: (coverage_fraction_or_None, list_of_uncovered_line_numbers)
        """
        norm_target = os.path.normpath(file_path)
        
        matching_file = None
        for f in self.file_line_hits:
            if f == norm_target or f.endswith(norm_target) or norm_target.endswith(f):
                matching_file = f
                break

        if not matching_file:
            return None, []

        line_map = self.file_line_hits.get(matching_file, {})
        executable_in_span = [
            (line_no, hits) for line_no, hits in line_map.items() if start_line <= line_no <= end_line
        ]

        if executable_in_span:
            covered = [line_no for line_no, hits in executable_in_span if hits > 0]
            uncovered = [line_no for line_no, hits in executable_in_span if hits == 0]
            fraction = len(covered) / len(executable_in_span)
            return fraction, sorted(uncovered)

        func_map = self.file_func_hits.get(matching_file, {})
        if name in func_map:
            hits = func_map[name]
            return (1.0, []) if hits > 0 else (0.0, list(range(start_line, end_line + 1)))

        return None, []


def _all_existing(workspace_dir: str, rel_paths: list[str]) -> list[str]:
    """Returns every path in rel_paths that exists under workspace_dir, in listed order."""
    found: list[str] = []
    for rel in rel_paths:
        full = os.path.join(workspace_dir, rel)
        if os.path.exists(full):
            found.append(full)
    return found


def auto_discover_coverage(workspace_dir: str) -> CoverageDatabase:
    """Searches workspace for known coverage reports (LCOV, XML, or Go cover profiles).

    All matching reports in each bucket are loaded and merged, so polyglot repos
    with multiple coverage files are fully covered. Records max-merge by file+line,
    so loading several reports never lowers an already-observed hit count.
    """
    cov_db = CoverageDatabase()
    for lcov in _all_existing(workspace_dir, [
        "coverage/lcov.info",
        "coverage.lcov",
        "coverage/lcovonly",
        "coverage/coverage.lcov",
        "lcov.info",
    ]):
        cov_db.load_lcov(lcov)

    for xml in _all_existing(workspace_dir, [
        "target/site/jacoco/jacoco.xml",
        "build/reports/jacoco/test/jacocoTestReport.xml",
        "build/reports/jacoco/test/jacoco.xml",
        "coverage.xml",
        "coverage/cobertura.xml",
        "build/logs/clover.xml",
        "clover.xml",
    ]):
        cov_db.load_xml(xml)

    for go in _all_existing(workspace_dir, ["coverage.out", "c.out", "cover.out"]):
        cov_db.load_go_cover(go)

    return cov_db


def generate_llvm_lcov_in_memory(binary: str, profdata: str | None, workspace_dir: str) -> str | None:
    """Invokes generate_llvm_lcov.py to produce a temporary LCOV file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    llvm_script = os.path.join(script_dir, "generate_llvm_lcov.py")
    if not os.path.exists(llvm_script):
        return None

    tmp_fd, tmp_lcov_path = tempfile.mkstemp(suffix=".lcov")
    os.close(tmp_fd)

    cmd = [sys.executable, llvm_script, "--binary", binary, "--output", tmp_lcov_path, "--workspace", workspace_dir]
    if profdata:
        cmd.extend(["--profdata", profdata])

    try:
        _ = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return tmp_lcov_path
    except (subprocess.SubprocessError, OSError) as e:
        print(f"Warning: llvm-cov LCOV generation failed: {e}", file=sys.stderr)
        if os.path.exists(tmp_lcov_path):
            os.unlink(tmp_lcov_path)
        return None


def _run_git_diff(workspace_dir: str, base_ref: str | None) -> str | None:
    """Runs `git diff --unified=0` and returns stdout, or None on failure."""
    cmd = ["git", "diff", "--unified=0"]
    if base_ref:
        cmd.append(base_ref)
    try:
        proc = subprocess.run(cmd, cwd=workspace_dir, capture_output=True, text=True, check=True)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"Warning: git diff failed: {e}", file=sys.stderr)
        return None
    return proc.stdout


def _hunk_added_lines(hunk_header: str) -> set[int]:
    """Parses a '@@ ... +start[,count] @@' hunk header into the set of added line numbers."""
    m = re.search(r"\+(\d+)(?:,(\d+))?", hunk_header)
    if not m:
        return set()
    start = int(m.group(1))
    count = int(m.group(2)) if m.group(2) else 1
    return set(range(start, start + count))


def _parse_diff_output(diff_text: str) -> dict[str, set[int]]:
    """Parses unified diff text into a map of file path -> modified line numbers."""
    diff_lines_by_file: dict[str, set[int]] = {}
    current_file: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = os.path.normpath(line[6:])
            _ = diff_lines_by_file.setdefault(current_file, set())
        elif line.startswith("@@ ") and current_file:
            diff_lines_by_file[current_file].update(_hunk_added_lines(line))
    return diff_lines_by_file


def get_git_diff_hunks(workspace_dir: str, base_ref: str | None) -> dict[str, set[int]]:
    """Returns map of relative file paths to modified line numbers from git diff."""
    diff_text = _run_git_diff(workspace_dir, base_ref)
    if diff_text is None:
        return {}
    return _parse_diff_output(diff_text)


def analyze_file(
    file_path: str,
    cov_db: CoverageDatabase,
    threshold: float,
    changed_lines: set[int] | None = None,
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
) -> list[FunctionMetric]:
    """Analyzes a single source file and returns metrics with recommendations."""
    ext = Path(file_path).suffix.lower()
    language = SUPPORTED_EXTENSIONS.get(ext)
    if not language:
        return []

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
        return []

    functions = extract_functions(file_path, content, language)
    metrics: list[FunctionMetric] = []

    for fn in functions:
        if changed_lines is not None:
            fn_lines = set(range(fn.line_start, fn.line_end + 1))
            if not fn_lines.intersection(changed_lines):
                continue

        cc = count_decision_points(fn.body, fn.language)
        cov, uncovered_lines = cov_db.get_function_coverage(file_path, fn.line_start, fn.line_end, fn.name)
        crap = calculate_crap(cc, cov)
        is_over = crap > threshold or cc > max_complexity

        status = "HIGH RISK" if is_over else "OK"
        cov_pct = 0.0 if cov is None else round(cov * 100, 1)

        recommendation = generate_recommendation(
            cc=cc,
            cov_pct=cov_pct,
            crap=crap,
            threshold=threshold,
            uncovered_lines=uncovered_lines,
            language=fn.language,
            func_name=fn.name,
            file_path=file_path,
            line_start=fn.line_start,
            line_end=fn.line_end,
            max_complexity=max_complexity,
        )

        metrics.append(FunctionMetric(
            file_path=file_path,
            function_name=fn.name,
            language=fn.language,
            line_start=fn.line_start,
            line_end=fn.line_end,
            complexity=cc,
            coverage=cov_pct,
            crap_score=crap,
            is_over_threshold=is_over,
            status=status,
            recommendation=recommendation
        ))

    return metrics


def _render_report_header(metrics: list["FunctionMetric"], threshold: float, scope_label: str, over_count: int) -> list[str]:
    """Renders the report title and summary metadata block."""
    return [
        "### 📊 CRAP Metric Report\n",
        f"- **Generated:** `{datetime.now().strftime('%d-%m-%Y %H:%M:%S')}`",  # noqa: DTZ005 - local time is intended for human-readable reports
        f"- **Scope:** `{scope_label}`",
        f"- **Configured Threshold:** `{threshold}`",
        f"- **Total Functions Analyzed:** `{len(metrics)}`",
        f"- **High-Risk Anti-Patterns (> {threshold}):** `{over_count}`\n",
    ]


def _render_high_risk_table(over_threshold: list["FunctionMetric"]) -> list[str]:
    """Renders the high-risk anti-pattern table."""
    out = [
        "#### ⚠️ High-Risk Anti-Patterns (Requires Action)\n",
        "| File | Function | Lines | CC | Coverage | Target Cov | CRAP Score | Status |",
        "|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for m in over_threshold:
        tgt = f"{m.recommendation.target_coverage_percent}%" if m.recommendation.target_coverage_percent is not None else "N/A (CC>30)"
        out.append(
            f"| `{m.file_path}` | `{m.function_name}` | `{m.line_start}-{m.line_end}` | "
            + f"`{m.complexity}` | `{m.coverage}%` | `{tgt}` | **`{m.crap_score}`** | ⚠️ HIGH RISK |"
        )
    out.append("")
    return out


def _render_within_threshold_table(within_threshold: list["FunctionMetric"]) -> list[str]:
    """Renders the within-threshold table (capped at 15 rows)."""
    out = [
        "#### ✅ Within Threshold\n",
        "| File | Function | Lines | CC | Coverage | CRAP Score | Status |",
        "|:---|:---|:---:|:---:|:---:|:---:|:---:|",
    ]
    for m in within_threshold[:15]:
        out.append(
            f"| `{m.file_path}` | `{m.function_name}` | `{m.line_start}-{m.line_end}` | "
            + f"`{m.complexity}` | `{m.coverage}%` | `{m.crap_score}` | ✅ OK |"
        )
    if len(within_threshold) > 15:
        out.append(f"\n*(... and {len(within_threshold) - 15} more functions within threshold)*")
    out.append("")
    return out


def _render_directive_block(idx: int, m: "FunctionMetric", threshold: float) -> list[str]:
    """Renders one prescriptive action + AI agent directive block for a metric."""
    rec = m.recommendation
    badge = "🔴 MANDATORY REFACTOR" if rec.category == "MANDATORY_REFACTOR" else "🟠 ADD UNIT TESTS"
    out = [
        f"#### {idx}. `{m.function_name}` in `{m.file_path}:{m.line_start}-{m.line_end}` — {badge}",
        f"> **Diagnosis:** {rec.summary}\n",
        f"- **Complexity:** `{m.complexity}` | **Current Coverage:** `{m.coverage}%` | **CRAP:** `{m.crap_score}`",
    ]
    if rec.target_coverage_percent is not None:
        out.append(f"- **Target Coverage:** **`{rec.target_coverage_percent}%`** *(Minimum needed to bring CRAP <= {threshold})*")
    if rec.uncovered_lines:
        out.append(f"- **Uncovered Lines:** `{rec.uncovered_lines_display}`")
    out.append("- **Recommended Actions:**")
    out.extend(f"  * {action}" for action in rec.actions)
    out.append("\n##### 🤖 AI Agent Directive (Prompt to Execute Fix)")
    out.append("```text")
    out.append(rec.ai_agent_directive)
    out.append("```\n")
    return out


def _render_action_plan(over_threshold: list["FunctionMetric"], threshold: float) -> list[str]:
    """Renders the prescriptive action plan section for the top over-threshold functions."""
    out = ["### 🎯 Prescriptive Action Plan & AI Agent Directives\n"]
    out.append(
        "> [!TIP]\n"
        + "> **For AI Agents:** Each action item below includes a ready-to-execute "
        + "directive block that can be directly consumed to refactor code or generate tests.\n"
    )
    for idx, m in enumerate(over_threshold[:5], 1):
        out.extend(_render_directive_block(idx, m, threshold))
    return out


def _partition_metrics(
    metrics: list["FunctionMetric"],
) -> tuple[list["FunctionMetric"], list["FunctionMetric"]]:
    """Splits metrics into (over_threshold, within_threshold), each sorted by CRAP desc."""
    over = sorted((m for m in metrics if m.is_over_threshold), key=lambda x: x.crap_score, reverse=True)
    within = sorted((m for m in metrics if not m.is_over_threshold), key=lambda x: x.crap_score, reverse=True)
    return over, within


def _render_report_body(
    over_threshold: list["FunctionMetric"],
    within_threshold: list["FunctionMetric"],
    threshold: float,
) -> list[str]:
    """Assembles the table sections and action plan (or the all-clear message)."""
    out: list[str] = []
    if over_threshold:
        out.extend(_render_high_risk_table(over_threshold))
    if within_threshold:
        out.extend(_render_within_threshold_table(within_threshold))
    if over_threshold:
        out.extend(_render_action_plan(over_threshold, threshold))
    else:
        out.append("✨ **All analyzed functions are within acceptable risk parameters.**")
    return out


def format_markdown(metrics: list["FunctionMetric"], threshold: float, scope_label: str) -> str:
    """Renders formatted GitHub-style markdown report with action recommendations and AI agent directives."""
    over_threshold, within_threshold = _partition_metrics(metrics)
    out = _render_report_header(metrics, threshold, scope_label, len(over_threshold))
    out.extend(_render_report_body(over_threshold, within_threshold, threshold))
    return "\n".join(out)


def get_default_report_filename(base_dir: str = ".") -> str:
    """Generates an archived report path: {base_dir}/reports/{dd-mm-yyyy-hh-mm-ss}-report.md."""
    timestamp = datetime.now().strftime("%d-%m-%Y-%H-%M-%S")  # noqa: DTZ005 - local time is intended for report filenames
    return os.path.join(base_dir, "reports", f"{timestamp}-report.md")


def build_arg_parser() -> argparse.ArgumentParser:
    """Constructs the CLI argument parser for the analyzer."""
    parser = argparse.ArgumentParser(description="Calculate CRAP metrics and recommend actions.")
    _ = parser.add_argument("--path", "-p", default=".", help="File or directory to analyze.")
    _ = parser.add_argument("--diff", action="store_true", help="Analyze only git-modified files and lines.")
    _ = parser.add_argument("--base", default=None, help="Base commit/branch for git diff (e.g. main, HEAD~1).")
    _ = parser.add_argument("--lcov", help="Path to LCOV coverage file.")
    _ = parser.add_argument("--llvm-binary", help="Path to instrumented binary to generate LCOV via llvm-cov.")
    _ = parser.add_argument("--llvm-profdata", help="Optional path to .profdata / .profraw file for llvm-cov.")
    _ = parser.add_argument("--threshold", type=float, default=30.0, help="CRAP threshold (default: 30.0).")
    _ = parser.add_argument("--format", choices=["markdown", "json", "table"], default="markdown", help="Output format.")
    _ = parser.add_argument("--save-report", nargs="?", const="auto", default=None,
                            help="Save report to {dd-mm-yyyy-hh-mm-ss}-report.md (or specified path).")
    _ = parser.add_argument("--strict", action="store_true", help="Exit with code 1 if any functions exceed threshold.")
    _ = parser.add_argument("--max-complexity", type=int, default=DEFAULT_MAX_COMPLEXITY,
                            help=f"Max Cyclomatic Complexity per function before flagging for decomposition (default: {DEFAULT_MAX_COMPLEXITY}, per Clean Code guidance).")
    return parser


@dataclass
class CliArgs:
    """Strongly-typed view of parsed CLI arguments (avoids argparse.Namespace's Any typing)."""
    path: str
    diff: bool
    base: str | None
    lcov: str | None
    llvm_binary: str | None
    llvm_profdata: str | None
    threshold: float
    format: str
    save_report: str | None
    strict: bool
    max_complexity: int


def parse_cli_args(argv: list[str] | None = None) -> CliArgs:
    """Parses CLI args into a typed CliArgs instance."""
    ns = build_arg_parser().parse_args(argv)
    return CliArgs(
        path=cast("str", ns.path),
        diff=cast("bool", ns.diff),
        base=cast("str | None", ns.base),
        lcov=cast("str | None", ns.lcov),
        llvm_binary=cast("str | None", ns.llvm_binary),
        llvm_profdata=cast("str | None", ns.llvm_profdata),
        threshold=cast("float", ns.threshold),
        format=cast("str", ns.format),
        save_report=cast("str | None", ns.save_report),
        strict=cast("bool", ns.strict),
        max_complexity=cast("int", ns.max_complexity),
    )


def build_coverage_database(args: CliArgs, workspace_dir: str) -> tuple["CoverageDatabase", str | None]:
    """Resolves coverage source. Returns (cov_db, temp_lcov_to_clean)."""
    if args.lcov:
        cov_db = CoverageDatabase()
        cov_db.load_auto(args.lcov)
        return cov_db, None

    if args.llvm_binary:
        cov_db = CoverageDatabase()
        generated_lcov = generate_llvm_lcov_in_memory(args.llvm_binary, args.llvm_profdata, workspace_dir)
        if not generated_lcov:
            return cov_db, None
        cov_db.load_lcov(generated_lcov)
        return cov_db, generated_lcov

    return auto_discover_coverage(workspace_dir), None


def _is_ignored_root(root: str) -> bool:
    """True if any path segment of root is an ignored directory name."""
    return any(part in IGNORED_DIR_NAMES for part in root.split(os.sep))


def _supported_files_in(root: str, files: list[str]) -> list[str]:
    """Returns full paths of supported-extension files within a directory."""
    return [
        os.path.join(root, f)
        for f in files
        if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def collect_target_files(path: str) -> list[str]:
    """Returns the list of supported files to analyze for a file or directory path."""
    if os.path.isfile(path):
        return [path]

    target_files: list[str] = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIR_NAMES]
        if _is_ignored_root(root):
            continue
        target_files.extend(_supported_files_in(root, files))
    return target_files


def compute_all_metrics(
    target_files: list[str],
    cov_db: CoverageDatabase,
    threshold: float,
    diff_hunks: dict[str, set[int]] | None,
    workspace_dir: str,
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
) -> list["FunctionMetric"]:
    """Analyzes each target file, honoring git diff hunk filtering when present."""
    all_metrics: list[FunctionMetric] = []
    for file_path in target_files:
        changed_lines: set[int] | None = None
        if diff_hunks is not None:
            norm_rel = os.path.normpath(os.path.relpath(file_path, workspace_dir))
            if norm_rel not in diff_hunks:
                continue
            changed_lines = diff_hunks[norm_rel]

        all_metrics.extend(analyze_file(file_path, cov_db, threshold, changed_lines, max_complexity))
    return all_metrics


def _render_json(all_metrics: list["FunctionMetric"], threshold: float, scope_label: str) -> str:
    data = {
        "scope": scope_label,
        "timestamp": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),  # noqa: DTZ005 - local time is intended for human-readable reports
        "threshold": threshold,
        "total_analyzed": len(all_metrics),
        "over_threshold_count": sum(1 for m in all_metrics if m.is_over_threshold),
        "metrics": [asdict(m) for m in all_metrics],
    }
    return json.dumps(data, indent=2)


def _render_table(all_metrics: list["FunctionMetric"], threshold: float, scope_label: str) -> str:
    _ = scope_label  # table format does not display scope; kept for renderer signature uniformity
    lines = [f"\n--- CRAP Metric Report (Threshold: {threshold}) ---"]
    for m in all_metrics:
        flag = "[OVER]" if m.is_over_threshold else "[OK]  "
        tgt = (f"(Target Cov: {m.recommendation.target_coverage_percent}%)"
               if m.recommendation.target_coverage_percent is not None else "(Must Refactor)")
        lines.append(
            f"{flag} {m.file_path}:{m.line_start}-{m.line_end} | {m.function_name} | "
            + f"CC: {m.complexity} | Cov: {m.coverage}% | CRAP: {m.crap_score} | "
            + f"{m.recommendation.category} {tgt}"
        )
    return "\n".join(lines)


def render_report(fmt: str, all_metrics: list["FunctionMetric"], threshold: float, scope_label: str) -> str:
    """Renders the metrics report using the requested output format."""
    renderers = {
        "json": _render_json,
        "markdown": format_markdown,
        "table": _render_table,
    }
    renderer = renderers.get(fmt, _render_table)
    return renderer(all_metrics, threshold, scope_label)


def resolve_report_filepath(save_report: str) -> tuple[str, str | None]:
    """Resolves (report_path, latest_symlink_dir).

    For auto/directory targets, reports are archived under `<dir>/reports/` and the
    second element is `<dir>` (where a `latest.md` symlink should be maintained).
    For an explicit file path, the second element is None (no archiving/symlink).
    """
    if save_report == "auto":
        return get_default_report_filename("."), "."
    if os.path.isdir(save_report):
        return get_default_report_filename(save_report), save_report
    return save_report, None


def _update_latest_symlink(report_filepath: str, base_dir: str) -> str:
    """Points `<base_dir>/latest.md` at the freshly written report. Returns the link path."""
    latest = os.path.join(base_dir, "latest.md")
    # Link relative to base_dir so the symlink stays valid if the tree is moved.
    target = os.path.relpath(report_filepath, base_dir)
    if os.path.islink(latest) or os.path.exists(latest):
        os.unlink(latest)
    os.symlink(target, latest)
    return latest


def save_report_to_disk(
    args: CliArgs,
    report_output: str,
    all_metrics: list["FunctionMetric"],
    scope_label: str,
) -> None:
    """Writes the report to disk (archiving under reports/) and updates the latest.md symlink."""
    save_report = args.save_report if args.save_report is not None else "auto"
    report_filepath, latest_dir = resolve_report_filepath(save_report)

    file_content = report_output
    if args.format != "markdown" and report_filepath.endswith(".md"):
        file_content = format_markdown(all_metrics, args.threshold, scope_label)

    os.makedirs(os.path.dirname(os.path.abspath(report_filepath)), exist_ok=True)
    with open(report_filepath, "w", encoding="utf-8") as rf:
        _ = rf.write(file_content)
    print(f"\n📄 Saved report to: {report_filepath}")

    if latest_dir is not None:
        latest = _update_latest_symlink(report_filepath, latest_dir)
        print(f"🔗 Updated latest report symlink: {latest}")


def _enforce_strict(args: CliArgs, all_metrics: list["FunctionMetric"]) -> None:
    """In strict mode, exits with code 1 if any function exceeds the threshold."""
    if args.strict and any(m.is_over_threshold for m in all_metrics):
        sys.exit(1)


def _run_analysis(args: CliArgs, cov_db: "CoverageDatabase", workspace_dir: str) -> None:
    """Runs the analysis pipeline: collect, compute, render, save, and strict-exit."""
    diff_hunks = get_git_diff_hunks(workspace_dir, args.base) if args.diff else None

    target_files = collect_target_files(args.path)
    all_metrics = compute_all_metrics(
        target_files, cov_db, args.threshold, diff_hunks, workspace_dir, args.max_complexity
    )

    scope_label = "Git Diff" if args.diff else args.path
    report_output = render_report(args.format, all_metrics, args.threshold, scope_label)
    print(report_output)

    if args.save_report:
        save_report_to_disk(args, report_output, all_metrics, scope_label)

    _enforce_strict(args, all_metrics)


def main():
    args = parse_cli_args()
    workspace_dir = os.path.abspath(args.path if os.path.isdir(args.path) else os.path.dirname(args.path) or ".")

    cov_db, temp_lcov_to_clean = build_coverage_database(args, workspace_dir)
    try:
        _run_analysis(args, cov_db, workspace_dir)
    finally:
        if temp_lcov_to_clean and os.path.exists(temp_lcov_to_clean):
            os.unlink(temp_lcov_to_clean)


if __name__ == "__main__":
    main()
