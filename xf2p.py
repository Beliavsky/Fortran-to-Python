import re
import ast
import sys
import argparse
import subprocess
import shlex
import time
import difflib
from fortran_output_compare import compare_outputs, normalized_lines, validate_tolerances
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import cast


def split_fortran_comment(line: str) -> tuple[str, str]:
    in_str = False
    quote = ""
    out: list[str] = []
    for ch in line:
        if in_str:
            out.append(ch)
            if ch == quote:
                in_str = False
        else:
            if ch in ("'", '"'):
                in_str = True
                quote = ch
                out.append(ch)
            elif ch == "!":
                code = "".join(out).rstrip()
                comment = line[len("".join(out)) + 1 :].strip()
                return code, comment
            else:
                out.append(ch)
    return "".join(out).rstrip(), ""


@dataclass
class UseSpec:
    module: str
    only_items: list[str] | None
    intrinsic: bool = False




def _replace_identifier_outside_strings(code: str, old: str, new: str) -> str:
    out: list[str] = []
    i = 0
    n = len(code)
    in_str = False
    quote = ""
    pat = re.compile(rf"(?i)\b{re.escape(old)}\b")
    while i < n:
        ch = code[i]
        if in_str:
            out.append(ch)
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            out.append(ch)
            i += 1
            continue
        j = i
        while j < n and code[j] not in ("'", '"'):
            j += 1
        out.append(pat.sub(new, code[i:j]))
        i = j
    return "".join(out)


def _choose_fresh_identifier(src: str, base: str) -> str:
    ids: set[str] = set()
    for raw in src.splitlines():
        code, _comment = split_fortran_comment(raw)
        ids.update(m.group(0).lower() for m in re.finditer(r"\b[a-z_]\w*\b", code, re.I))
    cand = base
    while cand.lower() in ids:
        cand += "_"
    return cand


def _preprocess_fortran_source(src: str) -> str:
    ids: set[str] = set()
    for raw in src.splitlines():
        code, _comment = split_fortran_comment(raw)
        ids.update(m.group(0).lower() for m in re.finditer(r"\b[a-z_]\w*\b", code, re.I))
    if "lambda" not in ids:
        return src
    repl = _choose_fresh_identifier(src, "lambda_")
    out_lines: list[str] = []
    for raw in src.splitlines():
        code, comment = split_fortran_comment(raw)
        new_code = _replace_identifier_outside_strings(code, "lambda", repl)
        if comment:
            if new_code:
                out_lines.append(f"{new_code} ! {comment}")
            else:
                out_lines.append(f"! {comment}")
        else:
            out_lines.append(new_code)
    return "\n".join(out_lines)

def _clean_fortran_code_lines(src: str) -> list[str]:
    out: list[str] = []
    for raw in src.splitlines():
        code, _c = split_fortran_comment(raw)
        s = code.strip()
        if s:
            out.append(s)
    return out


def _parse_file_interface(src: str) -> tuple[list[str], list[str], list[UseSpec]]:
    """Return (defined_modules, defined_symbols, use_specs) for one source."""
    code_lines = _clean_fortran_code_lines(src)
    defs: list[str] = []
    mods: list[str] = []
    uses: list[UseSpec] = []

    in_module = False
    in_module_contains = False

    for s in code_lines:
        sl = s.lower()

        # module declarations (skip 'module procedure')
        mm = re.match(r"^module\s+([a-z_]\w*)\b", sl, re.I)
        if mm and not re.match(r"^module\s+procedure\b", sl, re.I):
            mods.append(mm.group(1))
            in_module = True
            in_module_contains = False
            continue

        if re.match(r"^end\s+module\b", sl, re.I):
            in_module = False
            in_module_contains = False
            continue

        if in_module and sl == "contains":
            in_module_contains = True
            continue

        # type declarations
        mt = re.match(r"^type\s*(?:,\s*[^:]*)?::\s*([a-z_]\w*)\b", sl, re.I)
        if mt:
            defs.append(mt.group(1))
            continue

        # module declarative-part variables/parameters
        if in_module and not in_module_contains:
            pd = parse_decl(s)
            if pd:
                _ftype, attrs, rest = pd
                for nm, _shape, _init in parse_decl_items(rest, parse_decl_attr_dimension(attrs)):
                    defs.append(nm)
                continue
            td = re.match(r"^type\s*\(\s*([a-z_]\w*)\s*\)\s*(.*?)::\s*(.*)$", s, re.I)
            if td:
                attrs = td.group(2).strip()
                for nm, _shape, _init in parse_decl_items(td.group(3).strip(), parse_decl_attr_dimension(attrs)):
                    defs.append(nm)
                continue

        # function declarations
        mf = re.match(
            r"^(?!\s*end\s+function\b)\s*(?:(?:pure|elemental|recursive)\s+)*(?:\w+(?:\s*\([^)]*\))?\s+)*function\s+([a-z_]\w*)\s*\(",
            sl,
            re.I,
        )
        if mf:
            defs.append(mf.group(1))
            continue

        # subroutine declarations
        ms = re.match(
            r"^(?!\s*end\s+subroutine\b)\s*(?:(?:pure|elemental|recursive)\s+)*subroutine\s+([a-z_]\w*)\s*\(",
            sl,
            re.I,
        )
        if ms:
            defs.append(ms.group(1))
            continue

        # use statements
        mu = re.match(r"^use\s*(?:,\s*intrinsic\s*)?(?:::)?\s*([a-z_]\w*)\s*(.*)$", sl, re.I)
        if mu:
            mod = mu.group(1)
            tail = mu.group(2).strip()
            intrinsic = bool(re.search(r"\bintrinsic\b", sl, re.I))
            only_items: list[str] | None = None
            mo = re.search(r"\bonly\s*:\s*(.+)$", tail, re.I)
            if mo:
                only_raw = mo.group(1).strip()
                only_items = []
                for it in split_args(only_raw):
                    nm = it.strip()
                    if not nm:
                        continue
                    # For USE renames, keep the local imported name (a => b -> keep a).
                    if "=>" in nm:
                        nm = nm.split("=>", 1)[0].strip()
                    nm = nm.strip()
                    if re.match(r"^[a-z_]\w*$", nm, re.I):
                        only_items.append(nm)
            uses.append(UseSpec(module=mod, only_items=only_items, intrinsic=intrinsic))
            continue

    i = 0
    n = len(code_lines)
    while i < n:
        s = code_lines[i].strip()
        mgi = re.match(r"^interface(?:\s+([a-z_]\w*))?\s*$", s, re.I)
        if not mgi:
            i += 1
            continue
        gname = mgi.group(1)
        block: list[str] = []
        i += 1
        while i < n and not re.match(r"^\s*end\s+interface\b", code_lines[i], re.I):
            block.append(code_lines[i].strip())
            i += 1
        if i < n:
            i += 1
        if not gname:
            continue
        has_module_proc = any(re.match(r"^module\s+procedure\b", b, re.I) for b in block)
        if has_module_proc:
            defs.append(gname)

    return unique_preserve(mods), unique_preserve(defs), uses


def _extract_generic_interfaces(lines: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[dict[str, list[str]]]]:
    """Extract generic interface blocks that name module procedures."""
    filtered: list[tuple[str, str]] = []
    generics: list[dict[str, list[str]]] = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i][0].strip()
        m = re.match(r"^interface(?:\s+([a-z_]\w*))?\s*$", s, re.I)
        if not m:
            filtered.append(lines[i])
            i += 1
            continue
        gname = m.group(1)
        block: list[tuple[str, str]] = []
        i += 1
        while i < n and not re.match(r"^\s*end\s+interface\b", lines[i][0], re.I):
            block.append(lines[i])
            i += 1
        if i < n:
            i += 1
        procs: list[str] = []
        for code, _comment in block:
            mm = re.match(r"^\s*module\s+procedure\s+(.+)$", code.strip(), re.I)
            if mm:
                procs.extend([p.strip() for p in split_args(mm.group(1)) if p.strip()])
        if gname and procs:
            generics.append({"name": gname, "procedures": unique_preserve(procs)})
        else:
            filtered.append((s, ""))
            filtered.extend(block)
            filtered.append(("end interface", ""))
    return filtered, generics


def _insert_imports(py_text: str, import_lines: list[str]) -> str:
    if not import_lines:
        return py_text
    lines = py_text.splitlines()
    insert_at = 0
    while insert_at < len(lines):
        s = lines[insert_at].strip()
        if s.startswith("import ") or s.startswith("from "):
            insert_at += 1
            continue
        if s == "":
            insert_at += 1
            break
        break
    merged = lines[:insert_at] + import_lines + ([""] if import_lines and (insert_at < len(lines) and lines[insert_at].strip() != "") else []) + lines[insert_at:]
    return "\n".join(merged).rstrip() + "\n"


def collapse_fortran_continuations(raw_lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Collapse free-form continuation lines joined with trailing/leading '&'."""
    out: list[tuple[str, str]] = []
    i = 0
    n = len(raw_lines)
    while i < n:
        code, comment = raw_lines[i]
        cur_code = code.rstrip()
        cur_comment = comment
        while cur_code.rstrip().endswith("&"):
            cur_code = cur_code.rstrip()
            cur_code = cur_code[:-1].rstrip()
            i += 1
            if i >= n:
                break
            ncode, ncomment = raw_lines[i]
            s = ncode.lstrip()
            if s.startswith("&"):
                s = s[1:].lstrip()
            if cur_code and s:
                cur_code = f"{cur_code} {s}"
            else:
                cur_code = cur_code + s
            if ncomment.strip():
                if cur_comment.strip():
                    cur_comment = f"{cur_comment.strip()} | {ncomment.strip()}"
                else:
                    cur_comment = ncomment
        out.append((cur_code, cur_comment))
        i += 1
    return out


def find_matching_paren(text: str, open_pos: int) -> int:
    depth = 0
    in_str = False
    q = ""
    for p in range(open_pos, len(text)):
        ch = text[p]
        if in_str:
            if ch == q:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            q = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return p
    return -1


def split_args(s: str) -> list[str]:
    args: list[str] = []
    buf: list[str] = []
    pdepth = 0
    bdepth = 0
    in_str = False
    quote = ""
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            pdepth += 1
            buf.append(ch)
            continue
        if ch == ")":
            pdepth = max(0, pdepth - 1)
            buf.append(ch)
            continue
        if ch == "[":
            bdepth += 1
            buf.append(ch)
            continue
        if ch == "]":
            bdepth = max(0, bdepth - 1)
            buf.append(ch)
            continue
        if ch == "," and pdepth == 0 and bdepth == 0:
            arg = "".join(buf).strip()
            if arg:
                args.append(arg)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args

def split_top_level(s: str, delim: str, preserve_empty: bool = False) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    pdepth = 0
    bdepth = 0
    in_str = False
    quote = ""
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == '(':
            pdepth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ')':
            pdepth = max(0, pdepth - 1)
            buf.append(ch)
            i += 1
            continue
        if ch == '[':
            bdepth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ']':
            bdepth = max(0, bdepth - 1)
            buf.append(ch)
            i += 1
            continue
        if ch == delim and pdepth == 0 and bdepth == 0:
            parts.append(''.join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail or not parts or preserve_empty:
        parts.append(tail)
    return parts

def split_top_level_concat(s: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    pdepth = 0
    bdepth = 0
    in_str = False
    quote = ""
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == '(':
            pdepth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ')':
            pdepth = max(0, pdepth - 1)
            buf.append(ch)
            i += 1
            continue
        if ch == '[':
            bdepth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ']':
            bdepth = max(0, bdepth - 1)
            buf.append(ch)
            i += 1
            continue
        if i + 1 < n and s[i:i + 2] == '//' and pdepth == 0 and bdepth == 0:
            parts.append(''.join(buf).strip())
            buf = []
            i += 2
            continue
        buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail or not parts:
        parts.append(tail)
    return parts

def _fortran_unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", "\""):
        q = s[0]
        return s[1:-1].replace(q + q, q)
    return s


def _is_fortran_string_literal(s: str) -> bool:
    s = s.strip()
    if len(s) < 2 or s[0] not in ("'", "\""):
        return False
    q = s[0]
    i = 1
    n = len(s)
    while i < n:
        if s[i] == q:
            if i + 1 < n and s[i + 1] == q:
                i += 2
                continue
            i += 1
            while i < n and s[i].isspace():
                i += 1
            return i == n
        i += 1
    return False


def _rewrite_fortran_string_literals(s: str) -> str:
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch not in ("'", '"'):
            out.append(ch)
            i += 1
            continue
        q = ch
        j = i + 1
        while j < n:
            if s[j] == q:
                if j + 1 < n and s[j + 1] == q:
                    j += 2
                    continue
                lit = s[i:j + 1]
                out.append(repr(_fortran_unquote(lit)))
                i = j + 1
                break
            j += 1
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _strip_one_outer_paren(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == "(" and s[-1] == ")" and find_matching_paren(s, 0) == len(s) - 1:
        return s[1:-1].strip()
    return s


def _fortran_implied_do_expr(raw: str, translate_expr, arrays_1d: set[str]) -> str | None:
    """Translate an I/O implied-DO item, including nested implied-DOs."""
    s = raw.strip()
    if not (len(s) >= 2 and s[0] == "(" and s[-1] == ")" and find_matching_paren(s, 0) == len(s) - 1):
        return None
    inner = s[1:-1].strip()
    parts = [p.strip() for p in split_args(inner) if p.strip()]
    if len(parts) < 3:
        return None

    obj_parts: list[str] | None = None
    var = lo = hi = step = None

    if len(parts) >= 4:
        mm = re.fullmatch(r"([a-z_]\w*)\s*=\s*(.+)", parts[-3], re.I)
        if mm:
            obj_parts = parts[:-3]
            var = mm.group(1)
            lo = mm.group(2).strip()
            hi = parts[-2]
            step = parts[-1]
    if obj_parts is None:
        mm = re.fullmatch(r"([a-z_]\w*)\s*=\s*(.+)", parts[-2], re.I)
        if mm:
            obj_parts = parts[:-2]
            var = mm.group(1)
            lo = mm.group(2).strip()
            hi = parts[-1]
            step = None
    if obj_parts is None or not obj_parts or var is None or lo is None or hi is None:
        return None

    lo_py = translate_expr(lo, arrays_1d)
    hi_py = translate_expr(hi, arrays_1d)
    if step is None:
        step_py = "1"
    else:
        step_py = translate_expr(step, arrays_1d)

    body_parts: list[str] = []
    for p in obj_parts:
        nested_py = _fortran_implied_do_expr(p, translate_expr, arrays_1d)
        if nested_py is not None:
            body_parts.append(nested_py)
        else:
            expr_py = translate_expr(p, arrays_1d)
            body_parts.append(f"[{expr_py}]")

    if len(body_parts) == 1:
        body_py = body_parts[0]
    else:
        body_py = " + ".join(body_parts)
    return f"_xf2p_implied_do(lambda {var}: {body_py}, {lo_py}, {hi_py}, {step_py})"


def _is_recyclable_io_iterable(raw: str, decl_array_types: dict[str, str]) -> bool:
    s = raw.strip()
    if (
        s.startswith('[')
        or s.startswith('(/')
        or _fortran_implied_do_expr(s, lambda x, _a: x, set()) is not None
        or (re.fullmatch(r"[a-z_]\w*", s, flags=re.I) and s.lower() in decl_array_types)
    ):
        return True
    concat_parts = split_top_level_concat(s)
    if len(concat_parts) > 1:
        return any(_is_recyclable_io_iterable(part, decl_array_types) for part in concat_parts)
    return False


def _fortran_format_arg_count(fmt_literal: str) -> int | None:
    """Return the number of data items consumed by one pass of a limited format."""
    try:
        fmt_text = _strip_one_outer_paren(_fortran_unquote(fmt_literal.strip()))
    except Exception:
        return None

    def count_token(tok: str) -> int | None:
        tok = tok.strip()
        if not tok:
            return 0
        low = tok.lower()

        if tok[0] in ("'", '"') and tok[-1] == tok[0]:
            return 0

        mm = re.fullmatch(r"\*\((.*)\)", tok, re.I)
        if mm:
            return None

        mm = re.fullmatch(r"(\d+)\((.*)\)", tok, re.I)
        if mm:
            rep = int(mm.group(1))
            inner_total = 0
            for sub in split_args(mm.group(2).strip()):
                nsub = count_token(sub)
                if nsub is None:
                    return None
                inner_total += nsub
            return rep * inner_total

        mm = re.fullmatch(r"(\d*)/", low)
        if mm:
            return 0

        if low == ":":
            return 0

        mm = re.fullmatch(r"(\d*)x", low)
        if mm:
            return 0

        mm = re.fullmatch(r"(\d*)a(\d+)?", low)
        if mm:
            return int(mm.group(1) or "1")

        mm = re.fullmatch(r"(\d*)l(\d+)", low)
        if mm:
            return int(mm.group(1) or "1")

        mm = re.fullmatch(r"(\d*)i(\d+)(?:\.\d+)?", low)
        if mm:
            return int(mm.group(1) or "1")

        mm = re.fullmatch(r"(\d*)(es|en|e|d|g|f)(\d+)(?:\.(\d+))?(?:e(\d+))?", low)
        if mm:
            return int(mm.group(1) or "1")

        if tok.startswith("(") and tok.endswith(")") and find_matching_paren(tok, 0) == len(tok) - 1:
            total = 0
            for sub in split_args(tok[1:-1]):
                nsub = count_token(sub)
                if nsub is None:
                    return None
                total += nsub
            return total

        return None

    total = 0
    for item in split_args(fmt_text):
        nitem = count_token(item)
        if nitem is None:
            return None
        total += nitem
    return total



def _fortran_format_recycled_expr(fmt_literal: str, iterable_expr: str) -> str | None:
    """Return a Python expression for one-argument finite-format recycling over an iterable."""
    if _fortran_format_arg_count(fmt_literal) != 1:
        return None
    item_expr = _fortran_format_expr(fmt_literal, ["_xf2p_item"])
    if item_expr is None:
        return None
    # For finite format reversion during output, each new cycle starts a new record.
    return f"'\\n'.join({item_expr} for _xf2p_item in {iterable_expr})"


def _single_iterable_formatted_arg_plan(fmt_literal: str, raw_args: list[str], decl_array_types: dict[str, str]) -> tuple[int, int] | None:
    """Plan finite-format expansion when exactly one I/O argument is an iterable."""
    total = _fortran_format_arg_count(fmt_literal)
    if total is None:
        return None
    iterable_pos = [i for i, raw in enumerate(raw_args) if _is_recyclable_io_iterable(raw, decl_array_types)]
    if len(iterable_pos) != 1:
        return None
    pos = iterable_pos[0]
    needed = total - (len(raw_args) - 1)
    if needed <= 0:
        return None
    return pos, needed


def _fortran_format_expr(fmt_literal: str, arg_exprs: list[str]) -> str | None:
    """Return a Python expression for a limited Fortran character format string."""
    try:
        fmt_text = _strip_one_outer_paren(_fortran_unquote(fmt_literal.strip()))
    except Exception:
        return None

    parts: list[str] = []
    arg_i = 0
    STOP = "__xf2p_stop__"

    def take_arg() -> str | None:
        nonlocal arg_i
        if arg_i >= len(arg_exprs):
            return None
        out = arg_exprs[arg_i]
        arg_i += 1
        return out

    def add_token(tok: str) -> str:
        nonlocal arg_i
        tok = tok.strip()
        if not tok:
            return "ok"
        low = tok.lower()

        mm = re.fullmatch(r"\*\((.*)\)", tok, re.I)
        if mm:
            inner = mm.group(1).strip()
            if arg_i >= len(arg_exprs):
                return "ok"
            iterable = arg_exprs[arg_i]
            arg_i += 1
            inner_items = split_args(inner)
            if ":" in [it.strip().lower() for it in inner_items]:
                colon_i = next(i for i, it in enumerate(inner_items) if it.strip().lower() == ":")
                left = ",".join(inner_items[:colon_i]).strip()
                right = ",".join(inner_items[colon_i + 1:]).strip()
                if left and right:
                    left_n = _fortran_format_arg_count(repr("(" + left + ")"))
                    right_n = _fortran_format_arg_count(repr("(" + right + ")"))
                    if left_n == 1 and right_n == 0:
                        item_expr = _fortran_format_expr(repr("(" + left + ")"), ["_xf2p_item"])
                        sep_expr = _fortran_format_expr(repr("(" + right + ")"), [])
                        if item_expr is not None and sep_expr is not None:
                            parts.append(f"({sep_expr}).join({item_expr} for _xf2p_item in {iterable})")
                            return "ok"
            inner_expr = _fortran_format_expr(repr("(" + inner + ")"), ["_xf2p_item"])
            if inner_expr is None:
                return "fail"
            parts.append(f"''.join({inner_expr} for _xf2p_item in {iterable})")
            return "ok"

        if tok[0] in ("'", '"') and tok[-1] == tok[0]:
            parts.append(repr(_fortran_unquote(tok)))
            return "ok"

        mm = re.fullmatch(r"(\d+)\((.*)\)", tok, re.I)
        if mm:
            rep = int(mm.group(1))
            inner = mm.group(2).strip()
            inner_items = split_args(inner)
            for _ in range(rep):
                for sub in inner_items:
                    status = add_token(sub)
                    if status == "fail":
                        return "fail"
                    if status == STOP:
                        return STOP
            return "ok"

        mm = re.fullmatch(r"(\d*)/", low)
        if mm:
            rep = int(mm.group(1) or "1")
            parts.append(repr("\n" * rep))
            return "ok"

        if low == ":":
            if arg_i >= len(arg_exprs):
                return STOP
            return "ok"

        mm = re.fullmatch(r"(\d*)x", low)
        if mm:
            rep = int(mm.group(1) or "1")
            if rep == 1:
                parts.append(repr(" "))
            else:
                parts.append(f"{rep}*' '")
            return "ok"

        mm = re.fullmatch(r"(\d*)a(\d+)?", low)
        if mm:
            rep = int(mm.group(1) or "1")
            width = mm.group(2)
            for _ in range(rep):
                a = take_arg()
                if a is None:
                    return STOP
                if width is None:
                    parts.append(f"str({a})")
                else:
                    parts.append(f"str({a}).rjust({int(width)})")
            return "ok"

        mm = re.fullmatch(r"(\d*)l(\d+)", low)
        if mm:
            rep = int(mm.group(1) or "1")
            width = int(mm.group(2))
            for _ in range(rep):
                a = take_arg()
                if a is None:
                    return STOP
                parts.append(f"str(bool({a})).upper().replace('TRUE', 'T').replace('FALSE', 'F').rjust({width})")
            return "ok"

        mm = re.fullmatch(r"(\d*)i(\d+)(?:\.\d+)?", low)
        if mm:
            rep = int(mm.group(1) or "1")
            width = int(mm.group(2))
            for _ in range(rep):
                a = take_arg()
                if a is None:
                    return STOP
                if width == 0:
                    parts.append(f"str(int({a}))")
                else:
                    parts.append(f"format(int({a}), '{width}d')")
            return "ok"

        mm = re.fullmatch(r"(\d*)(es|en|e|d|g|f)(\d+)(?:\.(\d+))?(?:e(\d+))?", low)
        if mm:
            rep = int(mm.group(1) or "1")
            code = mm.group(2)
            width = int(mm.group(3))
            prec = mm.group(4)
            py_code = {"d": "E", "e": "E", "es": "E", "en": "E", "f": "f", "g": "G"}[code]
            spec = f"{width}.{int(prec)}{py_code}" if prec is not None else f"{width}{py_code}"
            for _ in range(rep):
                a = take_arg()
                if a is None:
                    return STOP
                parts.append(f"format(float({a}), '{spec}')")
            return "ok"

        if tok.startswith("(") and tok.endswith(")") and find_matching_paren(tok, 0) == len(tok) - 1:
            for sub in split_args(tok[1:-1]):
                status = add_token(sub)
                if status == "fail":
                    return "fail"
                if status == STOP:
                    return STOP
            return "ok"

        return "fail"

    items = split_args(fmt_text)
    if not items:
        return repr("")
    for item in items:
        status = add_token(item)
        if status == "fail":
            return None
        if status == STOP:
            break
    if arg_i < len(arg_exprs):
        for a in arg_exprs[arg_i:]:
            parts.append(f"str({a})")
    if not parts:
        return repr("")
    return " + ".join(parts)



def unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = it.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _find_dups_ci(items: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for it in items:
        key = it.strip().lower()
        if key in seen and key not in dups:
            dups.append(key)
        seen.add(key)
    return dups


_type_scalar_hint = {
    "integer": "int",
    "real": "np.float64",
    "logical": "bool",
    "complex": "complex",
    "character": "str",
}

_type_default_scalar_value = {
    "integer": "0",
    "real": "np.float64(0.0)",
    "logical": "False",
    "complex": "0j",
    "character": repr(""),
}

_type_dtype = {
    "integer": "np.int_",
    "real": "np.float64",
    "logical": "np.bool_",
    "complex": "np.complex128",
    "character": "object",
}

_type_ndarray_hint = {
    "integer": "npt.NDArray[np.int_]",
    "real": "npt.NDArray[np.float64]",
    "logical": "npt.NDArray[np.bool_]",
    "complex": "npt.NDArray[np.complex128]",
    "character": "npt.NDArray[object]",
}

_type_target_scalar_hint = {
    "integer": "npt.NDArray[np.int_]",
    "real": "npt.NDArray[np.float64]",
    "logical": "npt.NDArray[np.bool_]",
    "complex": "npt.NDArray[np.complex128]",
}

_LOCAL_RUNTIME_HELPERS = {
    "_f_size",
    "_f_spread",
    "_f_assign_array",
    "mean_1d",
    "var_1d",
    "argsort_real",
    "random_normal_vec",
    "random_choice2",
    "random_choice_prob",
    "random_choice_norep",
}

_INTRINSIC_ARGUMENTS = {
    'product': (('array', 'dim', 'mask'), 1),
    'unpack': (('vector', 'mask', 'field'), 3),
    'cshift': (('array', 'shift', 'dim'), 2),
    'eoshift': (('array', 'shift', 'boundary', 'dim'), 2),
    'is_contiguous': (('array',), 1),
    'adjustr': (('string',), 1),
    'scan': (('string', 'set', 'back', 'kind'), 2),
    'verify': (('string', 'set', 'back', 'kind'), 2),
    'repeat': (('string', 'ncopies'), 2),
    'command_argument_count': ((), 0),
    'btest': (('i', 'pos'), 2), 'ibset': (('i', 'pos'), 2),
    'ibclr': (('i', 'pos'), 2), 'ibits': (('i', 'pos', 'len'), 3),
    'iand': (('i', 'j'), 2), 'ior': (('i', 'j'), 2), 'ieor': (('i', 'j'), 2),
    'shiftl': (('i', 'shift'), 2), 'shiftr': (('i', 'shift'), 2),
}
_BIT_INTRINSICS = {'btest', 'ibset', 'ibclr', 'ibits', 'iand', 'ior', 'ieor', 'shiftl', 'shiftr'}


def _bind_intrinsic_arguments(name, text, parameters, required):
    bound = {}
    keyword_seen = False
    for part in split_args(text) if text.strip() else []:
        keyword = re.match(r'^([a-z_]\w*)\s*=(?!=)\s*(.+)$', part.strip(), re.I)
        if keyword:
            key, value = keyword.group(1).lower(), keyword.group(2)
            keyword_seen = True
        else:
            if keyword_seen:
                raise ValueError(f'{name.upper()}: positional argument after keyword')
            key = next((p for p in parameters if p not in bound), '')
            value = part.strip()
        if not value or key not in parameters or key in bound:
            raise ValueError(f'{name.upper()}: invalid or duplicate argument {key}')
        bound[key] = value
    if any(p not in bound for p in parameters[:required]):
        raise ValueError(f'{name.upper()}: missing required argument')
    return bound


def infer_function_result_ftype(header: str) -> str | None:
    """Infer scalar Fortran result type from function header when explicit.

    Examples:
      pure integer function f(...)
      real(kind=dp) pure function g(...)
    """
    h = header.strip()
    m = re.search(r"\b(integer|real|logical|complex)\b(?:\s*\([^)]*\))?\b[^!\n]*\bfunction\b", h, re.I)
    if not m:
        return None
    return m.group(1).lower()

_decl_re = re.compile(r"^(integer|real|logical|complex|character(?:\s*\([^)]*\))?)\b(.*)$", re.I)


def _find_top_level_double_colon(s: str) -> int:
    in_str = False
    quote = ""
    pdepth = 0
    bdepth = 0
    i = 0
    n = len(s)
    while i < n - 1:
        ch = s[i]
        if in_str:
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            i += 1
            continue
        if ch == "(":
            pdepth += 1
            i += 1
            continue
        if ch == ")":
            pdepth = max(0, pdepth - 1)
            i += 1
            continue
        if ch == "[":
            bdepth += 1
            i += 1
            continue
        if ch == "]":
            bdepth = max(0, bdepth - 1)
            i += 1
            continue
        if pdepth == 0 and bdepth == 0 and s.startswith("::", i):
            return i
        i += 1
    return -1


def parse_decl(line: str):
    s = line.strip()
    pos = _find_top_level_double_colon(s)
    if pos == -1:
        return None
    lhs = s[:pos].strip()
    rest = s[pos + 2 :].strip()
    m = _decl_re.match(lhs)
    if not m:
        return None
    ftype = m.group(1).lower()
    if ftype.startswith("character"):
        ftype = "character"
    attrs = m.group(2).strip().rstrip(",").strip()
    return ftype, attrs, rest


def parse_decl_attr_dimension(attrs: str) -> str | None:
    m = re.search(r"\bdimension\s*\(\s*(.*?)\s*\)", attrs, re.I)
    if not m:
        return None
    return m.group(1).strip()


def parse_decl_items(rest: str, default_shape: str | None = None):
    items = []

    def _split_init(part: str):
        """Split a declaration item into (lhs, init, op).

        Fortran allows both normal initialization ("=") and pointer
        initialization ("=>") in declaration lists.

        We must treat "=>" as a single token (not as "=" + ">") so that
        pointer initializers don't leak stray ">" characters into Python.
        """
        in_str = False
        quote = ""
        pdepth = 0
        bdepth = 0
        i = 0
        n = len(part)
        while i < n:
            ch = part[i]
            if in_str:
                if ch == quote:
                    in_str = False
                i += 1
                continue
            if ch in ("'", '"'):
                in_str = True
                quote = ch
                i += 1
                continue
            if ch == "(":
                pdepth += 1
                i += 1
                continue
            if ch == ")":
                pdepth = max(0, pdepth - 1)
                i += 1
                continue
            if ch == "[":
                bdepth += 1
                i += 1
                continue
            if ch == "]":
                bdepth = max(0, bdepth - 1)
                i += 1
                continue
            if pdepth == 0 and bdepth == 0:
                if part.startswith("=>", i):
                    return part[:i].strip(), part[i + 2 :].strip(), "=>"
                if ch == "=":
                    return part[:i].strip(), part[i + 1 :].strip(), "="
            i += 1
        return part.strip(), None, None

    for part in split_args(rest):
        part = part.strip()
        if not part:
            continue

        left, init, _op = _split_init(part)

        shape = None
        mm = re.match(r"^([a-z_]\w*)\s*\(\s*(.+)\s*\)\s*$", left, re.I)
        if mm:
            name = mm.group(1)
            shape = mm.group(2).strip()
        else:
            name = left
            shape = default_shape

        items.append((name, shape, init))

    return items


class basic_f2p:
    def __init__(self) -> None:
        self.out: list[str] = []
        self.indent = 0
        self.seen_parameter = False
        self._code_emit_count = 0
        self._block_code_start: list[int] = []
        self._decl_types: dict[str, str] = {}
        self._decl_array_types: dict[str, str] = {}
        self._decl_pointer: set[str] = set()
        self._decl_target: set[str] = set()
        self._decl_char_len: dict[str, str] = {}
        self._decl_lbounds: dict[str, list[str]] = {}
        self._decl_ubounds: dict[str, list[str]] = {}
        self._save_stack: list[tuple[str, list[str]]] = []
        self._host_scopes: list[tuple[dict[str, dict], str]] = []
        self._subr_sigs: dict[str, dict] = {}
        self._func_sigs: dict[str, dict] = {}
        self._current_result_name: str | None = None
        self._derived_types: set[str] = set()
        self._type_bindings: dict[str, dict[str, dict]] = {}
        self._type_components: dict[str, dict[str, str]] = {}
        self._component_specs: dict[str, dict[str, dict]] = {}
        self._allocation_counter = 0
        self._allocation_bound_names: dict[str, str] = {}
        self._allocation_source = ""
        self._decl_type_names: dict[str, str] = {}
        self._binding_targets: dict[str, dict] = {}
        self._select_case_stack: list[dict[str, object]] = []
        self._associate_stack: list[dict[str, object]] = []
        self._where_stack: list[dict[str, str]] = []
        self._forall_stack: list[int] = []
        self._do_stack: list[dict[str, object] | int] = []
        self._loop_counter = 0
        self._seen_scipy_special = False
        self._elemental_funcs: set[str] = set()

    def _kind_alias_value(self, remote: str) -> str | None:
        r = remote.strip().lower()
        mapping = {
            "real32": "4",
            "real64": "8",
            "int8": "1",
            "int16": "2",
            "int32": "4",
            "int64": "8",
        }
        return mapping.get(r)

    def _emit_intrinsic_use_aliases(self, lines: list[tuple[str, str]]) -> None:
        for code, _comment in lines:
            s = code.strip()
            mu = re.match(r"^use\b\s*(?:,\s*(intrinsic|non_intrinsic)\s*)?(?:::)?\s*([a-z_]\w*)\s*(.*)$", s, re.I)
            if not mu:
                continue
            if (mu.group(1) or "").lower() == "non_intrinsic":
                continue
            mod = mu.group(2).strip().lower()
            tail = mu.group(3).strip()
            if mod != "iso_fortran_env":
                continue
            mo = re.search(r"\bonly\s*:\s*(.+)$", tail, re.I)
            items = split_args(mo.group(1).strip()) if mo else [
                "int8", "int16", "int32", "int64", "real32", "real64"]
            if not mo:
                renames = split_args(tail.lstrip(",").strip()) if tail.strip() else []
                # Without ONLY, a renamed remote is not imported under its old name.
                for item in renames:
                    if "=>" in item:
                        remote = item.split("=>", 1)[1].strip().lower()
                        items = [p for p in items if p.lower() != remote]
                        items.append(item)
            for it in items:
                nm = it.strip()
                if not nm:
                    continue
                if "=>" in nm:
                    local_name, remote_name = [p.strip() for p in nm.split("=>", 1)]
                else:
                    local_name = nm.strip()
                    remote_name = nm.strip()
                alias_val = self._kind_alias_value(remote_name)
                if alias_val is not None and re.match(r"^[a-z_]\w*$", local_name, re.I):
                    self.emit(f"{local_name} = {alias_val}")

    def _type_hint(self, ftype: str, type_name: str | None = None, is_array: bool = False) -> str:
        if ftype == "type":
            if is_array:
                return "npt.NDArray[object]"
            return type_name if type_name else "SimpleNamespace"
        if is_array:
            return _type_ndarray_hint.get(ftype, "npt.NDArray[np.float64]")
        return _type_scalar_hint.get(ftype, "int")

    def _parse_decl_line(self, s: str):
        pd = parse_decl(s)
        if pd:
            ftype, attrs, rest = pd
            return ftype, None, attrs.lower(), parse_decl_items(rest, parse_decl_attr_dimension(attrs))
        td = re.match(r"^(?:type|class)\s*\(\s*([a-z_]\w*)\s*\)\s*(.*?)::\s*(.*)$", s, re.I)
        if td:
            attrs = td.group(2).strip()
            return "type", td.group(1), attrs.lower(), parse_decl_items(td.group(3).strip(), parse_decl_attr_dimension(attrs))
        return None

    def _parse_character_len(self, decl_line: str) -> str | None:
        s = decl_line.strip()
        m = re.search(r"\bcharacter\s*\(", s, re.I)
        if m:
            p0 = s.find("(", m.start())
            p1 = find_matching_paren(s, p0)
            if p0 != -1 and p1 != -1:
                inner = s[p0 + 1 : p1].strip()
                for part in split_args(inner):
                    mm = re.match(r"^len\s*=\s*(.+)$", part.strip(), re.I)
                    if mm:
                        return mm.group(1).strip()
                parts = [p.strip() for p in split_args(inner) if p.strip()]
                if parts and all(("kind" not in p.lower()) and ("=" not in p) for p in parts):
                    return parts[0]
        m = re.search(r"\bcharacter\s*\*\s*([a-z_]\w*|\d+)", s, re.I)
        if m:
            return m.group(1).strip()
        return None

    def _collect_save_names(self, lines: list[tuple[str, str]], sym: dict[str, dict], args: list[str]) -> list[str]:
        save_names: set[str] = set()
        arg_set = {a.lower() for a in args}
        for name, info in sym.items():
            if name in getattr(self, "_block_local_names", set()):
                continue
            attrs_l = str(info.get("attrs_l", "")).lower()
            if name.lower() in arg_set:
                continue
            if "save" in attrs_l or info.get("init") is not None:
                save_names.add(name)
        for code, _comment in lines:
            s = code.strip()
            if re.fullmatch(r"save", s, re.I):
                for name in sym:
                    if name.lower() not in arg_set and name not in getattr(self, "_block_local_names", set()):
                        save_names.add(name)
                continue
            m = re.match(r"save\s*(?:::)?\s*(.+)$", s, re.I)
            if m:
                for item in split_args(m.group(1)):
                    nm = item.strip()
                    if nm and nm.lower() not in arg_set and nm in sym:
                        save_names.add(nm)
        return sorted(save_names)

    def _emit_save_restore(self, save_dict_name: str, save_names: list[str], sym: dict[str, dict], arrays_1d: set[str]) -> None:
        for name in save_names:
            info = sym.get(name, {})
            ftype = info.get("ftype")
            is_array = bool(info.get("is_array"))
            init = info.get("init")
            if is_array:
                shape = info.get("shape")
                if shape is None:
                    init_py = "None"
                else:
                    shape_py = self._shape_to_py(str(shape), arrays_1d)
                    if ftype == "type":
                        init_py = f"np.empty({shape_py}, dtype=object)"
                    else:
                        dtype = _type_dtype.get(ftype, "object")
                        if init is None:
                            init_py = f"np.empty({shape_py}, dtype={dtype})"
                        else:
                            rhs = self.translate_expr(str(init), arrays_1d)
                            if ftype == "character" and info.get("char_len") is not None:
                                clen = self.translate_expr(str(info.get("char_len")), arrays_1d)
                                rhs = f"_f_str_assign({rhs}, {clen})"
                            init_py = f"np.full({shape_py}, {rhs}, dtype={dtype})"
            else:
                if ftype == "type":
                    cls = info.get("type_name") or "SimpleNamespace"
                    init_py = f"{cls}()"
                elif init is None:
                    default_val = _type_default_scalar_value.get(ftype, "0")
                    if ftype == "character" and info.get("char_len") is not None:
                        clen = self.translate_expr(str(info.get("char_len")), arrays_1d)
                        default_val = f"_f_str_assign({default_val}, {clen})"
                    init_py = default_val
                else:
                    init_py = self.translate_expr(str(init), arrays_1d)
                    if ftype == "character" and info.get("char_len") is not None:
                        clen = self.translate_expr(str(info.get("char_len")), arrays_1d)
                        init_py = f"_f_str_assign({init_py}, {clen})"
            self.emit(f"if {name!r} in {save_dict_name}:")
            self.indent += 1
            self.emit(f"{name} = _xf2p_copy_value({save_dict_name}[{name!r}])")
            self.indent -= 1
            self.emit("else:")
            self.indent += 1
            self.emit(f"{name} = _xf2p_copy_value({init_py})")
            self.indent -= 1

    def _emit_save_sync(self) -> None:
        if not self._save_stack:
            return
        save_dict_name, save_names = self._save_stack[-1]
        for name in save_names:
            self.emit(f"{save_dict_name}[{name!r}] = _xf2p_copy_value({name})")

    def _validate_unit_symbols(self, unit_kind: str, unit_name: str, args: list[str], body_lines: list[tuple[str, str]]) -> None:
        dups = _find_dups_ci(args)
        if dups:
            raise ValueError(f"{unit_kind} {unit_name}: duplicate formal argument(s): {', '.join(dups)}")

        # Track declarations by lexical scope. A `block ... end block` introduces
        # a nested scope that may legitimately redeclare names used elsewhere.
        # Use a scope-id stack (not just depth), because sibling blocks share depth.
        seen_decl: dict[tuple[tuple[int, ...], str], tuple] = {}
        scope_stack: list[int] = [0]
        next_scope_id = 1
        for i, (code, _comment) in enumerate(body_lines, start=1):
            s = code.strip()
            sl = s.lower()
            if re.match(r"^block\b", sl):
                scope_stack.append(next_scope_id)
                next_scope_id += 1
                continue
            if re.match(r"^end\s+block\b", sl):
                if len(scope_stack) > 1:
                    scope_stack.pop()
                continue
            parsed = self._parse_decl_line(s)
            if not parsed:
                continue
            ftype, type_name, attrs_l, items = parsed
            for name, shape, _init in items:
                key = (tuple(scope_stack), name.lower())
                sig = (
                    ftype,
                    (type_name or "").lower(),
                    shape is not None,
                    (shape or "").replace(" ", "").lower(),
                    attrs_l.replace(" ", ""),
                )
                if key in seen_decl:
                    prev = seen_decl[key]
                    if prev != sig:
                        raise ValueError(
                            f"{unit_kind} {unit_name}: conflicting declaration for '{name}' at body line {i}"
                        )
                    raise ValueError(
                        f"{unit_kind} {unit_name}: duplicate declaration for '{name}' at body line {i}"
                    )
                seen_decl[key] = sig


    def _is_function_header(self, s: str) -> bool:
        return bool(re.match(r"^(?!\s*end\s+function\b)\s*(?:(?:pure|elemental|recursive)\s+)*(?:\w+(?:\s*\([^)]*\))?\s+)*function\b", s, re.I))

    def _is_subroutine_header(self, s: str) -> bool:
        return bool(re.match(r"^(?!\s*end\s+subroutine\b)\s*(?:(?:pure|elemental|recursive)\s+)*subroutine\b", s, re.I))

    def _is_elemental_header(self, s: str) -> bool:
        return bool(re.search(r"\belemental\b", s, re.I))

    def _scalar_otype_expr(self, ftype: str | None, type_name: str | None = None) -> str:
        if ftype == "integer":
            return "np.int_"
        if ftype == "real":
            return "np.float64"
        if ftype == "logical":
            return "np.bool_"
        if ftype == "complex":
            return "np.complex128"
        return "object"

    def _collect_subprogram_body(self, lines: list[tuple[str, str]], start_idx: int, outer_kind: str) -> tuple[list[tuple[str, str]], int]:
        body: list[tuple[str, str]] = []
        i = start_idx
        n = len(lines)
        in_contains = False
        internal_depth = 0
        while i < n:
            code = lines[i][0]
            s = code.strip()
            sl = s.lower()
            if sl == "contains":
                in_contains = True
                body.append(lines[i])
                i += 1
                continue
            if in_contains:
                if self._is_function_header(s) or self._is_subroutine_header(s):
                    internal_depth += 1
                    body.append(lines[i])
                    i += 1
                    continue
                if re.match(r"^\s*end\s+function\b", s, re.I):
                    if outer_kind == "function" and internal_depth == 0:
                        break
                    if internal_depth > 0:
                        internal_depth -= 1
                    body.append(lines[i])
                    i += 1
                    continue
                if re.match(r"^\s*end\s+subroutine\b", s, re.I):
                    if outer_kind == "subroutine" and internal_depth == 0:
                        break
                    if internal_depth > 0:
                        internal_depth -= 1
                    body.append(lines[i])
                    i += 1
                    continue
            else:
                if re.match(rf"^\s*end\s+{re.escape(outer_kind)}\b", s, re.I):
                    break
            body.append(lines[i])
            i += 1
        return body, i

    def _split_internal_subprograms(self, body_lines: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str, list[tuple[str, str]]]]]:
        contains_idx = self._unit_contains_index(body_lines)
        if contains_idx is None:
            return body_lines, []
        main_lines = body_lines[:contains_idx]
        tail = body_lines[contains_idx + 1 :]
        internals: list[tuple[str, str, list[tuple[str, str]]]] = []
        i = 0
        n = len(tail)
        while i < n:
            line = tail[i][0].strip()
            if not line:
                i += 1
                continue
            if self._is_function_header(line):
                header = line
                body, end_idx = self._collect_subprogram_body(tail, i + 1, "function")
                internals.append(("function", header, body))
                i = end_idx + 1
                continue
            if self._is_subroutine_header(line):
                header = line
                body, end_idx = self._collect_subprogram_body(tail, i + 1, "subroutine")
                internals.append(("subroutine", header, body))
                i = end_idx + 1
                continue
            i += 1
        return main_lines, internals

    @staticmethod
    def _unit_contains_index(lines: list[tuple[str, str]]) -> int | None:
        """Find a unit's CONTAINS, not the binding section inside a type."""
        in_type = False
        for i, (code, _comment) in enumerate(lines):
            s = code.strip()
            if re.match(r"^end\s*type\b", s, re.I):
                in_type = False
            elif re.match(r"^type\b(?:\s*,[^:]*)?(?:\s*::\s*|\s+)[a-z_]\w*\s*$", s, re.I):
                in_type = True
            elif s.lower() == "contains" and not in_type:
                return i
        return None

    def _bound_signature(self, callee: str) -> dict | None:
        parts = callee.lower().replace("%", ".").split(".")
        type_name = self._decl_type_names.get(parts[0], "")
        for component in parts[1:-1]:
            type_name = self._type_components.get(type_name, {}).get(component, "")
        return self._type_bindings.get(type_name, {}).get(parts[-1])

    def _component_spec(self, reference: str) -> dict | None:
        path = reference.replace("%", ".")
        # Remove subscripts from the type path, including nested index calls.
        while True:
            stripped = re.sub(r"\([^()]*\)", "", path)
            if stripped == path:
                break
            path = stripped
        parts = [p.strip().lower() for p in path.split(".")]
        type_name = self._decl_type_names.get(parts[0], "")
        spec = None
        for field_name in parts[1:]:
            spec = self._component_specs.get(type_name, {}).get(field_name)
            if spec is None:
                return None
            type_name = spec.get("type_name") or ""
        return spec

    @staticmethod
    def _is_chained_subscript(reference: str) -> bool:
        opening = reference.find("(")
        if opening < 0:
            return False
        closing = find_matching_paren(reference, opening)
        return closing >= 0 and reference[closing + 1:].lstrip().startswith(("%", "."))

    def transpile_derived_type(self, header: str, body_lines: list[tuple[str, str]]) -> None:
        h = header.strip()
        m = re.match(r"^type\b(?:\s*,[^:]*)?(?:\s*::\s*|\s+)([a-z_]\w*)\s*$", h, re.I)
        if not m:
            return
        tname = m.group(1)
        self._derived_types.add(tname)
        bindings = self._type_bindings.setdefault(tname.lower(), {})
        components = self._type_components.setdefault(tname.lower(), {})
        component_specs = self._component_specs.setdefault(tname.lower(), {})

        self.emit("@dataclass")
        self.emit(f"class {tname}:")
        self.indent += 1
        had_field = False
        in_bindings = False
        for code, comment in body_lines:
            s = code.strip()
            if s.lower() == "contains":
                in_bindings = True
                continue
            if in_bindings:
                binding = re.match(r"^procedure\b\s*(?:\([^)]*\))?\s*(.*?)::\s*(.+)$", s, re.I)
                if not binding:
                    if s:
                        raise ValueError(f"unsupported type-bound declaration: {s}")
                    continue
                attrs = binding.group(1).lower()
                if "deferred" in attrs:
                    raise ValueError(f"unsupported deferred binding: {s}")
                for item in split_args(binding.group(2)):
                    pair = item.split("=>", 1)
                    name = pair[0].strip().lower()
                    target = pair[-1].strip().lower()
                    spec = self._binding_targets.get(target)
                    if spec is None:
                        raise ValueError(f"no translated procedure for binding {tname}%{name}: {target}")
                    passed = None
                    if not re.search(r"\bnopass\b", attrs):
                        named = re.search(r"\bpass\s*\(\s*(\w+)\s*\)", attrs)
                        passed = named.group(1) if named else (spec["args"][0] if spec["args"] else None)
                        if passed not in spec["args"]:
                            raise ValueError(f"invalid passed-object argument for {tname}%{name}")
                    args = [a for a in spec["args"] if a != passed]
                    outputs = [a for a in spec["out"] if a != passed]
                    bindings[name] = {"args": args, "out": outputs, "kind": spec["kind"]}
                    object_arg = _choose_fresh_identifier(" ".join(spec["args"]), "_xf2p_object")
                    formals = [object_arg] + [a + ("=None" if a in spec["optional"] else "") for a in args]
                    self.emit(f"def {name}({', '.join(formals)}):")
                    self.indent += 1
                    actuals = [f"{a}={object_arg if a == passed else a}" for a in spec["args"]]
                    call = f"{target}({', '.join(actuals)})"
                    if spec["kind"] == "function" or passed not in spec["out"]:
                        self.emit(f"return {call}")
                    elif not outputs:
                        self.emit(call)
                    else:
                        # Subroutines return their OUT/INOUT dummies, including
                        # the mutable passed object. Only expose explicit outputs.
                        self.emit(f"_xf2p_result = {call}")
                        indices = [spec["out"].index(a) for a in outputs]
                        self.emit("return " + ", ".join(f"_xf2p_result[{i}]" for i in indices))
                    self.indent -= 1
                    had_field = True
                continue
            pd = parse_decl(s)
            if pd:
                ftype, attrs, rest = pd
                attrs_l = attrs.lower()
                items = parse_decl_items(rest, parse_decl_attr_dimension(attrs))
                type_name = None
            else:
                td = re.match(r"^type\s*\(\s*([a-z_]\w*)\s*\)\s*(.*?)::\s*(.*)$", s, re.I)
                if not td:
                    continue
                ftype = "type"
                attrs_l = td.group(2).strip().lower()
                items = parse_decl_items(td.group(3).strip(), parse_decl_attr_dimension(td.group(2).strip()))
                type_name = td.group(1)
            for name, shape, init in items:
                component_specs[name.lower()] = {"ftype": ftype, "shape": shape,
                    "type_name": type_name.lower() if type_name else None,
                    "char_len": self._parse_character_len(s) if ftype == "character" else None}
                if type_name:
                    components[name.lower()] = type_name.lower()
                had_field = True
                cmt = f"  # {comment.strip()}" if comment.strip() else ""
                if shape is not None:
                    if "allocatable" in attrs_l or "pointer" in attrs_l:
                        self.emit(f"{name}: {self._type_hint(ftype, type_name, is_array=True)} | None = None{cmt}")
                        continue
                    shape_py = self._shape_to_py(shape, set())
                    dtype = "object" if ftype == "type" else _type_dtype[ftype]
                    if init is None and ftype != "type":
                        factory = f"np.empty({shape_py}, dtype={dtype})"
                    else:
                        init_py = self.translate_expr(init, set()) if init is not None else f"{type_name}()"
                        if ftype == "character":
                            length = self._parse_character_len(s)
                            if length is not None:
                                init_py = f"_f_str_assign({init_py}, {self.translate_expr(length, set())})"
                        factory = f"_f_init_component_array({shape_py}, {init_py}, {dtype})"
                    self.emit(f"{name}: {self._type_hint(ftype, type_name, is_array=True)} = field(default_factory=lambda: {factory}){cmt}")
                    continue
                if "allocatable" in attrs_l or "pointer" in attrs_l:
                    self.emit(f"{name}: {self._type_hint(ftype, type_name, is_array=False)} | None = None{cmt}")
                    continue
                if ftype == "type":
                    self.emit(f"{name}: {self._type_hint(ftype, type_name, is_array=False)} = field(default_factory={type_name}){cmt}")
                    continue
                hint = self._type_hint(ftype, None, is_array=False)
                if init is None:
                    default_val = _type_default_scalar_value.get(ftype, "0")
                else:
                    default_val = self.translate_expr(init, set())
                self.emit(f"{name}: {hint} = {default_val}{cmt}")
        if not had_field:
            self.emit("pass")
        self.indent = max(0, self.indent - 1)
        self.emit("")

    @staticmethod
    def _remove_top_level_def(lines: list[str], name: str) -> list[str]:
        start = None
        for i, ln in enumerate(lines):
            if re.match(rf"^def\s+{re.escape(name)}\s*\(", ln):
                start = i
                break
        if start is None:
            return lines
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if re.match(r"^(def|class)\s+\w+\s*\(|^@dataclass\b|^if __name__ == ", lines[j]):
                end = j
                break
        out = lines[:start]
        out.extend(lines[end:])
        while out and out[-1] == "":
            out.pop()
        return out

    @staticmethod
    def _drop_unused_runtime(lines: list[str]) -> list[str]:
        helper_names = [
            "_f_size",
            "_f_spread",
            "_f_assign_array",
            "mean_1d",
            "var_1d",
            "argsort_real",
            "random_normal_vec",
            "random_choice2",
            "random_choice_prob",
            "random_choice_norep",
        ]
        changed = True
        while changed:
            changed = False
            text = "\n".join(lines)
            for name in helper_names:
                # one reference means definition-only; remove it
                if len(re.findall(rf"\b{name}\s*\(", text)) <= 1:
                    new_lines = basic_f2p._remove_top_level_def(lines, name)
                    if len(new_lines) != len(lines):
                        lines = new_lines
                        text = "\n".join(lines)
                        changed = True

        # prune imports that are no longer needed
        def _drop_line(prefix: str) -> None:
            nonlocal lines
            lines = [ln for ln in lines if not ln.startswith(prefix)]

        text = "\n".join(lines)
        if "@dataclass" not in text:
            _drop_line("from dataclasses import dataclass")
        if "SimpleNamespace(" not in text:
            _drop_line("from types import SimpleNamespace")
        text = "\n".join(lines)
        if re.search(r"\bnpt\.", text) is None:
            _drop_line("import numpy.typing as npt")
        text = "\n".join(lines)
        if re.search(r"\bnp\.", text) is None:
            _drop_line("import numpy as np")
        text = "\n".join(lines)
        if re.search(r"\bsps\.", text) is None:
            _drop_line("import scipy.special as sps")
        return lines

    def emit(self, s: str = "") -> None:
        if s and not s.lstrip().startswith("#"):
            self._code_emit_count += 1
        self.out.append((" " * 4 * self.indent) + s if s else "")

    def emit_comment(self, c: str) -> None:
        cc = c.strip()
        if cc:
            self.emit(f"# {cc}")

    def _shape_to_py(self, shape: str, arrays_1d: set[str]) -> str:
        dims: list[str] = []
        for d in split_args(shape):
            ds = d.strip()
            if ":" in ds:
                p = ds.split(":", 1)
                lo = p[0].strip()
                hi = p[1].strip()
                if lo and hi:
                    if re.fullmatch(r"[+-]?\d+", lo) and lo == "1":
                        dims.append(self.translate_expr(hi, arrays_1d))
                    else:
                        lo_py = self.translate_expr(lo, arrays_1d)
                        hi_py = self.translate_expr(hi, arrays_1d)
                        dims.append(f"(({hi_py}) - ({lo_py}) + 1)")
                elif hi:
                    dims.append(self.translate_expr(hi, arrays_1d))
                else:
                    dims.append(ds)
            else:
                dims.append(self.translate_expr(ds, arrays_1d))
        if len(dims) == 1:
            return dims[0]
        return "(" + ", ".join(dims) + ")"

    def _shape_bounds(self, shape: str) -> list[tuple[str, str]]:
        bounds: list[tuple[str, str]] = []
        for d in split_args(shape):
            ds = d.strip()
            if ":" in ds:
                lo, hi = ds.split(":", 1)
                lo = lo.strip() or "1"
                hi = hi.strip()
                bounds.append((lo, hi))
            else:
                bounds.append(("1", ds))
        return bounds

    def _decl_bound_expr(self, name: str, dim0: int, which: str, arrays_1d: set[str]) -> str | None:
        key = name.split(".", 1)[0].lower()
        src = self._decl_lbounds if which == "lo" else self._decl_ubounds
        vals = src.get(key)
        if "." in name:
            spec = self._component_spec(name)
            bounds = self._shape_bounds(spec["shape"]) if spec and spec.get("shape") else []
            vals = [bound[0 if which == "lo" else 1] for bound in bounds]
        if not vals or dim0 < 0 or dim0 >= len(vals):
            return None
        raw = str(vals[dim0]).strip()
        if which == "hi":
            if raw == "":
                lo_vals = self._decl_lbounds.get(key)
                lo_raw = "1"
                if lo_vals and 0 <= dim0 < len(lo_vals):
                    lo_raw = str(lo_vals[dim0]).strip() or "1"
                lo_py = self.translate_expr(lo_raw, arrays_1d)
                base_name = name.split(".", 1)[0]
                return f"(_f_size({base_name}, dim={dim0 + 1}) + ({lo_py}) - 1)"
            if raw == "*":
                return None
        return self.translate_expr(raw, arrays_1d)

    def _index_expr_from_decl_bounds(self, name: str, idx_txt: str, dim0: int, arrays_1d: set[str]) -> str:
        idx_py = self.translate_expr(idx_txt, arrays_1d)
        lo_py = self._decl_bound_expr(name, dim0, "lo", arrays_1d)
        if lo_py is None or lo_py == "1":
            return f"({idx_py}) - 1"
        return f"({idx_py}) - ({lo_py})"

    @staticmethod
    def _split_section(text: str) -> tuple[str, str]:
        parts = split_top_level(text, ':', preserve_empty=True)
        if len(parts) not in (2, 3):
            raise ValueError(f"Invalid Fortran array section: {text!r}")
        return parts[0], ':'.join(parts[1:])

    def _slice_expr_from_decl_bounds(self, name: str, lo_txt: str, hi_txt: str, dim0: int, arrays_1d: set[str]) -> str:
        base_lo_py = self._decl_bound_expr(name, dim0, "lo", arrays_1d)
        triplet_tail = split_top_level(hi_txt, ':', preserve_empty=True)
        if len(triplet_tail) > 1:
            if len(triplet_tail) != 2 or not triplet_tail[1].strip():
                raise ValueError("Invalid Fortran array section stride")
            hi_txt, step_txt = triplet_tail
            lo_py = self.translate_expr(lo_txt.strip(), arrays_1d) if lo_txt.strip() else "None"
            hi_py = self.translate_expr(hi_txt.strip(), arrays_1d) if hi_txt.strip() else "None"
            step_py = self.translate_expr(step_txt.strip(), arrays_1d)
            array_py = self.translate_expr(name, arrays_1d)
            return f"_f_section_slice({array_py}, {dim0}, {base_lo_py or '1'}, {lo_py}, {hi_py}, {step_py})"
        lo_txt = lo_txt.strip()
        hi_txt = hi_txt.strip()
        if lo_txt:
            lo_py = self.translate_expr(lo_txt, arrays_1d)
            start = f"(int({lo_py}) - 1)" if base_lo_py is None or base_lo_py == "1" else f"(int({lo_py}) - int({base_lo_py}))"
        else:
            start = ""
        if hi_txt:
            hi_py = self.translate_expr(hi_txt, arrays_1d)
            stop = f"int({hi_py})" if base_lo_py is None or base_lo_py == "1" else f"(int({hi_py}) - int({base_lo_py}) + 1)"
        else:
            stop = ""
        return f"{start}:{stop}"

    def _translate_bit_call(self, name, inner, arrays_1d):
        parameters, required = _INTRINSIC_ARGUMENTS[name]
        raw = _bind_intrinsic_arguments(name, inner, parameters, required)
        bound = {k: self.translate_expr(v, arrays_1d) for k, v in raw.items()}
        bits = '32'
        literal = re.fullmatch(r'([+-]?\d+)_([a-z_]\w*|\d+)', raw['i'], re.I)
        if literal:
            bound['i'] = literal.group(1)
            bits = f'8 * ({self.translate_expr(literal.group(2), arrays_1d)})'
        name_match = re.match(r'^([a-z_]\w*)(?:\s*\(.*\))?$', raw['i'], re.I)
        if name_match:
            for symbols, _binding in reversed(self._host_scopes):
                info = symbols.get(name_match.group(1))
                if info is not None:
                    selector = re.match(r'^\s*\(\s*(?:kind\s*=\s*)?([^)]*)\)', info.get('attrs_l', ''), re.I)
                    if selector:
                        bits = f'8 * ({self.translate_expr(selector.group(1), arrays_1d)})'
                    break
        arguments = [repr(name)]
        arguments.extend(f"{'length' if k == 'len' else k}={v}" for k, v in bound.items())
        arguments.append(f'bits={bits}')
        return f"_f_bits({', '.join(arguments)})"

    def translate_expr(self, expr: str, arrays_1d: set[str]) -> str:
        s = expr.strip()
        keyword = re.match(r"^([a-z_]\w*)\s*=(?!=)\s*(.+)$", s, re.I)
        if keyword:
            return f"{keyword.group(1)}={self.translate_expr(keyword.group(2), arrays_1d)}"
        # Bit widths must be recovered before ordinary numeric-kind suffixes
        # are removed. Scan nested calls too, without matching string contents.
        bit_pattern = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|"
            r"\b(btest|ibset|ibclr|ibits|iand|ior|ieor|shiftl|shiftr)\s*\(", re.I)
        out, cursor = [], 0
        while match := bit_pattern.search(s, cursor):
            out.append(s[cursor:match.start()])
            if match.group(1):
                opening = s.find('(', match.start())
                closing = find_matching_paren(s, opening)
                if closing < 0:
                    raise ValueError('unbalanced bit intrinsic call')
                out.append(self._translate_bit_call(match.group(1).lower(), s[opening + 1:closing], arrays_1d))
                cursor = closing + 1
            else:
                out.append(match.group())
                cursor = match.end()
        s = ''.join(out) + s[cursor:]
        s = s.replace("%", ".")
        concat_parts = split_top_level_concat(s)
        if len(concat_parts) > 1:
            parts_py = [self.translate_expr(part, arrays_1d) for part in concat_parts]
            expr_py = parts_py[0]
            for part_py in parts_py[1:]:
                expr_py = f"_xf2p_concat({expr_py}, {part_py})"
            return expr_py

        if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
            return repr(_fortran_unquote(s))

        s = _rewrite_fortran_string_literals(s)

        implied_py = _fortran_implied_do_expr(s, self.translate_expr, arrays_1d)
        if implied_py is not None:
            return implied_py

        if len(s) >= 2 and s[0] == "[" and s[-1] == "]":
            inner = s[1:-1].strip()
            cc = _find_top_level_double_colon(inner)
            if cc != -1:
                type_spec = inner[:cc].strip().lower()
                elems_txt = inner[cc + 2 :].strip()
                dtype_map = {
                    "integer": "int",
                    "logical": "bool",
                    "real": "np.float64",
                    "complex": "np.complex128",
                    "character": "object",
                }
                base_type = None
                for key in dtype_map:
                    if type_spec.startswith(key):
                        base_type = key
                        break
                if base_type is not None:
                    if not elems_txt:
                        return f"np.asarray([], dtype={dtype_map[base_type]})"
                    elems_parts = [p.strip() for p in split_args(elems_txt) if p.strip()]
                    list_terms = []
                    for p in elems_parts:
                        implied_term = _fortran_implied_do_expr(p, self.translate_expr, arrays_1d)
                        if implied_term is not None:
                            list_terms.append(implied_term)
                        else:
                            list_terms.append(f"[{self.translate_expr(p, arrays_1d)}]")
                    if not list_terms:
                        return f"np.asarray([], dtype={dtype_map[base_type]})"
                    list_py = list_terms[0]
                    for term in list_terms[1:]:
                        list_py = f"{list_py} + {term}"
                    return f"np.asarray({list_py}, dtype={dtype_map[base_type]})"
            elems_parts = [p.strip() for p in split_args(inner) if p.strip()]
            list_terms = []
            has_implied = False
            for p in elems_parts:
                implied_term = _fortran_implied_do_expr(p, self.translate_expr, arrays_1d)
                if implied_term is not None:
                    has_implied = True
                    list_terms.append(implied_term)
                else:
                    list_terms.append(f"[{self.translate_expr(p, arrays_1d)}]")
            if has_implied:
                if not list_terms:
                    return "np.asarray([])"
                list_py = list_terms[0]
                for term in list_terms[1:]:
                    list_py = f"{list_py} + {term}"
                return f"np.asarray({list_py})"
            # Translate every constructor element, not just implied-DO terms:
            # a complex literal is a Fortran value, not a Python tuple.
            s = "[" + ", ".join(self.translate_expr(p, arrays_1d) for p in elems_parts) + "]"

        # kind(...) used as a kind selector
        # basic rule: if it uses a d exponent constant, treat it as double precision -> 8
        s = re.sub(r"\bkind\s*\(\s*[^)]*[dD][^)]*\)\s*", "8", s, flags=re.I)
        s = re.sub(r"\breal64\b", "8", s, flags=re.I)
        s = re.sub(r"\breal32\b", "4", s, flags=re.I)

        # fortran d exponent literal -> python e exponent literal
        s = re.sub(
            r"(?i)(\d+(?:\.\d*)?|\.\d+)[d]([+-]?\d+)",
            r"\1e\2",
            s,
        )
        # fortran kind suffix literal -> plain python numeric literal
        # e.g. 1.0_dp, 2_ikind, 3.5_rk
        s = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|"
                   r"\b(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*_(?:[a-z_]\w*|\d+)\b",
                   lambda m: m.group('number') if m.group('number') is not None else m.group(),
                   s, flags=re.I)

        def _top_level_complex_literal(txt: str) -> tuple[str, str] | None:
            t = txt.strip()
            if len(t) < 2 or t[0] != "(" or t[-1] != ")":
                return None
            if find_matching_paren(t, 0) != len(t) - 1:
                return None
            parts = [p.strip() for p in split_args(t[1:-1])]
            if len(parts) != 2:
                return None
            return parts[0], parts[1]

        def _rewrite_complex_groups(text: str) -> str:
            result = []
            i = 0
            while i < len(text):
                if text[i] in "\"'":
                    end = i + 1
                    while end < len(text):
                        if text[end] == "\\":
                            end += 2
                            continue
                        if text[end] == text[i]:
                            end += 1
                            break
                        end += 1
                    result.append(text[i:end])
                    i = end
                    continue
                if text[i] == "(":
                    end = find_matching_paren(text, i)
                    if end >= 0:
                        inner = text[i + 1:end]
                        prefix = text[:i].rstrip()
                        is_call = bool(prefix and (prefix[-1].isalnum() or prefix[-1] in "_)]"))
                        pair = _top_level_complex_literal(text[i:end + 1]) if not is_call else None
                        if pair:
                            result.append(f"_xf2p_cmplx({self.translate_expr(pair[0], arrays_1d)}, {self.translate_expr(pair[1], arrays_1d)})")
                        else:
                            result.append("(" + _rewrite_complex_groups(inner) + ")")
                        i = end + 1
                        continue
                result.append(text[i])
                i += 1
            return "".join(result)

        complex_parts = _top_level_complex_literal(s)
        if complex_parts is not None:
            re_py = self.translate_expr(complex_parts[0], arrays_1d)
            im_py = self.translate_expr(complex_parts[1], arrays_1d)
            return f"_xf2p_cmplx({re_py}, {im_py})"
        s = _rewrite_complex_groups(s)

        # Keep operator-looking text in Python-quoted string literals intact.
        # AND/OR/NOT first use Python precedence, then the AST pass below lowers
        # them to elementwise logical calls (including scalar/array operands).
        operators = {"true": "True", "false": "False", "eqv": " == ",
                     "neqv": " != ", "eq": " == ", "ne": " != ",
                     "lt": " < ", "le": " <= ", "gt": " > ", "ge": " >= ",
                     "and": " and ", "or": " or ", "not": " not "}
        s = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|"
                   r"\.(true|false|eqv|neqv|eq|ne|lt|le|gt|ge|and|or|not)\.",
                   lambda m: operators[m.group(1).lower()] if m.group(1) else m.group(),
                   s, flags=re.I)
        s = s.replace("/=", " != ")

        s = re.sub(r"\bsqrt\s*\(", "np.sqrt(", s, flags=re.I)
        s = re.sub(r"\bacos\s*\(", "np.arccos(", s, flags=re.I)
        s = re.sub(r"\bcos\s*\(", "np.cos(", s, flags=re.I)
        s = re.sub(r"\bsin\s*\(", "np.sin(", s, flags=re.I)
        s = re.sub(r"\blog\s*\(", "np.log(", s, flags=re.I)
        s = re.sub(r"\bexp\s*\(", "np.exp(", s, flags=re.I)
        s = re.sub(r"\bmax\s*\(", "np.maximum(", s, flags=re.I)
        s = re.sub(r"\bmin\s*\(", "np.minimum(", s, flags=re.I)
        s = re.sub(r"\bspread\s*\(", "_f_spread(", s, flags=re.I)
        s = re.sub(r"\bmodulo\s*\(", "_xf2p_modulo(", s, flags=re.I)
        s = re.sub(r"\bmod\s*\(", "_xf2p_mod(", s, flags=re.I)
        s = re.sub(r"\bmaxval\s*\(", "np.max(", s, flags=re.I)
        s = re.sub(r"\bminval\s*\(", "np.min(", s, flags=re.I)
        for intrinsic in ("minloc", "maxloc", "findloc"):
            s = re.sub(rf"\b{intrinsic}\s*\(", f"_f_{intrinsic}(", s, flags=re.I)
        s = re.sub(r"\bcount\s*\(", "np.count_nonzero(", s, flags=re.I)
        s = re.sub(r"\bsum\s*\(", "np.sum(", s, flags=re.I)
        s = re.sub(
            r"\ballocated\s*\(\s*([a-z_]\w*)\.([a-z_]\w*)\s*\)",
            r"(hasattr(\1, '\2') and (getattr(\1, '\2') is not None))",
            s,
            flags=re.I,
        )
        s = re.sub(r"\ballocated\s*\(\s*([^)]+?)\s*\)", r"(\1 is not None)", s, flags=re.I)
        s = re.sub(r"\bpresent\s*\(\s*([a-z_]\w*)\s*\)", r"(\1 is not None)", s, flags=re.I)
        s = re.sub(r"\bassociated\s*\(\s*([a-z_]\w*(?:\.[a-z_]\w*)*)\s*\)", r"(\1 is not None)", s, flags=re.I)
        s = re.sub(r"\bnull\s*\(\s*\)", "None", s, flags=re.I)
        s = s.replace("np.np.", "np.")
        s = re.sub(r"(?i)\.re\b", ".real", s)
        s = re.sub(r"(?i)\.im\b", ".imag", s)

        s = re.sub(r"\bsize\s*\(\s*([a-z_]\w*)\s*\)", r"_f_size(\1)", s, flags=re.I)
        s = re.sub(r"\bsize\s*\(\s*([^)]+)\s*\)", r"_f_size(\1)", s, flags=re.I)
        s = s.replace("np.np.", "np.")

        def _rewrite_np_sum_calls(txt: str) -> str:
            out: list[str] = []
            i = 0
            n = len(txt)
            while i < n:
                k = txt.lower().find("np.sum(", i)
                if k == -1:
                    out.append(txt[i:])
                    break
                out.append(txt[i:k])
                p0 = k + len("np.sum")
                if p0 >= n or txt[p0] != "(":
                    out.append(txt[k:k + 1])
                    i = k + 1
                    continue
                p1 = find_matching_paren(txt, p0)
                if p1 == -1:
                    out.append(txt[k:])
                    break
                inner = txt[p0 + 1 : p1]
                parts = [p.strip() for p in split_args(inner) if p.strip()]
                if not parts:
                    out.append("np.sum()")
                    i = p1 + 1
                    continue
                arr = parts[0]
                dim_expr = None
                mask_expr = None
                for ptxt in parts[1:]:
                    mk = re.match(r"^([a-z_]\w*)\s*=\s*(.+)$", ptxt, re.I)
                    if mk:
                        key = mk.group(1).lower()
                        val = mk.group(2).strip()
                        if key == "dim":
                            dim_expr = val
                        elif key == "mask":
                            mask_expr = val
                    elif dim_expr is None:
                        dim_expr = ptxt
                if mask_expr is not None:
                    arr_eff = f"np.where({mask_expr}, {arr}, 0.0)"
                else:
                    arr_eff = arr
                if dim_expr is not None:
                    repl = f"np.sum({arr_eff}, axis=({dim_expr}) - 1)"
                else:
                    repl = f"np.sum({arr_eff})"
                out.append(repl)
                i = p1 + 1
            return "".join(out)

        s = _rewrite_np_sum_calls(s)

        def _translate_special_call(name: str, inner: str) -> str | None:
            lname = name.lower()
            if lname not in _INTRINSIC_ARGUMENTS and lname not in {
                "gamma",
                "log_gamma",
                "log10",
                "tan",
                "asin", "atan", "atan2",
                "fraction", "exponent", "scale", "set_exponent",
                "nearest", "spacing", "rrspacing",
                "tiny", "huge", "digits", "precision", "range", "radix",
                "dim", "sign",
                "erf",
                "erfc",
                "erfc_scaled",
                "bessel_j0",
                "bessel_j1",
                "bessel_y0",
                "bessel_y1",
                "bessel_jn",
                "bessel_yn",
                "asinh",
                "acosh",
                "atanh",
                "hypot",
                "norm2",
                "epsilon",
                "sinh",
                "cosh",
                "tanh",
                "acosd",
                "asind",
                "atand",
                "atan2d",
                "cosd",
                "sind",
                "tand",
                "acospi",
                "asinpi",
                "atanpi",
                "atan2pi",
                "cospi",
                "sinpi",
                "tanpi",
                "trim",
                "len",
                "len_trim",
                "new_line",
                "achar",
                "char",
                "adjustl",
                "real",
                "aimag",
                "conjg",
                "cmplx",
                "int",
                "nint",
                "anint",
                "aint",
                "ceiling",
                "floor",
                "lbound",
                "ubound",
                "shape",
                "rank",
                "transpose",
                "matmul",
                "dot_product",
                "reshape",
                "index",
            }:
                return None
            parts = [p.strip() for p in split_args(inner)]
            if lname in _INTRINSIC_ARGUMENTS:
                parameters, required = _INTRINSIC_ARGUMENTS[lname]
                raw = _bind_intrinsic_arguments(lname, inner, parameters, required)
                bound = {k: self.translate_expr(v, arrays_1d) for k, v in raw.items()}
                if lname in _BIT_INTRINSICS:
                    return self._translate_bit_call(lname, inner, arrays_1d)
                return f"_f_{lname}({', '.join(f'{k}={v}' for k, v in bound.items())})"
            if lname in {"shape", "rank"}:
                parameters = ("source", "kind") if lname == "shape" else ("a",)
                bound = {}
                raw_arguments = {}
                for part in parts:
                    keyword = re.match(r"^([a-z_]\w*)\s*=\s*(.+)$", part, re.I)
                    if keyword:
                        key, value = keyword.group(1).lower(), keyword.group(2)
                    else:
                        key = next((parameter for parameter in parameters if parameter not in bound), "")
                        value = part
                    if not value or key not in parameters or key in bound:
                        raise ValueError(f"Invalid arguments to {lname}")
                    bound[key] = self.translate_expr(value, arrays_1d)
                    raw_arguments[key] = value.strip().lower()
                if parameters[0] not in bound:
                    raise ValueError(f"Invalid arguments to {lname}")
                if lname == "rank":
                    name = raw_arguments["a"]
                    symbol = next((info for symbols, _ in reversed(self._host_scopes)
                                   for key, info in symbols.items() if key.lower() == name), None)
                    if symbol is not None:
                        if not symbol.get("is_array"):
                            return "0"
                        shape = str(symbol.get("shape") or "").strip()
                        if shape and shape != "..":
                            # RANK does not require allocation/association when
                            # the object's rank is known from its declaration.
                            return str(len(self._shape_bounds(shape)))
                arguments = [bound[parameters[0]]]
                if "kind" in bound:
                    arguments.append(f"kind={bound['kind']}")
                return f"_f_{lname}({', '.join(arguments)})"
            if lname in {"transpose", "matmul", "dot_product", "reshape", "index"}:
                parameters = {"transpose": ("matrix",),
                              "matmul": ("matrix_a", "matrix_b"),
                              "dot_product": ("vector_a", "vector_b"),
                              "reshape": ("source", "shape", "pad", "order"),
                              "index": ("string", "substring", "back", "kind")}[lname]
                bound = {}
                for part in parts:
                    keyword = re.match(r"^([a-z_]\w*)\s*=\s*(.*)$", part, re.I)
                    if keyword:
                        key, value = keyword.group(1).lower(), keyword.group(2)
                    else:
                        key = next((p for p in parameters if p not in bound), "")
                        value = part
                    if key not in parameters or key in bound:
                        raise ValueError(f"Invalid arguments to {lname}")
                    bound[key] = self.translate_expr(value, arrays_1d)
                required = parameters[:2] if lname in {"reshape", "index"} else parameters
                if not set(required).issubset(bound):
                    raise ValueError(f"Invalid arguments to {lname}")
                callee = {"transpose": "np.transpose", "matmul": "matmul",
                          "dot_product": "_f_dot_product", "reshape": "_f_reshape",
                          "index": "_f_index"}[lname]
                if lname == "index":
                    arguments = [bound["string"], bound["substring"]]
                    if "back" in bound:
                        arguments.append(f"back={bound['back']}")
                    return f"{callee}({', '.join(arguments)})"
                if lname == "reshape":
                    arguments = [bound["source"], bound["shape"]]
                    arguments.extend(f"{p}={bound[p]}" for p in ("pad", "order") if p in bound)
                    return f"{callee}({', '.join(arguments)})"
                return f"{callee}({', '.join(bound[p] for p in parameters)})"
            args_py = [self.translate_expr(p, arrays_1d) for p in parts]
            if lname == "trim" and len(args_py) == 1:
                return f"str({args_py[0]}).rstrip(' ')"
            if lname == "len" and len(args_py) == 1:
                return f"_f_len({args_py[0]})"
            if lname == "len_trim" and len(args_py) == 1:
                return f"_f_len_trim({args_py[0]})"
            if lname == "new_line" and len(args_py) == 1:
                return repr("\n")
            if lname in {"achar", "char"} and len(args_py) >= 1:
                return f"chr(int({args_py[0]}))"
            if lname == "adjustl" and len(args_py) == 1:
                return f"_f_adjustl({args_py[0]})"
            if lname == "real" and len(args_py) >= 1:
                return f"_xf2p_real({args_py[0]})"
            if lname == "aimag" and len(args_py) == 1:
                return f"_xf2p_aimag({args_py[0]})"
            if lname == "conjg" and len(args_py) == 1:
                return f"_xf2p_conjg({args_py[0]})"
            if lname == "cmplx":
                if len(args_py) == 1:
                    return f"_xf2p_cmplx({args_py[0]})"
                if len(args_py) >= 2:
                    return f"_xf2p_cmplx({args_py[0]}, {args_py[1]})"
                return None
            if lname == "int":
                if len(parts) >= 1:
                    arg0_raw = parts[0].strip()
                    arg0_py = args_py[0]
                    if (
                        arg0_raw.startswith("[")
                        or arg0_raw.startswith("(/")
                        or arg0_raw.lower() in arrays_1d
                    ):
                        return f"np.asarray({arg0_py}, dtype=int)"
                    return f"int({arg0_py})"
                return None
            if lname == "nint" and len(args_py) == 1:
                return f"_xf2p_nint({args_py[0]})"
            if lname == "anint" and len(args_py) == 1:
                return f"_xf2p_anint({args_py[0]})"
            if lname == "aint" and len(args_py) == 1:
                return f"_xf2p_aint({args_py[0]})"
            if lname == "ceiling" and len(args_py) == 1:
                return f"_xf2p_ceiling({args_py[0]})"
            if lname == "floor" and len(args_py) == 1:
                return f"_xf2p_floor({args_py[0]})"
            if lname in {"lbound", "ubound"} and len(parts) >= 1:
                base_raw = parts[0].strip()
                base_py = self.translate_expr(base_raw, arrays_1d)
                dim_raw = None
                dim_py = None
                for idx_part, p in enumerate(parts[1:], start=1):
                    pm = re.match(r"(?is)^dim\s*=\s*(.+)$", p.strip())
                    if pm:
                        dim_raw = pm.group(1).strip()
                        dim_py = self.translate_expr(dim_raw, arrays_1d)
                    elif idx_part == 1 and dim_raw is None:
                        dim_raw = p.strip()
                        dim_py = self.translate_expr(dim_raw, arrays_1d)
                if re.fullmatch(r"[a-z_]\w*(?:\.[a-z_]\w*)*", base_raw, flags=re.I):
                    key = base_raw.split(".", 1)[0].lower()
                    vals = self._decl_lbounds.get(key) if lname == "lbound" else self._decl_ubounds.get(key)
                    if vals:
                        if dim_raw is None:
                            parts_py: list[str] = []
                            for idx0 in range(len(vals)):
                                bnd = self._decl_bound_expr(base_raw, idx0, "lo" if lname == "lbound" else "hi", arrays_1d)
                                if bnd is None:
                                    parts_py = []
                                    break
                                parts_py.append(bnd)
                            if parts_py:
                                return "np.asarray([" + ", ".join(parts_py) + "], dtype=int)"
                        if re.fullmatch(r"[+-]?\d+", dim_raw):
                            idx0 = int(dim_raw) - 1
                            bnd = self._decl_bound_expr(base_raw, idx0, "lo" if lname == "lbound" else "hi", arrays_1d)
                            if bnd is not None:
                                return bnd
                helper = "_xf2p_lbound" if lname == "lbound" else "_xf2p_ubound"
                if dim_py is None:
                    return f"{helper}({base_py})"
                return f"{helper}({base_py}, dim={dim_py})"
            if lname == "gamma" and len(args_py) == 1:
                return f"sps.gamma({args_py[0]})"
            if lname == "log_gamma" and len(args_py) == 1:
                return f"sps.gammaln({args_py[0]})"
            if lname == "log10" and len(args_py) == 1:
                return f"np.log10({args_py[0]})"
            if lname == "tan" and len(args_py) == 1:
                return f"np.tan({args_py[0]})"
            if lname in {"asin", "atan"} and len(args_py) == 1:
                return f"np.arc{lname[1:]}({args_py[0]})"
            if lname in {"atan", "atan2"} and len(args_py) == 2:
                return f"np.arctan2({', '.join(args_py)})"
            if lname in {"fraction", "exponent", "spacing", "rrspacing"} and len(args_py) == 1:
                return f"_f_{lname}({args_py[0]})"
            if lname in {"scale", "set_exponent", "nearest", "dim", "sign"} and len(args_py) == 2:
                return f"_f_{lname}({', '.join(args_py)})"
            if lname in {"tiny", "huge", "digits", "precision", "range", "radix"} and len(args_py) == 1:
                return f"_f_numeric_model({args_py[0]}, '{lname}')"
            if lname == "erf" and len(args_py) == 1:
                return f"sps.erf({args_py[0]})"
            if lname == "erfc" and len(args_py) == 1:
                return f"sps.erfc({args_py[0]})"
            if lname == "erfc_scaled" and len(args_py) == 1:
                return f"sps.erfcx({args_py[0]})"
            if lname in {"bessel_y0", "bessel_y1"} and len(args_py) == 1:
                return f"sps.{lname[-2:]}({args_py[0]})"
            if lname in {"sinh", "cosh", "tanh"} and len(args_py) == 1:
                return f"np.{lname}({args_py[0]})"
            if lname == "epsilon" and len(args_py) == 1:
                return f"_f_epsilon({args_py[0]})"
            if lname == "bessel_j0" and len(args_py) == 1:
                return f"sps.j0({args_py[0]})"
            if lname == "bessel_j1" and len(args_py) == 1:
                return f"sps.j1({args_py[0]})"
            if lname == "bessel_jn":
                if len(args_py) == 2:
                    return f"sps.jv({args_py[0]}, {args_py[1]})"
                if len(args_py) == 3:
                    return f"sps.jv(np.arange(int({args_py[0]}), int({args_py[1]}) + 1), {args_py[2]})"
            if lname == "bessel_yn":
                if len(args_py) == 2:
                    return f"sps.yn({args_py[0]}, {args_py[1]})"
                if len(args_py) == 3:
                    return f"sps.yn(np.arange(int({args_py[0]}), int({args_py[1]}) + 1), {args_py[2]})"
            if lname == "asinh" and len(args_py) == 1:
                return f"np.asinh({args_py[0]})"
            if lname == "acosh" and len(args_py) == 1:
                return f"np.acosh({args_py[0]})"
            if lname == "atanh" and len(args_py) == 1:
                return f"np.atanh({args_py[0]})"
            if lname == "hypot" and len(args_py) == 2:
                return f"np.hypot({args_py[0]}, {args_py[1]})"
            if lname == "norm2" and len(args_py) in {1, 2}:
                return f"_f_norm2({', '.join(args_py)})"
            if lname == "acosd" and len(args_py) == 1:
                return f"np.degrees(np.arccos({args_py[0]}))"
            if lname == "asind" and len(args_py) == 1:
                return f"np.degrees(np.arcsin({args_py[0]}))"
            if lname == "atand" and len(args_py) == 1:
                return f"np.degrees(np.arctan({args_py[0]}))"
            if lname in {"atand", "atan2d"} and len(args_py) == 2:
                return f"np.degrees(np.arctan2({', '.join(args_py)}))"
            if lname in {"atanpi", "atan2pi"} and len(args_py) == 2:
                return f"(np.arctan2({', '.join(args_py)}) / np.pi)"
            if lname == "cosd" and len(args_py) == 1:
                return f"np.cos(np.radians({args_py[0]}))"
            if lname == "sind" and len(args_py) == 1:
                return f"np.sin(np.radians({args_py[0]}))"
            if lname == "tand" and len(args_py) == 1:
                return f"np.tan(np.radians({args_py[0]}))"
            if lname == "acospi" and len(args_py) == 1:
                return f"(np.arccos({args_py[0]}) / np.pi)"
            if lname == "asinpi" and len(args_py) == 1:
                return f"(np.arcsin({args_py[0]}) / np.pi)"
            if lname == "atanpi" and len(args_py) == 1:
                return f"(np.arctan({args_py[0]}) / np.pi)"
            if lname == "cospi" and len(args_py) == 1:
                return f"_f_cospi({args_py[0]})"
            if lname == "sinpi" and len(args_py) == 1:
                return f"_f_sinpi({args_py[0]})"
            if lname == "tanpi" and len(args_py) == 1:
                return f"_f_tanpi({args_py[0]})"
            return None

        # 1d array element: a(i) -> a[(i)-1] (assume 1-based Fortran indexing)
        # Use a scanner (not regex) so nested references like x(idx(i)+1) work.
        def _convert_refs(txt: str) -> str:
            out: list[str] = []
            i = 0
            n = len(txt)
            chain_name = None
            while i < n:
                if txt[i] in "\"'":
                    end = i + 1
                    while end < n:
                        if txt[end] == "\\":
                            end += 2
                            continue
                        if txt[end] == txt[i]:
                            end += 1
                            break
                        end += 1
                    out.append(txt[i:end])
                    i = end
                    chain_name = None
                    continue
                m = re.match(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", txt[i:])
                if not m:
                    out.append(txt[i])
                    if not txt[i].isspace() and txt[i] != ".":
                        chain_name = None
                    i += 1
                    continue
                name = m.group(0)
                continuation = chain_name is not None and txt[:i].rstrip().endswith(".")
                full_name = f"{chain_name}.{name}" if continuation else name
                j = i + len(name)
                k = j
                while k < n and txt[k].isspace():
                    k += 1
                if k < n and txt[k] == "(":
                    pclose = find_matching_paren(txt, k)
                    if pclose != -1:
                        inner = txt[k + 1 : pclose]
                        inner_py = self.translate_expr(inner, arrays_1d)
                        root = full_name.split(".", 1)[0].lower()
                        dotted_array_ref = ("." in full_name) and (root not in {"np", "math", "random", "sps"}) and self._bound_signature(full_name) is None
                        chain_name = f"{full_name}({inner})"
                        special_call = None if "." in name else _translate_special_call(name, inner)
                        if special_call is not None:
                            out.append(special_call)
                            i = pclose + 1
                            continue
                        if name in arrays_1d or dotted_array_ref:
                            if "," in inner:
                                parts = [p.strip() for p in split_args(inner)]
                                idx_parts: list[str] = []
                                for ptxt in parts:
                                    if ptxt == ":":
                                        idx_parts.append(":")
                                    elif ":" in ptxt:
                                        lo, hi = self._split_section(ptxt)
                                        lo = lo.strip()
                                        hi = hi.strip()
                                        idx_parts.append(self._slice_expr_from_decl_bounds(full_name, lo, hi, len(idx_parts), arrays_1d))
                                    else:
                                        idx_parts.append(self._index_expr_from_decl_bounds(full_name, ptxt, len(idx_parts), arrays_1d))
                                out.append(f"{name}[{', '.join(idx_parts)}]")
                                i = pclose + 1
                                continue
                            if ":" in inner:
                                lo, hi = self._split_section(inner)
                                lo = lo.strip()
                                hi = hi.strip()
                                out.append(f"{name}[{self._slice_expr_from_decl_bounds(full_name, lo, hi, 0, arrays_1d)}]")
                            else:
                                out.append(f"{name}[{self._index_expr_from_decl_bounds(full_name, inner, 0, arrays_1d)}]")
                        else:
                            is_char_substring = self._decl_types.get(name.lower()) == "character"
                            if is_char_substring and ":" in inner and "," not in inner:
                                lo, hi = inner.split(":", 1)
                                lo = lo.strip()
                                hi = hi.strip()
                                lo_py = self.translate_expr(lo, arrays_1d) if lo else ""
                                hi_py = self.translate_expr(hi, arrays_1d) if hi else ""
                                start = f"(int({lo_py}) - 1)" if lo_py else ""
                                stop = f"int({hi_py})" if hi_py else ""
                                out.append(f"{name}[{start}:{stop}]")
                            else:
                                arg_parts = split_args(inner)
                                if len(arg_parts) > 1:
                                    args_joined = ", ".join(self.translate_expr(p.strip(), arrays_1d) for p in arg_parts)
                                    out.append(f"{name}({args_joined})")
                                else:
                                    out.append(f"{name}({inner_py})")
                        i = pclose + 1
                        continue
                root = name.split(".", 1)[0].lower()
                if "." in name and root in arrays_1d and root not in {"np", "math", "random", "sps"}:
                    root_name, path_name = name.split(".", 1)
                    out.append(f"_xf2p_component_array({root_name}, {path_name!r})")
                else:
                    out.append(name)
                i = j
                chain_name = full_name
            return "".join(out)

        s = _convert_refs(s)

        def _expr_kind(node: ast.AST) -> str | None:
            if isinstance(node, ast.Constant):
                if isinstance(node.value, bool):
                    return "logical"
                if isinstance(node.value, int):
                    return "integer"
                if isinstance(node.value, float):
                    return "real"
                if isinstance(node.value, complex):
                    return "complex"
                if isinstance(node.value, str):
                    return "character"
                return None
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                return _expr_kind(node.operand)
            if isinstance(node, ast.Name):
                return self._decl_types.get(node.id.lower())
            if isinstance(node, ast.List):
                if not node.elts:
                    return "real"
                kinds = {_expr_kind(elt) for elt in node.elts}
                kinds.discard(None)
                if not kinds:
                    return None
                if "character" in kinds:
                    return "character"
                if "complex" in kinds:
                    return "complex"
                if "real" in kinds:
                    return "real"
                if "integer" in kinds:
                    return "integer"
                if "logical" in kinds:
                    return "logical"
                return None
            if isinstance(node, ast.Call):
                fname = None
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    fname = f"{node.func.value.id}.{node.func.attr}"
                if fname in {"int", "_f_len", "_f_len_trim", "_xf2p_mod", "_xf2p_modulo", "_xf2p_div", "_xf2p_nint"}:
                    return "integer"
                if fname in {"float", "_xf2p_real", "np.float64", "np.sqrt", "np.log", "np.exp", "np.sin", "np.cos", "np.arccos", "np.arcsin", "np.arctan", "np.degrees", "np.radians"}:
                    return "real"
                if fname in {"complex", "_xf2p_cmplx", "_xf2p_conjg", "np.conj"}:
                    return "complex"
                if fname == "_xf2p_concat":
                    return "character"
                if fname == "np.asarray":
                    for kw in node.keywords:
                        if kw.arg == "dtype":
                            if isinstance(kw.value, ast.Name):
                                if kw.value.id == "int":
                                    return "integer"
                                if kw.value.id == "bool":
                                    return "logical"
                                if kw.value.id == "object":
                                    return "character"
                            if isinstance(kw.value, ast.Attribute) and isinstance(kw.value.value, ast.Name) and kw.value.value.id == "np":
                                if kw.value.attr in {"float64", "float32"}:
                                    return "real"
                                if kw.value.attr in {"complex128", "complex64"}:
                                    return "complex"
                    return None
            return None

        class _ExprFixer(ast.NodeTransformer):
            @staticmethod
            def logical_call(name, operands):
                return ast.Call(
                    func=ast.Attribute(value=ast.Name(id="np", ctx=ast.Load()),
                                       attr=name, ctx=ast.Load()),
                    args=operands, keywords=[])

            def visit_BoolOp(self, node: ast.BoolOp):
                self.generic_visit(node)
                name = "logical_and" if isinstance(node.op, ast.And) else "logical_or"
                result = node.values[0]
                for operand in node.values[1:]:
                    result = self.logical_call(name, [result, operand])
                return ast.copy_location(result, node)

            def visit_UnaryOp(self, node: ast.UnaryOp):
                self.generic_visit(node)
                if isinstance(node.op, ast.Not):
                    return ast.copy_location(self.logical_call("logical_not", [node.operand]), node)
                return node

            def visit_List(self, node: ast.List):
                self.generic_visit(node)
                kind = _expr_kind(node)
                if kind is None:
                    return node
                dtype_map = {
                    "integer": "int",
                    "real": "np.float64",
                    "logical": "bool",
                    "complex": "np.complex128",
                    "character": "object",
                }
                dtype_expr = ast.parse(dtype_map[kind], mode="eval").body
                return ast.Call(
                    func=ast.Attribute(value=ast.Name(id="np", ctx=ast.Load()), attr="asarray", ctx=ast.Load()),
                    args=[node],
                    keywords=[ast.keyword(arg="dtype", value=dtype_expr)],
                )

            def visit_BinOp(self, node: ast.BinOp):
                self.generic_visit(node)
                if isinstance(node.op, ast.Div):
                    if _expr_kind(node.left) == "integer" and _expr_kind(node.right) == "integer":
                        return ast.Call(
                            func=ast.Name(id="_xf2p_div", ctx=ast.Load()),
                            args=[node.left, node.right],
                            keywords=[],
                        )
                return node

        try:
            tree = ast.parse(s.strip(), mode="eval")
            tree = _ExprFixer().visit(tree)
            ast.fix_missing_locations(tree)
            s = ast.unparse(tree)
        except Exception:
            pass
        return s

    def _integer_assignment_rhs(self, lhs: str, rhs_py: str, arrays_1d: set[str]) -> str:
        """Convert integer assignments elementwise for arrays, scalarly otherwise."""
        match = re.match(r"\s*([A-Za-z_]\w*)", lhs)
        if match is None:
            return rhs_py
        base = match.group(1).lower()
        if self._decl_types.get(base) != "integer":
            return rhs_py
        is_array = base in self._decl_array_types or base in arrays_1d
        suffix = lhs[match.end():].strip()
        if suffix.startswith("("):
            # An indexed element is scalar; a section retains array rank.
            is_array = is_array and ":" in suffix
        if is_array:
            return f"np.asarray({rhs_py}, dtype=int)"
        return f"int({rhs_py})"

    def transpile_assignment(self, lhs: str, rhs_py: str, arrays_1d: set[str]) -> None:
        if self._where_masked_assignment(lhs, rhs_py, arrays_1d):
            return
        lhs = lhs.replace("%", ".")
        if self._is_chained_subscript(lhs):
            target = self.translate_expr(lhs, arrays_1d)
            spec = self._component_spec(lhs)
            whole_array = bool(spec and spec.get("shape") and not lhs.rstrip().endswith(")"))
            if spec and spec["ftype"] == "integer":
                rhs_py = f"np.asarray({rhs_py}, dtype=int)" if whole_array or ":" in lhs else f"int({rhs_py})"
            if spec and spec.get("char_len") is not None:
                rhs_py = f"_f_str_assign({rhs_py}, {self.translate_expr(spec['char_len'], arrays_1d)})"
            value = f"_f_assign_array({target}, {rhs_py})" if whole_array else f"_xf2p_copy_value({rhs_py})"
            self.emit(f"{target} = {value}")
            return
        mb = re.match(r"\s*([A-Za-z_]\w*)", lhs)
        lhs_base = mb.group(1).lower() if mb else lhs.split(".", 1)[0].strip().lower()
        rhs_py = self._integer_assignment_rhs(lhs, rhs_py, arrays_1d)
        char_len_raw = self._decl_char_len.get(lhs_base)
        if char_len_raw is not None:
            clen_py = self.translate_expr(str(char_len_raw), arrays_1d)
            rhs_py = f"_f_str_assign({rhs_py}, {clen_py})"
        mname = re.match(r"^\s*([a-z_]\w*(?:\.[a-z_]\w*)*)\s*\(", lhs, re.I)
        idx_name = None
        idx = None
        if mname:
            name_try = mname.group(1)
            open_pos = lhs.find("(", mname.end(1))
            if open_pos >= 0:
                close_pos = find_matching_paren(lhs, open_pos)
                if close_pos == len(lhs) - 1:
                    idx_name = name_try
                    idx = lhs[open_pos + 1 : close_pos].strip()
        if idx_name is not None and idx is not None:
            name = idx_name
            root = name.split(".", 1)[0].lower()
            dotted_array_ref = ("." in name) and (root not in {"np", "math", "random", "sps"})
            if name in arrays_1d or dotted_array_ref:
                if "," in idx:
                    parts = [p.strip() for p in split_args(idx)]
                    idx_parts: list[str] = []
                    for ptxt in parts:
                        if ptxt == ":":
                            idx_parts.append(":")
                        elif ":" in ptxt:
                            lo, hi = self._split_section(ptxt)
                            lo = lo.strip()
                            hi = hi.strip()
                            idx_parts.append(self._slice_expr_from_decl_bounds(name, lo, hi, len(idx_parts), arrays_1d))
                        else:
                            idx_parts.append(self._index_expr_from_decl_bounds(name, ptxt, len(idx_parts), arrays_1d))
                    self.emit(f"{name}[{', '.join(idx_parts)}] = {rhs_py}")
                    return
                if ":" in idx:
                    lo, hi = self._split_section(idx)
                    lo = lo.strip()
                    hi = hi.strip()
                    self.emit(f"{name}[{self._slice_expr_from_decl_bounds(name, lo, hi, 0, arrays_1d)}] = {rhs_py}")
                else:
                    self.emit(f"{name}[{self._index_expr_from_decl_bounds(name, idx, 0, arrays_1d)}] = {rhs_py}")
                return
        # Whole-array assignment or scalar assignment.
        # POINTER and TARGET entities need in-place updates to preserve aliasing.
        if lhs in arrays_1d:
            if re.fullmatch(r"[A-Za-z_]\w*", lhs) and (lhs.lower() in self._decl_pointer or lhs.lower() in self._decl_target):
                self.emit(f"{lhs}[...] = {rhs_py}")
            else:
                self.emit(f"{lhs} = _f_assign_array({lhs}, {rhs_py})")
            return

        if re.fullmatch(r"[A-Za-z_]\w*", lhs) and (lhs.lower() in self._decl_pointer or lhs.lower() in self._decl_target):
            self.emit(f"{lhs}[...] = {rhs_py}")
            return

        self.emit(f"{lhs} = _xf2p_copy_value({rhs_py})")

    def transpile_simple_stmt(self, stmt: str, arrays_1d: set[str]) -> None:
        s = stmt.strip()
        if self.handle_exec_line(s, arrays_1d):
            return
        mm = re.match(r'error\s+stop\s+(.+)$', s, re.I)
        if mm:
            self.emit(f"raise RuntimeError({mm.group(1).strip()})")
            return
        if s.lower() == "return":
            self._emit_save_sync()
            if self._current_result_name:
                self.emit(f"return {self._current_result_name}")
            else:
                self.emit("return")
            return
        if "=" in s and _find_top_level_double_colon(s) == -1:
            lhs, rhs = s.split("=", 1)
            lhs = lhs.strip()
            rhs_py = self.translate_expr(rhs, arrays_1d)
            if lhs in arrays_1d and rhs_py in ("True", "False"):
                self.emit(f"{lhs}[:] = {rhs_py}")
                return
            self.transpile_assignment(lhs, rhs_py, arrays_1d)
        else:
            self.emit("# unsupported inline statement")
            self.emit("pass")

    def emit_parameters_from_decl(self, ftype: str, attrs_l: str, rest: str, arrays_1d: set[str], *, block_entry: bool = False) -> set[str]:
        names: set[str] = set()
        if "parameter" not in attrs_l:
            return names
        if ftype == "type":
            return names
        for name, shape, init in parse_decl_items(rest):
            if not block_entry and name in getattr(self, "_block_local_names", set()):
                continue
            if init is None:
                continue
            # parameters are named constants: method (2) -> Final
            hint = _type_scalar_hint.get(ftype, "int")
            val = self.translate_expr(init, arrays_1d)
            self.emit(f"{name}: Final[{hint}] = {val}")
            names.add(name)
        return names

    def emit_var_inits_from_sym(
        self,
        sym: dict[str, dict],
        arrays_1d: set[str],
        parameter_names: set[str],
        skip_names: set[str] | None = None,
        *, block_entry: bool = False,
    ) -> None:
        # Allocate explicit-shape arrays and initialize scalars so Python is always valid.
        # Special handling:
        #   * POINTER entities start disassociated (None) unless initialized with => target.
        #   * TARGET scalars are represented as 0-d numpy arrays so pointers can alias them.
        if skip_names is None:
            skip_names = set()
        for name, info in sym.items():
            if not block_entry and name in getattr(self, "_block_local_names", set()):
                continue
            if name in parameter_names:
                continue
            if name in skip_names:
                continue

            ftype = info["ftype"]
            ftype_name = info.get("type_name")
            is_array = bool(info.get("is_array"))
            shape = info.get("shape")
            init = info.get("init")
            alloc = bool(info.get("alloc"))
            attrs_l = str(info.get("attrs_l", ""))
            is_ptr = bool(info.get("pointer")) or ("pointer" in attrs_l)
            is_tgt = bool(info.get("target")) or ("target" in attrs_l)

            # Arrays
            if is_array:
                # Pointer arrays: start disassociated (None) unless explicitly initialized.
                if is_ptr:
                    if init is None or re.match(r"^null\s*\(\s*\)\s*$", str(init), re.I):
                        self.emit(f"{name} = None")
                    else:
                        init_py = self.translate_expr(str(init), arrays_1d)
                        self.emit(f"{name} = {init_py}")
                    continue

                # Allocatable arrays start unallocated.
                if alloc:
                    self.emit(f"{name} = None")
                    continue

                # Only allocate explicit-shape, non-allocatable arrays here.
                if shape is None:
                    continue
                if str(shape).strip() == ":":
                    continue

                shape_py = self._shape_to_py(str(shape), arrays_1d)
                if ftype == "type":
                    self.emit(f"{name} = np.empty({shape_py}, dtype=object)")
                    continue

                dtype = _type_dtype[ftype]
                hint = _type_ndarray_hint[ftype]
                if init is None:
                    self.emit(f"{name}: {hint} = np.empty({shape_py}, dtype={dtype})")
                else:
                    init_py = self.translate_expr(str(init), arrays_1d)
                    if ftype == "character" and info.get("char_len") is not None:
                        clen_py = self.translate_expr(str(info.get("char_len")), arrays_1d)
                        init_py = f"_f_str_assign({init_py}, {clen_py})"
                    self.emit(f"{name}: {hint} = np.full({shape_py}, {init_py}, dtype={dtype})")
                continue

            # Scalars
            if alloc:
                self.emit(f"{name} = None")
                continue
            if ftype == "type":
                # Derived-type scalars.
                cls = ftype_name if ftype_name else "SimpleNamespace"
                if is_ptr:
                    # Pointer-to-derived-type starts disassociated.
                    self.emit(f"{name} = None")
                else:
                    self.emit(f"{name} = {cls}()")
                continue

            # Pointer scalars start disassociated unless explicitly initialized.
            if is_ptr:
                if init is None or re.match(r"^null\s*\(\s*\)\s*$", str(init), re.I):
                    self.emit(f"{name} = None")
                else:
                    init_py = self.translate_expr(str(init), arrays_1d)
                    self.emit(f"{name} = {init_py}")
                continue

            # Target scalars are stored as 0-d numpy arrays for aliasing.
            if is_tgt and ftype in _type_dtype and ftype != "character":
                dtype = _type_dtype[ftype]
                hint = _type_target_scalar_hint.get(ftype, "np.ndarray")
                if init is None:
                    default_val = _type_default_scalar_value.get(ftype, "0")
                    self.emit(f"{name}: {hint} = np.array({default_val}, dtype={dtype})")
                else:
                    init_py = self.translate_expr(str(init), arrays_1d)
                    self.emit(f"{name}: {hint} = np.array({init_py}, dtype={dtype})")
                continue

            # Regular (non-target) scalars.
            hint = _type_scalar_hint.get(ftype, "int")
            if init is None:
                default_val = _type_default_scalar_value.get(ftype, "0")
                if ftype == "character" and info.get("char_len") is not None:
                    clen_py = self.translate_expr(str(info.get("char_len")), arrays_1d)
                    default_val = f"_f_str_assign({default_val}, {clen_py})"
                self.emit(f"{name}: {hint} = {default_val}")
            else:
                init_py = self.translate_expr(str(init), arrays_1d)
                if ftype == "character" and info.get("char_len") is not None:
                    clen_py = self.translate_expr(str(info.get("char_len")), arrays_1d)
                    init_py = f"_f_str_assign({init_py}, {clen_py})"
                self.emit(f"{name}: {hint} = {init_py}")

    def _xf2p_select_case_cond(self, select_expr_py: str, raw_case_list: str, arrays_1d: set[str]) -> str:
        conds: list[str] = []
        for item in split_args(raw_case_list):
            tok = item.strip()
            if not tok:
                continue
            if ":" in tok:
                lo, hi = tok.split(":", 1)
                lo = lo.strip()
                hi = hi.strip()
                parts: list[str] = []
                if lo:
                    lo_py = self.translate_expr(lo, arrays_1d)
                    parts.append(f"({select_expr_py}) >= ({lo_py})")
                if hi:
                    hi_py = self.translate_expr(hi, arrays_1d)
                    parts.append(f"({select_expr_py}) <= ({hi_py})")
                conds.append(" and ".join(parts) if parts else "True")
            else:
                tok_py = self.translate_expr(tok, arrays_1d)
                conds.append(f"({select_expr_py}) == ({tok_py})")
        if not conds:
            return "False"
        return " or ".join(f"({c})" for c in conds)

    def _xf2p_select_case_start(self, head: str, arrays_1d: set[str], inline_stmt: str | None = None) -> None:
        if not self._select_case_stack:
            return
        st = self._select_case_stack[-1]
        if st.get("in_case", False):
            start = int(st.get("case_start", self._code_emit_count))
            if self._code_emit_count == start:
                self.emit("pass")
            self.indent = max(0, self.indent - 1)
        if head == "default":
            kw = "else"
            line = f"{kw}:"
        else:
            cond = self._xf2p_select_case_cond(str(st["expr"]), head, arrays_1d)
            kw = "if" if not st.get("had_case", False) else "elif"
            line = f"{kw} {cond}:"
        self.emit(line)
        self.indent += 1
        st["had_case"] = True
        st["in_case"] = True
        st["case_start"] = self._code_emit_count
        if inline_stmt and inline_stmt.strip():
            self.transpile_simple_stmt(inline_stmt.strip(), arrays_1d)


    def _associate_bindings(self, raw: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for item in split_args(raw):
            part = item.strip()
            if not part:
                continue
            if "=>" not in part:
                continue
            name, selector = part.split("=>", 1)
            name = name.strip()
            selector = selector.strip()
            if name:
                out.append((name, selector))
        return out

    def _associate_array_element_ref(self, selector: str, arrays_1d: set[str]) -> str | None:
        mm = re.match(r"^([a-z_]\w*(?:%[a-z_]\w*)*)\s*\((.*)\)\s*$", selector, re.I)
        if not mm:
            return None
        name_raw = mm.group(1).strip()
        idx_raw = mm.group(2).strip()
        root = name_raw.split("%", 1)[0].lower()
        if root not in arrays_1d:
            return None
        if "," in idx_raw or ":" in idx_raw:
            return None
        name_py = name_raw.replace("%", ".")
        idx_py = self.translate_expr(idx_raw, arrays_1d)
        return f"{name_py}[(({idx_py}) - 1):((({idx_py}) - 1) + 1)].reshape(())"

    def _associate_alias_metadata(self, selector: str, arrays_1d: set[str]) -> tuple[bool, bool, str | None]:
        sel = selector.strip()
        mm_name = re.fullmatch(r"[a-z_]\w*(?:%[a-z_]\w*)*", sel, re.I)
        if mm_name:
            root = sel.split("%", 1)[0].lower()
            is_array = root in arrays_1d
            return True, is_array, root
        mm = re.match(r"^([a-z_]\w*(?:%[a-z_]\w*)*)\s*\((.*)\)\s*$", sel, re.I)
        if mm:
            root = mm.group(1).split("%", 1)[0].lower()
            if root not in arrays_1d:
                return False, False, None
            idx = mm.group(2).strip()
            is_array = (":" in idx) or ("," in idx)
            return True, is_array, root
        return False, False, None

    def _start_associate_block(self, raw: str, arrays_1d: set[str]) -> None:
        self.emit("if True:")
        self.indent += 1
        frame: dict[str, object] = {
            "added_decl_pointer": set(),
            "added_decl_types": {},
            "added_decl_array_types": {},
            "added_arrays_1d": set(),
            "code_start": self._code_emit_count,
        }
        for assoc_name, selector in self._associate_bindings(raw):
            assoc_l = assoc_name.lower()
            can_alias, is_array_alias, root = self._associate_alias_metadata(selector, arrays_1d)
            if can_alias:
                if is_array_alias:
                    rhs_py = self.translate_expr(selector, arrays_1d)
                else:
                    rhs_py = self._associate_array_element_ref(selector, arrays_1d)
                    if rhs_py is None:
                        selector_py = self.translate_expr(selector, arrays_1d)
                        if re.fullmatch(r"[a-z_]\w*", selector.strip(), re.I):
                            self.emit(f"if not isinstance({selector_py}, np.ndarray):")
                            self.indent += 1
                            self.emit(f"{selector_py} = np.asarray({selector_py})")
                            self.indent -= 1
                        rhs_py = selector_py
                self.emit(f"{assoc_name} = {rhs_py}")
                self._decl_pointer.add(assoc_l)
                cast(set[str], frame["added_decl_pointer"]).add(assoc_l)
                if is_array_alias:
                    base_type = self._decl_array_types.get(root or "", self._decl_types.get(root or "", "real"))
                    self._decl_array_types[assoc_l] = base_type
                    cast(dict[str, str], frame["added_decl_array_types"])[assoc_l] = base_type
                    arrays_1d.add(assoc_l)
                    cast(set[str], frame["added_arrays_1d"]).add(assoc_l)
                else:
                    base_type = self._decl_types.get(root or "", "real")
                    self._decl_types[assoc_l] = base_type
                    cast(dict[str, str], frame["added_decl_types"])[assoc_l] = base_type
            else:
                rhs_py = self.translate_expr(selector, arrays_1d)
                self.emit(f"{assoc_name} = _xf2p_copy_value({rhs_py})")
                if assoc_l in arrays_1d:
                    cast(set[str], frame["added_arrays_1d"]).add(assoc_l)
        self._associate_stack.append(frame)

    def _end_associate_block(self, arrays_1d: set[str]) -> None:
        if not self._associate_stack:
            return
        frame = self._associate_stack.pop()
        for name in cast(set[str], frame.get("added_decl_pointer", set())):
            self._decl_pointer.discard(name)
        for name in cast(dict[str, str], frame.get("added_decl_types", {})).keys():
            self._decl_types.pop(name, None)
        for name in cast(dict[str, str], frame.get("added_decl_array_types", {})).keys():
            self._decl_array_types.pop(name, None)
        for name in cast(set[str], frame.get("added_arrays_1d", set())):
            arrays_1d.discard(name)
        start = int(frame.get("code_start", self._code_emit_count))
        if self._code_emit_count == start:
            self.emit("pass")
        self.indent = max(0, self.indent - 1)

    def _where_parent_mask_expr(self) -> str | None:
        if len(self._where_stack) <= 1:
            return None
        parts = [frame["active"] for frame in self._where_stack[:-1]]
        if not parts:
            return None
        return " & ".join(f"({p})" for p in parts)

    def _where_current_mask_expr(self) -> str | None:
        if not self._where_stack:
            return None
        parts = [frame["active"] for frame in self._where_stack]
        return " & ".join(f"({p})" for p in parts)

    def _start_where_block(self, cond_raw: str, arrays_1d: set[str]) -> None:
        cond_py = self.translate_expr(cond_raw, arrays_1d)
        tag = f"{len(self._where_stack) + 1}_{self._code_emit_count + 1}"
        active_name = f"_xf2p_where_mask_{tag}"
        matched_name = f"_xf2p_where_matched_{tag}"
        outer = self._where_current_mask_expr()
        if outer is None:
            active_expr = f"np.asarray({cond_py}, dtype=bool)"
        else:
            active_expr = f"(np.asarray({outer}, dtype=bool) & np.asarray({cond_py}, dtype=bool))"
        self.emit(f"{active_name} = np.asarray({active_expr}, dtype=bool)")
        self.emit(f"{matched_name} = np.array({active_name}, copy=True)")
        self._where_stack.append({"active": active_name, "matched": matched_name})

    def _where_elsewhere(self, cond_raw: str | None, arrays_1d: set[str]) -> None:
        if not self._where_stack:
            return
        frame = self._where_stack[-1]
        active_name = frame["active"]
        matched_name = frame["matched"]
        parent = self._where_parent_mask_expr()
        if cond_raw is None:
            base_expr = f"np.ones_like({matched_name}, dtype=bool)"
        else:
            cond_py = self.translate_expr(cond_raw, arrays_1d)
            base_expr = f"np.asarray({cond_py}, dtype=bool)"
        if parent is not None:
            base_expr = f"(np.asarray({parent}, dtype=bool) & ({base_expr}))"
        self.emit(f"{active_name} = np.asarray(({base_expr}) & (~{matched_name}), dtype=bool)")
        self.emit(f"{matched_name} = np.asarray({matched_name} | {active_name}, dtype=bool)")

    def _end_where_block(self) -> None:
        if self._where_stack:
            self._where_stack.pop()

    def _where_masked_assignment(self, lhs: str, rhs_py: str, arrays_1d: set[str]) -> bool:
        mask_expr = self._where_current_mask_expr()
        if mask_expr is None:
            return False
        lhs = lhs.replace("%", ".")
        if self._is_chained_subscript(lhs):
            target = self.translate_expr(lhs, arrays_1d)
            spec = self._component_spec(lhs)
            if spec and spec["ftype"] == "integer":
                rhs_py = f"np.asarray({rhs_py}, dtype=int)"
            if spec and spec.get("char_len") is not None:
                rhs_py = f"_f_str_assign({rhs_py}, {self.translate_expr(spec['char_len'], arrays_1d)})"
            value = f"np.where({mask_expr}, {rhs_py}, {target})"
            if spec and spec.get("shape") and not lhs.rstrip().endswith(")"):
                value = f"_f_assign_array({target}, {value})"
            self.emit(f"{target} = {value}")
            return True
        lhs_base = lhs.split(".", 1)[0].strip().lower()
        rhs_py = self._integer_assignment_rhs(lhs, rhs_py, arrays_1d)
        mname = re.match(r"^\s*([a-z_]\w*(?:\.[a-z_]\w*)*)\s*\(", lhs, re.I)
        idx_name = None
        idx = None
        if mname:
            name_try = mname.group(1)
            open_pos = lhs.find("(", mname.end(1))
            if open_pos >= 0:
                close_pos = find_matching_paren(lhs, open_pos)
                if close_pos == len(lhs) - 1:
                    idx_name = name_try
                    idx = lhs[open_pos + 1 : close_pos].strip()
        if idx_name is not None and idx is not None and (":" in idx or "," in idx):
            name = idx_name
            if "," in idx:
                parts = [p.strip() for p in split_args(idx)]
                idx_parts: list[str] = []
                for ptxt in parts:
                    if ptxt == ":":
                        idx_parts.append(":")
                    elif ":" in ptxt:
                        lo, hi = self._split_section(ptxt)
                        lo = lo.strip()
                        hi = hi.strip()
                        idx_parts.append(self._slice_expr_from_decl_bounds(name, lo, hi, len(idx_parts), arrays_1d))
                    else:
                        idx_parts.append(self._index_expr_from_decl_bounds(name, ptxt, len(idx_parts), arrays_1d))
                target = f"{name}[{', '.join(idx_parts)}]"
            else:
                lo, hi = self._split_section(idx)
                lo = lo.strip()
                hi = hi.strip()
                target = f"{name}[{self._slice_expr_from_decl_bounds(name, lo, hi, 0, arrays_1d)}]"
            self.emit(f"{target} = np.where({mask_expr}, {rhs_py}, {target})")
            return True
        is_array_target = (lhs in arrays_1d) or (lhs_base in self._decl_array_types)
        if is_array_target:
            if re.fullmatch(r"[A-Za-z_]\w*", lhs) and (lhs.lower() in self._decl_pointer or lhs.lower() in self._decl_target):
                self.emit(f"{lhs}[...] = np.where({mask_expr}, {rhs_py}, {lhs})")
            else:
                self.emit(f"{lhs} = _f_assign_array({lhs}, np.where({mask_expr}, {rhs_py}, {lhs}))")
            return True
        return False

    def _parse_forall_header(self, raw: str, arrays_1d: set[str]) -> tuple[list[tuple[str, str, str, str | None]], str | None]:
        loops: list[tuple[str, str, str, str | None]] = []
        mask_raw: str | None = None
        for part in split_args(raw):
            part = part.strip()
            if not part:
                continue
            mm = re.match(r"^([a-z_]\w*)\s*=\s*(.+)$", part, re.I)
            if mm:
                var = mm.group(1)
                rhs = mm.group(2).strip()
                trip = [p.strip() for p in split_top_level(rhs, ':')]
                if len(trip) in (2, 3) and trip[0] != '' and trip[1] != '':
                    lo_py = self.translate_expr(trip[0], arrays_1d)
                    hi_py = self.translate_expr(trip[1], arrays_1d)
                    step_py = self.translate_expr(trip[2], arrays_1d) if len(trip) == 3 and trip[2] != '' else None
                    loops.append((var, lo_py, hi_py, step_py))
                    continue
            if mask_raw is None:
                mask_raw = part
            else:
                mask_raw = mask_raw + ', ' + part
        mask_py = self.translate_expr(mask_raw, arrays_1d) if mask_raw is not None else None
        return loops, mask_py

    def _emit_forall_block_start(self, header_raw: str, arrays_1d: set[str]) -> int:
        loops, mask_py = self._parse_forall_header(header_raw, arrays_1d)
        levels = 0
        for var, lo_py, hi_py, step_py in loops:
            if step_py is None:
                self.emit(f"for {var} in range({lo_py}, ({hi_py}) + 1):")
            else:
                self.emit(f"for {var} in range({lo_py}, ({hi_py}) + (1 if ({step_py}) > 0 else -1), {step_py}):")
            self.indent += 1
            self._block_code_start.append(self._code_emit_count)
            levels += 1
        if mask_py is not None:
            self.emit(f"if {mask_py}:")
            self.indent += 1
            self._block_code_start.append(self._code_emit_count)
            levels += 1
        return levels

    def _emit_forall_block_end(self, levels: int) -> None:
        for _ in range(levels):
            if self._block_code_start:
                start = self._block_code_start.pop()
                if self._code_emit_count == start:
                    self.emit("pass")
            self.indent = max(0, self.indent - 1)

    def _enter_do_loop(self, entry: dict[str, object], name: str | None) -> None:
        """Wrap named loop iterations so outer transfers can unwind inner loops."""
        entry["name"] = name.lower() if name else None
        if name:
            if any(isinstance(loop, dict) and loop.get("name") == name.lower()
                   for loop in self._do_stack):
                raise ValueError(f"duplicate active DO construct name: {name}")
            entry["target"] = self._loop_counter
            self.emit("try:")
            self.indent += 1
        self._block_code_start.append(self._code_emit_count)
        self._do_stack.append(entry)

    def _close_do_loop_body(self, entry: dict[str, object]) -> None:
        start = self._block_code_start.pop()
        if self._code_emit_count == start:
            self.emit("pass")
        self.indent -= 1
        if entry.get("name"):
            control = f"_xf2p_loop_control_{entry['target']}"
            self.emit(f"except _xf2p_LoopControl as {control}:")
            self.indent += 1
            self.emit(f"if {control}.args[0] != {entry['target']}:")
            self.indent += 1
            self.emit("raise")
            self.indent -= 1
            self.emit(f"if {control}.args[1] == 'cycle':")
            self.indent += 1
            self.emit("continue")
            self.indent -= 1
            self.emit("break")
            self.indent -= 2

    def handle_exec_line(self, s: str, arrays_1d: set[str]) -> bool:
        sl = s.lower()
        if re.match(r"(?:[a-z_]\w*\s*:\s*)?select\s+rank\s*\(", s, re.I):
            raise ValueError("SELECT RANK is not yet supported; branch selection cannot be ignored safely")
        if s in getattr(self, "_lexical_block_entries", {}):
            declarations = self._lexical_block_entries[s]
            parameters: set[str] = set()
            for declaration, _ in declarations:
                parsed = parse_decl(declaration)
                if parsed:
                    ftype, attrs, rest = parsed
                    parameters |= self.emit_parameters_from_decl(
                        ftype, attrs.lower(), rest, arrays_1d, block_entry=True)
            symbols = self._host_symbol_table(declarations)
            for info in symbols.values():
                info["alloc"] = "allocatable" in info["attrs_l"]
            self.emit_var_inits_from_sym(symbols, arrays_1d, parameters, block_entry=True)
            return True

        pwhere = None
        if sl.startswith("where"):
            p0 = s.lower().find("where") + len("where")
            while p0 < len(s) and s[p0].isspace():
                p0 += 1
            if p0 < len(s) and s[p0] == "(":
                p1 = find_matching_paren(s, p0)
                if p1 != -1:
                    pwhere = (p0, p1)

        pforall = None
        if sl.startswith("forall"):
            p0 = s.lower().find("forall") + len("forall")
            while p0 < len(s) and s[p0].isspace():
                p0 += 1
            if p0 < len(s) and s[p0] == "(":
                p1 = find_matching_paren(s, p0)
                if p1 != -1:
                    pforall = (p0, p1)

        pdo_concurrent = None
        mm = re.match(r"(?:[a-z_]\w*\s*:\s*)?do\s+concurrent", s, re.I)
        if mm:
            if re.match(r"[a-z_]\w*\s*:", s, re.I):
                raise ValueError("named DO CONCURRENT is not yet supported")
            p0 = mm.end()
            while p0 < len(s) and s[p0].isspace():
                p0 += 1
            if p0 < len(s) and s[p0] == "(":
                p1 = find_matching_paren(s, p0)
                if p1 != -1:
                    pdo_concurrent = (p0, p1)

        # ignore some non-exec lines
        if sl in ("implicit none", "contains"):
            return True
        if sl.startswith("use "):
            return True
        if sl.startswith("end function") or sl.startswith("end program") or sl.startswith("end module"):
            return True
        if sl == "end":
            return True

        mm = re.match(r"associate\s*\(\s*(.*)\s*\)\s*(?:;\s*(.*))?$", s, re.I)
        if mm:
            self._start_associate_block(mm.group(1), arrays_1d)
            inline_stmt = (mm.group(2) or "").strip()
            if inline_stmt:
                self.transpile_simple_stmt(inline_stmt, arrays_1d)
            return True

        if re.match(r"end\s+associate", s, re.I):
            self._end_associate_block(arrays_1d)
            return True

        if re.match(r"end\s+where", s, re.I):
            self._end_where_block()
            return True

        mm = re.match(r"elsewhere\s*\(\s*(.+)\s*\)\s*$", s, re.I)
        if mm:
            self._where_elsewhere(mm.group(1), arrays_1d)
            return True

        if re.match(r"elsewhere\s*$", s, re.I):
            self._where_elsewhere(None, arrays_1d)
            return True

        if pwhere is not None:
            p0, p1 = pwhere
            cond_raw = s[p0 + 1 : p1].strip()
            tail = s[p1 + 1 :].strip()
            if tail:
                self._start_where_block(cond_raw, arrays_1d)
                self.transpile_simple_stmt(tail, arrays_1d)
                self._end_where_block()
            else:
                self._start_where_block(cond_raw, arrays_1d)
            return True

        if re.match(r"end\s+forall", s, re.I):
            levels = self._forall_stack.pop() if self._forall_stack else 0
            self._emit_forall_block_end(levels)
            return True

        if pforall is not None:
            p0, p1 = pforall
            header_raw = s[p0 + 1 : p1].strip()
            tail = s[p1 + 1 :].strip()
            levels = self._emit_forall_block_start(header_raw, arrays_1d)
            if tail:
                self.transpile_simple_stmt(tail, arrays_1d)
                self._emit_forall_block_end(levels)
            else:
                self._forall_stack.append(levels)
            return True

        if pdo_concurrent is not None:
            p0, p1 = pdo_concurrent
            header_raw = s[p0 + 1 : p1].strip()
            tail = s[p1 + 1 :].strip()
            levels = self._emit_forall_block_start(header_raw, arrays_1d)
            if tail:
                self.transpile_simple_stmt(tail, arrays_1d)
                self._emit_forall_block_end(levels)
            else:
                self._do_stack.append(levels)
            return True

        mm = re.match(r"select\s+case\s*\(\s*(.+)\s*\)\s*$", s, re.I)
        if mm:
            expr = self.translate_expr(mm.group(1), arrays_1d)
            self._select_case_stack.append({"expr": expr, "had_case": False, "in_case": False, "case_start": self._code_emit_count})
            return True

        mm = re.match(r"case\s+default\s*(?:;\s*(.*))?$", s, re.I)
        if mm and self._select_case_stack:
            self._xf2p_select_case_start("default", arrays_1d, mm.group(1))
            return True

        mm = re.match(r"case\s*\(\s*(.*?)\s*\)\s*(?:;\s*(.*))?$", s, re.I)
        if mm and self._select_case_stack:
            self._xf2p_select_case_start(mm.group(1), arrays_1d, mm.group(2))
            return True

        if sl.startswith("end select"):
            if self._select_case_stack:
                st = self._select_case_stack.pop()
                if st.get("in_case", False):
                    start = int(st.get("case_start", self._code_emit_count))
                    if self._code_emit_count == start:
                        self.emit("pass")
                    self.indent = max(0, self.indent - 1)
            return True

        # if (...) then
        mm = re.match(r"if\s*\(\s*(.+)\s*\)\s*then$", s, re.I)
        if mm:
            cond = self.translate_expr(mm.group(1), arrays_1d)
            self.emit(f"if {cond}:")
            self.indent += 1
            self._block_code_start.append(self._code_emit_count)
            return True

        mm = re.match(r"else\s+if\s*\(\s*(.+)\s*\)\s*then$", s, re.I)
        if mm:
            cond = self.translate_expr(mm.group(1), arrays_1d)
            self.indent = max(0, self.indent - 1)
            self.emit(f"elif {cond}:")
            self.indent += 1
            return True

        if sl == "else":
            self.indent = max(0, self.indent - 1)
            self.emit("else:")
            self.indent += 1
            return True

        if sl.startswith("end if"):
            if self._block_code_start:
                start = self._block_code_start.pop()
                if self._code_emit_count == start:
                    self.emit("pass")
            self.indent = max(0, self.indent - 1)
            return True

        # [label:] do while (...)
        mm = re.match(r"(?:([a-z_]\w*)\s*:\s*)?do\s+while\s*\(\s*(.+)\s*\)$", s, re.I)
        if mm:
            cond = self.translate_expr(mm.group(2), arrays_1d)
            self.emit(f"while {cond}:")
            self.indent += 1
            self._loop_counter += 1
            self._enter_do_loop({"kind": "while", "levels": 1}, mm.group(1))
            return True

        mm = re.fullmatch(r"(?:([a-z_]\w*)\s*:\s*)?do", s, re.I)
        if mm:
            self.emit("while True:")
            self.indent += 1
            self._loop_counter += 1
            self._enter_do_loop({"kind": "while", "levels": 1}, mm.group(1))
            return True

        # [label:] do i = a, b[, step]
        mm = re.match(r"(?:([a-z_]\w*)\s*:\s*)?do\s+([a-z_]\w*)\s*=\s*(.+)$", s, re.I)
        if mm:
            var = mm.group(2)
            rhs = mm.group(3).strip()
            parts = split_args(rhs)
            if len(parts) in (2, 3):
                a = self.translate_expr(parts[0], arrays_1d)
                b = self.translate_expr(parts[1], arrays_1d)
                self._loop_counter += 1
                loop_id = self._loop_counter
                lo_tmp = f"_xf2p_do_lo_{loop_id}"
                hi_tmp = f"_xf2p_do_hi_{loop_id}"
                step_tmp = f"_xf2p_do_step_{loop_id}"
                stop_tmp = f"_xf2p_do_stop_{loop_id}"
                self.emit(f"{lo_tmp} = {a}")
                self.emit(f"{hi_tmp} = {b}")
                if len(parts) == 2:
                    self.emit(f"{step_tmp} = 1")
                else:
                    step_py = self.translate_expr(parts[2], arrays_1d)
                    self.emit(f"{step_tmp} = {step_py}")
                self.emit(f"{stop_tmp} = {hi_tmp} + (1 if {step_tmp} > 0 else -1)")
                self.emit(f"for {var} in range({lo_tmp}, {stop_tmp}, {step_tmp}):")
                self.indent += 1
                self._enter_do_loop({"kind": "fortran_do", "levels": 1,
                                     "post_assign": f"{var} = {hi_tmp} + {step_tmp}"}, mm.group(1))
                return True

        if re.match(r"end\s+do(?:\s+[a-z_]\w*)?$", s, re.I):
            entry = self._do_stack.pop() if self._do_stack else 1
            end_name = re.fullmatch(r"end\s+do\s+([a-z_]\w*)", s, re.I)
            if end_name and (not isinstance(entry, dict) or entry.get("name") != end_name.group(1).lower()):
                raise ValueError(f"END DO construct name does not match active loop: {s}")
            if isinstance(entry, dict) and entry.get("kind") in {"fortran_do", "while"}:
                self._close_do_loop_body(entry)
                post_assign = str(entry.get("post_assign", ""))
                if post_assign:
                    self.emit("else:")
                    self.indent += 1
                    self.emit(post_assign)
                    self.indent = max(0, self.indent - 1)
                return True
            levels = int(entry.get("levels", 1)) if isinstance(entry, dict) else int(entry)
            for _ in range(levels):
                if self._block_code_start:
                    start = self._block_code_start.pop()
                    if self._code_emit_count == start:
                        self.emit("pass")
                self.indent = max(0, self.indent - 1)
            return True

        # ALLOCATE objects and allocation options are separate top-level items.
        mm = re.match(r"allocate\s*\((.*)\)\s*$", s, re.I)
        if mm:
            options = {}
            objects = []
            for item in split_args(mm.group(1)):
                option = re.match(r"^(\w+)\s*=\s*(.+)$", item.strip(), re.I)
                if option:
                    key = option.group(1).lower()
                    if key not in {"source", "mold", "stat", "errmsg"} or key in options:
                        raise ValueError(f"unsupported or duplicate ALLOCATE option: {item}")
                    options[key] = option.group(2).strip()
                else:
                    target = re.fullmatch(r"([a-z_]\w*(?:\s*%\s*[a-z_]\w*)*)\s*(?:\((.*)\))?", item.strip(), re.I)
                    if not target:
                        raise ValueError(f"unsupported ALLOCATE object/type-spec: {item}")
                    objects.append((re.sub(r"\s*%\s*", ".", target.group(1)), target.group(2)))
            if not objects or ("source" in options and "mold" in options):
                raise ValueError(f"invalid ALLOCATE statement: {s}")
            self._allocation_counter += 1
            stem = _choose_fresh_identifier(self._allocation_source, f"_xf2p_allocate_{self._allocation_counter}")
            model_name = _choose_fresh_identifier(self._allocation_source, f"{stem}_model")
            model_raw = options.get("source", options.get("mold"))
            if model_raw is not None:
                self.emit(f"{model_name} = {self.translate_expr(model_raw, arrays_1d)}")
            status = self.translate_expr(options["stat"], arrays_1d) if "stat" in options else None
            message = self.translate_expr(options["errmsg"], arrays_1d) if "errmsg" in options else None
            if message and not status:
                raise ValueError("ALLOCATE ERRMSG without STAT is not supported")
            if status:
                self.emit("try:")
                self.indent += 1
            for name, shape_raw in objects:
                spec = self._component_spec(name) if "." in name else None
                ftype = spec["ftype"] if spec else self._decl_types.get(name.lower())
                if ftype not in _type_dtype and ftype != "type":
                    raise ValueError(f"unknown ALLOCATE object type: {name}")
                self.emit(f"if {name} is not None:")
                self.indent += 1
                self.emit(f"raise ValueError('ALLOCATE object already allocated: {name}')")
                self.indent -= 1
                declared_shape = spec.get("shape") if spec else None
                rank = len(self._shape_bounds(declared_shape)) if declared_shape else len(self._decl_lbounds.get(name.lower(), []))
                if not rank and (name.lower() in self._decl_array_types or name in arrays_1d):
                    rank = 1
                bounds_name = self._allocation_bound_names.setdefault(name.lower(), _choose_fresh_identifier(self._allocation_source, f"{stem}_bounds_{len(self._allocation_bound_names)}"))
                component_lows = []
                if shape_raw is not None:
                    bounds = self._shape_bounds(shape_raw)
                    if len(bounds) != rank or any(not hi for _lo, hi in bounds):
                        raise ValueError(f"invalid ALLOCATE bounds for {name}")
                    bounds_py = [(self.translate_expr(lo, arrays_1d), self.translate_expr(hi, arrays_1d)) for lo, hi in bounds]
                    component_lows = [lo for lo, _hi in bounds_py]
                    self.emit(f"{bounds_name} = [" + ", ".join(f"(int({lo}), int({hi}))" for lo, hi in bounds_py) + "]")
                    shape_py = f"[max(0, hi - lo + 1) for lo, hi in {bounds_name}]"
                    lows = [f"{bounds_name}[{d}][0]" for d in range(rank)]
                elif rank:
                    if model_raw is None:
                        raise ValueError(f"ALLOCATE {name} requires bounds, SOURCE, or MOLD")
                    shape_py = "None"
                    lows = []
                    for d in range(rank):
                        # Whole array variables retain bounds; array expressions
                        # (including sections) have one-based allocation bounds.
                        low = self._decl_bound_expr(model_raw, d, "lo", arrays_1d) if re.fullmatch(r"[a-z_]\w*(?:%[a-z_]\w*)*", model_raw, re.I) else None
                        lows.append(low or "1")
                    component_lows = list(lows)
                    self.emit(f"{bounds_name} = [" + ", ".join(f"(int({lo}), None)" for lo in lows) + "]")
                    lows = [f"{bounds_name}[{d}][0]" for d in range(rank)]
                else:
                    shape_py, lows = "()", []
                if "." in name and any(lo != "1" for lo in component_lows):
                    self.emit(f"if any(lo != 1 for lo, hi in {bounds_name}):")
                    self.indent += 1
                    self.emit("raise NotImplementedError('non-default bounds for allocated components are not supported')")
                    self.indent -= 1
                dtype = "object" if ftype == "type" else _type_dtype[ftype]
                type_name = spec.get("type_name") if spec else self._decl_type_names.get(name.lower())
                factory = type_name if ftype == "type" else "None"
                length = spec.get("char_len") if spec else self._decl_char_len.get(name.lower())
                if length in {":", "*"}:
                    raise ValueError("deferred-length CHARACTER allocation is not supported")
                length_py = self.translate_expr(length, arrays_1d) if length is not None else "None"
                model = model_name if model_raw is not None else "None"
                self.emit(f"{name} = _f_allocate({model}, shape={shape_py}, dtype={dtype}, source={'source' in options}, rank={rank}, factory={factory}, char_len={length_py})")
                if "." not in name:
                    self._decl_lbounds[name.lower()] = [f"({lo}) if _f_size({name}, dim={d+1}) else 1" for d, lo in enumerate(lows)]
                    self._decl_ubounds[name.lower()] = [f"({lo}) + _f_size({name}, dim={d+1}) - 1 if _f_size({name}, dim={d+1}) else 0" for d, lo in enumerate(lows)]
            if status:
                self.indent -= 1
                self.emit("except (MemoryError, ValueError, TypeError, OverflowError) as _xf2p_allocation_error:")
                self.indent += 1
                self.emit(f"{status} = 1")
                if message:
                    length = self._decl_char_len.get(options["errmsg"].lower())
                    text = "str(_xf2p_allocation_error)"
                    if length:
                        text = f"_f_str_assign({text}, {self.translate_expr(length, arrays_1d)})"
                    self.emit(f"{message} = {text}")
                self.indent -= 1
                self.emit("else:")
                self.indent += 1
                self.emit(f"{status} = 0")
                self.indent -= 1
            return True

        if re.match(r"allocate\b", s, re.I):
            raise ValueError(f"unsupported ALLOCATE statement: {s}")

        # open(newunit=fp, file="temp.txt", ...) or open(unit=iu, file="temp.txt", ...)
        mm = re.match(r"open\s*\(\s*(.+)\s*\)\s*$", s, re.I)
        if mm:
            spec = mm.group(1).strip()
            unit_m = re.search(r"\b(?:newunit|unit)\s*=\s*([^,]+)", spec, re.I)
            file_m = re.search(r"\bfile\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            status_m = re.search(r"\bstatus\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            action_m = re.search(r"\baction\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            position_m = re.search(r"\bposition\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            unit_var = unit_m.group(1).strip() if unit_m else None
            file_expr = file_m.group(1).strip() if file_m else None
            status = status_m.group(1).strip() if status_m else None
            action = action_m.group(1).strip() if action_m else None
            position = position_m.group(1).strip() if position_m else None
            if unit_var is None or file_expr is None:
                self.emit(f"# unsupported open form: {s}")
                return True
            mode = "r"
            st = status.strip().strip("'\"").lower() if status else ""
            act = action.strip().strip("'\"").lower() if action else ""
            pos = position.strip().strip("'\"").lower() if position else ""
            if act == "write" or st == "replace":
                mode = "w"
            if pos == "append":
                mode = "a"
            self.emit(f"{unit_var} = open({self.translate_expr(file_expr, arrays_1d)}, {mode!r})")
            return True

        # close(fp)
        mm = re.match(r"close\s*\(\s*(.+?)\s*\)\s*$", s, re.I)
        if mm:
            unit = self.translate_expr(mm.group(1), arrays_1d)
            self.emit(f"{unit}.close()")
            return True

        # call random_number(x)
        mm = re.match(r"call\s+random_number\s*\(\s*([a-z_]\w*)\s*\)\s*$", s, re.I)
        if mm:
            name = mm.group(1)
            if name in arrays_1d:
                self.emit(f"{name} = _f_assign_array({name}, np.random.random(size={name}.shape))")
            else:
                self.emit(f"{name} = np.float64(np.random.random())")
            return True

        # open(newunit=fp, file="temp.txt", ...) or open(unit=iu, file="temp.txt", ...)
        mm = re.match(r"open\s*\(\s*(.+)\s*\)\s*$", s, re.I)
        if mm:
            spec = mm.group(1).strip()
            unit_m = re.search(r"\b(?:newunit|unit)\s*=\s*([^,]+)", spec, re.I)
            file_m = re.search(r"\bfile\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            status_m = re.search(r"\bstatus\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            action_m = re.search(r"\baction\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            position_m = re.search(r"\bposition\s*=\s*(.+?)(?:,\s*[a-z_]\w*\s*=|$)", spec, re.I)
            unit_var = unit_m.group(1).strip() if unit_m else None
            file_expr = file_m.group(1).strip() if file_m else None
            status = status_m.group(1).strip() if status_m else None
            action = action_m.group(1).strip() if action_m else None
            position = position_m.group(1).strip() if position_m else None
            if unit_var is None or file_expr is None:
                self.emit(f"# unsupported open form: {s}")
                return True
            mode = "r"
            st = status.strip().strip("'\"").lower() if status else ""
            act = action.strip().strip("'\"").lower() if action else ""
            pos = position.strip().strip("'\"").lower() if position else ""
            if act == "write" or st == "replace":
                mode = "w"
            if pos == "append":
                mode = "a"
            self.emit(f"{unit_var} = open({self.translate_expr(file_expr, arrays_1d)}, {mode!r})")
            return True

        # close(fp)
        mm = re.match(r"close\s*\(\s*(.+?)\s*\)\s*$", s, re.I)
        if mm:
            unit = self.translate_expr(mm.group(1), arrays_1d)
            self.emit(f"{unit}.close()")
            return True

        # read(unit, "(a)", iostat=ios) text
        if sl.startswith("read"):
            p0 = s.find("(")
            if p0 != -1:
                p1 = find_matching_paren(s, p0)
                if p1 != -1:
                    spec = s[p0 + 1 : p1].strip()
                    rest = s[p1 + 1 :].strip()
                    parts = split_args(spec)
                    if len(parts) >= 2:
                        unit = self.translate_expr(parts[0].strip(), arrays_1d)
                        fmt = parts[1].strip()
                        kws = {}
                        for p in parts[2:]:
                            mk = re.match(r"^\s*([a-z_]\w*)\s*=\s*(.+?)\s*$", p, re.I)
                            if mk:
                                kws[mk.group(1).lower()] = mk.group(2).strip()
                        unit_raw = parts[0].strip()
                        unit_base_m = re.match(r"([a-z_]\w*)", unit_raw, re.I)
                        unit_base = unit_base_m.group(1).lower() if unit_base_m else ""
                        internal_char_source = (
                            self._decl_types.get(unit_base) == "character"
                            or self._decl_array_types.get(unit_base) == "character"
                        )
                        unit_py = self.translate_expr(unit_raw, arrays_1d)
                        if fmt == "*" and internal_char_source and rest:
                            ios_var = kws.get("iostat")
                            items = [a.strip() for a in split_args(rest) if a.strip()]
                            self.emit(f"__xf2p_read_parts = str({unit_py}).split()")
                            self.emit("try:")
                            self.indent += 1
                            for i, tgt in enumerate(items):
                                lhs = self.translate_expr(tgt, arrays_1d)
                                base = re.match(r"^([a-z_]\w*)", tgt, re.I)
                                bnm = base.group(1).lower() if base else ""
                                ftype = self._decl_types.get(bnm, self._decl_array_types.get(bnm, ""))
                                if ftype == "integer":
                                    rhs = f"int(__xf2p_read_parts[{i}])"
                                elif ftype == "logical":
                                    rhs = f"(str(__xf2p_read_parts[{i}]).strip().lower() in ('t', 'true', '.true.'))"
                                elif ftype == "character":
                                    rhs = f"_f_str_assign(str(__xf2p_read_parts[{i}]), _f_len({lhs}))"
                                else:
                                    rhs = f"float(__xf2p_read_parts[{i}])"
                                self.emit(f"{lhs} = {rhs}")
                            if ios_var is not None:
                                self.emit(f"{ios_var} = 0")
                            self.indent -= 1
                            self.emit("except Exception:")
                            self.indent += 1
                            if ios_var is not None:
                                self.emit(f"{ios_var} = 1")
                            else:
                                self.emit("raise")
                            self.indent -= 1
                            return True
                        if fmt != "*":
                            fmt_txt = _fortran_unquote(fmt).strip().lower() if (len(fmt) >= 2 and fmt[0] in ("'", '"') and fmt[-1] == fmt[0]) else ""
                            if fmt_txt in {"(a)", "a"} and rest:
                                ios_var = kws.get("iostat")
                                lhs = self.translate_expr(rest, arrays_1d)
                                if internal_char_source:
                                    self.emit(f"__xf2p_line = str({unit_py})")
                                    if ios_var is not None:
                                        self.emit(f"{ios_var} = 0")
                                    self.emit(f"{lhs} = __xf2p_line.rstrip('\\n')")
                                    return True
                                self.emit(f"__xf2p_line = {unit}.readline()")
                                if ios_var is not None:
                                    self.emit(f"{ios_var} = 0 if __xf2p_line != '' else -1")
                                self.emit(f"{lhs} = __xf2p_line.rstrip('\\n')")
                                return True

        # read(fp,*) a, b, arr(i,:), ...
        mm = re.match(r"read\s*\(\s*([a-z_]\w*)\s*,\s*\*\s*\)\s*(.+)$", s, re.I)
        if mm:
            unit = mm.group(1)
            rest = mm.group(2).strip()
            items = [a.strip() for a in split_args(rest) if a.strip()]
            if len(items) == 1:
                tgt = items[0]
                # row-slice target: mat(i,:)
                mrow = re.match(r"^([a-z_]\w*)\s*\(\s*([^,]+)\s*,\s*:\s*\)\s*$", tgt, re.I)
                if mrow:
                    arr = mrow.group(1)
                    ridx = self.translate_expr(mrow.group(2), arrays_1d)
                    ftype = self._decl_array_types.get(arr.lower(), "")
                    cast = "int" if ftype == "integer" else "float"
                    self.emit(f"__read_vals = [{cast}(v) for v in {unit}.readline().split()]")
                    self.emit(f"{arr}[{self._index_expr_from_decl_bounds(arr, mrow.group(2), 0, arrays_1d)}, :] = np.asarray(__read_vals[:{arr}.shape[1]], dtype={arr}.dtype)")
                    return True
                # scalar target
                lhs = self.translate_expr(tgt, arrays_1d)
                base = re.match(r"^([a-z_]\w*)", tgt, re.I)
                bnm = base.group(1).lower() if base else ""
                ftype = self._decl_types.get(bnm, "")
                cast = "int" if ftype == "integer" else ("bool" if ftype == "logical" else "float")
                self.emit(f"{lhs} = {cast}({unit}.readline().split()[0])")
                return True
            # multiple scalar targets
            self.emit(f"__read_parts = {unit}.readline().split()")
            for i, tgt in enumerate(items):
                lhs = self.translate_expr(tgt, arrays_1d)
                base = re.match(r"^([a-z_]\w*)", tgt, re.I)
                bnm = base.group(1).lower() if base else ""
                ftype = self._decl_types.get(bnm, "")
                cast = "int" if ftype == "integer" else ("bool" if ftype == "logical" else "float")
                self.emit(f"{lhs} = {cast}(__read_parts[{i}])")
            return True

        # call foo(...)
        mm = re.match(r"call\s+([a-z_]\w*(?:\s*%\s*[a-z_]\w*)*)\s*(?:\((.*)\))?\s*$", s, re.I)
        if mm:
            opening = s.find("(")
            if opening != -1 and find_matching_paren(s, opening) != len(s) - 1:
                raise ValueError(f"unsupported CALL statement: {s}")
            cname = re.sub(r"\s*%\s*", ".", mm.group(1))
            cname_l = cname.lower()
            argtxt = (mm.group(2) or "").strip()
            args_py: list[str] = []
            kwargs_py: dict[str, str] = {}
            if argtxt:
                for a in split_args(argtxt):
                    a = a.strip()
                    mk = re.match(r"^([a-z_]\w*)\s*=\s*(.+)$", a, re.I)
                    if mk:
                        kwargs_py[mk.group(1).lower()] = self.translate_expr(mk.group(2), arrays_1d)
                    else:
                        args_py.append(self.translate_expr(a, arrays_1d))
            if cname_l == 'move_alloc':
                raw = _bind_intrinsic_arguments(cname_l, argtxt, ('from', 'to', 'stat', 'errmsg'), 2)
                source, destination = raw['from'], raw['to']
                if not all(re.fullmatch(r'[a-z_]\w*', name, re.I) for name in (source, destination)):
                    raise ValueError('MOVE_ALLOC currently requires named variables, not components')
                symbols = {name: info for scope, _ in self._host_scopes for name, info in scope.items()}
                a, b = symbols.get(source), symbols.get(destination)
                if not a or not b or any('allocatable' not in info.get('attrs_l', '') for info in (a, b)):
                    raise ValueError('MOVE_ALLOC requires ALLOCATABLE variables')
                rank_a = len(self._shape_bounds(a['shape'])) if a.get('shape') else 0
                rank_b = len(self._shape_bounds(b['shape'])) if b.get('shape') else 0
                if source == destination or rank_a != rank_b or a['ftype'] != b['ftype'] or a.get('type_name') != b.get('type_name'):
                    raise ValueError('MOVE_ALLOC requires distinct variables of matching type and rank')
                if rank_a:
                    self._allocation_counter += 1
                    bounds_name = _choose_fresh_identifier(self._allocation_source, f'_xf2p_move_bounds_{self._allocation_counter}')
                    lows = [self._decl_bound_expr(source, d, 'lo', arrays_1d) or '1' for d in range(rank_a)]
                    self.emit(f"{bounds_name} = [{', '.join(lows)}] if {source} is not None else None")
                    self._decl_lbounds[destination.lower()] = [f'{bounds_name}[{d}]' for d in range(rank_a)]
                    self._decl_ubounds[destination.lower()] = [''] * rank_a
                self.emit(f'{destination}, {source} = {source}, None')
                if 'stat' in raw:
                    self.emit(f"{self.translate_expr(raw['stat'], arrays_1d)} = 0")
                return True
            if cname_l == 'get_command_argument':
                raw = _bind_intrinsic_arguments(cname_l, argtxt, ('number', 'value', 'length', 'status'), 1)
                number = self.translate_expr(raw['number'], arrays_1d)
                length = f"len({self.translate_expr(raw['value'], arrays_1d)})" if 'value' in raw else 'None'
                self._allocation_counter += 1
                temporary = _choose_fresh_identifier(self._allocation_source, f'_xf2p_command_arg_{self._allocation_counter}')
                self.emit(f'{temporary} = _f_get_command_argument({number}, {length})')
                for index, output in enumerate(('value', 'length', 'status')):
                    if output in raw:
                        self.emit(f"{self.translate_expr(raw[output], arrays_1d)} = {temporary}[{index}]")
                return True
            # Fortran random_seed adapters for valid Python
            if cname.lower() == "random_seed":
                if "size" in kwargs_py:
                    self.emit(f"{kwargs_py['size']} = 1")
                elif "put" in kwargs_py:
                    self.emit(f"np.random.seed(int(np.sum({kwargs_py['put']})) % (2**32 - 1))")
                else:
                    self.emit("np.random.seed(None)")
                return True
            merged = list(args_py)
            for k, v in kwargs_py.items():
                merged.append(f"{k}={v}")
            sig = self._bound_signature(cname) if "." in cname else self._subr_sigs.get(cname_l)
            if "." in cname and sig is None:
                raise ValueError(f"unsupported or unresolved type-bound call: {s}")
            if sig:
                formal_args = sig.get("args", [])
                out_formals = sig.get("out", [])
                if kwargs_py == {} and len(formal_args) > 0 and len(args_py) > len(formal_args):
                    # Robustness for malformed Fortran with duplicated actual arguments.
                    args_py = args_py[: len(formal_args)]
                    merged = list(args_py)
                actual_by_formal: dict[str, str] = {}
                for i, formal in enumerate(formal_args):
                    if i < len(args_py):
                        actual_by_formal[formal] = args_py[i]
                for k, v in kwargs_py.items():
                    actual_by_formal[k] = v
                out_actuals = [actual_by_formal.get(fm, "") for fm in out_formals]
                if out_actuals and all(x != "" for x in out_actuals):
                    self.emit(f"{', '.join(out_actuals)} = {cname}({', '.join(merged)})")
                    return True
            self.emit(f"{cname}({', '.join(merged)})")
            return True

        if re.match(r"^call\b", s, re.I):
            raise ValueError(f"unsupported CALL statement: {s}")

        # return
        if sl == "return":
            if self._current_result_name:
                self.emit(f"return {self._current_result_name}")
            else:
                self.emit("return")
            return True
        mm = re.fullmatch(r"(exit|cycle)(?:\s+([a-z_]\w*))?", s, re.I)
        if mm:
            action, name = mm.group(1).lower(), mm.group(2)
            if not self._do_stack:
                raise ValueError(f"{action.upper()} outside a DO loop is not supported")
            if name:
                target = next((loop for loop in reversed(self._do_stack)
                               if isinstance(loop, dict) and loop.get("name") == name.lower()), None)
                if target is None:
                    raise ValueError(f"unknown DO construct name in {action.upper()}: {name}")
                if target is not self._do_stack[-1]:
                    self.emit(f"raise _xf2p_LoopControl({target['target']}, {action!r})")
                    return True
            self.emit("break" if action == "exit" else "continue")
            return True
        mm = re.match(r"(?:error\s+)?stop(?:\s+(.+))?$", s, re.I)
        if mm:
            msg = (mm.group(1) or '"stop"').strip()
            self.emit(f"raise RuntimeError({msg})")
            return True

        # pointer association: p => target_expr
        mm = re.match(r"^([a-z_]\w*(?:%[a-z_]\w*)*)\s*=>\s*(.+)$", s, re.I)
        if mm:
            lhs = mm.group(1).replace("%", ".")
            rhs_raw = mm.group(2).strip()
            if re.match(r"^null\s*\(\s*\)\s*$", rhs_raw, re.I):
                self.emit(f"{lhs} = None")
            else:
                rhs_py = self.translate_expr(rhs_raw, arrays_1d)
                self.emit(f"{lhs} = {rhs_py}")
            return True

        # nullify(p1, p2, ...)
        mm = re.match(r"nullify\s*\(\s*(.+)\s*\)\s*$", s, re.I)
        if mm:
            for a in split_args(mm.group(1)):
                nm = a.strip().replace("%", ".")
                if nm:
                    self.emit(f"{nm} = None")
            return True

        # deallocate(p) / deallocate(a) -- model as None
        mm = re.match(r"deallocate\s*\(\s*(.+)\s*\)\s*$", s, re.I)
        if mm:
            for a in split_args(mm.group(1)):
                nm = a.strip().replace("%", ".")
                if nm:
                    self.emit(f"{nm} = None")
            return True

        # print *
        mm = re.match(r"print\s*\*\s*$", s, re.I)
        if mm:
            self.emit("print()")
            return True

        # print *, ...
        mm = re.match(r"print\s*\*\s*,\s*(.+)$", s, re.I)
        if mm:
            raw_args = [a.strip() for a in split_args(mm.group(1))]
            if len(raw_args) == 1:
                a0 = raw_args[0].strip()
                implied_py = _fortran_implied_do_expr(a0, self.translate_expr, arrays_1d)
                if implied_py is not None:
                    self.emit(f"_xf2p_print_star(*{implied_py})")
                    return True
                if re.fullmatch(r"[a-z_]\w*", a0, flags=re.I) and a0.lower() in self._decl_array_types:
                    self.emit(f"_xf2p_print_star(*np.ravel({a0}, order='F'))")
                    return True
            args2 = []
            for a in raw_args:
                if _is_fortran_string_literal(a):
                    args2.append(a)
                else:
                    implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                    if implied_py is not None:
                        args2.append(f"*{implied_py}")
                    else:
                        args2.append(f"*_xf2p_io_items({self.translate_expr(a, arrays_1d)})")
            self.emit(f"_xf2p_print_star({', '.join(args2)})")
            return True

        # print "fmt", ...
        mm = re.match(r"print\s*((\"|').*?\2)\s*,\s*(.+)$", s, re.I)
        if mm:
            fmt = mm.group(1)
            raw_args = [a.strip() for a in split_args(mm.group(3))]
            args2 = []
            for a in raw_args:
                if _is_fortran_string_literal(a):
                    args2.append(a)
                else:
                    implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                    if implied_py is not None:
                        args2.append(implied_py)
                    else:
                        args2.append(self.translate_expr(a, arrays_1d))
            if len(raw_args) == 1:
                a0 = raw_args[0].strip()
                if _is_recyclable_io_iterable(a0, self._decl_array_types):
                    fmt_expr = _fortran_format_recycled_expr(fmt, args2[0])
                    if fmt_expr is not None:
                        self.emit(f"print({fmt_expr})")
                        return True
            if len(raw_args) > 1:
                plan = _single_iterable_formatted_arg_plan(fmt, raw_args, self._decl_array_types)
                if plan is not None:
                    iter_pos, iter_need = plan
                    iter_raw = raw_args[iter_pos].strip()
                    iter_tmp = f"_xf2p_fmt_items_{self._code_emit_count + 1}"
                    if re.fullmatch(r"[a-z_]\w*", iter_raw, flags=re.I) and iter_raw.lower() in self._decl_array_types:
                        self.emit(f"{iter_tmp} = list(np.ravel({args2[iter_pos]}, order='F'))")
                    else:
                        self.emit(f"{iter_tmp} = list({args2[iter_pos]})")
                    expanded_args = args2[:iter_pos] + [f"{iter_tmp}[{k}]" for k in range(iter_need)] + args2[iter_pos + 1:]
                    fmt_expr = _fortran_format_expr(fmt, expanded_args)
                    if fmt_expr is not None:
                        self.emit(f"print({fmt_expr})")
                        return True
            fmt_expr = _fortran_format_expr(fmt, args2)
            if fmt_expr is not None:
                self.emit(f"print({fmt_expr})")
            else:
                self.emit(f"_xf2p_print_star({', '.join(args2)})")
            return True

        # robust write(...) parser
        if re.match(r"write\b", s, re.I):
            mkw = re.match(r"write\b", s, re.I)
            j = mkw.end()
            while j < len(s) and s[j].isspace():
                j += 1
            if j < len(s) and s[j] == "(":
                p1 = find_matching_paren(s, j)
                if p1 != -1:
                    ctl = s[j + 1 : p1].strip()
                    rest = s[p1 + 1 :].strip()
                    ctl_parts = [p.strip() for p in split_args(ctl)]
                    unit_raw = ctl_parts[0] if ctl_parts else "*"
                    fmt_raw = ctl_parts[1] if len(ctl_parts) >= 2 else "*"
                    advance_no = any(re.match(r"(?is)^advance\s*=\s*['\"]no['\"]$", p) for p in ctl_parts[2:])
                    unit_base_m = re.match(r"([a-z_]\w*)", unit_raw, re.I)
                    unit_base = unit_base_m.group(1).lower() if unit_base_m else ""
                    internal_char_target = unit_raw != "*" and (
                        self._decl_types.get(unit_base) == "character"
                        or self._decl_array_types.get(unit_base) == "character"
                    )

                    raw_args = [a.strip() for a in split_args(rest)] if rest else []

                    def _star_args(raw_list):
                        out = []
                        for a in raw_list:
                            if _is_fortran_string_literal(a):
                                out.append(self.translate_expr(a, arrays_1d))
                            else:
                                implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                                if implied_py is not None:
                                    out.append(f"*{implied_py}")
                                else:
                                    out.append(f"*_xf2p_io_items({self.translate_expr(a, arrays_1d)})")
                        return out

                    def _fmt_args(raw_list):
                        out = []
                        for a in raw_list:
                            if _is_fortran_string_literal(a):
                                out.append(self.translate_expr(a, arrays_1d))
                            else:
                                implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                                if implied_py is not None:
                                    out.append(implied_py)
                                else:
                                    out.append(self.translate_expr(a, arrays_1d))
                        return out

                    if fmt_raw == "*":
                        args_star = _star_args(raw_args)
                        if internal_char_target:
                            target_py = self.translate_expr(unit_raw, arrays_1d)
                            rhs = "''" if not args_star else f"_xf2p_star_text({', '.join(args_star)})"
                            rhs = f"_f_str_assign({rhs}, _f_len({target_py}))"
                            self.transpile_assignment(unit_raw, rhs, arrays_1d)
                            return True
                        file_txt = "" if unit_raw == "*" else f", file={self.translate_expr(unit_raw, arrays_1d)}"
                        if not args_star:
                            if file_txt:
                                self.emit(f"print({file_txt[2:]})")
                            else:
                                self.emit("print()")
                        else:
                            self.emit(f"_xf2p_print_star({', '.join(args_star)}{file_txt})")
                        return True

                    if _is_fortran_string_literal(fmt_raw):
                        args_fmt = _fmt_args(raw_args)
                        fmt_expr = None
                        if len(raw_args) == 1:
                            a0 = raw_args[0].strip()
                            if _is_recyclable_io_iterable(a0, self._decl_array_types):
                                fmt_expr = _fortran_format_recycled_expr(fmt_raw, args_fmt[0])
                        if fmt_expr is None and len(raw_args) > 1:
                            plan = _single_iterable_formatted_arg_plan(fmt_raw, raw_args, self._decl_array_types)
                            if plan is not None:
                                iter_pos, iter_need = plan
                                iter_raw = raw_args[iter_pos].strip()
                                iter_tmp = f"_xf2p_fmt_items_{self._code_emit_count + 1}"
                                if re.fullmatch(r"[a-z_]\w*", iter_raw, flags=re.I) and iter_raw.lower() in self._decl_array_types:
                                    self.emit(f"{iter_tmp} = list(np.ravel({args_fmt[iter_pos]}, order='F'))")
                                else:
                                    self.emit(f"{iter_tmp} = list({args_fmt[iter_pos]})")
                                expanded_args = args_fmt[:iter_pos] + [f"{iter_tmp}[{k}]" for k in range(iter_need)] + args_fmt[iter_pos + 1:]
                                fmt_expr = _fortran_format_expr(fmt_raw, expanded_args)
                        if fmt_expr is None:
                            fmt_expr = _fortran_format_expr(fmt_raw, args_fmt)
                        if internal_char_target:
                            target_py = self.translate_expr(unit_raw, arrays_1d)
                            rhs_core = fmt_expr if fmt_expr is not None else ("''" if not raw_args else f"_xf2p_star_text({', '.join(_star_args(raw_args))})")
                            rhs = f"_f_str_assign({rhs_core}, _f_len({target_py}))"
                            self.transpile_assignment(unit_raw, rhs, arrays_1d)
                            return True
                        file_txt = "" if unit_raw == "*" else f", file={self.translate_expr(unit_raw, arrays_1d)}"
                        if fmt_expr is not None:
                            self.emit(f"print({fmt_expr}{', end=""' if advance_no else ''}{file_txt})")
                        else:
                            args_star = _star_args(raw_args)
                            self.emit(f"_xf2p_print_star({', '.join(args_star)}{file_txt})")
                        return True

                    args_star = _star_args(raw_args)
                    if internal_char_target:
                        target_py = self.translate_expr(unit_raw, arrays_1d)
                        rhs = "''" if not args_star else f"_xf2p_star_text({', '.join(args_star)})"
                        rhs = f"_f_str_assign({rhs}, _f_len({target_py}))"
                        self.transpile_assignment(unit_raw, rhs, arrays_1d)
                    else:
                        file_txt = "" if unit_raw == "*" else f", file={self.translate_expr(unit_raw, arrays_1d)}"
                        if args_star:
                            self.emit(f"_xf2p_print_star({', '.join(args_star)}{file_txt})")
                        else:
                            if file_txt:
                                self.emit(f"print({file_txt[2:]})")
                            else:
                                self.emit("print()")
                    return True

        # write(*,*)
        mm = re.match(r"write\s*\(\s*\*\s*,\s*\*\s*\)\s*$", s, re.I)
        if mm:
            self.emit("print()")
            return True

        # write(*,*) ...
        mm = re.match(r"write\s*\(\s*\*\s*,\s*\*\s*\)\s*(.+)$", s, re.I)
        if mm:
            raw_args = [a.strip() for a in split_args(mm.group(1))]
            if len(raw_args) == 1:
                a0 = raw_args[0].strip()
                implied_py = _fortran_implied_do_expr(a0, self.translate_expr, arrays_1d)
                if implied_py is not None:
                    self.emit(f"_xf2p_print_star(*{implied_py})")
                    return True
                if re.fullmatch(r"[a-z_]\w*", a0, flags=re.I) and a0.lower() in self._decl_array_types:
                    self.emit(f"_xf2p_print_star(*np.ravel({a0}, order='F'))")
                    return True
            args2 = []
            for a in raw_args:
                if _is_fortran_string_literal(a):
                    args2.append(a)
                else:
                    implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                    if implied_py is not None:
                        args2.append(f"*{implied_py}")
                    else:
                        args2.append(f"*_xf2p_io_items({self.translate_expr(a, arrays_1d)})")
            self.emit(f"_xf2p_print_star({', '.join(args2)})")
            return True

        # write(unit,*) ...
        mm = re.match(r"write\s*\(\s*([a-z_]\w*)\s*,\s*\*\s*\)\s*(.*)$", s, re.I)
        if mm:
            unit = mm.group(1)
            rest = mm.group(2).strip()
            if not rest:
                self.emit(f"print(file={unit})")
                return True
            args2 = []
            raw_args = [a.strip() for a in split_args(rest)]
            if len(raw_args) == 1:
                implied_py = _fortran_implied_do_expr(raw_args[0], self.translate_expr, arrays_1d)
                if implied_py is not None:
                    self.emit(f"_xf2p_print_star(*{implied_py}, file={unit})")
                    return True
            for a in raw_args:
                if _is_fortran_string_literal(a):
                    args2.append(a)
                else:
                    implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                    if implied_py is not None:
                        args2.append(f"*{implied_py}")
                    else:
                        args2.append(f"*_xf2p_io_items({self.translate_expr(a, arrays_1d)})")
            self.emit(f"_xf2p_print_star({', '.join(args2)}, file={unit})")
            return True

        # write(*,"fmt") ...
        mm = re.match(r"write\s*\(\s*\*\s*,\s*(([\"']).*?\2)\s*\)\s*(.*)$", s, re.I)
        if mm:
            fmt = mm.group(1)
            rest = mm.group(3).strip()
            if not rest:
                self.emit("print()")
                return True
            raw_args = [a.strip() for a in split_args(rest)]
            args2 = []
            for a in raw_args:
                if _is_fortran_string_literal(a):
                    args2.append(a)
                else:
                    implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                    if implied_py is not None:
                        args2.append(implied_py)
                    else:
                        args2.append(self.translate_expr(a, arrays_1d))
            if len(raw_args) == 1:
                a0 = raw_args[0].strip()
                if _is_recyclable_io_iterable(a0, self._decl_array_types):
                    fmt_expr = _fortran_format_recycled_expr(fmt, args2[0])
                    if fmt_expr is not None:
                        self.emit(f"print({fmt_expr})")
                        return True
            if len(raw_args) > 1:
                plan = _single_iterable_formatted_arg_plan(fmt, raw_args, self._decl_array_types)
                if plan is not None:
                    iter_pos, iter_need = plan
                    iter_raw = raw_args[iter_pos].strip()
                    iter_tmp = f"_xf2p_fmt_items_{self._code_emit_count + 1}"
                    if re.fullmatch(r"[a-z_]\w*", iter_raw, flags=re.I) and iter_raw.lower() in self._decl_array_types:
                        self.emit(f"{iter_tmp} = list(np.ravel({args2[iter_pos]}, order='F'))")
                    else:
                        self.emit(f"{iter_tmp} = list({args2[iter_pos]})")
                    expanded_args = args2[:iter_pos] + [f"{iter_tmp}[{k}]" for k in range(iter_need)] + args2[iter_pos + 1:]
                    fmt_expr = _fortran_format_expr(fmt, expanded_args)
                    if fmt_expr is not None:
                        self.emit(f"print({fmt_expr})")
                        return True
            fmt_expr = _fortran_format_expr(fmt, args2)
            if fmt_expr is not None:
                self.emit(f"print({fmt_expr})")
            else:
                self.emit(f"_xf2p_print_star({', '.join(args2)})")
            return True

        # write(unit,"fmt") ...
        mm = re.match(r"write\s*\(\s*([^,]+?)\s*,\s*(([\"']).*?\3)\s*\)\s*(.*)$", s, re.I)
        if mm:
            unit = mm.group(1).strip()
            fmt = mm.group(2)
            rest = mm.group(4).strip()
            if not rest:
                self.emit(f"print(file={unit})")
                return True
            raw_args = [a.strip() for a in split_args(rest)]
            args2 = []
            for a in raw_args:
                if _is_fortran_string_literal(a):
                    args2.append(a)
                else:
                    implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                    if implied_py is not None:
                        args2.append(implied_py)
                    else:
                        args2.append(self.translate_expr(a, arrays_1d))
            if len(raw_args) == 1:
                a0 = raw_args[0].strip()
                if _is_recyclable_io_iterable(a0, self._decl_array_types):
                    fmt_expr = _fortran_format_recycled_expr(fmt, args2[0])
                    if fmt_expr is not None:
                        self.emit(f"print({fmt_expr}, file={unit})")
                        return True
            if len(raw_args) > 1:
                plan = _single_iterable_formatted_arg_plan(fmt, raw_args, self._decl_array_types)
                if plan is not None:
                    iter_pos, iter_need = plan
                    iter_raw = raw_args[iter_pos].strip()
                    iter_tmp = f"_xf2p_fmt_items_{self._code_emit_count + 1}"
                    if re.fullmatch(r"[a-z_]\w*", iter_raw, flags=re.I) and iter_raw.lower() in self._decl_array_types:
                        self.emit(f"{iter_tmp} = list(np.ravel({args2[iter_pos]}, order='F'))")
                    else:
                        self.emit(f"{iter_tmp} = list({args2[iter_pos]})")
                    expanded_args = args2[:iter_pos] + [f"{iter_tmp}[{k}]" for k in range(iter_need)] + args2[iter_pos + 1:]
                    fmt_expr = _fortran_format_expr(fmt, expanded_args)
                    if fmt_expr is not None:
                        self.emit(f"print({fmt_expr}, file={unit})")
                        return True
            fmt_expr = _fortran_format_expr(fmt, args2)
            if fmt_expr is not None:
                self.emit(f"print({fmt_expr}, file={unit})")
            else:
                self.emit(f"_xf2p_print_star({', '.join(args2)}, file={unit})")
            return True

        # generic write(...) ... fallback
        if re.match(r"write\b", s, re.I):
            mkw = re.match(r"write\b", s, re.I)
            j = mkw.end()
            while j < len(s) and s[j].isspace():
                j += 1
            if j < len(s) and s[j] == "(":
                p1 = find_matching_paren(s, j)
                if p1 != -1:
                    ctl = s[j + 1 : p1].strip()
                    rest = s[p1 + 1 :].strip()
                    ctl_parts = [p.strip() for p in split_args(ctl)]
                    unit_raw = ctl_parts[0] if ctl_parts else "*"
                    fmt_raw = ctl_parts[1] if len(ctl_parts) >= 2 else "*"
                    advance_no = any(re.match(r"(?is)^advance\s*=\s*['\"]no['\"]$", p) for p in ctl_parts[2:])
                    unit_base_m = re.match(r"([a-z_]\w*)", unit_raw, re.I)
                    unit_base = unit_base_m.group(1).lower() if unit_base_m else ""
                    internal_char_target = unit_raw != "*" and (
                        self._decl_types.get(unit_base) == "character"
                        or self._decl_array_types.get(unit_base) == "character"
                    )

                    raw_args = [a.strip() for a in split_args(rest)] if rest else []

                    if fmt_raw == "*":
                        args_star = []
                        for a in raw_args:
                            if _is_fortran_string_literal(a):
                                args_star.append(self.translate_expr(a, arrays_1d))
                            else:
                                implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                                if implied_py is not None:
                                    args_star.append(f"*{implied_py}")
                                else:
                                    args_star.append(f"*_xf2p_io_items({self.translate_expr(a, arrays_1d)})")
                        if internal_char_target:
                            target_py = self.translate_expr(unit_raw, arrays_1d)
                            rhs = "''" if not args_star else f"_xf2p_star_text({', '.join(args_star)})"
                            rhs = f"_f_str_assign({rhs}, _f_len({target_py}))"
                            self.transpile_assignment(unit_raw, rhs, arrays_1d)
                            return True
                        file_txt = "" if unit_raw == "*" else f", file={self.translate_expr(unit_raw, arrays_1d)}"
                        if not args_star:
                            if file_txt:
                                self.emit(f"print({file_txt[2:]})")
                            else:
                                self.emit("print()")
                        else:
                            self.emit(f"_xf2p_print_star({', '.join(args_star)}{file_txt})")
                        return True

                    if _is_fortran_string_literal(fmt_raw):
                        args_fmt = []
                        for a in raw_args:
                            if _is_fortran_string_literal(a):
                                args_fmt.append(self.translate_expr(a, arrays_1d))
                            else:
                                implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                                if implied_py is not None:
                                    args_fmt.append(implied_py)
                                else:
                                    args_fmt.append(self.translate_expr(a, arrays_1d))
                        fmt_expr = None
                        if len(raw_args) == 1:
                            a0 = raw_args[0].strip()
                            if _is_recyclable_io_iterable(a0, self._decl_array_types):
                                fmt_expr = _fortran_format_recycled_expr(fmt_raw, args_fmt[0])
                        if fmt_expr is None and len(raw_args) > 1:
                            plan = _single_iterable_formatted_arg_plan(fmt_raw, raw_args, self._decl_array_types)
                            if plan is not None:
                                iter_pos, iter_need = plan
                                iter_raw = raw_args[iter_pos].strip()
                                iter_tmp = f"_xf2p_fmt_items_{self._code_emit_count + 1}"
                                if re.fullmatch(r"[a-z_]\w*", iter_raw, flags=re.I) and iter_raw.lower() in self._decl_array_types:
                                    self.emit(f"{iter_tmp} = list(np.ravel({args_fmt[iter_pos]}, order='F'))")
                                else:
                                    self.emit(f"{iter_tmp} = list({args_fmt[iter_pos]})")
                                expanded_args = args_fmt[:iter_pos] + [f"{iter_tmp}[{k}]" for k in range(iter_need)] + args_fmt[iter_pos + 1:]
                                fmt_expr = _fortran_format_expr(fmt_raw, expanded_args)
                        if fmt_expr is None:
                            fmt_expr = _fortran_format_expr(fmt_raw, args_fmt)
                        if internal_char_target:
                            target_py = self.translate_expr(unit_raw, arrays_1d)
                            rhs_core = fmt_expr if fmt_expr is not None else ("''" if not raw_args else f"_xf2p_star_text({', '.join(f'*_xf2p_io_items({self.translate_expr(a, arrays_1d)})' if not _is_fortran_string_literal(a) else self.translate_expr(a, arrays_1d) for a in raw_args)})")
                            rhs = f"_f_str_assign({rhs_core}, _f_len({target_py}))"
                            self.transpile_assignment(unit_raw, rhs, arrays_1d)
                            return True
                        file_txt = "" if unit_raw == "*" else f", file={self.translate_expr(unit_raw, arrays_1d)}"
                        if fmt_expr is not None:
                            self.emit(f"print({fmt_expr}{', end=""' if advance_no else ''}{file_txt})")
                        else:
                            args_star = []
                            for a in raw_args:
                                if _is_fortran_string_literal(a):
                                    args_star.append(self.translate_expr(a, arrays_1d))
                                else:
                                    implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                                    if implied_py is not None:
                                        args_star.append(f"*{implied_py}")
                                    else:
                                        args_star.append(f"*_xf2p_io_items({self.translate_expr(a, arrays_1d)})")
                            self.emit(f"_xf2p_print_star({', '.join(args_star)}{file_txt})")
                        return True

                    # dynamic format expression: keep output valid even when we cannot fully
                    # compile the runtime format string.
                    args_star = []
                    for a in raw_args:
                        if _is_fortran_string_literal(a):
                            args_star.append(self.translate_expr(a, arrays_1d))
                        else:
                            implied_py = _fortran_implied_do_expr(a, self.translate_expr, arrays_1d)
                            if implied_py is not None:
                                args_star.append(f"*{implied_py}")
                            else:
                                args_star.append(f"*_xf2p_io_items({self.translate_expr(a, arrays_1d)})")
                    if internal_char_target:
                        target_py = self.translate_expr(unit_raw, arrays_1d)
                        rhs = "''" if not args_star else f"_xf2p_star_text({', '.join(args_star)})"
                        rhs = f"_f_str_assign({rhs}, _f_len({target_py}))"
                        self.transpile_assignment(unit_raw, rhs, arrays_1d)
                    else:
                        file_txt = "" if unit_raw == "*" else f", file={self.translate_expr(unit_raw, arrays_1d)}"
                        if args_star:
                            self.emit(f"_xf2p_print_star({', '.join(args_star)}{file_txt})")
                        else:
                            if file_txt:
                                self.emit(f"print({file_txt[2:]})")
                            else:
                                self.emit("print()")
                    return True

        # single-line if: if (cond) stmt
        if sl.startswith("if") and not sl.endswith("then"):
            p0 = s.find("(")
            if p0 != -1:
                p1 = find_matching_paren(s, p0)
                if p1 != -1:
                    cond_txt = s[p0 + 1 : p1].strip()
                    stmt = s[p1 + 1 :].strip()
                    if stmt:
                        cond = self.translate_expr(cond_txt, arrays_1d)
                        self.emit(f"if {cond}:")
                        self.indent += 1
                        self.transpile_simple_stmt(stmt, arrays_1d)
                        self.indent = max(0, self.indent - 1)
                        return True

        # assignment
        if "=" in s and _find_top_level_double_colon(s) == -1:
            lhs, rhs = s.split("=", 1)
            lhs = lhs.strip()
            rhs_py = self.translate_expr(rhs, arrays_1d)
            # Boolean scalar to whole array (common pattern)
            if lhs in arrays_1d and rhs_py in ("True", "False"):
                self.emit(f"{lhs}[:] = {rhs_py}")
                return True
            # Defer to transpile_assignment so POINTER/TARGET aliasing is preserved.
            self.transpile_assignment(lhs, rhs_py, arrays_1d)
            return True

        return False

    def transpile_function(self, header: str, body_lines: list[tuple[str, str]]) -> None:
        hdr = header.strip()
        is_elemental = self._is_elemental_header(hdr)
        # tolerate arbitrary prefixes such as:
        # "pure real(kind=dp) function f(...)" or "real(kind=dp) pure function f(...)"
        m = re.search(r"\bfunction\s+(\w+)\s*\(\s*([^\)]*)\s*\)\s*result\s*\(\s*(\w+)\s*\)", hdr, re.I)
        if m:
            fname = m.group(1)
            args = [a.strip() for a in m.group(2).split(",") if a.strip()]
            result_name = m.group(3)
        else:
            m2 = re.search(r"\bfunction\s+(\w+)\s*\(\s*([^\)]*)\s*\)", hdr, re.I)
            if not m2:
                return
            fname = m2.group(1)
            args = [a.strip() for a in m2.group(2).split(",") if a.strip()]
            result_name = fname

        main_lines, internals = self._split_internal_subprograms(body_lines)
        self._validate_unit_symbols("function", fname, args, main_lines)

        sym: dict[str, dict] = {}
        arrays_1d: set[str] = set()
        arg_hints: dict[str, str] = {}
        header_ftype = infer_function_result_ftype(hdr)
        result_hint = _type_scalar_hint.get(header_ftype, "int")
        result_is_scalar = True
        result_is_derived = False
        result_type_name: str | None = None
        result_ftype = header_ftype

        self._emit_intrinsic_use_aliases(main_lines)

        # declarations pass
        for code, _comment in main_lines:
            s = code.strip()
            pd = parse_decl(s)
            if pd:
                ftype, attrs, rest = pd
                attrs_l = attrs.lower()
                items = parse_decl_items(rest, parse_decl_attr_dimension(attrs))
                type_name = None
            else:
                td = re.match(r"^(?:type|class)\s*\(\s*([a-z_]\w*)\s*\)\s*(.*?)::\s*(.*)$", s, re.I)
                if not td:
                    continue
                ftype = "type"
                attrs_l = td.group(2).strip().lower()
                items = parse_decl_items(td.group(3).strip(), parse_decl_attr_dimension(td.group(2).strip()))
                type_name = td.group(1)

            for name, shape, init in items:
                is_array = shape is not None
                is_alloc = "allocatable" in attrs_l
                sym[name] = {
                    "ftype": ftype,
                    "type_name": type_name,
                    "is_array": is_array,
                    "shape": shape,
                    "init": init,
                    "alloc": is_alloc,
                    "attrs_l": attrs_l,
                    "pointer": "pointer" in attrs_l,
                    "target": "target" in attrs_l,
                    "char_len": self._parse_character_len(s) if ftype == "character" else None,
                }
                if is_array:
                    arrays_1d.add(name)

                if name in args and "intent(in" in attrs_l:
                    if is_array:
                        arg_hints[name] = self._type_hint(ftype, type_name, is_array=True)
                    else:
                        arg_hints[name] = self._type_hint(ftype, type_name, is_array=False)

                if name == result_name:
                    result_ftype = ftype
                    if is_array:
                        result_hint = _type_ndarray_hint.get(ftype, "npt.NDArray[np.float64]")
                        result_is_scalar = False
                    else:
                        if ftype == "type":
                            result_hint = self._type_hint(ftype, type_name, is_array=False)
                            result_is_scalar = False
                            result_is_derived = True
                            result_type_name = type_name
                        else:
                            result_hint = _type_scalar_hint[ftype]
                            result_is_scalar = True

        arg_specs = []
        for a in args:
            info = sym.get(a)
            if info is None:
                arg_specs.append({"ftype": None, "type_name": None, "is_array": False})
            else:
                arg_specs.append({
                    "ftype": info.get("ftype"),
                    "type_name": info.get("type_name"),
                    "is_array": bool(info.get("is_array")),
                })
        self._func_sigs[fname.lower()] = {"args": list(args), "arg_specs": arg_specs}

        args_annot = []
        for a in args:
            hint = arg_hints.get(a, "int")
            default_none = False
            info = sym.get(a)
            if info and "optional" in info.get("attrs_l", ""):
                default_none = True
            if default_none:
                args_annot.append(f"{a}: {hint} = None")
            else:
                args_annot.append(f"{a}: {hint}")

        save_names = self._collect_save_names(main_lines, sym, args)
        save_dict_name = f"_{fname}_save"
        self.emit(f"{save_dict_name} = {{}}")
        contiguous = [(a, 'intent(in)' not in str(sym[a].get('attrs_l', '')).replace(' ', ''))
                      for a in args if a in sym and sym[a].get('is_array')
                      and 'contiguous' in sym[a].get('attrs_l', '')
                      and not sym[a].get('pointer') and 'allocatable' not in sym[a].get('attrs_l', '')]
        if contiguous:
            self.emit(f"@_f_contiguous_arguments({', '.join(repr(spec) for spec in contiguous)})")
        self.emit(f"def {fname}({', '.join(args_annot)}) -> {result_hint}:")
        self.indent += 1
        self._save_stack.append((save_dict_name, save_names))

        # If the first non-code lines are comments (just after signature),
        # emit them as a Python docstring.
        lead_doc: list[str] = []
        lead_idx = 0
        for code, comment in main_lines:
            if code.strip():
                break
            if comment.strip():
                lead_doc.append(comment.strip())
            lead_idx += 1
        if lead_doc:
            if len(lead_doc) == 1:
                self.emit(f'"""{lead_doc[0]}"""')
            else:
                self.emit('"""')
                for ln in lead_doc:
                    self.emit(ln)
                self.emit('"""')

        use_symbols = self._use_variable_symbols(main_lines)
        self._host_scopes.append((use_symbols, "global"))
        scope_sym = self._procedure_scope(sym, set(args) | {result_name})
        arrays_1d.update(name for name, info in scope_sym.items() if info.get("is_array"))
        local_scope = dict(sym)
        for arg in args:
            local_scope.setdefault(arg, dict(ftype="integer", is_array=False))
        local_scope.setdefault(result_name, dict(ftype=result_ftype, is_array=not result_is_scalar))
        self._host_scopes.append((local_scope, "nonlocal"))
        if is_elemental:
            self._elemental_funcs.add(fname.lower())
            _xf2p_elem_guard = " or ".join(f"_xf2p_is_arraylike({a})" for a in args) if args else "False"
            self.emit(f"if {_xf2p_elem_guard}:")
            self.indent += 1
            self.emit(f"return np.vectorize({fname}, otypes=[{self._scalar_otype_expr(result_ftype, result_type_name)}])({', '.join(args)})")
            self.indent -= 1

        for kind, header, ibody in internals:
            if kind == "function":
                self.transpile_function(header, ibody)
            else:
                self.transpile_subroutine(header, ibody)

        # parameters inside function (if any)
        parameter_names: set[str] = set()
        for code, _comment in main_lines:
            s = code.strip()
            pd = parse_decl(s)
            if not pd:
                continue
            ftype, attrs, rest = pd
            attrs_l = attrs.lower()
            if "parameter" in attrs_l:
                parameter_names |= self.emit_parameters_from_decl(ftype, attrs_l, rest, arrays_1d)

        # allocate/init explicit-shape arrays and scalars
        self.emit_var_inits_from_sym(sym, arrays_1d, parameter_names, skip_names=set(args) | set(save_names))
        self._emit_save_restore(save_dict_name, save_names, sym, arrays_1d)
        # initialize derived-type/component bases that appear as name%field
        comp_bases: set[str] = set()
        for code, _comment in main_lines:
            for mbase in re.finditer(r"\b([a-z_]\w*)\s*%", code, re.I):
                comp_bases.add(mbase.group(1))
        known_names = {k.lower() for k in scope_sym} | {a.lower() for a in args}
        for b in sorted(comp_bases):
            if b.lower() not in known_names and b not in parameter_names:
                self.emit(f"{b} = SimpleNamespace()")
        result_has_components = any(b.lower() == result_name.lower() for b in comp_bases)
        if (result_has_components or result_is_derived) and result_name.lower() not in {k.lower() for k in sym}:
            cls = result_type_name if result_type_name else "SimpleNamespace"
            self.emit(f"{result_name} = {cls}()")
        self._decl_type_names = {k.lower(): v["type_name"].lower() for k, v in scope_sym.items() if v.get("type_name")}
        self._decl_types = {k.lower(): v["ftype"] for k, v in scope_sym.items()}
        self._decl_array_types = {k.lower(): v["ftype"] for k, v in scope_sym.items() if v.get("is_array")}
        self._decl_types = {k.lower(): v["ftype"] for k, v in scope_sym.items()}
        self._decl_array_types = {k.lower(): v["ftype"] for k, v in scope_sym.items() if v.get("is_array")}
        self._decl_pointer = {k.lower() for k, v in scope_sym.items() if v.get('pointer') or ('pointer' in str(v.get('attrs_l', '')))}
        self._decl_target = {k.lower() for k, v in scope_sym.items() if v.get('target') or ('target' in str(v.get('attrs_l', '')))}
        self._decl_char_len = {k.lower(): str(v.get('char_len')) for k, v in scope_sym.items() if v.get('char_len') is not None}
        self._decl_lbounds = {k.lower(): [lo for lo, _hi in self._shape_bounds(str(v.get('shape')))] for k, v in scope_sym.items() if v.get('is_array') and v.get('shape') is not None}
        self._decl_ubounds = {k.lower(): [hi for _lo, hi in self._shape_bounds(str(v.get('shape')))] for k, v in scope_sym.items() if v.get('is_array') and v.get('shape') is not None}

        # exec pass
        prev_result_name = self._current_result_name
        self._current_result_name = result_name
        for idx, (code, comment) in enumerate(main_lines):
            s = code.strip()
            if idx < lead_idx and not s and comment.strip():
                continue
            self.emit_comment(comment)
            if not s:
                continue
            if self._parse_decl_line(s):
                continue
            self.handle_exec_line(s, arrays_1d)

        # basic default return (safe)
        self._emit_save_sync()
        self.emit(f"return {result_name}")
        self._current_result_name = prev_result_name
        self._host_scopes.pop()
        self._host_scopes.pop()  # procedure-local USE associations
        if self._save_stack:
            self._save_stack.pop()
        self.indent = max(0, self.indent - 1)
        self.emit("")

    def transpile_program_body(self, body_lines: list[tuple[str, str]]) -> None:
        # gather decls and arrays
        self._emit_intrinsic_use_aliases(body_lines)
        sym: dict[str, dict] = {}
        arrays_1d: set[str] = set()

        for code, _comment in body_lines:
            s = code.strip()
            if not s:
                continue
            parsed = self._parse_decl_line(s)
            if not parsed:
                continue
            ftype, type_name, attrs_l, items = parsed
            if "parameter" in attrs_l:
                continue
            for name, shape, init in items:
                is_array = shape is not None
                is_alloc = "allocatable" in attrs_l
                sym[name] = {
                    "ftype": ftype,
                    "type_name": type_name,
                    "is_array": is_array,
                    "shape": shape,
                    "init": init,
                    "alloc": is_alloc,
                    "attrs_l": attrs_l,
                    "pointer": "pointer" in attrs_l,
                    "target": "target" in attrs_l,
                    "char_len": self._parse_character_len(s) if ftype == "character" else None,
                }
                if is_array:
                    arrays_1d.add(name)

        # parameters
        parameter_names: set[str] = set()
        for code, _comment in body_lines:
            s = code.strip()
            if not s:
                continue
            pd = parse_decl(s)
            if not pd:
                continue
            ftype, attrs, rest = pd
            attrs_l = attrs.lower()
            if "parameter" in attrs_l:
                parameter_names |= self.emit_parameters_from_decl(ftype, attrs_l, rest, arrays_1d)

        # declare/init variables (explicit-shape arrays + scalars)
        self.emit_var_inits_from_sym(sym, arrays_1d, parameter_names)
        # USE entities already have storage in the translated module. Retain
        # their type/bounds metadata, but never initialize a local copy here.
        sym = {**self._use_variable_symbols(body_lines), **sym}
        arrays_1d.update(name for name, info in sym.items() if info.get("is_array"))
        self._decl_type_names = {k.lower(): v["type_name"].lower() for k, v in sym.items() if v.get("type_name")}
        self._decl_types = {k.lower(): v["ftype"] for k, v in sym.items()}
        self._decl_array_types = {k.lower(): v["ftype"] for k, v in sym.items() if v.get("is_array")}
        self._decl_pointer = {k.lower() for k, v in sym.items() if v.get('pointer') or ('pointer' in str(v.get('attrs_l', '')))}
        self._decl_target = {k.lower() for k, v in sym.items() if v.get('target') or ('target' in str(v.get('attrs_l', '')))}
        self._decl_char_len = {k.lower(): str(v.get('char_len')) for k, v in sym.items() if v.get('char_len') is not None}
        self._decl_lbounds = {k.lower(): [lo for lo, _hi in self._shape_bounds(str(v.get('shape')))] for k, v in sym.items() if v.get('is_array') and v.get('shape') is not None}
        self._decl_ubounds = {k.lower(): [hi for _lo, hi in self._shape_bounds(str(v.get('shape')))] for k, v in sym.items() if v.get('is_array') and v.get('shape') is not None}

        # exec statements
        for code, comment in body_lines:
            s = code.strip()
            self.emit_comment(comment)
            if not s:
                continue
            if parse_decl(s):
                continue
            self.handle_exec_line(s, arrays_1d)


    def _xf2p_generic_arg_cond(self, expr: str, spec: dict) -> str:
        ftype = str(spec.get("ftype") or "").lower()
        is_array = bool(spec.get("is_array"))
        if ftype == "character":
            return f"_xf2p_is_char_array({expr})" if is_array else f"_xf2p_is_char_scalar({expr})"
        if ftype == "integer":
            return f"_xf2p_is_integer_array({expr})" if is_array else f"_xf2p_is_integer_scalar({expr})"
        if ftype == "real":
            return f"_xf2p_is_real_array({expr})" if is_array else f"_xf2p_is_real_scalar({expr})"
        if ftype == "logical":
            return f"_xf2p_is_logical_array({expr})" if is_array else f"_xf2p_is_logical_scalar({expr})"
        if ftype == "complex":
            return f"_xf2p_is_complex_array({expr})" if is_array else f"_xf2p_is_complex_scalar({expr})"
        return "True"

    def _xf2p_generic_call_arg(self, expr: str, spec: dict) -> str:
        if not bool(spec.get("is_array")):
            return expr
        ftype = str(spec.get("ftype") or "").lower()
        if ftype == "character":
            return f"np.asarray({expr}, dtype=object)"
        if ftype in _type_dtype:
            return f"np.asarray({expr}, dtype={_type_dtype[ftype]})"
        return f"np.asarray({expr})"

    def _emit_generic_interface_wrapper(self, generic_name: str, proc_names: list[str]) -> None:
        candidates: list[tuple[str, dict]] = []
        for proc in proc_names:
            sig = self._func_sigs.get(proc.lower()) or self._subr_sigs.get(proc.lower())
            if sig is not None:
                candidates.append((proc, sig))
        if not candidates:
            return
        self.emit(f"def {generic_name}(*args):")
        self.indent += 1
        for proc, sig in candidates:
            arg_specs = list(sig.get("arg_specs", []))
            conds = [f"len(args) == {len(arg_specs)}"]
            for j, spec in enumerate(arg_specs):
                cond = self._xf2p_generic_arg_cond(f"args[{j}]", spec)
                if cond != "True":
                    conds.append(cond)
            call_args = [self._xf2p_generic_call_arg(f"args[{j}]", spec) for j, spec in enumerate(arg_specs)]
            self.emit(f"if {' and '.join(conds)}:")
            self.indent += 1
            self.emit(f"return {proc}({', '.join(call_args)})")
            self.indent -= 1
        self.emit(f"raise TypeError('no matching specific procedure for generic interface {generic_name}')")
        self.indent -= 1
        self.emit("")


    def transpile_module(self, header: str, body_lines: list[tuple[str, str]]) -> None:
        # Flatten a Fortran module into top-level Python definitions:
        # declarative-part parameters/variables/types become module globals,
        # and contained procedures are emitted as top-level defs.
        decl_lines = body_lines
        tail: list[tuple[str, str]] = []
        contains_idx = self._unit_contains_index(body_lines)
        if contains_idx is not None:
            decl_lines = body_lines[:contains_idx]
            tail = body_lines[contains_idx + 1 :]

        decl_lines, generic_interfaces = _extract_generic_interfaces(decl_lines)

        # Emit derived types from the module declarative part.
        filtered_decl: list[tuple[str, str]] = []
        i = 0
        ndecl = len(decl_lines)
        while i < ndecl:
            line = decl_lines[i][0].strip()
            if re.match(r"^type\b", line, re.I) and not re.match(r"^type\s*\(", line, re.I):
                dtype_header = line
                dtype_body: list[tuple[str, str]] = []
                i += 1
                while i < ndecl and not re.match(r"\s*end\s+type\b", decl_lines[i][0], re.I):
                    dtype_body.append(decl_lines[i])
                    i += 1
                if i < ndecl:
                    i += 1
                self.transpile_derived_type(dtype_header, dtype_body)
                continue
            filtered_decl.append(decl_lines[i])
            i += 1
        decl_lines = filtered_decl

        self._emit_intrinsic_use_aliases(decl_lines)

        sym: dict[str, dict] = {}
        arrays_1d: set[str] = set()

        for code, _comment in decl_lines:
            s = code.strip()
            if not s:
                continue
            parsed = self._parse_decl_line(s)
            if not parsed:
                continue
            ftype, type_name, attrs_l, items = parsed
            for name, shape, init in items:
                is_array = shape is not None
                is_alloc = "allocatable" in attrs_l
                sym[name] = {
                    "ftype": ftype,
                    "type_name": type_name,
                    "is_array": is_array,
                    "shape": shape,
                    "init": init,
                    "alloc": is_alloc,
                    "attrs_l": attrs_l,
                    "pointer": "pointer" in attrs_l,
                    "target": "target" in attrs_l,
                    "char_len": self._parse_character_len(s) if ftype == "character" else None,
                }
                if is_array:
                    arrays_1d.add(name)

        # Specification inquiries such as PARAMETER r=RANK(a) must see array
        # declarations even before their storage has been initialized.
        self._host_scopes.append(({**self._use_variable_symbols(decl_lines), **sym}, "global"))
        parameter_names: set[str] = set()
        for code, _comment in decl_lines:
            s = code.strip()
            if not s:
                continue
            pd = parse_decl(s)
            if not pd:
                continue
            ftype, attrs, rest = pd
            attrs_l = attrs.lower()
            if "parameter" in attrs_l:
                parameter_names |= self.emit_parameters_from_decl(ftype, attrs_l, rest, arrays_1d)

        self.emit_var_inits_from_sym(sym, arrays_1d, parameter_names)
        if sym or parameter_names:
            self.emit("")

        module_name = re.fullmatch(r"module\s+([a-z_]\w*)", header.strip(), re.I).group(1).lower()
        for name, info in sym.items():
            if "parameter" in info["attrs_l"]:
                continue
            owner = self._module_storage_owners.setdefault(name.lower(), module_name)
            if owner != module_name:
                raise ValueError(f"module variable '{name}' is declared in both {owner} and {module_name}; separate module namespaces are not yet supported")
        local_names = set(sym)
        sym = {**self._use_variable_symbols(decl_lines), **sym}
        arrays_1d.update(name for name, info in sym.items() if info.get("is_array"))
        default_private = any(re.fullmatch(r"\s*private\s*", code, re.I) for code, _ in decl_lines)
        public, private = set(), set()
        for code, _ in decl_lines:
            access = re.fullmatch(r"\s*(public|private)\s*(?:::)?\s+(.+)", code, re.I)
            if access:
                (public if access.group(1).lower() == "public" else private).update(
                    item.strip().lower() for item in split_args(access.group(2)))
        self._module_variable_symbols[module_name] = {
            name: info for name, info in sym.items()
            if name.lower() not in private and "private" not in info["attrs_l"]
            and (not default_private or name.lower() in public
                 or (name in local_names and "public" in info["attrs_l"]))
        }

        if contains_idx is not None:
            i = 0
            n = len(tail)
            while i < n:
                line = tail[i][0].strip()
                if not line:
                    i += 1
                    continue
                if self._is_function_header(line):
                    func_header = line
                    fbody: list[tuple[str, str]] = []
                    i += 1
                    while i < n and not re.match(r"\s*end\s+function\b", tail[i][0], re.I):
                        fbody.append(tail[i])
                        i += 1
                    if i < n:
                        i += 1
                    self.transpile_function(func_header, fbody)
                    continue
                if self._is_subroutine_header(line):
                    sub_header = line
                    sbody: list[tuple[str, str]] = []
                    i += 1
                    while i < n and not re.match(r"\s*end\s+subroutine\b", tail[i][0], re.I):
                        sbody.append(tail[i])
                        i += 1
                    if i < n:
                        i += 1
                    self.transpile_subroutine(sub_header, sbody)
                    continue
                i += 1

        for gi in generic_interfaces:
            self._emit_generic_interface_wrapper(gi["name"], gi["procedures"])
        self._host_scopes.pop()

    def _host_symbol_table(self, lines: list[tuple[str, str]]) -> dict[str, dict]:
        symbols = {}
        for code, _comment in lines:
            parsed = self._parse_decl_line(code.strip())
            if parsed is None:
                continue
            ftype, type_name, attrs, items = parsed
            for name, shape, init in items:
                symbols[name] = dict(ftype=ftype, type_name=type_name,
                    is_array=shape is not None, shape=shape, init=init,
                    attrs_l=attrs, pointer="pointer" in attrs, target="target" in attrs,
                    char_len=self._parse_character_len(code) if ftype == "character" else None)
        return symbols

    def _procedure_scope(self, local: dict[str, dict], excluded: set[str]) -> dict[str, dict]:
        """Declare Python bindings and retain metadata for host-associated names."""
        shadowed = {name.lower() for name in local} | {name.lower() for name in excluded}
        inherited = {}
        for symbols, binding in reversed(self._host_scopes):
            visible = {name: info for name, info in symbols.items() if name.lower() not in shadowed}
            if visible:
                self.emit(f"{binding} {', '.join(sorted(visible))}")
            inherited.update(visible)
            shadowed.update(name.lower() for name in symbols)
        return {**inherited, **local}

    def _use_variable_symbols(self, lines: list[tuple[str, str]]) -> dict[str, dict]:
        """Resolve variable storage for modules in this translation unit."""
        symbols = {}
        for code, _ in lines:
            use = re.fullmatch(r"\s*use\s*(?:,\s*(intrinsic|non_intrinsic)\s*)?(?:::)?\s*([a-z_]\w*)\s*(.*)", code, re.I)
            if not use or (use.group(1) or "").lower() == "intrinsic":
                continue
            exported = self._module_variable_symbols.get(use.group(2).lower(), {})
            tail = use.group(3).strip().lstrip(",").strip()
            only = re.match(r"only\s*:\s*(.*)", tail, re.I)
            selected = {} if only else dict(exported)
            for item in split_args(only.group(1) if only else tail):
                parts = [part.strip().lower() for part in item.split("=>", 1)]
                local, remote = parts[0], parts[-1]
                info = next((info for name, info in exported.items() if name.lower() == remote), None)
                if info is None:
                    continue
                if local != remote:
                    raise ValueError("renamed USE-associated module variables are not yet supported; use the original name")
                name = next(name for name in exported if name.lower() == remote)
                selected[name] = info
            symbols.update(selected)
        return symbols

    def transpile_program(self, body_lines: list[tuple[str, str]]) -> None:
        # Handle internal procedures after "contains".
        main_lines = body_lines
        tail: list[tuple[str, str]] = []
        contains_idx = self._unit_contains_index(body_lines)
        if contains_idx is not None:
            main_lines = body_lines[:contains_idx]
            tail = body_lines[contains_idx + 1 :]

        # Extract derived types declared in the program declarative part and
        # emit them as top-level dataclasses before internal procedures that may
        # reference those types in annotations.
        filtered_main: list[tuple[str, str]] = []
        i = 0
        nmain = len(main_lines)
        while i < nmain:
            line = main_lines[i][0].strip()
            if re.match(r"^type\b", line, re.I) and not re.match(r"^type\s*\(", line, re.I):
                header = line
                tbody: list[tuple[str, str]] = []
                i += 1
                while i < nmain and not re.match(r"\s*end\s+type\b", main_lines[i][0], re.I):
                    tbody.append(main_lines[i])
                    i += 1
                if i < nmain:
                    i += 1
                self.transpile_derived_type(header, tbody)
                continue
            filtered_main.append(main_lines[i])
            i += 1
        main_lines = filtered_main

        # Internal procedures are closures over this invocation of main, not
        # top-level functions reading unrelated Python module globals.
        self.emit("def main() -> None:")
        self.indent += 1
        use_symbols = self._use_variable_symbols(main_lines)
        if use_symbols:
            self.emit(f"global {', '.join(sorted(use_symbols))}")
        self._host_scopes.append((use_symbols, "global"))
        self._host_scopes.append((self._host_symbol_table(main_lines), "nonlocal"))
        if contains_idx is not None:
            i = 0
            n = len(tail)
            while i < n:
                line = tail[i][0].strip()
                if not line:
                    i += 1
                    continue
                if self._is_function_header(line):
                    header = line
                    fbody: list[tuple[str, str]] = []
                    i += 1
                    while i < n and not re.match(r"\s*end\s+function\b", tail[i][0], re.I):
                        fbody.append(tail[i])
                        i += 1
                    if i < n:
                        i += 1
                    self.transpile_function(header, fbody)
                    continue
                if self._is_subroutine_header(line):
                    header = line
                    sbody: list[tuple[str, str]] = []
                    i += 1
                    while i < n and not re.match(r"\s*end\s+subroutine\b", tail[i][0], re.I):
                        sbody.append(tail[i])
                        i += 1
                    if i < n:
                        i += 1
                    self.transpile_subroutine(header, sbody)
                    continue
                i += 1

        code0 = self._code_emit_count
        self.transpile_program_body(main_lines)
        if self._code_emit_count == code0:
            self.emit("pass")
        self._host_scopes.pop()
        self._host_scopes.pop()  # main-program USE associations
        self.indent = max(0, self.indent - 1)
        self.emit("")

    def transpile_subroutine(self, header: str, body_lines: list[tuple[str, str]]) -> None:
        hdr = header.strip()
        is_elemental = self._is_elemental_header(hdr)
        m = re.match(r"(?:(?:pure|elemental|recursive)\s+)*subroutine\s+(\w+)\s*\(\s*([^\)]*)\s*\)", hdr, re.I)
        if not m:
            return
        sname = m.group(1)
        args = [a.strip() for a in m.group(2).split(",") if a.strip()]

        main_lines, internals = self._split_internal_subprograms(body_lines)
        self._validate_unit_symbols("subroutine", sname, args, main_lines)

        sym: dict[str, dict] = {}
        arrays_1d: set[str] = set()
        arg_hints: dict[str, str] = {}

        self._emit_intrinsic_use_aliases(main_lines)

        for code, _comment in main_lines:
            s = code.strip()
            pd = parse_decl(s)
            if pd:
                ftype, attrs, rest = pd
                attrs_l = attrs.lower()
                items = parse_decl_items(rest, parse_decl_attr_dimension(attrs))
                type_name = None
            else:
                td = re.match(r"^(?:type|class)\s*\(\s*([a-z_]\w*)\s*\)\s*(.*?)::\s*(.*)$", s, re.I)
                if not td:
                    continue
                ftype = "type"
                attrs_l = td.group(2).strip().lower()
                items = parse_decl_items(td.group(3).strip(), parse_decl_attr_dimension(td.group(2).strip()))
                type_name = td.group(1)
            for name, shape, init in items:
                is_array = shape is not None
                is_alloc = "allocatable" in attrs_l
                sym[name] = {
                    "ftype": ftype,
                    "type_name": type_name,
                    "is_array": is_array,
                    "shape": shape,
                    "init": init,
                    "alloc": is_alloc,
                    "attrs_l": attrs_l,
                    "pointer": "pointer" in attrs_l,
                    "target": "target" in attrs_l,
                    "char_len": self._parse_character_len(s) if ftype == "character" else None,
                }
                if is_array:
                    arrays_1d.add(name)
                if name in args:
                    if is_array:
                        arg_hints[name] = self._type_hint(ftype, type_name, is_array=True)
                    else:
                        arg_hints[name] = self._type_hint(ftype, type_name, is_array=False)

        args_annot = []
        for a in args:
            hint = arg_hints.get(a, "float")
            default_none = False
            info = sym.get(a)
            if info and "optional" in info.get("attrs_l", ""):
                default_none = True
            if default_none:
                args_annot.append(f"{a}: {hint} = None")
            else:
                args_annot.append(f"{a}: {hint}")
        out_formals: list[str] = []
        pure_out_formals: list[str] = []
        vector_formals: list[str] = []
        out_otypes: list[str] = []
        for a in args:
            info = sym.get(a)
            if not info:
                vector_formals.append(a)
                continue
            attrs_l = info.get("attrs_l", "")
            if "intent(out" in attrs_l or "intent(inout" in attrs_l:
                out_formals.append(a)
                out_otypes.append(self._scalar_otype_expr(cast(str, info.get("ftype")), cast(str | None, info.get("type_name"))))
            if "intent(out" in attrs_l and "intent(inout" not in attrs_l:
                pure_out_formals.append(a)
            else:
                vector_formals.append(a)
        arg_specs = []
        for a in args:
            info = sym.get(a)
            if info is None:
                arg_specs.append({"ftype": None, "type_name": None, "is_array": False})
            else:
                arg_specs.append({
                    "ftype": info.get("ftype"),
                    "type_name": info.get("type_name"),
                    "is_array": bool(info.get("is_array")),
                })
        self._subr_sigs[sname.lower()] = {"args": list(args), "out": list(out_formals), "arg_specs": arg_specs}

        save_names = self._collect_save_names(main_lines, sym, args)
        save_dict_name = f"_{sname}_save"
        self.emit(f"{save_dict_name} = {{}}")
        contiguous = [(a, 'intent(in)' not in str(sym[a].get('attrs_l', '')).replace(' ', ''))
                      for a in args if a in sym and sym[a].get('is_array')
                      and 'contiguous' in sym[a].get('attrs_l', '')
                      and not sym[a].get('pointer') and 'allocatable' not in sym[a].get('attrs_l', '')]
        if contiguous:
            self.emit(f"@_f_contiguous_arguments({', '.join(repr(spec) for spec in contiguous)})")
        self.emit(f"def {sname}({', '.join(args_annot)}):")
        self.indent += 1
        self._save_stack.append((save_dict_name, save_names))
        use_symbols = self._use_variable_symbols(main_lines)
        self._host_scopes.append((use_symbols, "global"))
        scope_sym = self._procedure_scope(sym, set(args))
        arrays_1d.update(name for name, info in scope_sym.items() if info.get("is_array"))
        local_scope = dict(sym)
        for arg in args:
            local_scope.setdefault(arg, dict(ftype="integer", is_array=False))
        self._host_scopes.append((local_scope, "nonlocal"))

        for kind, header, ibody in internals:
            if kind == "function":
                self.transpile_function(header, ibody)
            else:
                self.transpile_subroutine(header, ibody)

        if is_elemental and out_formals and vector_formals:
            _xf2p_elem_guard = " or ".join(f"_xf2p_is_arraylike({a})" for a in vector_formals)
            _xf2p_lambda_args = [f"_xf2p_{a}" for a in vector_formals]
            _xf2p_call_args: list[str] = []
            for _xf2p_a in args:
                if _xf2p_a in pure_out_formals:
                    _xf2p_call_args.append("None")
                elif _xf2p_a in vector_formals:
                    _xf2p_call_args.append(f"_xf2p_{_xf2p_a}")
                else:
                    _xf2p_call_args.append(_xf2p_a)
            self.emit(f"if {_xf2p_elem_guard}:")
            self.indent += 1
            self.emit(f"_xf2p_vec = np.vectorize(lambda {', '.join(_xf2p_lambda_args)}: {sname}({', '.join(_xf2p_call_args)}), otypes=[{', '.join(out_otypes)}])")
            self.emit(f"return _xf2p_vec({', '.join(vector_formals)})")
            self.indent -= 1

        parameter_names: set[str] = set()
        for code, _comment in main_lines:
            s = code.strip()
            pd = parse_decl(s)
            if not pd:
                continue
            ftype, attrs, rest = pd
            attrs_l = attrs.lower()
            if "parameter" in attrs_l:
                parameter_names |= self.emit_parameters_from_decl(ftype, attrs_l, rest, arrays_1d)

        self.emit_var_inits_from_sym(sym, arrays_1d, parameter_names, skip_names=set(args) | set(save_names))
        self._emit_save_restore(save_dict_name, save_names, sym, arrays_1d)
        self._decl_type_names = {k.lower(): v["type_name"].lower() for k, v in scope_sym.items() if v.get("type_name")}
        self._decl_types = {k.lower(): v["ftype"] for k, v in scope_sym.items()}
        self._decl_array_types = {k.lower(): v["ftype"] for k, v in scope_sym.items() if v.get("is_array")}
        self._decl_pointer = {k.lower() for k, v in scope_sym.items() if v.get('pointer') or ('pointer' in str(v.get('attrs_l', '')))}
        self._decl_target = {k.lower() for k, v in scope_sym.items() if v.get('target') or ('target' in str(v.get('attrs_l', '')))}
        self._decl_char_len = {k.lower(): str(v.get('char_len')) for k, v in scope_sym.items() if v.get('char_len') is not None}
        self._decl_lbounds = {k.lower(): [lo for lo, _hi in self._shape_bounds(str(v.get('shape')))] for k, v in scope_sym.items() if v.get('is_array') and v.get('shape') is not None}
        self._decl_ubounds = {k.lower(): [hi for _lo, hi in self._shape_bounds(str(v.get('shape')))] for k, v in scope_sym.items() if v.get('is_array') and v.get('shape') is not None}

        for code, comment in main_lines:
            s = code.strip()
            self.emit_comment(comment)
            if not s:
                continue
            if parse_decl(s):
                continue
            self.handle_exec_line(s, arrays_1d)

        self._emit_save_sync()
        if out_formals:
            if len(out_formals) == 1:
                self.emit(f"return {out_formals[0]}")
            else:
                self.emit("return " + ", ".join(out_formals))

        self._host_scopes.pop()
        self._host_scopes.pop()  # procedure-local USE associations
        if self._save_stack:
            self._save_stack.pop()
        self.indent = max(0, self.indent - 1)
        self.emit("")

    def _lower_lexical_blocks(self, lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Alpha-rename BLOCK locals without creating a Python function boundary.

        Retaining the surrounding control flow makes RETURN/CYCLE/EXIT work as
        before. Declaration metadata remains visible to the existing passes,
        but storage is initialized at the executable block-entry marker.
        """
        self._block_local_names: set[str] = set()
        self._lexical_block_entries: dict[str, list[tuple[str, str]]] = {}
        scopes: list[dict[str, str]] = []
        starts: dict[int, tuple[dict[str, str], str]] = {}
        owners: dict[int, int] = {}
        stack: list[int] = []
        used = set(re.findall(r"\b[a-z_]\w*\b", "\n".join(code for code, _ in lines), re.I))
        used = {name.lower() for name in used}
        for index, (code, _) in enumerate(lines):
            if re.fullmatch(r"\s*(?:[a-z_]\w*\s*:\s*)?block\s*", code, re.I):
                marker = f"__xf2p_block_entry_{index}"
                starts[index] = ({}, marker)
                stack.append(index)
                self._lexical_block_entries[marker] = []
                continue
            if re.fullmatch(r"\s*end\s*block(?:\s+[a-z_]\w*)?\s*", code, re.I):
                if not stack:
                    raise ValueError("END BLOCK without BLOCK")
                stack.pop()
                continue
            if not stack:
                continue
            parsed = self._parse_decl_line(code.strip())
            if parsed:
                _, _, attrs, items = parsed
                if "save" in attrs or (any(init is not None for _, _, init in items) and "parameter" not in attrs):
                    raise ValueError("BLOCK SAVE/initialized local variables are not yet supported")
                mapping = starts[stack[-1]][0]
                for name, _, _ in items:
                    key = name.lower()
                    if key in mapping:
                        raise ValueError(f"BLOCK: duplicate declaration for '{name}'")
                    new = f"xf2p_block_{stack[-1]}_{key}"
                    while new.lower() in used:
                        new += "_"
                    used.add(new.lower())
                    mapping[key] = new
                    self._block_local_names.add(new)
                owners[index] = stack[-1]
            elif re.match(r"\s*(?:use|save|type\b(?!\s*\())", code, re.I):
                raise ValueError("BLOCK-local USE, SAVE, or derived-type definitions are not yet supported")
        if stack:
            raise ValueError("BLOCK without END BLOCK")

        result = []
        token = re.compile(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"|\.[a-z_]\w*\.|\b[a-z_]\w*\b", re.I)
        for index, (code, comment) in enumerate(lines):
            if index in starts:
                mapping, marker = starts[index]
                scopes.append(mapping)
                result.append((marker, comment))
                continue
            if re.fullmatch(r"\s*end\s*block(?:\s+[a-z_]\w*)?\s*", code, re.I):
                scopes.pop()
                result.append(("", comment))
                continue
            visible = {key: value for scope in scopes for key, value in scope.items()}
            def rename(match):
                name = match.group()
                # Components are not variables in the containing BLOCK scope.
                if code[:match.start()].rstrip().endswith("%"):
                    return name
                # Keep keyword argument names (f(x=x)), while renaming the
                # actual variable. Declaration/control bindings are different.
                if (re.match(r"\s*=(?!=)", code[match.end():])
                        and not re.match(r"\s*(?:do|forall|associate)\b", code, re.I)):
                    prefix = re.sub(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"", "", code[:match.start()])
                    if prefix.count("(") > prefix.count(")"):
                        return name
                return visible.get(name.lower(), name)
            rewritten = token.sub(rename, code)
            result.append((rewritten, comment))
            if index in owners:
                marker = starts[owners[index]][1]
                self._lexical_block_entries[marker].append((rewritten, comment))
        return result

    def transpile(self, src: str) -> str:
        self._host_scopes = []
        self._module_variable_symbols: dict[str, dict[str, dict]] = {}
        self._module_storage_owners: dict[str, str] = {}
        raw = [split_fortran_comment(l) for l in src.splitlines()]
        raw = collapse_fortran_continuations(raw)
        raw = self._lower_lexical_blocks(raw)
        self._type_bindings = {}
        self._type_components = {}
        self._component_specs = {}
        self._allocation_counter = 0
        self._allocation_bound_names = {}
        self._allocation_source = src
        self._decl_type_names = {}
        # Bindings precede their implementations; collect signatures before
        # emitting dataclass forwarding methods and resolving bound CALLs.
        self._binding_targets = {}
        for i, (code, _comment) in enumerate(raw):
            header = re.search(r"\b(function|subroutine)\s+(\w+)\s*\(([^)]*)\)", code, re.I)
            if not header or re.match(r"\s*end\b", code, re.I):
                continue
            kind, name = header.group(1).lower(), header.group(2).lower()
            args = [a.strip().lower() for a in split_args(header.group(3)) if a.strip()]
            body, _end = self._collect_subprogram_body(raw, i + 1, kind)
            main_lines, _internals = self._split_internal_subprograms(body)
            outputs, optional = set(), set()
            for statement, _ in main_lines:
                declaration = self._parse_decl_line(statement.strip())
                if not declaration:
                    continue
                _ftype, _type_name, attrs, items = declaration
                for arg, _shape, _init in items:
                    if re.search(r"intent\s*\(\s*(?:out|inout)\s*\)", attrs):
                        outputs.add(arg.lower())
                    if "optional" in attrs:
                        optional.add(arg.lower())
            self._binding_targets[name] = {"kind": kind, "args": args,
                "out": [a for a in args if a in outputs], "optional": optional}
        self.seen_parameter = any(re.search(r"\bparameter\b", code, re.I) for code, _c in raw)
        self._seen_scipy_special = any(
            re.search(r"\b(?:gamma|log_gamma|erf|erfc|erfc_scaled|bessel_j0|bessel_j1|bessel_y0|bessel_y1|bessel_jn|bessel_yn)\s*\(",
                      re.sub(r"'([^']|'')*'|\"([^\"]|\"\")*\"", "", code), re.I)
            for code, _c in raw
        )

        self.out = []
        self.indent = 0
        self._code_emit_count = 0
        self._block_code_start = []
        self._select_case_stack = []
        self._do_stack = []
        self._loop_counter = 0

        self.emit("import numpy as np")
        self.emit("import numpy.typing as npt")
        self.emit("from dataclasses import dataclass, field")
        self.emit("from types import SimpleNamespace")
        self.emit("from fortran_py_runtime import *")
        if any(re.match(r"\s*[a-z_]\w*\s*:\s*do\b", code, re.I) for code, _ in raw):
            self.emit("class _xf2p_LoopControl(Exception):")
            self.indent += 1
            self.emit("pass")
            self.indent -= 1
            self.emit("")
        if self._seen_scipy_special:
            self.emit("try:")
            self.indent += 1
            self.emit("import scipy.special as sps")
            self.indent -= 1
            self.emit("except ImportError as _xf2p_scipy_error:")
            self.indent += 1
            self.emit("raise ImportError('This translated program requires SciPy special functions; install with: python -m pip install scipy') from _xf2p_scipy_error")
            self.indent -= 1
        if self.seen_parameter:
            self.emit("from typing import Final")
        self.emit("")
        self.emit("def _xf2p_flatten(x):")
        self.indent += 1
        self.emit('"""Flatten nested list/tuple values emitted by transpiled implied-DOs."""')
        self.emit("if isinstance(x, (list, tuple)):")
        self.indent += 1
        self.emit("for item in x:")
        self.indent += 1
        self.emit("yield from _xf2p_flatten(item)")
        self.indent -= 1
        self.indent -= 1
        self.emit("else:")
        self.indent += 1
        self.emit("yield x")
        self.indent -= 1
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit('"""Return True for list/tuple/ndarray values handled elementally."""')
        self.emit("return isinstance(x, (list, tuple, np.ndarray)) and not isinstance(x, (str, bytes))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_concat(a, b):")
        self.indent += 1
        self.emit('"""Fortran CHARACTER concatenation with scalar/array broadcasting."""')
        self.emit("if _xf2p_is_arraylike(a):")
        self.indent += 1
        self.emit("aa = np.asarray(a, dtype=object)")
        self.indent -= 1
        self.emit("else:")
        self.indent += 1
        self.emit("aa = a")
        self.indent -= 1
        self.emit("if _xf2p_is_arraylike(b):")
        self.indent += 1
        self.emit("bb = np.asarray(b, dtype=object)")
        self.indent -= 1
        self.emit("else:")
        self.indent += 1
        self.emit("bb = b")
        self.indent -= 1
        self.emit("if isinstance(aa, np.ndarray) and isinstance(bb, np.ndarray):")
        self.indent += 1
        self.emit("return np.vectorize(lambda x, y: str(x) + str(y), otypes=[object])(aa, bb)")
        self.indent -= 1
        self.emit("if isinstance(aa, np.ndarray):")
        self.indent += 1
        self.emit("return np.vectorize(lambda x: str(x) + str(bb), otypes=[object])(aa)")
        self.indent -= 1
        self.emit("if isinstance(bb, np.ndarray):")
        self.indent += 1
        self.emit("return np.vectorize(lambda y: str(aa) + str(y), otypes=[object])(bb)")
        self.indent -= 1
        self.emit("return str(aa) + str(bb)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_div(a, b):")
        self.indent += 1
        self.emit('"""Fortran division with integer truncation and scalar/array broadcasting."""')
        self.emit("if _xf2p_is_arraylike(a) or _xf2p_is_arraylike(b):")
        self.indent += 1
        self.emit("aa = np.asarray(a)")
        self.emit("bb = np.asarray(b)")
        self.emit("if np.issubdtype(aa.dtype, np.integer) and np.issubdtype(bb.dtype, np.integer):")
        self.indent += 1
        self.emit("rr = np.trunc(aa / bb)")
        self.emit("return np.asarray(np.rint(rr), dtype=np.result_type(aa.dtype, bb.dtype))")
        self.indent -= 1
        self.emit("return aa / bb")
        self.indent -= 1
        self.emit("if isinstance(a, (int, np.integer)) and isinstance(b, (int, np.integer)) and not isinstance(a, (bool, np.bool_)) and not isinstance(b, (bool, np.bool_)):")
        self.indent += 1
        self.emit("return int(np.trunc(a / b))")
        self.indent -= 1
        self.emit("return a / b")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_nint(x):")
        self.emit('    """Fortran NINT with ties away from zero and array support."""')
        self.emit("    if _xf2p_is_arraylike(x):")
        self.emit("        xx = np.asarray(x, dtype=np.float64)")
        self.emit("        rr = np.copysign(np.floor(np.abs(xx) + 0.5), xx)")
        self.emit("        return np.asarray(rr, dtype=int)")
        self.emit("    xx = float(np.asarray(x))")
        self.emit("    return int(np.copysign(np.floor(abs(xx) + 0.5), xx))")
        self.emit("")
        self.emit("def _xf2p_anint(x):")
        self.emit('    """Fortran ANINT with ties away from zero and array support."""')
        self.emit("    if _xf2p_is_arraylike(x):")
        self.emit("        xx = np.asarray(x, dtype=np.float64)")
        self.emit("        return np.copysign(np.floor(np.abs(xx) + 0.5), xx)")
        self.emit("    xx = float(np.asarray(x))")
        self.emit("    return float(np.copysign(np.floor(abs(xx) + 0.5), xx))")
        self.emit("")
        self.emit("def _xf2p_aint(x):")
        self.emit('    """Fortran AINT with truncation toward zero and array support."""')
        self.emit("    if _xf2p_is_arraylike(x):")
        self.emit("        xx = np.asarray(x, dtype=np.float64)")
        self.emit("        return np.trunc(xx)")
        self.emit("    xx = float(np.asarray(x))")
        self.emit("    return float(np.trunc(xx))")
        self.emit("")
        self.emit("def _xf2p_ceiling(x):")
        self.emit('    """Fortran CEILING with scalar/array support."""')
        self.emit("    if _xf2p_is_arraylike(x):")
        self.emit("        xx = np.asarray(x, dtype=np.float64)")
        self.emit("        return np.asarray(np.ceil(xx), dtype=int)")
        self.emit("    xx = float(np.asarray(x))")
        self.emit("    return int(np.ceil(xx))")
        self.emit("")
        self.emit("def _xf2p_floor(x):")
        self.emit('    """Fortran FLOOR with scalar/array support."""')
        self.emit("    if _xf2p_is_arraylike(x):")
        self.emit("        xx = np.asarray(x, dtype=np.float64)")
        self.emit("        return np.asarray(np.floor(xx), dtype=int)")
        self.emit("    xx = float(np.asarray(x))")
        self.emit("    return int(np.floor(xx))")
        self.emit("")
        self.emit("def _xf2p_mod(a, p):")
        self.indent += 1
        self.emit('"""Fortran MOD intrinsic with scalar/array broadcasting."""')
        self.emit("if _xf2p_is_arraylike(a) or _xf2p_is_arraylike(p):")
        self.indent += 1
        self.emit("aa = np.asarray(a)")
        self.emit("pp = np.asarray(p)")
        self.emit("rr = aa - np.trunc(aa / pp) * pp")
        self.emit("if np.issubdtype(aa.dtype, np.integer) and np.issubdtype(pp.dtype, np.integer):")
        self.indent += 1
        self.emit("return np.asarray(np.rint(rr), dtype=np.result_type(aa.dtype, pp.dtype))")
        self.indent -= 1
        self.emit("return rr")
        self.indent -= 1
        self.emit("rr = a - np.trunc(a / p) * p")
        self.emit("if isinstance(a, (int, np.integer)) and isinstance(p, (int, np.integer)) and not isinstance(a, (bool, np.bool_)) and not isinstance(p, (bool, np.bool_)):")
        self.indent += 1
        self.emit("return int(np.rint(rr))")
        self.indent -= 1
        self.emit("return rr")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_modulo(a, p):")
        self.indent += 1
        self.emit('"""Fortran MODULO intrinsic with scalar/array broadcasting."""')
        self.emit("if _xf2p_is_arraylike(a) or _xf2p_is_arraylike(p):")
        self.indent += 1
        self.emit("aa = np.asarray(a)")
        self.emit("pp = np.asarray(p)")
        self.emit("rr = aa - np.floor(aa / pp) * pp")
        self.emit("if np.issubdtype(aa.dtype, np.integer) and np.issubdtype(pp.dtype, np.integer):")
        self.indent += 1
        self.emit("return np.asarray(np.rint(rr), dtype=np.result_type(aa.dtype, pp.dtype))")
        self.indent -= 1
        self.emit("return rr")
        self.indent -= 1
        self.emit("rr = a - np.floor(a / p) * p")
        self.emit("if isinstance(a, (int, np.integer)) and isinstance(p, (int, np.integer)) and not isinstance(a, (bool, np.bool_)) and not isinstance(p, (bool, np.bool_)):")
        self.indent += 1
        self.emit("return int(np.rint(rr))")
        self.indent -= 1
        self.emit("return rr")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_lbound(x, dim=None):")
        self.indent += 1
        self.emit('"""Fortran LBOUND for arraylike values with default lower bound 1."""')
        self.emit("if dim is not None:")
        self.indent += 1
        self.emit("return 1")
        self.indent -= 1
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("if x.ndim == 0:")
        self.indent += 1
        self.emit("return 1")
        self.indent -= 1
        self.emit("return np.ones(x.ndim, dtype=int)")
        self.indent -= 1
        self.emit("if isinstance(x, (list, tuple)) and not isinstance(x, (str, bytes)):")
        self.indent += 1
        self.emit("return 1")
        self.indent -= 1
        self.emit("return 1")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_ubound(x, dim=None):")
        self.indent += 1
        self.emit('"""Fortran UBOUND for arraylike values with default lower bound 1."""')
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("if x.ndim == 0:")
        self.indent += 1
        self.emit("return 1")
        self.indent -= 1
        self.emit("if dim is not None:")
        self.indent += 1
        self.emit("return int(x.shape[int(dim) - 1])")
        self.indent -= 1
        self.emit("return np.asarray(x.shape, dtype=int)")
        self.indent -= 1
        self.emit("if isinstance(x, (list, tuple)) and not isinstance(x, (str, bytes)):")
        self.indent += 1
        self.emit("if dim is not None:")
        self.indent += 1
        self.emit("return len(x)")
        self.indent -= 1
        self.emit("return np.asarray([len(x)], dtype=int)")
        self.indent -= 1
        self.emit("return 1")
        self.indent -= 1
        self.emit("")
        self.emit("def _f_len(x):")
        self.indent += 1
        self.emit('"""Fortran LEN for a scalar character value or character array."""')
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("if x.ndim == 0:")
        self.indent += 1
        self.emit("return len(str(x.item()))")
        self.indent -= 1
        self.emit("if x.size == 0:")
        self.indent += 1
        self.emit("return 0")
        self.indent -= 1
        self.emit("return len(str(np.ravel(x, order='F')[0]))")
        self.indent -= 1
        self.emit("if isinstance(x, (list, tuple)) and not isinstance(x, (str, bytes)):")
        self.indent += 1
        self.emit("if not x:")
        self.indent += 1
        self.emit("return 0")
        self.indent -= 1
        self.emit("return _f_len(x[0])")
        self.indent -= 1
        self.emit("return len(str(x))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_cmplx(x, y=0.0):")
        self.indent += 1
        self.emit('"""Fortran CMPLX with scalar/array broadcasting."""')
        self.emit("if _xf2p_is_arraylike(x) or _xf2p_is_arraylike(y):")
        self.indent += 1
        self.emit("if _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("xx = np.asarray(x)")
        self.indent -= 1
        self.emit("else:")
        self.indent += 1
        self.emit("xx = x")
        self.indent -= 1
        self.emit("if _xf2p_is_arraylike(y):")
        self.indent += 1
        self.emit("yy = np.asarray(y)")
        self.indent -= 1
        self.emit("else:")
        self.indent += 1
        self.emit("yy = y")
        self.indent -= 1
        self.emit("return np.asarray(np.real(xx), dtype=np.float64) + 1j * np.asarray(np.real(yy), dtype=np.float64)")
        self.indent -= 1
        self.emit("return complex(float(np.real(x)), float(np.real(y)))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_real(x):")
        self.indent += 1
        self.emit('"""Fortran REAL intrinsic for scalar or array input."""')
        self.emit("if _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return np.asarray(np.real(np.asarray(x)), dtype=np.float64)")
        self.indent -= 1
        self.emit("return np.float64(np.real(x))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_aimag(x):")
        self.indent += 1
        self.emit('"""Fortran AIMAG intrinsic for scalar or array input."""')
        self.emit("if _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return np.asarray(np.imag(np.asarray(x)), dtype=np.float64)")
        self.indent -= 1
        self.emit("return np.float64(np.imag(x))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_conjg(x):")
        self.indent += 1
        self.emit('"""Fortran CONJG intrinsic for scalar or array input."""')
        self.emit("if _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return np.conj(np.asarray(x))")
        self.indent -= 1
        self.emit("return np.conj(x)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_io_scalar(x):")
        self.indent += 1
        self.emit('"""Format one scalar for Fortran-like list-directed output."""')
        self.emit("if isinstance(x, np.ndarray) and x.ndim == 0:")
        self.indent += 1
        self.emit("return _xf2p_io_scalar(x.item())")
        self.indent -= 1
        self.emit("if isinstance(x, (complex, np.complexfloating)):")
        self.indent += 1
        self.emit("return f'({float(np.real(x)):.8f},{float(np.imag(x)):.8f})'")
        self.indent -= 1
        self.emit("return x")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_first_scalar(x):")
        self.indent += 1
        self.emit('"""Return the first scalar element from a scalar or arraylike value."""')
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("if x.ndim == 0:")
        self.indent += 1
        self.emit("return x.item()")
        self.indent -= 1
        self.emit("if x.size == 0:")
        self.indent += 1
        self.emit("return None")
        self.indent -= 1
        self.emit("return np.ravel(x, order='F')[0]")
        self.indent -= 1
        self.emit("if isinstance(x, (list, tuple)) and not isinstance(x, (str, bytes)):")
        self.indent += 1
        self.emit("if not x:")
        self.indent += 1
        self.emit("return None")
        self.indent -= 1
        self.emit("return _xf2p_first_scalar(x[0])")
        self.indent -= 1
        self.emit("return x")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_char_scalar(x):")
        self.indent += 1
        self.emit("return isinstance(x, (str, bytes))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_char_array(x):")
        self.indent += 1
        self.emit("if not _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return False")
        self.indent -= 1
        self.emit("v = _xf2p_first_scalar(x)")
        self.emit("return v is None or _xf2p_is_char_scalar(v)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_integer_scalar(x):")
        self.indent += 1
        self.emit("return isinstance(x, (int, np.integer)) and not isinstance(x, (bool, np.bool_))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_integer_array(x):")
        self.indent += 1
        self.emit("if not _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return False")
        self.indent -= 1
        self.emit("v = _xf2p_first_scalar(x)")
        self.emit("return v is None or _xf2p_is_integer_scalar(v)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_real_scalar(x):")
        self.indent += 1
        self.emit("return isinstance(x, (float, np.floating))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_real_array(x):")
        self.indent += 1
        self.emit("if not _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return False")
        self.indent -= 1
        self.emit("v = _xf2p_first_scalar(x)")
        self.emit("return v is None or _xf2p_is_real_scalar(v)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_logical_scalar(x):")
        self.indent += 1
        self.emit("return isinstance(x, (bool, np.bool_))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_logical_array(x):")
        self.indent += 1
        self.emit("if not _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return False")
        self.indent -= 1
        self.emit("v = _xf2p_first_scalar(x)")
        self.emit("return v is None or _xf2p_is_logical_scalar(v)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_complex_scalar(x):")
        self.indent += 1
        self.emit("return isinstance(x, (complex, np.complexfloating))")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_is_complex_array(x):")
        self.indent += 1
        self.emit("if not _xf2p_is_arraylike(x):")
        self.indent += 1
        self.emit("return False")
        self.indent -= 1
        self.emit("v = _xf2p_first_scalar(x)")
        self.emit("return v is None or _xf2p_is_complex_scalar(v)")
        self.indent -= 1
        self.emit("")

        self.emit("def _xf2p_io_items(x):")
        self.indent += 1
        self.emit('"""Flatten list-directed output items the way Fortran prints arrays."""')
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("return [_xf2p_io_scalar(v) for v in np.ravel(x, order='F')]")
        self.indent -= 1
        self.emit("if isinstance(x, (list, tuple)) and not isinstance(x, (str, bytes)):")
        self.indent += 1
        self.emit("out = []")
        self.emit("for item in x:")
        self.indent += 1
        self.emit("out.extend(_xf2p_io_items(item))")
        self.indent -= 1
        self.emit("return out")
        self.indent -= 1
        self.emit("return [_xf2p_io_scalar(x)]")
        self.indent -= 1
        self.emit("")

        self.emit("def _xf2p_print_star(*args, file=None):")
        self.indent += 1
        self.emit('"""Approximate Fortran list-directed PRINT/WRITE to stdout or a file."""')
        self.emit("items = []")
        self.emit("for arg in args:")
        self.indent += 1
        self.emit("if isinstance(arg, np.ndarray):")
        self.indent += 1
        self.emit("items.extend(list(np.ravel(arg, order='F')))")
        self.indent -= 1
        self.emit("elif isinstance(arg, (list, tuple)) and not isinstance(arg, (str, bytes)):")
        self.indent += 1
        self.emit("items.extend(_xf2p_io_items(arg))")
        self.indent -= 1
        self.emit("else:")
        self.indent += 1
        self.emit("items.append(arg)")
        self.indent -= 1
        self.indent -= 1
        self.emit("if not items:")
        self.indent += 1
        self.emit("print(file=file)")
        self.emit("return")
        self.indent -= 1
        self.emit("if all(isinstance(x, str) for x in items):")
        self.indent += 1
        self.emit("print(''.join(str(x) for x in items), file=file)")
        self.emit("return")
        self.indent -= 1
        self.emit("print(*items, file=file)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_star_text(*args):")
        self.indent += 1
        self.emit('"""Return list-directed text for internal WRITE fallbacks."""')
        self.emit("items = []")
        self.emit("for arg in args:")
        self.indent += 1
        self.emit("if isinstance(arg, np.ndarray):")
        self.indent += 1
        self.emit("items.extend(list(np.ravel(arg, order='F')))")
        self.indent -= 1
        self.emit("elif isinstance(arg, (list, tuple)) and not isinstance(arg, (str, bytes)):")
        self.indent += 1
        self.emit("items.extend(_xf2p_io_items(arg))")
        self.indent -= 1
        self.emit("else:")
        self.indent += 1
        self.emit("items.append(arg)")
        self.indent -= 1
        self.indent -= 1
        self.emit("if not items:")
        self.indent += 1
        self.emit("return ''")
        self.indent -= 1
        self.emit("if all(isinstance(x, str) for x in items):")
        self.indent += 1
        self.emit("return ''.join(str(x) for x in items)")
        self.indent -= 1
        self.emit("return ' '.join(str(x) for x in items)")
        self.indent -= 1
        self.emit("")

        self.emit("def _xf2p_implied_do(func, lo, hi, step=1):")
        self.indent += 1
        self.emit('"""Expand a Fortran I/O implied-DO into a flat Python list."""')
        self.emit("ilo = int(lo)")
        self.emit("ihi = int(hi)")
        self.emit("istep = int(step)")
        self.emit("stop = ihi + (1 if istep > 0 else -1)")
        self.emit("out = []")
        self.emit("for _xf2p_i in range(ilo, stop, istep):")
        self.indent += 1
        self.emit("out.extend(_xf2p_flatten(func(_xf2p_i)))")
        self.indent -= 1
        self.emit("return out")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_component_array(obj, path):")
        self.indent += 1
        self.emit('"""Project a component path over an array of derived-type values."""')
        self.emit("attrs = path.split('.')")
        self.emit("out = []")
        self.emit("for _xf2p_item in obj:")
        self.indent += 1
        self.emit("val = _xf2p_item")
        self.emit("for _xf2p_attr in attrs:")
        self.indent += 1
        self.emit("val = getattr(val, _xf2p_attr)")
        self.indent -= 1
        self.emit("out.append(val)")
        self.indent -= 1
        self.emit("return np.asarray(out)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_copy_value(x):")
        self.indent += 1
        self.emit('"""Fortran-style assignment copy for arrays and derived-type values."""')
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("return np.array(x, copy=True)")
        self.indent -= 1
        self.emit("if hasattr(x, '__dict__'):")
        self.indent += 1
        self.emit("import copy as _xf2p_copy_mod")
        self.emit("return _xf2p_copy_mod.deepcopy(x)")
        self.indent -= 1
        self.emit("return x")
        self.indent -= 1
        self.emit("")

        i = 0
        n = len(raw)

        in_module = False
        found_program = False
        loose_main: list[tuple[str, str]] = []

        while i < n:
            line = raw[i][0].strip()
            if not line:
                self.emit_comment(raw[i][1])
                i += 1
                continue

            if re.match(r"module\b", line, re.I) and not re.match(r"module\s+procedure\b", line, re.I):
                in_module = True
                header = line
                mbody: list[tuple[str, str]] = []
                i += 1
                while i < n and not re.match(r"\s*end\s+module\b", raw[i][0], re.I):
                    mbody.append(raw[i])
                    i += 1
                if i < n:
                    i += 1
                self.transpile_module(header, mbody)
                in_module = False
                continue

            if re.match(r"^type\b", line, re.I) and not re.match(r"^type\s*\(", line, re.I):
                header = line
                tbody: list[tuple[str, str]] = []
                i += 1
                while i < n and not re.match(r"\s*end\s+type\b", raw[i][0], re.I):
                    tbody.append(raw[i])
                    i += 1
                if i < n:
                    i += 1
                self.transpile_derived_type(header, tbody)
                continue

            if self._is_function_header(line):
                header = line
                body: list[tuple[str, str]] = []
                i += 1
                while i < n and not re.match(r"\s*end\s+function\b", raw[i][0], re.I):
                    body.append(raw[i])
                    i += 1
                if i < n:
                    i += 1
                self.transpile_function(header, body)
                continue

            if self._is_subroutine_header(line):
                header = line
                body: list[tuple[str, str]] = []
                i += 1
                while i < n and not re.match(r"\s*end\s+subroutine\b", raw[i][0], re.I):
                    body.append(raw[i])
                    i += 1
                if i < n:
                    i += 1
                self.transpile_subroutine(header, body)
                continue

            if re.match(r"program\b", line, re.I):
                found_program = True
                body: list[tuple[str, str]] = []
                i += 1
                while i < n and not re.match(r"\s*end\s+program\b", raw[i][0], re.I):
                    body.append(raw[i])
                    i += 1
                if i < n:
                    i += 1
                self.transpile_program(body)
                continue

            if not in_module:
                loose_main.append(raw[i])

            i += 1

        # unnamed main program (no "program" statement)
        if not found_program:
            if any(code.strip() or comment.strip() for code, comment in loose_main):
                self.transpile_program(loose_main)

        lines = "\n".join(self.out).rstrip().splitlines()
        lines = self._drop_unused_runtime(lines)
        out_lines: list[str] = []
        i = 0
        while i < len(lines):
            if lines[i].strip() == 'if __name__ == "__main__":':
                if i + 1 < len(lines) and lines[i + 1].strip() == "main()":
                    i += 2
                    continue
            out_lines.append(lines[i])
            i += 1
        has_main = any(ln.startswith("def main(") for ln in out_lines)
        if has_main:
            if out_lines and out_lines[-1].strip() != "":
                out_lines.append("")
            out_lines.append('if __name__ == "__main__":')
            out_lines.append("    main()")
        return "\n".join(out_lines).rstrip() + "\n"


def _report_run_diff(reference: str, actual: str, rtol: float = 1e-9,
                     atol: float = 1e-11, exact: bool = False) -> bool:
    result = compare_outputs(reference, actual, rtol, atol, exact=exact)
    if result["status"] == "match":
        print("Run diff: MATCH")
        return True
    print("Run diff: DIFF")
    print(f"  first mismatch line: {result['reference_line']}")
    if result["actual_line"] != result["reference_line"]:
        print(f"  python mismatch line: {result['actual_line']}")
    print(f"  fortran: {result['reference_text'] if result['reference_text'] is not None else '<no line>'}")
    print(f"  python : {result['actual_text'] if result['actual_text'] is not None else '<no line>'}")
    print("  " + result["detail"])
    if exact:
        for line in difflib.unified_diff(normalized_lines(reference), normalized_lines(actual),
                                         fromfile="fortran", tofile="python", n=1):
            print(line)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Partial Fortran-to-Python transpiler")
    ap.add_argument("input_f90", nargs="+", help="input .f90 source file(s)")
    ap.add_argument("--mode-program", action="store_true", help="treat all input files as one program (default)")
    ap.add_argument("--mode-each", action="store_true", help="transpile each input file independently")
    ap.add_argument("--out", help="output .py path (single target; valid for program mode or one-file each mode)")
    ap.add_argument("--out-dir", help="output directory for --mode-each (default: source file directories)")
    ap.add_argument("--run", action="store_true", help="run translated Python script after writing it")
    ap.add_argument("--compile", action="store_true", help="compile original Fortran source")
    ap.add_argument("--run-both", action="store_true", help="run original Fortran and translated Python (no timing)")
    ap.add_argument("--run-diff", action="store_true", help="run Fortran and Python and compare stdout numerically")
    ap.add_argument("--rtol", type=float, default=1e-9, help="relative tolerance for real output tokens (default: 1e-9)")
    ap.add_argument("--atol", type=float, default=1e-11, help="absolute tolerance for real output tokens (default: 1e-11)")
    ap.add_argument("--diff-exact", action="store_true", help="compare normalized stdout text exactly (implies --run-diff)")
    ap.add_argument("--tee", action="store_true", help="print transformed output (run output, or transpiled source when not running)")
    ap.add_argument("--tee-both", action="store_true", help="print both original and transformed outputs (run output, or source when not running)")
    ap.add_argument("--time", action="store_true", help="time transpile/compile/run stages (implies --run)")
    ap.add_argument("--time-both", action="store_true", help="time both original Fortran and translated Python (implies --run-both)")
    ap.add_argument(
        "--compiler",
        default="gfortran -O3 -march=native",
        help='compiler command, e.g. "gfortran -O2 -Wall"',
    )
    args = ap.parse_args()
    try:
        validate_tolerances(args.rtol, args.atol)
    except ValueError as exc:
        ap.error(str(exc))
    if args.diff_exact:
        args.run_diff = True

    if args.time_both:
        args.run_diff = True
    if args.run_diff:
        args.run_both = True
    if args.run_both:
        args.run = True
        args.compile = True
    if args.time_both:
        args.time = True
    if args.time:
        args.run = True
    if args.tee_both:
        args.tee = True

    show_fortran_output = bool(args.run_both or args.time_both or args.tee_both)
    show_python_output = bool(args.run or args.run_both or args.time or args.time_both or args.tee or args.tee_both)

    if args.mode_program and args.mode_each:
        print("Transpile: FAIL (choose at most one of --mode-program and --mode-each)")
        return 1
    mode_each = bool(args.mode_each)

    in_paths = [Path(p) for p in args.input_f90]
    for p in in_paths:
        if not p.exists():
            print(f"Missing file: {p}")
            return 1
    if mode_each and args.out and len(in_paths) > 1:
        print("Transpile: FAIL (--out with --mode-each is allowed only for one input file)")
        return 1
    if (not mode_each) and len(in_paths) > 1 and args.out:
        print("Transpile: FAIL (--out is allowed only for a single input in --mode-program)")
        return 1

    def _ensure_runtime_file(dst_dir: Path) -> None:
        rt = Path(__file__).with_name("fortran_py_runtime.py")
        if rt.exists():
            dst = dst_dir / "fortran_py_runtime.py"
            if not dst.exists():
                dst.write_text(rt.read_text(encoding="utf-8"), encoding="utf-8")

    def process_one(src_paths: list[Path], out_path: Path) -> int:
        timings = {}
        diff_failed = False
        ft_run = None
        ft_exe = out_path.with_suffix(".orig.exe")
        compiler_parts = shlex.split(args.compiler)

        if args.compile or args.run_both:
            if args.time:
                if len(compiler_parts) > 1:
                    print("Compile options:", " ".join(compiler_parts[1:]))
                else:
                    print("Compile options: <none>")
            build_cmd = compiler_parts + [str(p) for p in src_paths] + ["-o", str(ft_exe)]
            print("Build (original-fortran):", " ".join(build_cmd))
            t0_build = time.perf_counter()
            cp = subprocess.run(build_cmd, text=True, capture_output=True)
            timings["compile"] = time.perf_counter() - t0_build
            if cp.returncode != 0:
                print(f"Build (original-fortran): FAIL (exit {cp.returncode})")
                if cp.stdout.strip():
                    print(cp.stdout.rstrip())
                if cp.stderr.strip():
                    print(cp.stderr.rstrip())
                return cp.returncode
            print("Build (original-fortran): PASS")

        if args.run_both:
            t0_ft = time.perf_counter()
            ft_run = subprocess.run([str(ft_exe)], text=True, capture_output=True)
            timings["fortran_run"] = time.perf_counter() - t0_ft
            if ft_run.returncode != 0:
                print(f"Run (original-fortran): FAIL (exit {ft_run.returncode})")
                if ft_run.stdout.strip():
                    print(ft_run.stdout.rstrip())
                if ft_run.stderr.strip():
                    print(ft_run.stderr.rstrip())
                return ft_run.returncode
            print("Run (original-fortran): PASS")
            if show_fortran_output and ft_run.stdout.strip():
                if args.run_both and not args.tee_both:
                    print("--- output (original-fortran) ---")
                print(ft_run.stdout.rstrip())
            if show_fortran_output and ft_run.stderr.strip():
                if args.run_both and not args.tee_both and not ft_run.stdout.strip():
                    print("--- output (original-fortran) ---")
                print(ft_run.stderr.rstrip())

        t0_transpile = time.perf_counter()
        src = _preprocess_fortran_source("\n\n".join(p.read_text(encoding="utf-8") for p in src_paths))
        t = basic_f2p()
        try:
            py = t.transpile(src)
        except ValueError as e:
            print(f"Transpile: FAIL ({e})")
            return 1
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        src_tag = ", ".join(p.name for p in src_paths)
        py = f"# transpiled by xf2p.py from {src_tag} on {stamp}\n" + py
        out_path.write_text(py, encoding="utf-8")
        _ensure_runtime_file(out_path.parent)
        if args.tee_both:
            try:
                src_text = src_paths[0].read_text(encoding="utf-8") if len(src_paths) == 1 else "\n\n".join(
                    p.read_text(encoding="utf-8") for p in src_paths
                )
                src_tag = src_paths[0].name if len(src_paths) == 1 else ", ".join(p.name for p in src_paths)
                print(f"--- original: {src_tag} ---")
                print(src_text.rstrip())
            except OSError:
                pass
        if args.tee:
            try:
                out_text = out_path.read_text(encoding="utf-8")
                print(f"--- transpiled: {out_path} ---")
                print(out_text.rstrip())
            except OSError:
                pass
        timings["transpile"] = time.perf_counter() - t0_transpile

        if args.run:
            cmd = [sys.executable, str(out_path)]
            t0_py = time.perf_counter()
            rp = subprocess.run(cmd, text=True, capture_output=True)
            timings["python_run"] = time.perf_counter() - t0_py
            if rp.returncode != 0:
                if "SyntaxError" in (rp.stderr or ""):
                    print(f"Run: FAIL (translated Python is invalid: syntax error in {out_path})")
                else:
                    print(f"Run: FAIL (exit {rp.returncode})")
                if rp.stdout.strip():
                    print(rp.stdout.rstrip())
                if rp.stderr.strip():
                    print(rp.stderr.rstrip())
                return rp.returncode
            if args.run_both:
                print("Run (translated-python): PASS")
            if show_python_output and rp.stdout.strip():
                if args.run_both and not args.tee_both:
                    print("--- output (translated-python) ---")
                print(rp.stdout.rstrip())
            if show_python_output and rp.stderr.strip():
                if args.run_both and not args.tee_both and not rp.stdout.strip():
                    print("--- output (translated-python) ---")
                print(rp.stderr.rstrip())

            if args.run_diff and ft_run is not None:
                diff_failed = not _report_run_diff(ft_run.stdout or "", rp.stdout or "",
                                                   args.rtol, args.atol, args.diff_exact)

        if args.time:
            fortran_total = timings.get("compile", 0.0) + timings.get("fortran_run", 0.0)
            print("")
            print("Timing summary (seconds):")
            base = timings.get("python_run", 0.0)

            def _ratio(v):
                if base > 0.0:
                    return f"{(v / base):.6f}"
                return "n/a"

            rows = []
            rows.append(("transpile", timings.get("transpile", 0.0)))
            if "python_run" in timings:
                rows.append(("python run", timings["python_run"]))
            if "compile" in timings:
                rows.append(("compile", timings["compile"]))
            if "fortran_run" in timings:
                rows.append(("fortran run", timings["fortran_run"]))
            if "compile" in timings or "fortran_run" in timings:
                rows.append(("fortran total", fortran_total))

            print("  stage            seconds    ratio(vs python run)")
            for name, val in rows:
                print(f"  {name:<14} {val:>8.6f}    {_ratio(val)}")
        return int(diff_failed)

    if not mode_each:
        if len(in_paths) == 1:
            out_path = Path(args.out) if args.out else in_paths[-1].with_name(f"{in_paths[-1].stem}_f.py")
            return process_one(in_paths, out_path)

        # Multi-file program mode: emit one Python module per Fortran input file.
        # This preserves separate namespaces and wires USE-based imports.
        timings: dict[str, float] = {}
        ft_run = None
        compiler_parts = shlex.split(args.compiler)
        if args.out_dir:
            ft_exe = Path(args.out_dir) / f"{in_paths[-1].stem}.orig.exe"
        else:
            ft_exe = in_paths[-1].with_suffix(".orig.exe")
        ft_exe.parent.mkdir(parents=True, exist_ok=True)

        if args.compile or args.run_both:
            if args.time:
                if len(compiler_parts) > 1:
                    print("Compile options:", " ".join(compiler_parts[1:]))
                else:
                    print("Compile options: <none>")
            build_cmd = compiler_parts + [str(p) for p in in_paths] + ["-o", str(ft_exe)]
            print("Build (original-fortran):", " ".join(build_cmd))
            t0_build = time.perf_counter()
            cp = subprocess.run(build_cmd, text=True, capture_output=True)
            timings["compile"] = time.perf_counter() - t0_build
            if cp.returncode != 0:
                print(f"Build (original-fortran): FAIL (exit {cp.returncode})")
                if cp.stdout.strip():
                    print(cp.stdout.rstrip())
                if cp.stderr.strip():
                    print(cp.stderr.rstrip())
                return cp.returncode
            print("Build (original-fortran): PASS")

        if args.run_both:
            t0_ft = time.perf_counter()
            ft_run = subprocess.run([str(ft_exe)], text=True, capture_output=True)
            timings["fortran_run"] = time.perf_counter() - t0_ft
            if ft_run.returncode != 0:
                print(f"Run (original-fortran): FAIL (exit {ft_run.returncode})")
                if ft_run.stdout.strip():
                    print(ft_run.stdout.rstrip())
                if ft_run.stderr.strip():
                    print(ft_run.stderr.rstrip())
                return ft_run.returncode
            print("Run (original-fortran): PASS")
            if show_fortran_output and ft_run.stdout.strip():
                if args.run_both and not args.tee_both:
                    print("--- output (original-fortran) ---")
                print(ft_run.stdout.rstrip())
            if show_fortran_output and ft_run.stderr.strip():
                if args.run_both and not args.tee_both and not ft_run.stdout.strip():
                    print("--- output (original-fortran) ---")
                print(ft_run.stderr.rstrip())

        t0_transpile = time.perf_counter()
        file_src: dict[Path, str] = {p: _preprocess_fortran_source(p.read_text(encoding="utf-8")) for p in in_paths}
        file_mods: dict[Path, list[str]] = {}
        file_defs: dict[Path, list[str]] = {}
        file_uses: dict[Path, list[UseSpec]] = {}
        for p in in_paths:
            mods, defs, uses = _parse_file_interface(file_src[p])
            file_mods[p] = mods
            file_defs[p] = defs
            file_uses[p] = uses

        module_provider: dict[str, Path] = {}
        for p in in_paths:
            for m in file_mods[p]:
                module_provider[m.lower()] = p

        generated: dict[Path, Path] = {}
        file_module_variables: dict[Path, dict[str, dict[str, dict]]] = {}
        rc = 0
        for p in in_paths:
            out_path = (Path(args.out_dir) / f"{p.stem}_f.py") if args.out_dir else p.with_name(f"{p.stem}_f.py")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"[mode-program] {p} -> {out_path}")
            src = file_src[p]
            t = basic_f2p()
            try:
                py = t.transpile(src)
            except ValueError as e:
                print(f"Transpile: FAIL ({e})")
                return 1
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            py = f"# transpiled by xf2p.py from {p.name} on {stamp}\n" + py
            out_path.write_text(py, encoding="utf-8")
            _ensure_runtime_file(out_path.parent)
            if not args.run:
                if args.tee_both:
                    print(f"--- original: {p} ---")
                    print(src.rstrip())
                if args.tee:
                    print(f"--- transpiled: {out_path} ---")
                    print(py.rstrip())
            generated[p] = out_path
            file_module_variables[p] = t._module_variable_symbols

        # Add inter-file imports according to USE dependencies.
        for p in in_paths:
            out_path = generated[p]
            local_defs = {x.lower() for x in file_defs[p]}
            imports: list[str] = []
            for us in file_uses[p]:
                if us.intrinsic:
                    continue
                provider = module_provider.get(us.module.lower())
                if provider is None or provider == p:
                    continue
                mod_py = generated[provider].stem
                names: list[str]
                if us.only_items is not None:
                    names = [
                        nm
                        for nm in us.only_items
                        if nm.lower() not in local_defs and nm.lower() not in _LOCAL_RUNTIME_HELPERS
                    ]
                else:
                    # import all known symbols from provider, excluding local collisions
                    names = [
                        nm
                        for nm in file_defs[provider]
                        if nm.lower() not in local_defs and nm.lower() not in _LOCAL_RUNTIME_HELPERS
                    ]
                names = unique_preserve(names)
                if not names:
                    continue
                variables = file_module_variables[provider].get(us.module.lower(), {})
                referenced = {name.lower() for name in names}
                # _parse_file_interface retains local names in ONLY lists.
                # Also check remote names so a rename cannot bypass this guard.
                for code, _ in collapse_fortran_continuations(
                        [split_fortran_comment(line) for line in file_src[p].splitlines()]):
                    use = re.match(r"\s*use\s*(?:,\s*(?:intrinsic|non_intrinsic)\s*)?(?:::)?\s*([a-z_]\w*)\b(.*)", code, re.I)
                    if use and use.group(1).lower() == us.module.lower():
                        referenced.update(match.group(1).lower() for match in
                                          re.finditer(r"=>\s*([a-z_]\w*)", use.group(2), re.I))
                mutable = {var.lower() for var, info in variables.items()
                           if "parameter" not in info["attrs_l"]}
                if referenced & mutable:
                    print("Transpile: FAIL (mutable USE-associated variables across separate Python files are not yet supported; combine the module and program into a single Fortran input file)")
                    return 1
                imports.append(f"from {mod_py} import {', '.join(names)}")
            if imports:
                py = out_path.read_text(encoding="utf-8")
                py = _insert_imports(py, unique_preserve(imports))
                out_path.write_text(py, encoding="utf-8")
        timings["transpile"] = time.perf_counter() - t0_transpile

        if args.run:
            main_out = generated[in_paths[-1]]
            cmd = [sys.executable, str(main_out)]
            t0_py = time.perf_counter()
            rp = subprocess.run(cmd, text=True, capture_output=True)
            timings["python_run"] = time.perf_counter() - t0_py
            if rp.returncode != 0:
                if "SyntaxError" in (rp.stderr or ""):
                    print(f"Run: FAIL (translated Python is invalid: syntax error in {main_out})")
                else:
                    print(f"Run: FAIL (exit {rp.returncode})")
                if rp.stdout.strip():
                    print(rp.stdout.rstrip())
                if rp.stderr.strip():
                    print(rp.stderr.rstrip())
                return rp.returncode
            if args.run_both:
                print("Run (translated-python): PASS")
            else:
                print("Run: PASS")
            if show_python_output and rp.stdout.strip():
                if args.run_both and not args.tee_both:
                    print("--- output (translated-python) ---")
                print(rp.stdout.rstrip())
            if show_python_output and rp.stderr.strip():
                if args.run_both and not args.tee_both and not rp.stdout.strip():
                    print("--- output (translated-python) ---")
                print(rp.stderr.rstrip())

            if args.run_diff and ft_run is not None:
                rc = int(not _report_run_diff(ft_run.stdout or "", rp.stdout or "",
                                              args.rtol, args.atol, args.diff_exact))

        if args.time:
            fortran_total = timings.get("compile", 0.0) + timings.get("fortran_run", 0.0)
            print("")
            print("Timing summary (seconds):")
            base = timings.get("python_run", 0.0)

            def _ratio(v):
                if base > 0.0:
                    return f"{(v / base):.6f}"
                return "n/a"

            rows = []
            rows.append(("transpile", timings.get("transpile", 0.0)))
            if "python_run" in timings:
                rows.append(("python run", timings["python_run"]))
            if "compile" in timings:
                rows.append(("compile", timings["compile"]))
            if "fortran_run" in timings:
                rows.append(("fortran run", timings["fortran_run"]))
            if "compile" in timings or "fortran_run" in timings:
                rows.append(("fortran total", fortran_total))

            print("  stage            seconds    ratio(vs python run)")
            for name, val in rows:
                print(f"  {name:<14} {val:>8.6f}    {_ratio(val)}")
        return rc

    rc = 0
    for p in in_paths:
        print(f"[mode-each] {p}")
        if args.out:
            out_path = Path(args.out)
        elif args.out_dir:
            out_path = Path(args.out_dir) / f"{p.stem}_f.py"
        else:
            out_path = p.with_name(f"{p.stem}_f.py")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc = process_one([p], out_path)
        if rc != 0:
            break
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
