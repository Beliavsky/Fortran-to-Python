"""Survey Fortran-to-Python translations without changing source files."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import glob
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$")


def compare(reference: str, actual: str, rtol: float, atol: float) -> dict:
    expected, observed = reference.split(), actual.split()
    if len(expected) != len(observed):
        return {"status": "mismatch", "detail": f"Token counts differ: {len(expected)} vs {len(observed)}"}
    for index, (a, b) in enumerate(zip(expected, observed), 1):
        equal = a == b
        if NUMBER.fullmatch(a) and NUMBER.fullmatch(b):
            if re.fullmatch(r"[+-]?\d+", a) and re.fullmatch(r"[+-]?\d+", b):
                equal = int(a) == int(b)
            else:
                equal = math.isclose(float(a.lower().replace("d", "e")),
                                     float(b.lower().replace("d", "e")), rel_tol=rtol, abs_tol=atol)
        if not equal:
            return {"status": "mismatch", "detail": f"Token {index}: Fortran {a!r}, Python {b!r}"}
    return {"status": "match"}


def stage(command: list[str], cwd: Path, timeout: float) -> dict:
    started = time.perf_counter()
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        result = {"status": "pass" if proc.returncode == 0 else "fail",
                  "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")
        result = {"status": "timeout", "stdout": decode(exc.stdout), "stderr": decode(exc.stderr)}
    except OSError as exc:
        result = {"status": "error", "stdout": "", "stderr": str(exc)}
    result.update(command=command, elapsed_seconds=round(time.perf_counter() - started, 6))
    return result


def library_only(sources: list[Path]) -> bool:
    # Conservative classification: explicit PROGRAM or a bare END can be a
    # main program. Anything uncertain proceeds to translation/compilation.
    text = "\n".join(p.read_text(encoding="utf-8-sig", errors="replace") for p in sources)
    lines = [line.split("!", 1)[0].strip().lower() for line in text.splitlines()]
    if any(re.match(r"program\s+\w+", line) or line == "end" for line in lines):
        return False
    return any(re.match(r"(?:module\s+(?!procedure\b)|(?:pure\s+)?subroutine\s+|.*\bfunction\s+)",
                        line) for line in lines)


def evaluate(sources: list[Path], directory: Path, args) -> dict:
    result = {"sources": [str(p) for p in sources], "work_dir": str(directory),
              "classification": "program", "stages": {name: {"status": "not_requested"}
              for name in ("compile", "fortran_run", "translate", "python_run", "comparison")}}
    stages = result["stages"]
    if library_only(sources):
        result.update(classification="library_only", outcome="skipped_library")
        return result
    ft_dir, py_dir = directory / "fortran", directory / "python"
    ft_dir.mkdir(parents=True)
    py_dir.mkdir()
    for data in args.data:
        shutil.copy2(data, ft_dir / data.name)
        shutil.copy2(data, py_dir / data.name)
    output = py_dir / "translated.py"
    translation_sources = sources
    if len(sources) > 1:
        # xf2p --out accepts only one input. Combine the explicitly ordered
        # group locally; never let its default output land beside user sources.
        combined = py_dir / "combined.f90"
        combined.write_text("\n".join(p.read_text(encoding="utf-8-sig") for p in sources), encoding="utf-8")
        translation_sources = [combined]
    stages["translate"] = stage([sys.executable, str(ROOT / "xf2p.py"),
                                  *map(str, translation_sources), "--out", str(output)], py_dir, args.timeout)
    if stages["translate"]["status"] == "pass" and not output.exists():
        stages["translate"].update(status="fail", stderr="Translator did not create output")
    if args.run or args.run_both or args.run_diff:
        stages["python_run"] = {"status": "blocked"}
        if stages["translate"]["status"] == "pass":
            stages["python_run"] = stage([sys.executable, str(output)], py_dir, args.timeout)
    if args.compile or args.run_both or args.run_diff:
        command = shlex.split(args.compiler, posix=os.name != "nt")
        command = [word[1:-1] if word.startswith('"') and word.endswith('"') else word for word in command]
        exe = ft_dir / ("original.exe" if os.name == "nt" else "original")
        stages["compile"] = stage([*command, *map(str, sources), "-o", str(exe)], ft_dir, args.timeout)
        if "cannot open module file" in stages["compile"].get("stderr", "").lower():
            result["classification"] = "missing_module_dependency"
        if args.run_both or args.run_diff:
            stages["fortran_run"] = {"status": "blocked"}
            if stages["compile"]["status"] == "pass":
                stages["fortran_run"] = stage([str(exe)], ft_dir, args.timeout)
    if args.run_diff:
        stages["comparison"] = {"status": "not_compared"}
        if stages["fortran_run"]["status"] == stages["python_run"]["status"] == "pass":
            stages["comparison"] = compare(stages["fortran_run"]["stdout"], stages["python_run"]["stdout"],
                                            args.rtol, args.atol)
    result["outcome"] = "pass"
    for name, value in stages.items():
        if value["status"] in ("fail", "error", "timeout", "mismatch"):
            result["outcome"] = f"{name}_{value['status']}"
            break
    return result


def report_text(report: dict) -> str:
    lines = ["Fortran-to-Python batch report", f"Started: {report['started_utc']}",
             f"Ended: {report['ended_utc']}", f"Elapsed: {report['elapsed_seconds']:.2f} seconds",
             f"Cases: {len(report['cases'])}", f"Summary: {json.dumps(report['summary'], sort_keys=True)}", ""]
    for index, case in enumerate(report["cases"], 1):
        lines.extend([f"[{index}] {' + '.join(case['sources'])}",
                      f"  {case['outcome']} ({case['classification']})"])
        for name, value in case["stages"].items():
            lines.append(f"  {name}: {value['status']}" +
                         (f" ({value['elapsed_seconds']:.3f}s)" if "elapsed_seconds" in value else ""))
            if value["status"] in ("fail", "error", "timeout", "mismatch"):
                for key in ("detail", "stdout", "stderr"):
                    if value.get(key):
                        lines.extend("    " + line for line in value[key].splitlines())
        # Include both outputs on mismatches, even though execution succeeded.
        if case["stages"]["comparison"]["status"] == "mismatch":
            for name in ("fortran_run", "python_run"):
                lines.append(f"  {name} output:")
                lines.extend("    " + line for line in case["stages"][name]["stdout"].splitlines())
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patterns", nargs="*", help="Fortran files or quoted glob patterns (supports **)")
    parser.add_argument("--group", nargs="+", action="append", default=[], metavar="SOURCE",
                        help="Ordered source files for one program; repeat for multiple programs")
    parser.add_argument("--compile", action="store_true", help="Also compile original Fortran")
    parser.add_argument("--run", action="store_true", help="Run translated Python")
    parser.add_argument("--run-both", action="store_true", help="Compile/run Fortran and run Python")
    parser.add_argument("--run-diff", action="store_true", help="Run both and compare output tokens")
    parser.add_argument("--compiler", default="gfortran -O0 -g -fcheck=all -fbacktrace")
    parser.add_argument("--timeout", type=float, default=90, help="Seconds allowed per subprocess")
    parser.add_argument("--limit", type=int, help="Maximum number of cases")
    parser.add_argument("--rtol", type=float, default=1e-9)
    parser.add_argument("--atol", type=float, default=1e-11)
    parser.add_argument("--data", type=Path, action="append", default=[], help="Data file copied into both run directories")
    parser.add_argument("--out-dir", type=Path, default=Path("reports"), help="Report and retained work directory parent")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if any(not math.isfinite(v) or v < 0 for v in (args.rtol, args.atol)):
        parser.error("tolerances must be finite and nonnegative")
    if not shlex.split(args.compiler, posix=os.name != "nt"):
        parser.error("--compiler must not be empty")
    cases, seen = [], set()
    for pattern in args.patterns:
        matches = sorted(glob.glob(pattern, recursive=True))
        if not matches:
            parser.error(f"No files match: {pattern}")
        for match in matches:
            path = Path(match).resolve()
            if not path.is_file():
                parser.error(f"Not a file: {path}")
            if path not in seen:
                cases.append([path])
                seen.add(path)
    cases.extend([[Path(p).resolve() for p in group] for group in args.group])
    if not cases:
        parser.error("Provide file patterns or --group sources")
    args.data = [p.resolve() for p in args.data]
    for path in [p for case in cases for p in case] + args.data:
        if not path.is_file():
            parser.error(f"Not a file: {path}")
    if len({p.name for p in args.data}) != len(args.data):
        parser.error("--data files must have distinct basenames")
    cases = cases[:args.limit] if args.limit else cases
    args.out_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="xf2p_batch_" + datetime.now().strftime("%Y%m%d_%H%M%S_"),
                                     dir=args.out_dir.resolve()))
    started, start = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    results = []
    for index, sources in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {' + '.join(map(str, sources))}", flush=True)
        result = evaluate(sources, directory / f"case_{index:04d}", args)
        results.append(result)
        print("  " + result["outcome"], flush=True)
        # Save progress after every case so interrupted long surveys retain results.
        report = {"schema_version": 1, "started_utc": started,
                  "ended_utc": datetime.now(timezone.utc).isoformat(),
                  "elapsed_seconds": time.perf_counter() - start,
                  "completed_cases": len(results), "requested_cases": len(cases),
                  "complete": len(results) == len(cases),
                  "options": {k: v for k, v in vars(args).items() if k not in ("out_dir", "data")},
                  "data": list(map(str, args.data)), "cases": results,
                  "summary": dict(Counter(r["outcome"] for r in results))}
        (directory / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (directory / "results.txt").write_text(report_text(report), encoding="utf-8")
    print(f"Reports: {directory}")
    print(json.dumps(report["summary"], sort_keys=True))
    return int(any(r["outcome"] not in ("pass", "skipped_library") for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
