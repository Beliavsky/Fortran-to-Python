#!/usr/bin/env python3
"""Pre-commit regression checks for xf2p.py."""

from __future__ import annotations

import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    src = repo / "xfit_mix.f90"
    if not src.exists():
        print(f"[regression] skip: missing {src}")
        return 0

    out_py = Path(tempfile.gettempdir()) / "_xf2p_precommit_xfit_mix.py"

    cmd = [sys.executable, "xf2p.py", str(src), "--out", str(out_py)]
    print("[regression] transpile:", " ".join(cmd))
    p = subprocess.run(cmd, cwd=repo, text=True, capture_output=True)
    if p.returncode != 0:
        print("[regression] FAIL: xf2p transpile failed")
        if p.stdout.strip():
            print(p.stdout.rstrip())
        if p.stderr.strip():
            print(p.stderr.rstrip())
        return p.returncode

    try:
        py_compile.compile(str(out_py), doraise=True)
    except py_compile.PyCompileError as e:
        print("[regression] FAIL: generated Python has syntax errors")
        print(str(e))
        return 1
    finally:
        try:
            if out_py.exists():
                out_py.unlink()
        except OSError:
            pass

    print("[regression] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
