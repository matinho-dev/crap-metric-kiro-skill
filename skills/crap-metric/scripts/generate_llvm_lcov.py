#!/usr/bin/env python3
"""
LLVM-COV to LCOV Exporter
Finds or merges LLVM instrumentation profiles (.profraw / .profdata) and exports
coverage in standard LCOV format using `llvm-cov export -format=lcov`.

Compatible with:
- Clang / LLVM (C, C++, Objective-C) instrumented with -fprofile-instr-generate -fcoverage-mapping
- Rust (cargo llvm-cov, rustc -C instrument-coverage)
- Swift (swift test --enable-code-coverage)
- Zig (zig test with coverage)
"""

import argparse
import os
import shutil
import subprocess
import sys
from typing import cast


def _find_via_xcrun(tool_name: str) -> str | None:
    """Resolves a tool via macOS `xcrun --find`, or None if unavailable."""
    if sys.platform != "darwin":
        return None
    try:
        res = subprocess.run(
            ["xcrun", "--find", tool_name],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        # xcrun not available or tool not found via xcrun; fall through to other lookups.
        return None
    found = res.stdout.strip()
    return found if found and os.path.exists(found) else None


def _find_in_common_locations(tool_name: str) -> str | None:
    """Scans common Homebrew / Linux LLVM install locations for the tool."""
    common_locations = [
        f"/opt/homebrew/opt/llvm/bin/{tool_name}",
        f"/usr/local/opt/llvm/bin/{tool_name}",
        f"/usr/lib/llvm-18/bin/{tool_name}",
        f"/usr/lib/llvm-17/bin/{tool_name}",
        f"/usr/lib/llvm-16/bin/{tool_name}",
        f"/usr/lib/llvm-15/bin/{tool_name}",
    ]
    return next((loc for loc in common_locations if os.path.exists(loc)), None)


def find_tool(tool_name: str) -> str | None:
    """Finds LLVM tool (e.g. llvm-cov, llvm-profdata), checking PATH, xcrun (macOS), and Homebrew."""
    return (
        shutil.which(tool_name)
        or _find_via_xcrun(tool_name)
        or _find_in_common_locations(tool_name)
    )


_PROFILE_NOISE_DIRS = (".git", "node_modules", "vendor")


def _is_profile_noise_dir(root: str) -> bool:
    """True if the directory path contains a noisy/irrelevant segment."""
    return any(part in root.split(os.sep) for part in _PROFILE_NOISE_DIRS)


def _classify_profiles(root: str, files: list[str]) -> tuple[list[str], list[str]]:
    """Splits a directory's files into (.profraw paths, .profdata paths)."""
    raw = [os.path.join(root, f) for f in files if f.endswith(".profraw")]
    data = [os.path.join(root, f) for f in files if f.endswith(".profdata")]
    return raw, data


def discover_profiles(search_dir: str) -> tuple[list[str], list[str]]:
    """Discovers .profraw and .profdata files in workspace."""
    profraw_files: list[str] = []
    profdata_files: list[str] = []

    for root, _, files in os.walk(search_dir):
        if _is_profile_noise_dir(root):
            continue
        raw, data = _classify_profiles(root, files)
        profraw_files.extend(raw)
        profdata_files.extend(data)

    return profraw_files, profdata_files


def merge_profraw(
    profdata_tool: str,
    raw_files: list[str],
    output_profdata: str
) -> bool:
    """Merges .profraw files into a single .profdata using llvm-profdata."""
    cmd = [profdata_tool, "merge", "-sparse"] + raw_files + ["-o", output_profdata]
    try:
        _ = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running llvm-profdata merge: {cast('str', e.stderr)}", file=sys.stderr)
        return False


def export_lcov(
    llvm_cov_tool: str,
    binary: str,
    profdata: str,
    output_file: str | None = None,
    extra_objects: list[str] | None = None,
    sources: list[str] | None = None,
    ignore_regex: str | None = None
) -> bool:
    """Exports LCOV trace data using `llvm-cov export -format=lcov`."""
    cmd = [
        llvm_cov_tool,
        "export",
        "-format=lcov",
        binary,
        f"-instr-profile={profdata}"
    ]

    if extra_objects:
        for obj in extra_objects:
            cmd.append(f"-object={obj}")

    if ignore_regex:
        cmd.append(f"--ignore-filename-regex={ignore_regex}")

    if sources:
        cmd.append("--sources")
        cmd.extend(sources)

    try:
        if output_file:
            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as out:
                _ = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, check=True, text=True)
            print(f"Successfully generated LCOV coverage at: {output_file}")
        else:
            _ = subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running llvm-cov export: {cast('str', e.stderr)}", file=sys.stderr)
        return False


def _discover_profile_source(workspace: str) -> tuple[str | None, list[str] | None]:
    """Discovers a profdata file or raw files in the workspace. Exits if none found."""
    discovered_raw, discovered_data = discover_profiles(workspace)
    if discovered_data:
        print(f"Using discovered profdata: {discovered_data[0]}")
        return discovered_data[0], None
    if discovered_raw:
        print(f"Discovered {len(discovered_raw)} .profraw file(s).")
        return None, discovered_raw
    print(
        "Error: No .profdata or .profraw files found. Run tests with LLVM profiling enabled first.",
        file=sys.stderr,
    )
    sys.exit(1)


def _merge_raw_to_profdata(raw_files: list[str], llvm_profdata: str | None, workspace: str) -> str:
    """Merges raw profiles into a single .profdata file. Exits on failure."""
    if not llvm_profdata:
        print("Error: 'llvm-profdata' required to merge .profraw files but not found.", file=sys.stderr)
        sys.exit(1)
    merged_output = os.path.join(workspace, "coverage.profdata")
    print(f"Merging {len(raw_files)} raw profile(s) into {merged_output}...")
    if not merge_profraw(llvm_profdata, raw_files, merged_output):
        sys.exit(1)
    return merged_output


def _resolve_profdata(
    arg_profdata: str | None,
    arg_profraw: list[str] | None,
    llvm_profdata: str | None,
    workspace: str,
) -> str:
    """Resolves the .profdata file to use, discovering and merging as needed. Exits on failure."""
    if arg_profdata:
        return arg_profdata

    raw_files = arg_profraw
    profdata_file: str | None = None
    if not raw_files:
        profdata_file, raw_files = _discover_profile_source(workspace)

    if profdata_file:
        return profdata_file
    if raw_files:
        return _merge_raw_to_profdata(raw_files, llvm_profdata, workspace)

    print("Error: Could not resolve a .profdata file for coverage export.", file=sys.stderr)
    sys.exit(1)


def _resolve_llvm_cov() -> str:
    """Resolves the llvm-cov tool path, exiting if unavailable."""
    llvm_cov = find_tool("llvm-cov")
    if not llvm_cov:
        print("Error: 'llvm-cov' could not be found on PATH or via xcrun (macOS).", file=sys.stderr)
        sys.exit(1)
    return llvm_cov


def main():
    parser = argparse.ArgumentParser(
        description="Generate LCOV coverage data from LLVM instrumentation using llvm-cov."
    )
    _ = parser.add_argument(
        "--binary", "-b", required=True,
        help="Path to instrumented binary, test executable, or dylib/so."
    )
    _ = parser.add_argument(
        "--profdata", "-p",
        help="Path to merged .profdata file. If not supplied, auto-merges discovered .profraw files."
    )
    _ = parser.add_argument(
        "--profraw", nargs="+",
        help="One or more .profraw files to merge."
    )
    _ = parser.add_argument(
        "--output", "-o", default="coverage/lcov.info",
        help="Output LCOV file path (default: coverage/lcov.info). Use '-' for stdout."
    )
    _ = parser.add_argument(
        "--object", action="append", dest="extra_objects",
        help="Additional executable or object file(s) to include."
    )
    _ = parser.add_argument(
        "--sources", nargs="+",
        help="Specific source files or directories to restrict coverage to."
    )
    _ = parser.add_argument(
        "--ignore-regex", default=r"(^/usr|Xcode\.app|Tests?|vendor/)",
        help="Regex pattern of source paths to exclude (e.g. system headers)."
    )
    _ = parser.add_argument(
        "--workspace", default=".",
        help="Workspace root to search for profiles (default: current directory)."
    )

    args = parser.parse_args()
    arg_binary = cast("str", args.binary)
    arg_profdata = cast("str | None", args.profdata)
    arg_profraw = cast("list[str] | None", args.profraw)
    arg_output = cast("str", args.output)
    arg_extra_objects = cast("list[str] | None", args.extra_objects)
    arg_sources = cast("list[str] | None", args.sources)
    arg_ignore_regex = cast("str", args.ignore_regex)
    arg_workspace = cast("str", args.workspace)

    # 1. Resolve tools
    llvm_cov = _resolve_llvm_cov()
    llvm_profdata = find_tool("llvm-profdata")

    # 2. Resolve .profdata (discovering / merging raw profiles as needed)
    profdata_file = _resolve_profdata(arg_profdata, arg_profraw, llvm_profdata, arg_workspace)

    # 3. Export LCOV
    out_dest = None if arg_output == "-" else arg_output
    success = export_lcov(
        llvm_cov_tool=llvm_cov,
        binary=arg_binary,
        profdata=profdata_file,
        output_file=out_dest,
        extra_objects=arg_extra_objects,
        sources=arg_sources,
        ignore_regex=arg_ignore_regex,
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
