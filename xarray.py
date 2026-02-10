#!/usr/bin/env python3
"""Advisory checker for simple DO loops replaceable by array operations."""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cli_paths as cpaths
import fortran_scan as fscan
import xunset

DO_RE = re.compile(
    r"^\s*do\s+([a-z][a-z0-9_]*)\s*=\s*([^,]+?)\s*,\s*([^,]+?)(?:\s*,\s*([^,]+?))?\s*$",
    re.IGNORECASE,
)
END_DO_RE = re.compile(r"^\s*end\s*do\b", re.IGNORECASE)
IF_THEN_RE = re.compile(r"^\s*if\s*\((.+)\)\s*then\s*$", re.IGNORECASE)
END_IF_RE = re.compile(r"^\s*end\s*if\b", re.IGNORECASE)
ASSIGN_RE = re.compile(r"^\s*(.+?)\s*=\s*(.+)$", re.IGNORECASE)
SIMPLE_NAME_RE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*$", re.IGNORECASE)
INDEXED_NAME_RE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*\(\s*([a-z][a-z0-9_]*)\s*\)\s*$", re.IGNORECASE)
ADD_ACC_RE = re.compile(
    r"^\s*([a-z][a-z0-9_]*)\s*\+\s*(.+)$",
    re.IGNORECASE,
)
MUL_ACC_RE = re.compile(
    r"^\s*([a-z][a-z0-9_]*)\s*\*\s*(.+)$",
    re.IGNORECASE,
)
ADD_ONE_RE = re.compile(
    r"^\s*([a-z][a-z0-9_]*)\s*\+\s*1(?:\.0+)?(?:_[a-z0-9]+)?\s*$",
    re.IGNORECASE,
)

BEGIN_TAG = "!! beginning of code that xarray.py suggests replacing"
END_TAG = "!! end of code that xarray.py suggests replacing"


@dataclass
class Finding:
    """One loop-to-array replacement suggestion."""

    path: Path
    rule: str
    unit_kind: str
    unit_name: str
    start_line: int
    end_line: int
    suggestion: str


def choose_files(args_files: List[Path], exclude: Iterable[str]) -> List[Path]:
    """Resolve source files from args or current-directory defaults."""
    if args_files:
        files = cpaths.expand_path_args(args_files)
    else:
        files = sorted(
            set(Path(".").glob("*.f90")) | set(Path(".").glob("*.F90")),
            key=lambda p: p.name.lower(),
        )
    return fscan.apply_excludes(files, exclude)


def make_backup_path(path: Path) -> Path:
    """Create a non-overwriting backup path next to path."""
    base = Path(str(path) + ".bak")
    if not base.exists():
        return base
    idx = 1
    while True:
        cand = Path(f"{path}.bak{idx}")
        if not cand.exists():
            return cand
        idx += 1


def replace_index_with_slice(expr: str, idx_var: str, lb: str, ub: str) -> str:
    """Rewrite occurrences of name(idx_var) to name(lb:ub) in expression."""
    pat = re.compile(
        rf"\b([a-z][a-z0-9_]*)\s*\(\s*{re.escape(idx_var)}\s*\)",
        re.IGNORECASE,
    )
    return pat.sub(lambda m: f"{m.group(1)}({lb}:{ub})", expr)


def build_range(lb: str, ub: str, step: Optional[str]) -> str:
    """Build Fortran slice-range text from loop bounds and optional step."""
    lb_s = lb.strip()
    ub_s = ub.strip()
    if step is None:
        return f"{lb_s}:{ub_s}"
    st = step.strip()
    return f"{lb_s}:{ub_s}:{st}"


def has_loop_var(expr: str, loop_var: str) -> bool:
    """Check whether expression still contains loop index variable."""
    return re.search(rf"\b{re.escape(loop_var)}\b", expr, re.IGNORECASE) is not None


def split_range(rng: str) -> Tuple[str, str]:
    """Split range text into (lb, ub_or_ub_step)."""
    return rng.split(":", 1)[0], rng.split(":", 1)[1]


def maybe_elementwise(loop_var: str, rng: str, body_stmt: str) -> Optional[str]:
    """Detect elementwise assignment loop and build replacement."""
    m = ASSIGN_RE.match(body_stmt.strip())
    if not m:
        return None
    lhs = m.group(1).strip()
    rhs = m.group(2).strip()
    m_lhs = INDEXED_NAME_RE.match(lhs)
    if not m_lhs:
        return None
    lhs_name = m_lhs.group(1)
    lhs_idx = m_lhs.group(2).lower()
    if lhs_idx != loop_var.lower():
        return None
    lb, ubtxt = split_range(rng)
    rhs_sliced = replace_index_with_slice(rhs, loop_var, lb, ubtxt)
    # The helper above expects (lb, ub-text). rng may include step in ub-text.
    if has_loop_var(rhs_sliced, loop_var):
        return None
    if rhs_sliced == rhs:
        return None
    return f"{lhs_name}({rng}) = {rhs_sliced}"


def maybe_reduction_sum(
    loop_var: str,
    rng: str,
    body_stmt: str,
    prev_stmt: Optional[str],
) -> Optional[str]:
    """Detect sum-reduction loop with preceding initialization and build replacement."""
    if prev_stmt is None:
        return None
    mp = ASSIGN_RE.match(prev_stmt.strip())
    ml = ASSIGN_RE.match(body_stmt.strip())
    if not mp or not ml:
        return None
    acc_prev = SIMPLE_NAME_RE.match(mp.group(1).strip())
    acc_lhs = SIMPLE_NAME_RE.match(ml.group(1).strip())
    if not acc_prev or not acc_lhs:
        return None
    acc_name_prev = acc_prev.group(1).lower()
    acc_name_lhs = acc_lhs.group(1).lower()
    if acc_name_prev != acc_name_lhs:
        return None
    madd = ADD_ACC_RE.match(ml.group(2).strip())
    if not madd:
        return None
    acc_in_rhs = madd.group(1).lower()
    if acc_in_rhs != acc_name_lhs:
        return None
    expr = madd.group(2).strip()
    lb, ubtxt = rng.split(":", 1)
    expr_sliced = replace_index_with_slice(expr, loop_var, lb, ubtxt)
    if has_loop_var(expr_sliced, loop_var):
        return None
    if expr_sliced == expr:
        return None
    return f"{acc_name_lhs} = sum({expr_sliced})"


def maybe_reduction_product(
    loop_var: str,
    rng: str,
    body_stmt: str,
    prev_stmt: Optional[str],
) -> Optional[str]:
    """Detect product-reduction loop and build replacement."""
    if prev_stmt is None:
        return None
    mp = ASSIGN_RE.match(prev_stmt.strip())
    ml = ASSIGN_RE.match(body_stmt.strip())
    if not mp or not ml:
        return None
    acc_prev = SIMPLE_NAME_RE.match(mp.group(1).strip())
    acc_lhs = SIMPLE_NAME_RE.match(ml.group(1).strip())
    if not acc_prev or not acc_lhs:
        return None
    acc_name_prev = acc_prev.group(1).lower()
    acc_name_lhs = acc_lhs.group(1).lower()
    if acc_name_prev != acc_name_lhs:
        return None
    mmul = MUL_ACC_RE.match(ml.group(2).strip())
    if not mmul:
        return None
    acc_in_rhs = mmul.group(1).lower()
    if acc_in_rhs != acc_name_lhs:
        return None
    expr = mmul.group(2).strip()
    lb, ubtxt = rng.split(":", 1)
    expr_sliced = replace_index_with_slice(expr, loop_var, lb, ubtxt)
    if has_loop_var(expr_sliced, loop_var):
        return None
    if expr_sliced == expr:
        return None
    return f"{acc_name_lhs} = product({expr_sliced})"


def maybe_masked_sum(
    loop_var: str,
    rng: str,
    prev_stmt: Optional[str],
    if_stmt: str,
    body_stmt: str,
) -> Optional[str]:
    """Detect masked sum inside IF block within loop."""
    if prev_stmt is None:
        return None
    mp = ASSIGN_RE.match(prev_stmt.strip())
    if not mp:
        return None
    acc_prev = SIMPLE_NAME_RE.match(mp.group(1).strip())
    if not acc_prev:
        return None
    acc = acc_prev.group(1).lower()
    mif = IF_THEN_RE.match(if_stmt.strip())
    ml = ASSIGN_RE.match(body_stmt.strip())
    if not mif or not ml:
        return None
    lhs = SIMPLE_NAME_RE.match(ml.group(1).strip())
    if not lhs or lhs.group(1).lower() != acc:
        return None
    madd = ADD_ACC_RE.match(ml.group(2).strip())
    if not madd or madd.group(1).lower() != acc:
        return None
    cond = mif.group(1).strip()
    expr = madd.group(2).strip()
    lb, ubtxt = rng.split(":", 1)
    cond_s = replace_index_with_slice(cond, loop_var, lb, ubtxt)
    expr_s = replace_index_with_slice(expr, loop_var, lb, ubtxt)
    if has_loop_var(cond_s, loop_var) or has_loop_var(expr_s, loop_var):
        return None
    if cond_s == cond or expr_s == expr:
        return None
    return f"{acc} = sum({expr_s}, mask = {cond_s})"


def maybe_count(
    loop_var: str,
    rng: str,
    prev_stmt: Optional[str],
    if_stmt: str,
    body_stmt: str,
) -> Optional[str]:
    """Detect count-in-if pattern and build COUNT replacement."""
    if prev_stmt is None:
        return None
    mp = ASSIGN_RE.match(prev_stmt.strip())
    if not mp:
        return None
    k_prev = SIMPLE_NAME_RE.match(mp.group(1).strip())
    if not k_prev:
        return None
    kname = k_prev.group(1).lower()
    mif = IF_THEN_RE.match(if_stmt.strip())
    ml = ASSIGN_RE.match(body_stmt.strip())
    if not mif or not ml:
        return None
    lhs = SIMPLE_NAME_RE.match(ml.group(1).strip())
    if not lhs or lhs.group(1).lower() != kname:
        return None
    madd1 = ADD_ONE_RE.match(ml.group(2).strip())
    if not madd1 or madd1.group(1).lower() != kname:
        return None
    cond = mif.group(1).strip()
    lb, ubtxt = rng.split(":", 1)
    cond_s = replace_index_with_slice(cond, loop_var, lb, ubtxt)
    if has_loop_var(cond_s, loop_var):
        return None
    if cond_s == cond:
        return None
    return f"{kname} = count({cond_s})"


def analyze_unit(unit: xunset.Unit) -> List[Finding]:
    """Analyze one unit for simple loop-to-array opportunities."""
    findings: List[Finding] = []
    body = unit.body
    i = 0
    while i < len(body):
        ln, stmt = body[i]
        mdo = DO_RE.match(stmt.strip())
        if not mdo:
            i += 1
            continue
        loop_var = mdo.group(1)
        lb = mdo.group(2)
        ub = mdo.group(3)
        step = mdo.group(4)
        rng = build_range(lb, ub, step)

        # Form A: one-statement loop body.
        if i + 2 < len(body):
            ln_body, stmt_body = body[i + 1]
            ln_end, stmt_end = body[i + 2]
            if END_DO_RE.match(stmt_end.strip()):
                sugg_elem = maybe_elementwise(loop_var, rng, stmt_body)
                if sugg_elem is not None:
                    findings.append(
                        Finding(
                            path=unit.path,
                            rule="elementwise",
                            unit_kind=unit.kind,
                            unit_name=unit.name,
                            start_line=ln,
                            end_line=ln_end,
                            suggestion=sugg_elem,
                        )
                    )
                    i += 3
                    continue
                prev_stmt = body[i - 1][1] if i - 1 >= 0 else None
                start_line = body[i - 1][0] if i - 1 >= 0 else ln
                sugg_sum = maybe_reduction_sum(loop_var, rng, stmt_body, prev_stmt)
                if sugg_sum is not None:
                    findings.append(
                        Finding(
                            path=unit.path,
                            rule="reduction_sum",
                            unit_kind=unit.kind,
                            unit_name=unit.name,
                            start_line=start_line,
                            end_line=ln_end,
                            suggestion=sugg_sum,
                        )
                    )
                    i += 3
                    continue
                sugg_prod = maybe_reduction_product(loop_var, rng, stmt_body, prev_stmt)
                if sugg_prod is not None:
                    findings.append(
                        Finding(
                            path=unit.path,
                            rule="reduction_product",
                            unit_kind=unit.kind,
                            unit_name=unit.name,
                            start_line=start_line,
                            end_line=ln_end,
                            suggestion=sugg_prod,
                        )
                    )
                    i += 3
                    continue

        # Form B: IF-block inside loop body:
        # do ...
        #    if (cond) then
        #       stmt
        #    end if
        # end do
        if i + 4 < len(body):
            _ln_if, stmt_if = body[i + 1]
            _ln_inside, stmt_inside = body[i + 2]
            _ln_eif, stmt_eif = body[i + 3]
            ln_end, stmt_end = body[i + 4]
            if IF_THEN_RE.match(stmt_if.strip()) and END_IF_RE.match(stmt_eif.strip()) and END_DO_RE.match(stmt_end.strip()):
                prev_stmt = body[i - 1][1] if i - 1 >= 0 else None
                start_line = body[i - 1][0] if i - 1 >= 0 else ln
                sugg_msum = maybe_masked_sum(loop_var, rng, prev_stmt, stmt_if, stmt_inside)
                if sugg_msum is not None:
                    findings.append(
                        Finding(
                            path=unit.path,
                            rule="reduction_masked_sum",
                            unit_kind=unit.kind,
                            unit_name=unit.name,
                            start_line=start_line,
                            end_line=ln_end,
                            suggestion=sugg_msum,
                        )
                    )
                    i += 5
                    continue
                sugg_cnt = maybe_count(loop_var, rng, prev_stmt, stmt_if, stmt_inside)
                if sugg_cnt is not None:
                    findings.append(
                        Finding(
                            path=unit.path,
                            rule="reduction_count",
                            unit_kind=unit.kind,
                            unit_name=unit.name,
                            start_line=start_line,
                            end_line=ln_end,
                            suggestion=sugg_cnt,
                        )
                    )
                    i += 5
                    continue
        i += 1
    return findings


def analyze_file(path: Path) -> List[Finding]:
    """Analyze one file."""
    infos, any_missing = fscan.load_source_files([path])
    if not infos or any_missing:
        return []
    finfo = infos[0]
    out: List[Finding] = []
    for unit in xunset.collect_units(finfo):
        out.extend(analyze_unit(unit))
    return out


def annotate_file(path: Path, findings: List[Finding]) -> Tuple[int, Optional[Path]]:
    """Insert begin/end markers and replacement comment around suggested blocks."""
    if not findings:
        return 0, None
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    inserted = 0
    for f in sorted(findings, key=lambda x: (x.start_line, x.end_line), reverse=True):
        sidx = f.start_line - 1
        eidx = f.end_line - 1
        if sidx < 0 or eidx < 0 or sidx >= len(lines) or eidx >= len(lines) or sidx > eidx:
            continue
        raw_s = lines[sidx]
        raw_e = lines[eidx]
        indent_s = re.match(r"^\s*", raw_s).group(0) if raw_s else ""
        indent_e = re.match(r"^\s*", raw_e).group(0) if raw_e else ""
        eol_s = "\r\n" if raw_s.endswith("\r\n") else ("\n" if raw_s.endswith("\n") else "\n")
        eol_e = "\r\n" if raw_e.endswith("\r\n") else ("\n" if raw_e.endswith("\n") else "\n")

        begin_msg = f"{indent_s}{BEGIN_TAG}{eol_s}"
        end_msg = f"{indent_e}{END_TAG}{eol_e}"
        sugg_msg = f"{indent_e}! {f.suggestion} !! suggested replacement by xarray.py{eol_e}"

        # Skip if already annotated around this range.
        if sidx - 1 >= 0 and lines[sidx - 1].strip().lower() == BEGIN_TAG.lower():
            continue
        lines.insert(eidx + 1, end_msg)
        lines.insert(eidx + 2, sugg_msg)
        lines.insert(sidx, begin_msg)
        inserted += 3

    if inserted == 0:
        return 0, None
    backup = make_backup_path(path)
    shutil.copy2(path, backup)
    path.write_text("".join(lines), encoding="utf-8")
    return inserted, backup


def main() -> int:
    """Run xarray advisory and optional annotation mode."""
    parser = argparse.ArgumentParser(
        description="Suggest replacing simple Fortran loops with array operations"
    )
    parser.add_argument("fortran_files", type=Path, nargs="*")
    parser.add_argument("--exclude", action="append", default=[], help="Glob pattern to exclude files")
    parser.add_argument("--verbose", action="store_true", help="Print full replacement suggestions")
    parser.add_argument("--annotate", action="store_true", help="Insert annotated suggestion blocks")
    args = parser.parse_args()

    files = choose_files(args.fortran_files, args.exclude)
    if not files:
        print("No source files remain after applying --exclude filters.")
        return 2

    findings: List[Finding] = []
    for p in files:
        findings.extend(analyze_file(p))

    if not findings:
        print("No array-operation replacement candidates found.")
        return 0

    findings.sort(key=lambda f: (f.path.name.lower(), f.start_line, f.end_line))
    print(f"{len(findings)} array-operation replacement candidate(s).")
    for f in findings:
        print(
            f"{f.path.name}:{f.start_line}-{f.end_line} {f.rule} "
            f"{f.unit_kind} {f.unit_name}"
        )
        if args.verbose:
            print(f"  suggest: {f.suggestion}")

    if args.annotate:
        by_file: Dict[Path, List[Finding]] = {}
        for f in findings:
            by_file.setdefault(f.path, []).append(f)
        total = 0
        touched = 0
        for p in sorted(by_file.keys(), key=lambda x: x.name.lower()):
            n, backup = annotate_file(p, by_file[p])
            total += n
            if n > 0:
                touched += 1
                print(f"\nAnnotated {p.name}: inserted {n}, backup {backup.name if backup else '(none)'}")
            elif args.verbose:
                print(f"\nNo annotations inserted in {p.name}")
        print(f"\n--annotate summary: files changed {touched}, inserted {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
