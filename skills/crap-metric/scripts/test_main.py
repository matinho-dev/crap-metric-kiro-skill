#!/usr/bin/env python3
"""
Unit tests for `main` and its extracted helpers in analyze.py.

These tests exercise `main()` end-to-end across every output format, the
save-report path, strict mode, and both file and directory inputs. They also
directly test the helper functions extracted during the CC refactor.

Running this module as a script (``python3 test_main.py``) traces execution of
analyze.py via the stdlib ``trace`` module and writes an LCOV file to
``coverage/main_coverage.lcov`` so the CRAP analyzer can measure real coverage:

    python3 test_main.py                         # run tests + emit LCOV
    python3 -m pytest test_main.py               # run tests only (if pytest present)
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Generator
from typing import cast, override
from unittest import mock

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze

# Tests intentionally exercise a module-private helper; bind it once via a typed
# alias so the private-usage suppression is confined to this single line.
from analyze import (
    _find_matching_brace as find_matching_brace,  # pyright: ignore[reportPrivateUsage]
)
from analyze import (
    _update_latest_symlink as update_latest_symlink,  # pyright: ignore[reportPrivateUsage]
)

# A tiny, self-contained sample source file the analyzer fully supports (python).
SAMPLE_SOURCE = (
    "def simple(a, b):\n"
    "    if a > b:\n"
    "        return a\n"
    "    return b\n"
)


@contextlib.contextmanager
def _argv(args: list[str]) -> Generator[None, None, None]:
    old = sys.argv
    sys.argv = ["analyze.py"] + args
    try:
        yield
    finally:
        sys.argv = old


def _run_main(args: list[str]) -> tuple[str, int | None]:
    """Runs analyze.main() with the given CLI args, capturing stdout.

    Returns (stdout_text, exit_code). exit_code is None unless SystemExit raised.
    """
    buf = io.StringIO()
    exit_code: int | None = None
    with _argv(args), contextlib.redirect_stdout(buf):
        try:
            analyze.main()
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 0
    return buf.getvalue(), exit_code


class TestHelpers(unittest.TestCase):
    def test_build_arg_parser_defaults(self):
        args = analyze.parse_cli_args(["--path", "x"])
        self.assertEqual(args.path, "x")
        self.assertEqual(args.threshold, 30.0)
        self.assertEqual(args.format, "markdown")
        self.assertIsNone(args.save_report)
        self.assertFalse(args.strict)
        self.assertFalse(args.diff)

    def test_build_arg_parser_save_report_const(self):
        args = analyze.parse_cli_args(["--save-report"])
        self.assertEqual(args.save_report, "auto")

    def test_collect_target_files_single_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.py")
            with open(p, "w") as f:
                _ = f.write(SAMPLE_SOURCE)
            self.assertEqual(analyze.collect_target_files(p), [p])

    def test_collect_target_files_directory_filters_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            keep = os.path.join(d, "a.py")
            skip = os.path.join(d, "notes.txt")
            for path, body in ((keep, SAMPLE_SOURCE), (skip, "hello")):
                with open(path, "w") as f:
                    _ = f.write(body)
            found = analyze.collect_target_files(d)
            self.assertIn(keep, found)
            self.assertNotIn(skip, found)

    def test_build_coverage_database_auto(self):
        with tempfile.TemporaryDirectory() as d:
            cov_db, temp = analyze.build_coverage_database(
                analyze.parse_cli_args(["--path", d]), d
            )
            self.assertIsInstance(cov_db, analyze.CoverageDatabase)
            self.assertIsNone(temp)

    def test_build_coverage_database_lcov(self):
        with tempfile.TemporaryDirectory() as d:
            lcov = os.path.join(d, "c.lcov")
            with open(lcov, "w") as f:
                _ = f.write("SF:foo.py\nDA:1,1\nend_of_record\n")
            args = analyze.parse_cli_args(["--path", d, "--lcov", lcov])
            cov_db, temp = analyze.build_coverage_database(args, d)
            self.assertIsInstance(cov_db, analyze.CoverageDatabase)
            self.assertIsNone(temp)

    def test_compute_all_metrics_diff_filter(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.py")
            with open(p, "w") as f:
                _ = f.write(SAMPLE_SOURCE)
            cov_db = analyze.CoverageDatabase()
            # Diff hunks that don't include the file -> filtered out.
            empty = analyze.compute_all_metrics([p], cov_db, 30.0, {"other.py": {1}}, d)
            self.assertEqual(empty, [])
            # No diff filtering -> metrics produced.
            allm = analyze.compute_all_metrics([p], cov_db, 30.0, None, d)
            self.assertTrue(len(allm) >= 1)

    def test_render_report_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.py")
            with open(p, "w") as f:
                _ = f.write(SAMPLE_SOURCE)
            metrics = analyze.compute_all_metrics([p], analyze.CoverageDatabase(), 30.0, None, d)
            js = analyze.render_report("json", metrics, 30.0, "scope")
            parsed_json = cast("dict[str, object]", json.loads(js))
            self.assertEqual(parsed_json["scope"], "scope")
            md = analyze.render_report("markdown", metrics, 30.0, "scope")
            self.assertIn("CRAP Metric Report", md)
            tbl = analyze.render_report("table", metrics, 30.0, "scope")
            self.assertIn("CRAP Metric Report", tbl)
            # Unknown format falls back to table renderer.
            fb = analyze.render_report("bogus", metrics, 30.0, "scope")
            self.assertIn("CRAP Metric Report", fb)

    def test_resolve_report_filepath(self):
        auto_path, auto_dir = analyze.resolve_report_filepath("auto")
        self.assertTrue(auto_path.endswith("-report.md"))
        self.assertIn("reports", auto_path.split(os.sep))
        self.assertEqual(auto_dir, ".")

        # Explicit file path: returned as-is, no symlink dir.
        self.assertEqual(analyze.resolve_report_filepath("out.md"), ("out.md", None))

        with tempfile.TemporaryDirectory() as d:
            dir_path, link_dir = analyze.resolve_report_filepath(d)
            self.assertTrue(dir_path.endswith("-report.md"))
            self.assertIn("reports", dir_path.split(os.sep))
            self.assertEqual(link_dir, d)

    def test_update_latest_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            reports = os.path.join(d, "reports")
            os.makedirs(reports)
            report = os.path.join(reports, "01-01-2026-00-00-00-report.md")
            with open(report, "w") as f:
                _ = f.write("# report")
            link = update_latest_symlink(report, d)
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.path.basename(link), "latest.md")
            # Resolves to the report content.
            with open(link) as f:
                self.assertEqual(f.read(), "# report")
            # Idempotent: a second call replaces the existing link.
            report2 = os.path.join(reports, "02-01-2026-00-00-00-report.md")
            with open(report2, "w") as f:
                _ = f.write("# newer")
            _ = update_latest_symlink(report2, d)
            with open(os.path.join(d, "latest.md")) as f:
                self.assertEqual(f.read(), "# newer")


_JACOCO_XML = """<?xml version="1.0"?>
<report name="demo">
  <package name="com/example">
    <sourcefile name="Foo.java">
      <line nr="10" ci="4" mi="0"/>
      <line nr="11" ci="0" mi="2"/>
      <line nr="12" ci="3" mi="0"/>
    </sourcefile>
  </package>
</report>
"""

_COBERTURA_XML = """<?xml version="1.0"?>
<coverage line-rate="0.5">
  <packages>
    <package name="pkg">
      <classes>
        <class filename="pkg/mod.py">
          <lines>
            <line number="10" hits="3"/>
            <line number="11" hits="0"/>
            <line number="12" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

_CLOVER_XML = """<?xml version="1.0"?>
<coverage generated="1">
  <project name="p">
    <file name="src/App.php" path="/abs/src/App.php">
      <line num="10" count="2" type="stmt"/>
      <line num="11" count="0" type="stmt"/>
      <line num="12" count="5" type="stmt"/>
    </file>
  </project>
</coverage>
"""


class TestXmlCoverage(unittest.TestCase):
    """Covers JaCoCo/Cobertura/Clover XML parsing, extension dispatch, and auto-discovery."""

    def _write(self, directory: str, name: str, body: str) -> str:
        path = os.path.join(directory, name)
        with open(path, "w") as f:
            _ = f.write(body)
        return path

    def test_jacoco_line_hits(self):
        cov_db = analyze.CoverageDatabase()
        with tempfile.TemporaryDirectory() as d:
            cov_db.load_xml(self._write(d, "jacoco.xml", _JACOCO_XML))
        frac, uncovered = cov_db.get_function_coverage("com/example/Foo.java", 10, 12, "any")
        self.assertAlmostEqual(cast("float", frac), 2 / 3)
        self.assertEqual(uncovered, [11])

    def test_cobertura_line_hits(self):
        cov_db = analyze.CoverageDatabase()
        with tempfile.TemporaryDirectory() as d:
            cov_db.load_xml(self._write(d, "coverage.xml", _COBERTURA_XML))
        frac, uncovered = cov_db.get_function_coverage("pkg/mod.py", 10, 12, "any")
        self.assertAlmostEqual(cast("float", frac), 2 / 3)
        self.assertEqual(uncovered, [11])

    def test_clover_line_hits(self):
        cov_db = analyze.CoverageDatabase()
        with tempfile.TemporaryDirectory() as d:
            cov_db.load_xml(self._write(d, "clover.xml", _CLOVER_XML))
        frac, uncovered = cov_db.get_function_coverage("/abs/src/App.php", 10, 12, "any")
        self.assertAlmostEqual(cast("float", frac), 2 / 3)
        self.assertEqual(uncovered, [11])

    def test_unrecognized_schema_is_ignored(self):
        cov_db = analyze.CoverageDatabase()
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "weird.xml", "<something><else/></something>")
            cov_db.load_xml(path)
        self.assertEqual(cov_db.file_line_hits, {})

    def test_missing_file_is_noop(self):
        cov_db = analyze.CoverageDatabase()
        cov_db.load_xml("/nonexistent/coverage.xml")
        self.assertEqual(cov_db.file_line_hits, {})

    def test_load_auto_dispatches_by_extension(self):
        with tempfile.TemporaryDirectory() as d:
            xml_db = analyze.CoverageDatabase()
            xml_db.load_auto(self._write(d, "jacoco.xml", _JACOCO_XML))
            self.assertTrue(xml_db.file_line_hits)

            lcov_db = analyze.CoverageDatabase()
            lcov_db.load_auto(self._write(d, "c.lcov", "SF:foo.py\nDA:1,1\nend_of_record\n"))
            self.assertIn(os.path.normpath("foo.py"), lcov_db.file_line_hits)

            go_db = analyze.CoverageDatabase()
            go_db.load_auto(self._write(d, "coverage.out", "mode: set\nfoo.go:1.1,2.2 1 1\n"))
            self.assertTrue(go_db.file_line_hits)

    def test_lcov_flag_accepts_xml(self):
        with tempfile.TemporaryDirectory() as d:
            xml_path = self._write(d, "jacoco.xml", _JACOCO_XML)
            args = analyze.parse_cli_args(["--path", d, "--lcov", xml_path])
            cov_db, temp = analyze.build_coverage_database(args, d)
            self.assertIsNone(temp)
            frac, _ = cov_db.get_function_coverage("com/example/Foo.java", 10, 12, "any")
            self.assertAlmostEqual(cast("float", frac), 2 / 3)

    def test_auto_discovery_finds_cobertura(self):
        with tempfile.TemporaryDirectory() as d:
            _ = self._write(d, "coverage.xml", _COBERTURA_XML)
            cov_db = analyze.auto_discover_coverage(d)
            frac, _ = cov_db.get_function_coverage("pkg/mod.py", 10, 12, "any")
            self.assertAlmostEqual(cast("float", frac), 2 / 3)

    def test_auto_discovery_merges_multiple_buckets(self):
        # A polyglot repo with a JaCoCo XML report AND a Go cover profile:
        # both must be discovered and merged into one database.
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "target", "site", "jacoco"))
            _ = self._write(
                d, os.path.join("target", "site", "jacoco", "jacoco.xml"), _JACOCO_XML
            )
            _ = self._write(d, "coverage.out", "mode: set\nsvc/main.go:5.1,7.2 1 1\n")
            cov_db = analyze.auto_discover_coverage(d)

            java_frac, _ = cov_db.get_function_coverage("com/example/Foo.java", 10, 12, "any")
            self.assertAlmostEqual(cast("float", java_frac), 2 / 3)
            go_frac, _ = cov_db.get_function_coverage("svc/main.go", 5, 7, "any")
            self.assertAlmostEqual(cast("float", go_frac), 1.0)

    def test_all_existing_collects_every_match(self):
        with tempfile.TemporaryDirectory() as d:
            _ = self._write(d, "coverage.xml", _COBERTURA_XML)
            _ = self._write(d, "clover.xml", _CLOVER_XML)
            cov_db = analyze.auto_discover_coverage(d)
            # Cobertura file and Clover file both loaded from the XML bucket.
            cob, _ = cov_db.get_function_coverage("pkg/mod.py", 10, 12, "any")
            clv, _ = cov_db.get_function_coverage("/abs/src/App.php", 10, 12, "any")
            self.assertAlmostEqual(cast("float", cob), 2 / 3)
            self.assertAlmostEqual(cast("float", clv), 2 / 3)

    def test_lcov_records_max_merge(self):
        # Loading two LCOV reports touching the same file+line keeps the MAX hit
        # count, so a covered hit is never clobbered by a later zero.
        cov_db = analyze.CoverageDatabase()
        with tempfile.TemporaryDirectory() as d:
            first = self._write(d, "a.lcov", "SF:x.py\nDA:1,0\nDA:2,5\nend_of_record\n")
            second = self._write(d, "b.lcov", "SF:x.py\nDA:1,3\nDA:2,0\nend_of_record\n")
            cov_db.load_lcov(first)
            cov_db.load_lcov(second)
        frac, uncovered = cov_db.get_function_coverage("x.py", 1, 2, "any")
        # Line 1 hit in second (3), line 2 hit in first (5) -> both covered.
        self.assertAlmostEqual(cast("float", frac), 1.0)
        self.assertEqual(uncovered, [])


class TestFindMatchingBrace(unittest.TestCase):
    """Covers analyze._find_matching_brace brace-matching, comment/string skipping, and edge cases."""

    def test_simple_balanced(self):
        # "{ }" — open at 0, close at 2 -> returns index past close (3).
        content = "{ }"
        self.assertEqual(find_matching_brace(content, 0), 3)

    def test_returns_index_after_closing_brace(self):
        content = "{abc}tail"
        idx = find_matching_brace(content, 0)
        self.assertEqual(content[idx:], "tail")

    def test_nested_braces(self):
        # Nested blocks must balance correctly.
        content = "{ a { b } c }"
        idx = find_matching_brace(content, 0)
        self.assertEqual(idx, len(content))
        self.assertEqual(content[idx - 1], "}")

    def test_deeply_nested(self):
        content = "{{{}}}"
        self.assertEqual(find_matching_brace(content, 0), len(content))

    def test_line_comment_with_brace_is_ignored(self):
        # A '}' inside a // comment must not close the block.
        content = "{ // }\n }"
        idx = find_matching_brace(content, 0)
        # The real closing brace is the last char.
        self.assertEqual(idx, len(content))

    def test_block_comment_with_braces_is_ignored(self):
        content = "{ /* } { } */ }"
        idx = find_matching_brace(content, 0)
        self.assertEqual(idx, len(content))

    def test_double_quoted_string_with_braces_ignored(self):
        content = '{ x = "} { }"; }'
        idx = find_matching_brace(content, 0)
        self.assertEqual(idx, len(content))

    def test_single_quoted_string_with_braces_ignored(self):
        content = "{ x = '}'; }"
        idx = find_matching_brace(content, 0)
        self.assertEqual(idx, len(content))

    def test_backtick_template_literal_with_braces_ignored(self):
        content = "{ x = `a}b{c`; }"
        idx = find_matching_brace(content, 0)
        self.assertEqual(idx, len(content))

    def test_escaped_quote_inside_string(self):
        # Escaped quote must not terminate the string early, so inner '}' stays ignored.
        content = '{ x = "a\\"} "; }'
        idx = find_matching_brace(content, 0)
        self.assertEqual(idx, len(content))

    def test_unbalanced_returns_end_of_content(self):
        # No closing brace -> scan reaches end and returns n.
        content = "{ a b c"
        self.assertEqual(find_matching_brace(content, 0), len(content))

    def test_brace_at_final_position(self):
        # Exercises the next_c boundary (curr + 1 == n) path.
        content = "{}"
        self.assertEqual(find_matching_brace(content, 0), 2)

    def test_open_index_not_zero(self):
        content = "prefix {inner} suffix"
        open_idx = content.index("{")
        idx = find_matching_brace(content, open_idx)
        self.assertEqual(content[idx:], " suffix")


class TestGetGitDiffHunks(unittest.TestCase):
    """Covers analyze.get_git_diff_hunks diff parsing, base_ref handling, and failure path."""

    @staticmethod
    def _completed(stdout: str) -> "subprocess.CompletedProcess[str]":
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout=stdout, stderr="")

    def test_parses_single_and_multi_line_hunks(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1 +1 @@\n"          # single line, no count -> line 1
            "@@ -10,0 +20,3 @@\n"    # count 3 -> lines 20,21,22
        )
        with mock.patch.object(subprocess, "run", return_value=self._completed(diff)):
            hunks = analyze.get_git_diff_hunks(".", None)
        key = os.path.normpath("foo.py")
        self.assertIn(key, hunks)
        self.assertEqual(hunks[key], {1, 20, 21, 22})

    def test_multiple_files(self):
        diff = (
            "+++ b/a.py\n"
            "@@ -0,0 +5,2 @@\n"
            "+++ b/b.py\n"
            "@@ -0,0 +100 @@\n"
        )
        with mock.patch.object(subprocess, "run", return_value=self._completed(diff)):
            hunks = analyze.get_git_diff_hunks(".", None)
        self.assertEqual(hunks[os.path.normpath("a.py")], {5, 6})
        self.assertEqual(hunks[os.path.normpath("b.py")], {100})

    def test_base_ref_appended_to_command(self):
        captured: dict[str, list[str]] = {}

        def fake_run(cmd: list[str], **_kwargs: object) -> "subprocess.CompletedProcess[str]":
            captured["cmd"] = cmd
            return self._completed("")

        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            _ = analyze.get_git_diff_hunks(".", "main")
        self.assertIn("main", captured["cmd"])

    def test_subprocess_failure_returns_empty(self):
        with mock.patch.object(
            subprocess, "run",
            side_effect=subprocess.CalledProcessError(1, ["git"]),
        ):
            hunks = analyze.get_git_diff_hunks(".", None)
        self.assertEqual(hunks, {})

    def test_empty_diff_returns_empty(self):
        with mock.patch.object(subprocess, "run", return_value=self._completed("")):
            hunks = analyze.get_git_diff_hunks(".", None)
        self.assertEqual(hunks, {})


class TestLoadGoCover(unittest.TestCase):
    """Covers analyze.CoverageDatabase.load_go_cover parsing and edge cases."""

    def _write(self, body: str) -> str:
        d = tempfile.mkdtemp()
        p = os.path.join(d, "cover.out")
        with open(p, "w") as f:
            _ = f.write(body)
        return p

    def test_missing_file_is_noop(self):
        cov = analyze.CoverageDatabase()
        cov.load_go_cover(os.path.join(tempfile.mkdtemp(), "nope.out"))
        self.assertEqual(cov.file_line_hits, {})

    def test_parses_spans_and_skips_mode_line(self):
        body = "mode: set\nfoo.go:3.10,5.2 1 2\n"
        cov = analyze.CoverageDatabase()
        cov.load_go_cover(self._write(body))
        key = os.path.normpath("foo.go")
        self.assertIn(key, cov.file_line_hits)
        self.assertEqual(cov.file_line_hits[key][3], 2)
        self.assertEqual(cov.file_line_hits[key][5], 2)

    def test_max_merge_of_overlapping_spans(self):
        body = "mode: count\nbar.go:4.1,4.9 1 1\nbar.go:4.1,4.9 1 7\n"
        cov = analyze.CoverageDatabase()
        cov.load_go_cover(self._write(body))
        key = os.path.normpath("bar.go")
        self.assertEqual(cov.file_line_hits[key][4], 7)

    def test_malformed_line_is_tolerated(self):
        body = "mode: set\nbaz.go:1.0,2.0 1 notanint\n"
        cov = analyze.CoverageDatabase()
        cov.load_go_cover(self._write(body))  # should warn, not raise
        self.assertNotIn(os.path.normpath("baz.go"), cov.file_line_hits)

    def test_short_line_ignored(self):
        body = "mode: set\nincomplete line\n"
        cov = analyze.CoverageDatabase()
        cov.load_go_cover(self._write(body))
        self.assertEqual(cov.file_line_hits, {})


class TestCountDecisionPoints(unittest.TestCase):
    """Covers analyze.count_decision_points base case, common patterns, and per-language branches."""

    def test_base_case_no_branches(self):
        self.assertEqual(analyze.count_decision_points("return a + b", "python"), 1)

    def test_common_patterns_counted(self):
        # if + for + while + && + || => base 1 + 5 = 6 (language-agnostic commons)
        body = "if (x) { for(;;){} while(y){} } a && b || c"
        self.assertEqual(analyze.count_decision_points(body, "java"), 6)

    def test_python_specific_keywords(self):
        # base 1 + if(1) + elif(1) + except(1) + and(1) + or(1) = 6
        body = "if a:\n    pass\nelif b and c or d:\n    pass\nexcept X:\n    pass"
        self.assertEqual(analyze.count_decision_points(body, "python"), 6)

    def test_typescript_specific_operators(self):
        # base 1 + ?? (1) + ternary ? (1) = 3
        body = "const v = a ?? b; const w = cond ? x : y;"
        self.assertEqual(analyze.count_decision_points(body, "typescript"), 3)

    def test_php_specific_keywords(self):
        # base 1 + if(1) + elseif(1) + foreach(1) + and(1) + or(1) = 6
        body = "if ($a) {} elseif ($b) {} foreach ($x as $y) {} $c and $d or $e;"
        self.assertEqual(analyze.count_decision_points(body, "php"), 6)

    def test_native_ternary_branch(self):
        # base 1 + ternary(1) = 2 for cpp
        body = "int z = cond ? 1 : 2;"
        self.assertEqual(analyze.count_decision_points(body, "cpp"), 2)

    def test_comments_and_strings_excluded(self):
        # 'if' inside a string/comment must not count toward complexity.
        body = 'x = "if for while"  # if for while\nreturn x'
        self.assertEqual(analyze.count_decision_points(body, "python"), 1)

    def test_javascript_compound_logical_assignments(self):
        # Patterns overlap by design: '&&=' also matches '&&', '||=' matches '||',
        # and '??=' matches '??'. base 1 + &&(1) + ||(1) + ??(2) + &&=(1) + ||=(1) + ??=(1) = 8
        body = "a &&= b; c ||= d; e ??= f; g = h ?? i;"
        self.assertEqual(analyze.count_decision_points(body, "javascript"), 8)

    def test_vue_uses_typescript_branch(self):
        # vue routes through the ts/js/vue branch: base 1 + ??(1) + ternary(1) = 3
        body = "const v = a ?? b; const w = c ? d : e;"
        self.assertEqual(analyze.count_decision_points(body, "vue"), 3)

    def test_switch_case_and_catch(self):
        # base 1 + case(2) + catch(1) = 4
        body = "switch(x){ case 1: break; case 2: break; } try{}catch(e){}"
        self.assertEqual(analyze.count_decision_points(body, "java"), 4)


def _make_metric(
    *,
    name: str = "fn",
    cc: int = 5,
    coverage: float = 0.0,
    crap: float = 50.0,
    over: bool = True,
    category: str = "ADD_UNIT_TESTS",
    target_cov: float | None = 40.0,
    uncovered: list[int] | None = None,
) -> "analyze.FunctionMetric":
    """Builds a FunctionMetric with a controllable recommendation for renderer tests."""
    uncovered = uncovered if uncovered is not None else []
    rec = analyze.FunctionRecommendation(
        category=category,
        severity="HIGH",
        target_coverage_percent=target_cov,
        uncovered_lines=uncovered,
        uncovered_lines_display=analyze.format_line_ranges(uncovered),
        summary=f"summary for {name}",
        actions=["do a thing", "do another thing"],
        ai_agent_directive=f"TASK: fix {name}",
    )
    return analyze.FunctionMetric(
        file_path="x.py", function_name=name, language="python",
        line_start=1, line_end=10, complexity=cc, coverage=coverage,
        crap_score=crap, is_over_threshold=over, status="HIGH RISK" if over else "OK",
        recommendation=rec,
    )


class TestFormatMarkdown(unittest.TestCase):
    """Covers analyze.format_markdown across over/within-threshold, badge, and branch paths."""

    def test_all_healthy_else_branch(self):
        metrics = [_make_metric(name="ok", crap=10.0, over=False, category="HEALTHY", target_cov=None)]
        md = analyze.format_markdown(metrics, 30.0, "scope")
        self.assertIn("All analyzed functions are within acceptable risk parameters", md)
        self.assertIn("Within Threshold", md)

    def test_add_unit_tests_badge_with_target_and_uncovered(self):
        m = _make_metric(name="needstests", category="ADD_UNIT_TESTS", target_cov=40.0, uncovered=[3, 4, 5])
        md = analyze.format_markdown([m], 30.0, "scope")
        self.assertIn("🟠 ADD UNIT TESTS", md)
        self.assertIn("Target Coverage", md)
        self.assertIn("Uncovered Lines", md)
        self.assertIn("Prescriptive Action Plan", md)

    def test_mandatory_refactor_badge_no_target(self):
        m = _make_metric(name="toobig", cc=35, crap=1260.0, category="MANDATORY_REFACTOR", target_cov=None)
        md = analyze.format_markdown([m], 30.0, "scope")
        self.assertIn("🔴 MANDATORY REFACTOR", md)
        self.assertIn("N/A (CC>30)", md)

    def test_within_threshold_truncation_over_15(self):
        metrics = [
            _make_metric(name=f"ok{i}", crap=float(i), over=False, category="HEALTHY", target_cov=None)
            for i in range(20)
        ]
        md = analyze.format_markdown(metrics, 30.0, "scope")
        self.assertIn("and 5 more functions within threshold", md)

    def test_mixed_over_and_within(self):
        metrics = [
            _make_metric(name="bad", over=True, crap=90.0),
            _make_metric(name="good", over=False, crap=10.0, category="HEALTHY", target_cov=None),
        ]
        md = analyze.format_markdown(metrics, 30.0, "scope")
        self.assertIn("High-Risk Anti-Patterns", md)
        self.assertIn("Within Threshold", md)


class TestMaxComplexityPolicy(unittest.TestCase):
    """Covers the Clean Code CC<=6 policy in generate_recommendation and analyze_file gating."""

    def test_default_max_complexity_is_six(self):
        self.assertEqual(analyze.DEFAULT_MAX_COMPLEXITY, 6)

    def test_cc_over_max_but_crap_ok_flags_reduce_complexity(self):
        rec = analyze.generate_recommendation(
            cc=7, cov_pct=100.0, crap=7.0, threshold=30.0,
            uncovered_lines=[], language="python", func_name="f",
        )
        self.assertEqual(rec.category, "REDUCE_COMPLEXITY")
        self.assertIn("Reduce the Cyclomatic Complexity", rec.ai_agent_directive)

    def test_cc_at_max_is_healthy(self):
        rec = analyze.generate_recommendation(
            cc=6, cov_pct=100.0, crap=6.0, threshold=30.0,
            uncovered_lines=[], language="python", func_name="f",
        )
        self.assertEqual(rec.category, "HEALTHY")

    def test_custom_max_complexity_relaxes_gate(self):
        rec = analyze.generate_recommendation(
            cc=9, cov_pct=100.0, crap=9.0, threshold=30.0,
            uncovered_lines=[], language="python", func_name="f", max_complexity=10,
        )
        self.assertEqual(rec.category, "HEALTHY")

    def test_analyze_file_flags_high_cc_as_over_threshold(self):
        # A CC>6 function is marked over-threshold under default policy. With no coverage its
        # CRAP also exceeds 30, so it surfaces as ADD_UNIT_TESTS (CRAP precedence); the point
        # is that it is flagged (is_over_threshold) rather than passing silently.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cx.py")
            body = (
                "def busy(a, b, c):\n"
                "    if a and b or c:\n"
                "        for i in a:\n"
                "            while i:\n"
                "                pass\n"
                "    elif b:\n"
                "        pass\n"
                "    try:\n"
                "        pass\n"
                "    except ValueError:\n"
                "        pass\n"
            )
            with open(p, "w") as f:
                _ = f.write(body)
            metrics = analyze.analyze_file(p, analyze.CoverageDatabase(), 30.0, None)
            busy = next(m for m in metrics if m.function_name == "busy")
            self.assertGreater(busy.complexity, 6)
            self.assertTrue(busy.is_over_threshold)

    def test_analyze_file_reduce_complexity_when_fully_covered(self):
        # With full coverage the CRAP stays low, so a CC>6 function is flagged REDUCE_COMPLEXITY.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cx.py")
            body = (
                "def busy(a, b, c):\n"
                "    if a and b or c:\n"
                "        for i in a:\n"
                "            while i:\n"
                "                pass\n"
                "    elif b:\n"
                "        pass\n"
                "    try:\n"
                "        pass\n"
                "    except ValueError:\n"
                "        pass\n"
            )
            with open(p, "w") as f:
                _ = f.write(body)
            # Fabricate 100% line coverage for the file so CRAP is low.
            cov = analyze.CoverageDatabase()
            norm = os.path.normpath(p)
            cov.file_line_hits[norm] = {ln: 1 for ln in range(1, len(body.splitlines()) + 1)}
            metrics = analyze.analyze_file(p, cov, 30.0, None)
            busy = next(m for m in metrics if m.function_name == "busy")
            self.assertGreater(busy.complexity, 6)
            self.assertTrue(busy.is_over_threshold)
            self.assertEqual(busy.recommendation.category, "REDUCE_COMPLEXITY")


class TestMainEndToEnd(unittest.TestCase):
    tmp: str = ""
    src: str = ""

    @override
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "sample.py")
        with open(self.src, "w") as f:
            _ = f.write(SAMPLE_SOURCE)

    @override
    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_main_table_file(self):
        out, code = _run_main(["--path", self.src, "--format", "table"])
        self.assertIn("CRAP Metric Report", out)
        self.assertIsNone(code)

    def test_main_json_file(self):
        out, _ = _run_main(["--path", self.src, "--format", "json"])
        data = cast("dict[str, object]", json.loads(out))
        self.assertEqual(data["scope"], self.src)
        self.assertGreaterEqual(cast("int", data["total_analyzed"]), 1)

    def test_main_markdown_directory(self):
        out, _ = _run_main(["--path", self.tmp, "--format", "markdown"])
        self.assertIn("CRAP Metric Report", out)

    def test_main_save_report_json_to_dir_writes_md(self):
        out_dir = os.path.join(self.tmp, "out")
        os.makedirs(out_dir, exist_ok=True)
        out, _ = _run_main(["--path", self.src, "--format", "json", "--save-report", out_dir])
        self.assertIn("Saved report to", out)
        # Timestamped report is archived under <out_dir>/reports/.
        archived = [f for f in os.listdir(os.path.join(out_dir, "reports")) if f.endswith("-report.md")]
        self.assertEqual(len(archived), 1)
        # A latest.md symlink at <out_dir> points at the newest report.
        latest = os.path.join(out_dir, "latest.md")
        self.assertTrue(os.path.islink(latest))
        with open(latest) as f:
            self.assertIn("CRAP Metric Report", f.read())

    def test_main_save_report_explicit_path(self):
        target = os.path.join(self.tmp, "myreport.md")
        _ = _run_main(["--path", self.src, "--format", "markdown", "--save-report", target])
        self.assertTrue(os.path.exists(target))

    def test_main_strict_no_over_threshold_exits_clean(self):
        # sample.py has only a trivial function -> not over threshold -> no exit(1).
        _, code = _run_main(["--path", self.src, "--strict", "--format", "json"])
        self.assertIsNone(code)

    def test_main_strict_over_threshold_exits_one(self):
        # analyze.py itself has over-threshold functions -> strict exits 1.
        analyze_py = os.path.join(SCRIPT_DIR, "analyze.py")
        _, code = _run_main(["--path", analyze_py, "--strict", "--format", "json"])
        self.assertEqual(code, 1)


def _exercise_all() -> unittest.TestResult:
    """Run every test across all test modules in-process (for trace-based LCOV generation)."""
    import test_generate_llvm_lcov

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    suite.addTests(loader.loadTestsFromModule(test_generate_llvm_lcov))
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


def _source_files() -> dict[str, str]:
    """Maps normalized source paths to their real paths for coverage recording."""
    paths = [
        os.path.join(SCRIPT_DIR, "analyze.py"),
        os.path.join(SCRIPT_DIR, "generate_llvm_lcov.py"),
    ]
    return {os.path.normpath(p): p for p in paths}


def _aggregate_hits(counts: dict[tuple[str, int], int], norm_targets: dict[str, str]) -> dict[str, dict[int, int]]:
    """Aggregates tracer line-hit counts into {normalized_source: {line: count}}."""
    hits_by_file: dict[str, dict[int, int]] = {norm: {} for norm in norm_targets}
    for (fname, line), count in counts.items():
        norm = os.path.normpath(fname)
        target = hits_by_file.get(norm)
        if target is not None:
            target[line] = count
    return hits_by_file


def _write_combined_lcov(lcov_file: str, norm_targets: dict[str, str], hits_by_file: dict[str, dict[int, int]]) -> None:
    """Writes one LCOV record per source file."""
    with open(lcov_file, "w") as f:
        for norm, real_path in norm_targets.items():
            with open(real_path, "r") as src:
                total_lines = len(src.readlines())
            target_hits = hits_by_file[norm]
            _ = f.write(f"SF:{real_path}\n")
            f.writelines(f"DA:{ln},{target_hits.get(ln, 0)}\n" for ln in range(1, total_lines + 1))
            _ = f.write("end_of_record\n")


def _generate_lcov() -> tuple[str, unittest.TestResult | None]:
    """Trace all scripts during the full test run; emit a combined multi-file LCOV."""
    import trace as trace_mod

    coverage_dir = os.path.join(SCRIPT_DIR, "coverage")
    os.makedirs(coverage_dir, exist_ok=True)
    lcov_file = os.path.join(coverage_dir, "main_coverage.lcov")
    norm_targets = _source_files()

    tracer = trace_mod.Trace(count=1, trace=0)
    result_holder: dict[str, unittest.TestResult] = {}

    def runner() -> None:
        result_holder["result"] = _exercise_all()

    tracer.runfunc(runner)

    hits_by_file = _aggregate_hits(tracer.results().counts, norm_targets)
    _write_combined_lcov(lcov_file, norm_targets, hits_by_file)

    total_traced = sum(len(h) for h in hits_by_file.values())
    print(f"\n[+] Wrote coverage LCOV to: {lcov_file}")
    print(f"[+] Traced {total_traced} executed lines across {len(norm_targets)} source file(s)")
    return lcov_file, result_holder.get("result")


if __name__ == "__main__":
    _lcov, result = _generate_lcov()
    ok = result is not None and result.wasSuccessful()
    sys.exit(0 if ok else 1)
