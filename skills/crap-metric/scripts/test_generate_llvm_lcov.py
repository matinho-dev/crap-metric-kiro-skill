#!/usr/bin/env python3
"""
Unit tests for `main` in generate_llvm_lcov.py.

`main` orchestrates tool resolution, profile discovery/merge, and LCOV export by
delegating to module-level helpers (`find_tool`, `discover_profiles`,
`merge_profraw`, `export_lcov`). These tests drive every branch by patching those
helpers and `sys.argv`, so no real llvm-cov / llvm-profdata binaries are required.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Generator
from typing import cast
from unittest import mock

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import generate_llvm_lcov as gll


@contextlib.contextmanager
def _argv(args: list[str]) -> Generator[None, None, None]:
    old = sys.argv
    sys.argv = ["generate_llvm_lcov.py"] + args
    try:
        yield
    finally:
        sys.argv = old


def _run_main(args: list[str]) -> int | None:
    """Runs gll.main() with argv, capturing stdout. Returns exit code or None."""
    buf = io.StringIO()
    code: int | None = None
    with _argv(args), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            gll.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
    return code


class TestGenerateLlvmLcovMain(unittest.TestCase):
    def test_llvm_cov_not_found_exits(self):
        with mock.patch.object(gll, "find_tool", return_value=None):
            code = _run_main(["--binary", "bin"])
        self.assertEqual(code, 1)

    def test_explicit_profdata_export_success(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-cov"), \
             mock.patch.object(gll, "export_lcov", return_value=True) as exp:
            code = _run_main(["--binary", "bin", "--profdata", "cov.profdata"])
        self.assertIsNone(code)
        exp.assert_called_once()
        self.assertEqual(cast("str", exp.call_args.kwargs["profdata"]), "cov.profdata")

    def test_explicit_profdata_export_failure_exits(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-cov"), \
             mock.patch.object(gll, "export_lcov", return_value=False):
            code = _run_main(["--binary", "bin", "--profdata", "cov.profdata"])
        self.assertEqual(code, 1)

    def test_output_stdout_passes_none_dest(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-cov"), \
             mock.patch.object(gll, "export_lcov", return_value=True) as exp:
            code = _run_main(["--binary", "bin", "--profdata", "cov.profdata", "--output", "-"])
        self.assertIsNone(code)
        self.assertIsNone(cast("str | None", exp.call_args.kwargs["output_file"]))

    def test_profraw_without_profdata_tool_exits(self):
        # find_tool returns llvm-cov but not llvm-profdata.
        def fake_find(tool: str) -> str | None:
            return "/usr/bin/llvm-cov" if tool == "llvm-cov" else None

        with mock.patch.object(gll, "find_tool", side_effect=fake_find):
            code = _run_main(["--binary", "bin", "--profraw", "a.profraw"])
        self.assertEqual(code, 1)

    def test_profraw_merge_success_then_export(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-tool"), \
             mock.patch.object(gll, "merge_profraw", return_value=True) as mrg, \
             mock.patch.object(gll, "export_lcov", return_value=True):
            code = _run_main(["--binary", "bin", "--profraw", "a.profraw", "b.profraw"])
        self.assertIsNone(code)
        mrg.assert_called_once()

    def test_profraw_merge_failure_exits(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-tool"), \
             mock.patch.object(gll, "merge_profraw", return_value=False):
            code = _run_main(["--binary", "bin", "--profraw", "a.profraw"])
        self.assertEqual(code, 1)

    def test_discover_profdata_used(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-cov"), \
             mock.patch.object(gll, "discover_profiles", return_value=([], ["found.profdata"])), \
             mock.patch.object(gll, "export_lcov", return_value=True) as exp:
            code = _run_main(["--binary", "bin"])
        self.assertIsNone(code)
        self.assertEqual(cast("str", exp.call_args.kwargs["profdata"]), "found.profdata")

    def test_discover_raw_then_merge(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-tool"), \
             mock.patch.object(gll, "discover_profiles", return_value=(["x.profraw"], [])), \
             mock.patch.object(gll, "merge_profraw", return_value=True) as mrg, \
             mock.patch.object(gll, "export_lcov", return_value=True):
            code = _run_main(["--binary", "bin"])
        self.assertIsNone(code)
        mrg.assert_called_once()

    def test_discover_nothing_exits(self):
        with mock.patch.object(gll, "find_tool", return_value="/usr/bin/llvm-cov"), \
             mock.patch.object(gll, "discover_profiles", return_value=([], [])):
            code = _run_main(["--binary", "bin"])
        self.assertEqual(code, 1)


class TestFindTool(unittest.TestCase):
    """Covers generate_llvm_lcov.find_tool PATH / xcrun / common-location / not-found paths."""

    def test_found_on_path(self):
        with mock.patch("generate_llvm_lcov.shutil.which", return_value="/usr/bin/llvm-cov"):
            self.assertEqual(gll.find_tool("llvm-cov"), "/usr/bin/llvm-cov")

    def test_found_via_xcrun_on_darwin(self):
        completed: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            args=["xcrun"], returncode=0, stdout="/xcode/llvm-cov\n", stderr=""
        )
        with mock.patch("generate_llvm_lcov.shutil.which", return_value=None), \
             mock.patch("generate_llvm_lcov.sys.platform", "darwin"), \
             mock.patch("generate_llvm_lcov.subprocess.run", return_value=completed), \
             mock.patch("generate_llvm_lcov.os.path.exists", return_value=True):
            self.assertEqual(gll.find_tool("llvm-cov"), "/xcode/llvm-cov")

    def test_xcrun_failure_falls_through_to_common_locations(self):
        def exists(path: str) -> bool:
            return path == "/opt/homebrew/opt/llvm/bin/llvm-cov"

        with mock.patch("generate_llvm_lcov.shutil.which", return_value=None), \
             mock.patch("generate_llvm_lcov.sys.platform", "darwin"), \
             mock.patch("generate_llvm_lcov.subprocess.run",
                        side_effect=subprocess.CalledProcessError(1, ["xcrun"])), \
             mock.patch("generate_llvm_lcov.os.path.exists", side_effect=exists):
            self.assertEqual(gll.find_tool("llvm-cov"), "/opt/homebrew/opt/llvm/bin/llvm-cov")

    def test_common_location_on_linux(self):
        def exists(path: str) -> bool:
            return path == "/usr/lib/llvm-17/bin/llvm-profdata"

        with mock.patch("generate_llvm_lcov.shutil.which", return_value=None), \
             mock.patch("generate_llvm_lcov.sys.platform", "linux"), \
             mock.patch("generate_llvm_lcov.os.path.exists", side_effect=exists):
            self.assertEqual(gll.find_tool("llvm-profdata"), "/usr/lib/llvm-17/bin/llvm-profdata")

    def test_not_found_returns_none(self):
        with mock.patch("generate_llvm_lcov.shutil.which", return_value=None), \
             mock.patch("generate_llvm_lcov.sys.platform", "linux"), \
             mock.patch("generate_llvm_lcov.os.path.exists", return_value=False):
            self.assertIsNone(gll.find_tool("llvm-cov"))


class TestDiscoverProfiles(unittest.TestCase):
    """Covers generate_llvm_lcov.discover_profiles file matching and noise-dir skipping."""

    def _tree(self, files: list[str]) -> str:
        root = tempfile.mkdtemp()
        for rel in files:
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                _ = f.write("x")
        return root

    def test_finds_profraw_and_profdata(self):
        root = self._tree(["a.profraw", "sub/b.profdata", "notes.txt"])
        raw, data = gll.discover_profiles(root)
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(data), 1)
        self.assertTrue(raw[0].endswith("a.profraw"))
        self.assertTrue(data[0].endswith("b.profdata"))

    def test_ignores_noise_directories(self):
        root = self._tree(["node_modules/x.profraw", ".git/y.profdata", "keep.profraw"])
        raw, data = gll.discover_profiles(root)
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(data), 0)
        self.assertTrue(raw[0].endswith("keep.profraw"))

    def test_empty_tree_returns_empty_lists(self):
        root = self._tree(["only.txt"])
        raw, data = gll.discover_profiles(root)
        self.assertEqual((raw, data), ([], []))


if __name__ == "__main__":
    _ = unittest.main()
