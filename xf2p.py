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
            r"^(?!\s*end\s+function\b)\s*(?:(?:pure|impure|elemental|recursive)\s+)*(?:\w+(?:\s*\([^)]*\))?\s+)*function\s+([a-z_]\w*)\s*\(",
            sl,
            re.I,
        )
        if mf:
            defs.append(mf.group(1))
            continue

        # subroutine declarations
        ms = re.match(
            r"^(?!\s*end\s+subroutine\b)\s*(?:(?:pure|impure|elemental|recursive)\s+)*subroutine\s+([a-z_]\w*)\s*\(",
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


def lower_enum_declarations(lines: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], dict[str, set[str]]]:
    """Lower ENUM, BIND(C) before the ordinary parameter and scoping passes."""
    output = []
    module_enumerators: dict[str, set[str]] = {}
    module, module_specification = None, False
    active, previous = False, None
    names: set[str] = set()
    for code, comment in lines:
        statements = split_top_level(code, ";")
        enum_line = active or any(re.match(r"\s*(?:enum\b|enumerator\b|end\s*enum\b)", statement, re.I)
                                  for statement in statements)
        for statement in statements if enum_line else [code]:
            text = statement.strip()
            start_module = re.fullmatch(r"module\s+([a-z_]\w*)", text, re.I)
            if start_module:
                module, module_specification = start_module.group(1).lower(), True
            elif re.match(r"end\s*module\b", text, re.I):
                module, module_specification = None, False
            elif re.fullmatch(r"contains", text, re.I):
                module_specification = False
            if re.match(r"enum\b", text, re.I) and len(split_top_level(text, "=")) == 1:
                if active:
                    raise ValueError("nested ENUM declarations are not supported")
                if not re.fullmatch(r"enum\s*,\s*bind\s*\(\s*c\s*\)", text, re.I):
                    raise ValueError("Only anonymous ENUM, BIND(C) declarations are supported")
                active, previous, names = True, None, set()
                output.append(("", comment))
                continue
            if re.fullmatch(r"end\s*enum", text, re.I):
                if not active:
                    raise ValueError("END ENUM without ENUM, BIND(C)")
                if not names:
                    raise ValueError("ENUM requires at least one ENUMERATOR")
                active = False
                output.append(("", comment))
                continue
            enumerator = re.match(r"enumerator\b(?!\s*[(%=])\s*(?:::)?\s*(.*)", text, re.I)
            if enumerator:
                if not active:
                    raise ValueError("ENUMERATOR outside ENUM, BIND(C)")
                items = split_args(enumerator.group(1))
                if not items:
                    raise ValueError("empty ENUMERATOR declaration")
                for item in items:
                    entry = re.fullmatch(r"([a-z_]\w*)\s*(?:=\s*(.+))?", item.strip(), re.I)
                    if not entry:
                        raise ValueError(f"malformed ENUMERATOR: {item}")
                    name, explicit = entry.group(1).lower(), entry.group(2)
                    if name in names:
                        raise ValueError(f"duplicate ENUMERATOR: {name}")
                    value = explicit if explicit is not None else ("0" if previous is None else f"{previous} + 1")
                    output.append((f"integer, parameter :: {name} = {value}", comment))
                    if module is not None and module_specification:
                        module_enumerators.setdefault(module, set()).add(name)
                    names.add(name)
                    previous = name
                continue
            if active and text:
                if re.match(r"end\b", text, re.I):
                    raise ValueError("ENUM without END ENUM")
                raise ValueError(f"unsupported statement within ENUM: {text}")
            output.append((statement, comment))
    if active:
        raise ValueError("ENUM without END ENUM")
    return output, module_enumerators


def reject_defined_operations(lines: list[tuple[str, str]]) -> None:
    """Reject declarations whose dispatch/assignment semantics we cannot preserve."""
    for index, (code, _comment) in enumerate(lines):
        declaration = re.match(r"^\s*interface\s+(operator|assignment)\s*\(\s*([^)]*?)\s*\)", code, re.I)
        binding = re.match(r"^\s*generic\b[^:]*::\s*(operator|assignment)\s*\(\s*([^)]*?)\s*\)\s*=>\s*(.*)$", code, re.I)
        match = declaration or binding
        if match is None:
            continue
        kind, symbol = match.group(1).lower(), match.group(2).strip()
        procedures = []
        if binding:
            procedures = split_args(binding.group(3))
        else:
            for body, _ in lines[index + 1:]:
                if re.match(r"^\s*end\s*interface\b", body, re.I):
                    break
                named = re.match(r"^\s*(?:module\s+)?procedure\b\s*(?:::)?\s*(.+)$", body, re.I)
                if named:
                    procedures.extend(split_args(named.group(1)))
                elif not re.match(r"^\s*end\b", body, re.I):
                    header = re.search(r"\b(?:function|subroutine)\s+(\w+)\s*\(", body, re.I)
                    if header:
                        procedures.append(header.group(1))
        detail = f"; procedure(s): {', '.join(procedures)}" if procedures else ""
        description = "operator overloading" if kind == "operator" else "defined assignment"
        raise ValueError(f"{description} is not yet supported: {kind.upper()}({symbol}){detail}")


def reject_goto_statements(lines: list[tuple[str, str]]) -> None:
    """Reject control transfers before unsupported statements can be discarded."""
    for code, _comment in lines:
        for statement in split_top_level(code, ";"):
            statement = re.sub(r"^\s*\d+\s+", "", statement).strip()
            action = statement
            conditional = re.match(r"if\s*\(", action, re.I)
            if conditional:
                close = find_matching_paren(action, conditional.end() - 1)
                if close < 0:
                    continue
                action = action[close + 1:].strip()
            jump = re.match(r"go\s*to(?=\s|\(|\d|$)", action, re.I)
            if jump is None:
                continue
            target = action[jump.end():].strip()
            # Fortran keywords are not reserved: GOTO can name a variable.
            if target.startswith("=") or re.match(r"[a-z_]\w*\s*=", action, re.I):
                continue
            if target.startswith("("):
                close = find_matching_paren(target, 0)
                if close >= 0 and target[close + 1:].lstrip().startswith("="):
                    continue
            raise ValueError(
                f"GOTO control flow is not yet supported; rewrite using structured "
                f"IF/DO, EXIT or CYCLE: {statement}")


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


def data_statements(lines: list[tuple[str, str]]):
    """Yield DATA specifications, without confusing variables named DATA."""
    for code, _comment in lines:
        specifications = []
        statements = split_top_level(code, ";")
        for statement in statements:
            statement = re.sub(r"^\s*\d+\s+", "", statement).strip()
            match = re.match(r"data\s+(.+)$", statement, re.I)
            if match is None or match.group(1).lstrip().startswith("="):
                continue
            if re.match(r"data\s*\([^)]*\)\s*=", statement, re.I):
                continue
            specifications.append((statement, match.group(1)))
        if specifications and len(specifications) != len(statements):
            raise ValueError("DATA statements sharing a line with other statements are not yet supported; split the line")
        yield from specifications


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


def _fortran_format_expr(fmt_literal: str, arg_exprs: list[str], *, following_items: bool = False) -> str | None:
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
            inner_literal = repr('(' + inner + ')')
            width = _fortran_format_arg_count(inner_literal)
            if width is None or width == 0:
                return "fail"
            # Partial final cycles and colon suppression need separate renderers.
            # Bound code expansion instead of generating quadratic megabytes for
            # huge repeated groups (a separate unsupported formatting case).
            if width > 128:
                raise ValueError('unsupported unlimited format: more than 128 data descriptors per repetition')
            renderers = []
            for count in range(width + 1):
                group_args = [f'_xf2p_group[{j}]' for j in range(count)]
                rendered = _fortran_format_expr(inner_literal, group_args)
                if rendered is None:
                    return 'fail'
                renderers.append(f'lambda _xf2p_group: {rendered}')
            more = _fortran_format_expr(inner_literal, [f'_xf2p_group[{j}]' for j in range(width)], following_items=True)
            if more is None:
                return 'fail'
            # Consume every remaining I/O item, flattening arrays in Fortran
            # order while leaving scalar CHARACTER values intact. Evaluate each
            # original expression once, even for mixed scalar/array lists.
            remaining = ', '.join(arg_exprs[arg_i:])
            iterable = f'[_xf2p_item for _xf2p_arg in [{remaining}] for _xf2p_item in _xf2p_io_items(_xf2p_arg)]'
            arg_i = len(arg_exprs)
            parts.append(f'_xf2p_unlimited_format({iterable}, {width}, [{", ".join(renderers)}], lambda _xf2p_group: {more})')
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
            if arg_i >= len(arg_exprs) and not following_items:
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
    'dprod': (('x', 'y'), 2),
    'selected_int_kind': (('r',), 1),
    'selected_real_kind': (('p', 'r', 'radix'), 0),
    'selected_logical_kind': (('bits',), 1),
    'maxval': (('array', 'dim', 'mask'), 1),
    'minval': (('array', 'dim', 'mask'), 1),
    'product': (('array', 'dim', 'mask'), 1),
    'unpack': (('vector', 'mask', 'field'), 3),
    'cshift': (('array', 'shift', 'dim'), 2),
    'eoshift': (('array', 'shift', 'boundary', 'dim'), 2),
    'is_contiguous': (('array',), 1),
    'associated': (('pointer', 'target'), 1),
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
    m = re.search(r"\b(double\s+precision|double\s+complex|integer|real|logical|complex)\b(?:\s*\([^)]*\))?\b[^!\n]*\bfunction\b", h, re.I)
    if not m:
        return None
    ftype = re.sub(r'\s+', ' ', m.group(1).lower())
    return {'double precision': 'real', 'double complex': 'complex'}.get(ftype, ftype)

_decl_re = re.compile(r"^(double\s+precision|double\s+complex|integer|real|logical|complex|character(?:\s*\([^)]*\))?)\b(.*)$", re.I)


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
        # Without attributes/initialization, :: is optional. Parse a complete
        # type specification and validate the entity list, rather than treating
        # every statement beginning with REAL/INTEGER/etc. as a declaration.
        type_match = re.match(r'^(double\s+precision|double\s+complex|integer|real|logical|complex|character)\b', s, re.I)
        if not type_match:
            return None
        cursor = type_match.end()
        while cursor < len(s) and s[cursor].isspace():
            cursor += 1
        if cursor < len(s) and s[cursor] == '(':
            closing = find_matching_paren(s, cursor)
            if closing < 0:
                return None
            cursor = closing + 1
        elif cursor < len(s) and s[cursor] == '*':
            cursor += 1
            while cursor < len(s) and s[cursor].isspace():
                cursor += 1
            if cursor < len(s) and s[cursor] == '(':
                closing = find_matching_paren(s, cursor)
                if closing < 0:
                    return None
                cursor = closing + 1
            else:
                length = re.match(r'\d+', s[cursor:])
                if not length:
                    return None
                cursor += length.end()
        rest = s[cursor:].strip()
        if not rest:
            return None
        for entity in split_args(rest):
            entity = entity.strip()
            name = re.match(r'^[a-z_]\w*', entity, re.I)
            if not name:
                return None
            tail = entity[name.end():].strip()
            if tail and not (tail.startswith('(') and find_matching_paren(tail, 0) == len(tail) - 1):
                return None
        return parse_decl(s[:cursor].strip() + ' :: ' + rest)
    lhs = s[:pos].strip()
    rest = s[pos + 2 :].strip()
    m = _decl_re.match(lhs)
    if not m:
        return None
    ftype = re.sub(r'\s+', ' ', m.group(1).lower())
    double_kind = ftype in {'double precision', 'double complex'}
    ftype = {'double precision': 'real', 'double complex': 'complex'}.get(ftype, ftype)
    if ftype.startswith("character"):
        ftype = "character"
    attrs = m.group(2).strip().rstrip(",").strip()
    if double_kind:
        # Normalize legacy double types once, preserving their kind for all
        # consumers: declarations, dummy signatures and KIND inquiries.
        attrs = '(kind=8)' + (', ' + attrs.lstrip(',').strip() if attrs else '')
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
        self._generic_names = set()
        self._generic_kind_keyword = '_xf2p_kind_hints'
        self._function_result_models = {}
        self._current_result_name: str | None = None
        self._current_subroutine_outputs: list[str] = []
        self._optional_allocatable_presence = {}
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
        self._forall_stack: list[dict] = []
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
        # Legacy CHARACTER*(expr) has the same LEN semantics as
        # CHARACTER(LEN=expr); use balanced parentheses for nested expressions.
        m = re.search(r"\bcharacter\s*\*\s*\(", s, re.I)
        if m:
            p0 = s.find("(", m.start())
            p1 = find_matching_paren(s, p0)
            if p1 != -1:
                return s[p0 + 1 : p1].strip()
        m = re.search(r"\bcharacter\s*\*\s*([a-z_]\w*|\d+)", s, re.I)
        if m:
            return m.group(1).strip()
        return None

    def _apply_data_initializers(self, lines: list[tuple[str, str]], sym: dict[str, dict], args=()) -> None:
        """Attach supported DATA values before normal initialization/SAVE analysis."""
        names = {name.lower(): name for name in sym}
        for statement, specification in data_statements(lines):
            groups = split_top_level(specification, "/", preserve_empty=True)
            if len(groups) < 3 or len(groups) % 2 != 1 or groups[-1].strip():
                raise ValueError(f"malformed or unsupported DATA specification: {statement}")
            for index in range(0, len(groups) - 1, 2):
                objects = split_args(groups[index].strip().lstrip(",").strip())
                values = []
                for value in split_args(groups[index + 1]):
                    repeated = split_top_level(value, "*")
                    if len(repeated) == 1:
                        values.append((value, 1))
                    elif len(repeated) == 2 and re.fullmatch(r"\d+", repeated[0].strip()):
                        values.append((repeated[1].strip(), int(repeated[0])))
                    else:
                        raise ValueError(f"DATA repeat count must be a literal nonnegative integer: {value}")
                selected = []
                for obj in objects:
                    if not re.fullmatch(r"[a-z_]\w*", obj, re.I):
                        raise ValueError(f"DATA currently supports whole declared variables, not partial objects or implied-DOs: {obj}")
                    name = names.get(obj.lower())
                    if name is None:
                        raise ValueError(f"DATA requires an explicit declaration for '{obj}'")
                    info = sym[name]
                    if (info['ftype'] not in {'integer', 'real', 'complex', 'logical', 'character'}
                            or info.get('alloc') or info.get('pointer') or info.get('target')
                            or 'parameter' in info.get('attrs_l', '')
                            or name.lower() in {a.lower() for a in args}
                            or name in getattr(self, '_block_local_names', set())):
                        raise ValueError(f"DATA initialization is not supported for '{obj}' in this context")
                    if info.get('init') is not None:
                        raise ValueError(f"duplicate initialization of DATA object '{obj}'")
                    selected.append((name, info))
                arrays = [info for _, info in selected if info.get('is_array')]
                if arrays and len(selected) != 1:
                    raise ValueError("DATA groups mixing arrays and other objects are not yet supported; use separate groups")
                value_count = sum(count for _, count in values)
                if not selected or (not arrays and value_count != len(selected)):
                    raise ValueError(f"DATA object/value count mismatch: {statement}")
                scalar_values = [value for value, count in values for _ in range(count)] if not arrays else []
                for index, (name, info) in enumerate(selected):
                    if arrays:
                        if not value_count or not info.get('shape') or any(not hi for _, hi in self._shape_bounds(info['shape'])):
                            raise ValueError(f"DATA requires a nonempty value list and explicit shape for '{name}'")
                        info['init'] = '0'  # Non-None marks the implicit SAVE initialization.
                        info['data_values'] = values
                    else:
                        info['init'] = scalar_values[index]
                    info['data_initialized'] = True
            self._data_handled_count += 1

    def _data_init_expr(self, info: dict, arrays_1d: set[str]) -> str:
        ftype = info['ftype']
        if info.get('data_values'):
            chunks = []
            for value, count in info['data_values']:
                value_py = self.translate_expr(value, arrays_1d)
                if ftype == 'character' and info.get('char_len') is not None:
                    length = self.translate_expr(str(info['char_len']), arrays_1d)
                    value_py = f"_f_str_assign({value_py}, {length})"
                chunks.append(f"np.full({count}, {value_py}, dtype={_type_dtype[ftype]})")
            shape = self._shape_to_py(str(info['shape']), arrays_1d)
            return f"np.concatenate([{', '.join(chunks)}]).reshape({shape}, order='F')"
        rhs = self.translate_expr(str(info['init']), arrays_1d)
        if ftype == 'character' and info.get('char_len') is not None:
            length = self.translate_expr(str(info['char_len']), arrays_1d)
            rhs = f"_f_str_assign({rhs}, {length})"
        if ftype != 'character':
            rhs = f"{_type_scalar_hint[ftype]}({rhs})"
        return rhs

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
            if info.get('data_initialized'):
                init_py = self._data_init_expr(info, arrays_1d)
            elif "allocatable" in info.get("attrs_l", ""):
                init_py = "None"
            elif is_array:
                shape = info.get("shape")
                if shape is None:
                    init_py = "None"
                else:
                    shape_py = self._shape_to_py(str(shape), arrays_1d)
                    if ftype == "type":
                        cls = info.get("type_name") or "SimpleNamespace"
                        rhs = self.translate_expr(str(init), arrays_1d) if init is not None else f"{cls}()"
                        init_py = f"_f_init_component_array({shape_py}, {rhs}, object)"
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
                    init_py = self.translate_expr(str(init), arrays_1d) if init is not None else f"{cls}()"
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
        return bool(re.match(r"^(?!\s*end\s+function\b)\s*(?:(?:pure|impure|elemental|recursive)\s+)*(?:\w+(?:\s*\([^)]*\))?\s+)*function\b", s, re.I))

    def _is_subroutine_header(self, s: str) -> bool:
        return bool(re.match(r"^(?!\s*end\s+subroutine\b)\s*(?:(?:pure|impure|elemental|recursive)\s+)*subroutine\b", s, re.I))

    def _is_elemental_header(self, s: str) -> bool:
        return bool(re.search(r"\belemental\b", s, re.I))

    @staticmethod
    def _has_value_attribute(attrs):
        return 'value' in {part.strip().lower() for part in split_args(attrs)}

    def _emit_value_dummy_copies(self, args, symbols):
        # Immutable scalars already behave by value. Copy mutable derived-type
        # values as well, so component assignments cannot affect the actual.
        for name in args:
            info = symbols.get(name, {})
            if self._has_value_attribute(info.get('attrs_l', '')):
                self.emit(f'{name} = _xf2p_copy_value({name})')

    def _emit_allocatable_dummy_entry(self, args, symbols):
        # Fortran deallocates an ALLOCATABLE INTENT(OUT) actual on entry,
        # before executing even the first statement of the procedure body.
        for name in args:
            attrs = re.sub(r'\s+', '', symbols.get(name, {}).get('attrs_l', '')).lower()
            attributes = split_args(attrs)
            if 'allocatable' in attributes:
                optional = 'optional' in attributes
                if optional:
                    flag = _choose_fresh_identifier(self._allocation_source, f'_xf2p_present_{name}')
                    self.emit(f'{flag} = {name} is not {self._optional_absent_name}')
                    self._optional_allocatable_presence[name.lower()] = flag
                if 'intent(out)' in attributes:
                    # Preserve the omission sentinel when forwarding an absent
                    # optional dummy to another optional allocatable dummy.
                    if optional:
                        self.emit(f'if {flag}:')
                        self.indent += 1
                    self.emit(f'{name} = None')
                    if optional:
                        self.indent -= 1

    def _optional_dummy_default(self, info):
        attrs = re.sub(r'\s+', '', info.get('attrs_l', '')).lower()
        if 'allocatable' in split_args(attrs):
            return self._optional_absent_name
        return 'None'

    def _scalar_dummy_writes(self, lines, eligible, signatures, symbols):
        """Find direct scalar definitions and copy-back through known CALLs."""
        written = set()

        def mark(target):
            match = re.match(r'^\s*([a-z_]\w*)\s*(?:\(|$)', target, re.I)
            if match and match.group(1).lower() in eligible:
                written.add(match.group(1).lower())

        for code, _comment in lines:
            statement = code.strip()
            if self._parse_decl_line(statement):
                continue
            statement = re.sub(r'^\w+\s*:\s*(?=do\b)', '', statement, flags=re.I)
            conditional = re.match(r'if\s*\(', statement, re.I)
            if conditional:
                closing = find_matching_paren(statement, statement.find('('))
                if closing >= 0:
                    statement = statement[closing + 1:].strip()
            assignment = split_top_level(statement, '=')
            if len(assignment) > 1 and _find_top_level_double_colon(statement) == -1:
                mark(assignment[0].strip())
            loop = re.match(r'do\s+(?:\d+\s+)?([a-z_]\w*)\s*=', statement, re.I)
            if loop:
                mark(loop.group(1))
            call = re.fullmatch(r'call\s+(\w+)\s*(?:\((.*)\))?', statement, re.I)
            if call:
                callee, arguments = call.group(1).lower(), split_args(call.group(2) or '')
                signature = signatures.get(callee)
                if signature and signature['kind'] == 'subroutine':
                    formals = signature['args']
                    for index, actual in enumerate(arguments):
                        keyword = re.fullmatch(r'\s*(\w+)\s*=\s*(.+)', actual)
                        formal = keyword.group(1).lower() if keyword else (formals[index] if index < len(formals) else '')
                        if formal in signature['out']:
                            mark(keyword.group(2) if keyword else actual)
                intrinsic_outputs = {
                    'cpu_time': ('time',) if signature is None and callee not in self._generic_names else (),
                    'random_number': ('harvest',), 'random_seed': ('size', 'get'),
                    'move_alloc': ('from', 'to'),
                    'execute_command_line': ('exitstat', 'cmdstat', 'cmdmsg'),
                    'get_command_argument': ('value', 'length', 'status'),
                }.get(callee, ())
                intrinsic_formals = {
                    'cpu_time': ('time',),
                    'random_number': ('harvest',), 'random_seed': ('size', 'put', 'get'),
                    'move_alloc': ('from', 'to', 'stat', 'errmsg'),
                    'execute_command_line': ('command', 'wait', 'exitstat', 'cmdstat', 'cmdmsg'),
                    'get_command_argument': ('number', 'value', 'length', 'status'),
                }.get(callee, ())
                for index, actual in enumerate(arguments):
                    keyword = re.fullmatch(r'\s*(\w+)\s*=\s*(.+)', actual)
                    formal = keyword.group(1).lower() if keyword else (intrinsic_formals[index] if index < len(intrinsic_formals) else '')
                    if formal in intrinsic_outputs:
                        mark(keyword.group(2) if keyword else actual)
            # Unlike CALL, a function invocation may occur anywhere in an
            # expression. Its scalar definitions still propagate to its caller.
            expression_scan = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"",
                                     lambda match: ' ' * len(match.group()), statement)
            for match in re.finditer(r'\b(\w+)\s*\(', expression_scan):
                signature = signatures.get(match.group(1).lower())
                if not signature or signature['kind'] != 'function' or not signature['out']:
                    continue
                opening = statement.find('(', match.start())
                closing = find_matching_paren(statement, opening)
                if closing < 0:
                    continue
                for index, actual in enumerate(split_args(statement[opening + 1:closing])):
                    keyword = re.fullmatch(r'\s*(\w+)\s*=\s*(.+)', actual)
                    formals = signature['args']
                    formal = keyword.group(1).lower() if keyword else (formals[index] if index < len(formals) else '')
                    if formal in signature['out']:
                        mark(keyword.group(2) if keyword else actual)
            io = re.match(r'(read|write|open|close|rewind)\s*\(', statement, re.I)
            if io:
                closing = find_matching_paren(statement, statement.find('('))
                if closing < 0:
                    continue
                controls = split_args(statement[statement.find('(') + 1:closing])
                if io.group(1).lower() == 'read':
                    for target in split_args(statement[closing + 1:]):
                        mark(target)
                for index, control in enumerate(controls):
                    keyword = re.fullmatch(r'\s*(\w+)\s*=\s*(.+)', control)
                    if keyword and keyword.group(1).lower() in {'iostat', 'iomsg', 'newunit'}:
                        mark(keyword.group(2))
                    if io.group(1).lower() == 'write' and (index == 0 or (keyword and keyword.group(1).lower() == 'unit')):
                        unit = (keyword.group(2) if keyword else control).strip().lower()
                        if symbols.get(unit, {}).get('ftype') == 'character':
                            mark(unit)
        return written

    def _function_scalar_copyback(self, source):
        """Rewrite effectful function results/calls without eager evaluation.

        Inline sequencing keeps calls inside conditions, loop tests and nested
        expressions in their original evaluation position. Only changed source
        spans are replaced, preserving the rest of the generated formatting.
        """
        signatures = {name: spec for name, spec in self._binding_targets.items()
                      if spec['kind'] == 'function' and spec['out']}
        if not signatures:
            return source
        tree = ast.parse(source)
        edits = []
        lines = source.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))

        def position(line, column):
            # AST columns are UTF-8 byte offsets, not Unicode character offsets.
            return offsets[line - 1] + len(lines[line - 1].encode('utf-8')[:column].decode('utf-8'))

        def replace(node, value):
            edits.append((position(node.lineno, node.col_offset),
                          position(node.end_lineno, node.end_col_offset), value))

        def fresh():
            self._allocation_counter += 1
            return _choose_fresh_identifier(source, f'_xf2p_func_{self._allocation_counter}')

        class Calls(ast.NodeTransformer):
            def visit_Call(visitor, node):
                # Capture array-element/component destinations at call entry,
                # rather than recomputing them after other outputs change.
                spec = signatures.get(node.func.id) if isinstance(node.func, ast.Name) else None
                if not spec:
                    return visitor.generic_visit(node)
                actuals = dict(zip(spec['args'], node.args))
                actuals.update({kw.arg: kw.value for kw in node.keywords})
                prefixes, setters = [], []
                for index, formal in enumerate(spec['out'], 1):
                    actual = actuals.get(formal)
                    if actual is None:  # Omitted OPTIONAL dummy.
                        continue
                    if isinstance(actual, ast.Name):
                        setters.append((index, f'{actual.id} := {{value}}'))
                    elif isinstance(actual, (ast.Subscript, ast.Attribute)):
                        base = fresh()
                        prefixes.append(f'({base} := {ast.unparse(visitor.visit(actual.value))})')
                        actual.value = ast.Name(id=base, ctx=ast.Load())
                        if isinstance(actual, ast.Subscript):
                            if isinstance(actual.slice, ast.Slice):
                                raise ValueError('modified scalar function dummy requires a scalar actual, not an array section')
                            key = fresh()
                            prefixes.append(f'({key} := {ast.unparse(visitor.visit(actual.slice))})')
                            actual.slice = ast.Name(id=key, ctx=ast.Load())
                            setters.append((index, f'{base}.__setitem__({key}, {{value}})'))
                        else:
                            setters.append((index, f'setattr({base}, {actual.attr!r}, {{value}})'))
                    else:
                        raise ValueError(f'modified dummy argument of {node.func.id} requires a definable actual, not {ast.unparse(actual)}')
                node = visitor.generic_visit(node)
                result = fresh()
                sequence = prefixes + [f'({result} := {ast.unparse(node)})']
                sequence += ['(' + setter.format(value=f'{result}[{index}]') + ')'
                             for index, setter in setters]
                sequence.append(f'{result}[0]')
                return ast.parse('(' + ', '.join(sequence) + ')[-1]', mode='eval').body

        calls = Calls()

        class Rewrite(ast.NodeVisitor):
            function = None

            def visit_FunctionDef(visitor, node):
                previous = visitor.function
                visitor.function = signatures.get(node.name)
                for statement in node.body:
                    visitor.visit(statement)
                visitor.function = previous

            def visit_Return(visitor, node):
                if node.value is None:
                    return
                value = calls.visit(node.value)
                if visitor.function:
                    outputs = [ast.Name(id=name, ctx=ast.Load()) for name in visitor.function['out']]
                    value = ast.Tuple(elts=[value] + outputs, ctx=ast.Load())
                replace(node.value, ast.unparse(value))

            def visit_Call(visitor, node):
                # Transform an outer call only once, including all nested calls.
                if any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                       and child.func.id in signatures for child in ast.walk(node)):
                    replace(node, ast.unparse(calls.visit(node)))
                else:
                    visitor.generic_visit(node)

        Rewrite().visit(tree)
        for start, stop, value in sorted(edits, reverse=True):
            source = source[:start] + value + source[stop:]
        return source

    def _emit_procedure_return(self):
        self._emit_save_sync()
        if self._current_result_name:
            self.emit(f'return {self._current_result_name}')
        elif self._current_subroutine_outputs:
            self.emit('return ' + ', '.join(self._current_subroutine_outputs))
        else:
            self.emit('return')

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

        extension = re.search(r'\bextends\s*\(\s*([a-z_]\w*)\s*\)', h, re.I)
        parent = extension.group(1).lower() if extension else None
        if parent:
            if parent not in self._component_specs or parent == tname.lower():
                raise ValueError(f'no translated parent type for {tname}: {parent}')
            bindings.update(self._type_bindings.get(parent, {}))
            components.update(self._type_components.get(parent, {}))
            component_specs.update(self._component_specs[parent])
            components[parent] = parent
            component_specs[parent] = {'ftype': 'type', 'shape': None,
                                      'type_name': parent, 'attrs_l': '', 'char_len': None}
            parent_class = next(name for name in self._derived_types if name.lower() == parent)
            self.emit(f'@_f_extended_type({parent!r}, {parent_class}, bindings={tuple(bindings)!r})')

        self.emit("@dataclass")
        self.emit(f"class {tname}:")
        self.indent += 1
        had_field = bool(parent)
        if parent:
            self.emit(f'{parent}: {parent_class} = field(default_factory={parent_class})')
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
                    formals = [object_arg] + [a + ('=' + (self._optional_absent_name if a in spec.get('optional_allocatable', set()) else 'None')
                                                   if a in spec['optional'] else '') for a in args]
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
                if parent and name.lower() in component_specs:
                    raise ValueError(f'component {tname}%{name} conflicts with inherited component')
                component_specs[name.lower()] = {"ftype": ftype, "shape": shape,
                    "type_name": type_name.lower() if type_name else None,
                    "attrs_l": attrs_l,
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

    def _set_allocatable_array_bounds(self, name, rank):
        self._decl_lbounds[name.lower()] = [f'_f_array_lbound({name}, {d+1})' for d in range(rank)]
        self._decl_ubounds[name.lower()] = [f'_f_array_ubound({name}, {d+1})' for d in range(rank)]

    def _register_allocatable_array_bounds(self, symbols):
        for name, info in symbols.items():
            if (info.get('is_array') and info.get('shape') is not None
                    and any(attr in info.get('attrs_l', '') for attr in ('allocatable', 'pointer'))):
                self._set_allocatable_array_bounds(name, len(self._shape_bounds(info['shape'])))

    def _decl_bound_expr(self, name: str, dim0: int, which: str, arrays_1d: set[str]) -> str | None:
        key = name.split(".", 1)[0].lower()
        src = self._decl_lbounds if which == "lo" else self._decl_ubounds
        vals = src.get(key)
        if "." in name:
            spec = self._component_spec(name)
            if spec and spec.get('shape') and 'pointer' in spec.get('attrs_l', ''):
                helper = '_f_array_lbound' if which == 'lo' else '_f_array_ubound'
                return f'{helper}({self.translate_expr(name, arrays_1d)}, {dim0+1})'
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

    def _cartesian_array_reference(self, name, parts, arrays_1d, bounds_name=None):
        bounds_name = bounds_name or name
        array_expr = self.translate_expr(bounds_name, arrays_1d) if bounds_name != name else name
        indices = []
        for axis, part in enumerate(parts):
            if len(split_top_level(part, ':', preserve_empty=True)) > 1:
                lo, hi = self._split_section(part)
                section = self._slice_expr_from_decl_bounds(bounds_name, lo, hi, axis, arrays_1d)
                endpoints = split_top_level(section, ':', preserve_empty=True)
                if len(endpoints) == 2:
                    section = f"slice({endpoints[0] or 'None'}, {endpoints[1] or 'None'})"
                indices.append(section)
            else:
                indices.append(self._index_expr_from_decl_bounds(bounds_name, part, axis, arrays_1d))
        return f"{name}[_f_array_indices({array_expr}, {', '.join(indices)})]"

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

    def _integer_model_kind(self, expr: str, arrays_1d: set[str]) -> str | None:
        """Recover INTEGER model kind without evaluating the argument value."""
        raw = expr.strip()
        literal = re.fullmatch(r"[+-]?\d+(?:_([a-z_]\w*|\d+))?", raw, re.I)
        if literal:
            return self.translate_expr(literal.group(1), arrays_1d) if literal.group(1) else "4"

        def declared_kind(reference):
            if "." in reference or "%" in reference:
                info = self._component_spec(reference)
            else:
                name = reference.lower()
                info = next((symbols[name] for symbols, _ in reversed(self._host_scopes)
                             if name in symbols), None)
            if not info or info.get("ftype") != "integer":
                return None
            attrs = info.get("attrs_l", "").strip()
            if attrs.startswith("("):
                closing = find_matching_paren(attrs, 0)
                selector = attrs[1:closing].strip()
                selector = re.sub(r"^kind\s*=\s*", "", selector, flags=re.I)
                return self.translate_expr(selector, arrays_1d)
            legacy = re.match(r"\*\s*(\d+)", attrs)
            return legacy.group(1) if legacy else "4"

        # Retain kind suffixes inside arithmetic rather than letting expression
        # translation discard them. Placeholders are private to this analysis.
        kinds = {}
        def typed_literal(match):
            name = f"_xf2p_model_literal_{len(kinds)}"
            kinds[name] = self.translate_expr(match.group(1), arrays_1d)
            return name
        prepared = re.sub(r"(?<![\w.])\d+_([a-z_]\w*|\d+)\b", typed_literal, raw, flags=re.I)
        try:
            tree = ast.parse(self.translate_expr(prepared, arrays_1d), mode="eval").body
        except SyntaxError:
            return None

        def reference_name(node):
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                parent = reference_name(node.value)
                return f"{parent}.{node.attr}" if parent else None
            if isinstance(node, ast.Subscript):
                return reference_name(node.value)
            return None

        def infer(node):
            if isinstance(node, ast.Name):
                return kinds.get(node.id) or declared_kind(node.id)
            if isinstance(node, ast.Constant):
                return "4" if type(node.value) is int else None
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                return infer(node.operand)
            if isinstance(node, (ast.Subscript, ast.Attribute)):
                reference = reference_name(node)
                return declared_kind(reference) if reference else None
            if isinstance(node, ast.BinOp):
                left, right = infer(node.left), infer(node.right)
                if left and right:
                    return f"max({left}, {right})"
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "_xf2p_div":
                left, right = (infer(arg) for arg in node.args)
                if left and right:
                    return f"max({left}, {right})"
            if isinstance(node, ast.Call) and ast.unparse(node.func) in {"_f_maxval", "_f_minval"}:
                explicit = next((kw.value for kw in node.keywords if kw.arg == "integer_kind"), None)
                return ast.unparse(explicit) if explicit is not None else infer(node.args[0])
            if isinstance(node, ast.Call) and ast.unparse(node.func) == '_f_bit_size':
                return ast.unparse(node.args[0])
            return None
        return infer(tree)

    def _translate_model_inquiry(self, name, inner, arrays_1d):
        argument = _bind_intrinsic_arguments(name, inner, ("x",), 1)["x"]
        kind = self._integer_model_kind(argument, arrays_1d)
        if kind is not None:
            return f"_f_numeric_model(None, {name!r}, integer_kind={kind})"
        return f"_f_numeric_model({self.translate_expr(argument, arrays_1d)}, {name!r})"

    def _numeric_declared_kind(self, info, symbols=None):
        if info.get('ftype') not in {'integer', 'real', 'complex'}:
            return None
        return self._declared_value_kind(info, symbols)

    def _declared_value_kind(self, info, symbols=None):
        if info.get('ftype') not in {'integer', 'real', 'complex', 'logical', 'character'}:
            return None
        attrs = info.get('attrs_l', '').strip()
        kind = '1' if info['ftype'] == 'character' else '4'
        if attrs.startswith('('):
            closing = find_matching_paren(attrs, 0)
            selectors = split_args(attrs[1:closing])
            named = next((re.match(r'\s*kind\s*=\s*(.+)', part, re.I) for part in selectors
                          if re.match(r'\s*kind\s*=', part, re.I)), None)
            if named:
                kind = named.group(1)
            elif info['ftype'] == 'character':
                if len(selectors) > 1 and '=' not in selectors[1]:
                    kind = selectors[1].strip()
            else:
                kind = selectors[0].strip()
        elif info['ftype'] != 'character':
            legacy = re.match(r'\*\s*(\d+)', attrs)
            if legacy:
                kind = legacy.group(1)
        visible = {name: value for scope, _ in self._host_scopes for name, value in scope.items()}
        visible.update(symbols or {})
        # A specific's local kind parameters are not Python globals visible
        # to the generic wrapper. Inline their constant definitions instead.
        for _ in range(len(visible) + 1):
            previous = kind
            for name, value in visible.items():
                if 'parameter' in value.get('attrs_l', '') and value.get('init') is not None:
                    kind = _replace_identifier_outside_strings(kind, name, '(' + str(value['init']) + ')')
            if kind == previous:
                break
        return self.translate_expr(kind, set())

    def _expression_call_model(self, name, inner, arrays):
        """Infer an intrinsic/procedure result without evaluating its arguments."""
        name = name.lower()
        if name in self._function_result_models:
            return self._function_result_models[name]
        if name in self._generic_names:
            return None
        parts = split_args(inner)
        positional, keywords = [], {}
        for part in parts:
            keyword = re.match(r'\s*([a-z_]\w*)\s*=(?!=)\s*(.*)', part, re.I)
            if keyword:
                keywords[keyword.group(1).lower()] = keyword.group(2)
            else:
                positional.append(part)
        def argument(index=0):
            if index < len(positional):
                return positional[index]
            keys = {'matmul': ('matrix_a', 'matrix_b'),
                    'dot_product': ('vector_a', 'vector_b'),
                    'reshape': ('source',), 'transpose': ('matrix',),
                    'merge': ('tsource',), 'spread': ('source',),
                    'all': ('mask',), 'any': ('mask',)}.get(name, ('a', 'x', 'z', 'array', 'source', 'string'))
            if name in {'matmul', 'dot_product'}:
                return keywords.get(keys[index])
            return next((keywords[key] for key in keys if key in keywords), None)
        def first_model():
            raw = argument()
            return self._generic_expression_model(raw, arrays) if raw is not None else None
        if name == 'kind':
            return ('integer', '4')
        if name == '_f_bit_size':
            return ('integer', self.translate_expr(inner, arrays))
        if name == 'bit_size':
            raw = _bind_intrinsic_arguments('bit_size', inner, ('i',), 1)['i']
            model = self._generic_expression_model(raw, arrays)
            return model if model and model[0] == 'integer' else None
        if name in {'int', 'nint', 'ceiling', 'floor', 'size', 'shape', 'lbound', 'ubound',
                    'count', 'len', 'len_trim', 'index', 'scan', 'verify', 'maxloc', 'minloc',
                    'selected_int_kind', 'selected_real_kind', 'selected_char_kind',
                    'digits', 'range', 'radix', 'precision', 'exponent'}:
            kind = keywords.get('kind')
            if name in {'int', 'nint', 'ceiling', 'floor'} and len(positional) > 1:
                kind = positional[1]
            return ('integer', self.translate_expr(kind, arrays) if kind else '4')
        if name in {'real', 'cmplx', 'logical'}:
            kind = keywords.get('kind')
            kind_position = 2 if name == 'cmplx' else 1
            if len(positional) > kind_position:
                kind = positional[kind_position]
            family = {'real': 'real', 'cmplx': 'complex', 'logical': 'logical'}[name]
            if kind:
                return (family, self.translate_expr(kind, arrays))
            model = first_model() if name == 'real' else None
            return (family, model[1] if model and model[0] == 'complex' else '4')
        if name == 'dble':
            return ('real', '8')
        if name == 'dprod':
            return ('real', '8')
        if name in {'aint', 'anint'}:
            model = first_model()
            kind = keywords.get('kind') or (positional[1] if len(positional) > 1 else None)
            return ('real', self.translate_expr(kind, arrays)) if kind else model
        if name in {'min', 'max'}:
            arguments = positional or list(keywords.values())
            result = None
            for raw in arguments:
                model = self._generic_expression_model(raw, arrays)
                if model is None:
                    return None
                result = model if result is None else self._combine_expression_models(result, model)
            return result
        if name in {'matmul', 'dot_product'}:
            raw1, raw2 = argument(), argument(1)
            left = self._generic_expression_model(raw1, arrays) if raw1 else None
            right = self._generic_expression_model(raw2, arrays) if raw2 else None
            if name == 'matmul' and left and right and left[0] == right[0] == 'logical':
                return ('logical', '4')
            return self._combine_expression_models(left, right)
        if name in {'all', 'any'}:
            return first_model()
        if name in {'allocated', 'associated', 'present', 'btest', 'is_contiguous'}:
            return ('logical', '4')
        if name in {'achar', 'char'}:
            kind = keywords.get('kind') or (positional[1] if len(positional) > 1 else None)
            return ('character', self.translate_expr(kind, arrays) if kind else '1')
        if name in {'abs', 'aimag', 'conjg', 'sqrt', 'exp', 'log', 'log10', 'sin', 'cos', 'tan',
                    'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh', 'aint', 'anint', 'sum', 'product',
                    'maxval', 'minval', 'transpose', 'reshape', 'trim', 'adjustl', 'adjustr',
                    'mod', 'modulo', 'sign', 'dim', 'atan2', 'merge', 'pack', 'unpack', 'spread',
                    'cshift', 'eoshift', 'huge', 'tiny', 'epsilon', 'spacing', 'rrspacing',
                    'fraction', 'scale', 'set_exponent', 'nearest'}:
            model = first_model()
            if model and name in {'abs', 'aimag'} and model[0] == 'complex':
                return ('real', model[1])
            return model
        return None

    @staticmethod
    def _combine_expression_models(left, right):
        if not left or not right:
            return None
        if left[0] == right[0]:
            return left if left[1] == right[1] else (left[0], f'max({left[1]}, {right[1]})')
        if left[0] == 'integer':
            return right
        if right[0] == 'integer':
            return left
        if {left[0], right[0]} == {'real', 'complex'}:
            return ('complex', f'max({left[1]}, {right[1]})')
        return None

    def _generic_expression_model(self, expression, arrays):
        """Recover intrinsic type/kind before literal kind information is erased."""
        expression = expression.strip()
        if expression.startswith('(') and find_matching_paren(expression, 0) == len(expression) - 1:
            components = split_args(expression[1:-1])
            if len(components) == 2:
                models = [self._generic_expression_model(part, arrays) for part in components]
                if all(model and model[0] in {'integer', 'real'} for model in models):
                    kinds = [model[1] if model[0] == 'real' else '4' for model in models]
                    return ('complex', kinds[0] if kinds[0] == kinds[1] else f'max({kinds[0]}, {kinds[1]})')
        char_literal = re.fullmatch(r"([a-z_]\w*|\d+)_(?:'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\")", expression, re.I)
        if char_literal:
            return ('character', self.translate_expr(char_literal.group(1), arrays))
        models = {}
        def placeholder(model):
            name = f'_xf2p_kind_literal_{len(models)}'
            models[name] = model
            return name
        # Model nested calls before translating them: e.g. REAL(x,KIND=8)
        # currently loses its KIND selector in the executable translation.
        call_pattern = re.compile(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"|\b([a-z_]\w*)\s*\(", re.I)
        chunks, cursor = [], 0
        while match := call_pattern.search(expression, cursor):
            chunks.append(expression[cursor:match.start()])
            if match.group(1):
                opening = expression.find('(', match.start())
                closing = find_matching_paren(expression, opening)
                if closing < 0:
                    return None
                model = self._expression_call_model(match.group(1), expression[opening+1:closing], arrays)
                if model:
                    chunks.append(placeholder(model))
                    cursor = closing + 1
                    continue
            chunks.append(match.group())
            cursor = match.end()
        expression = ''.join(chunks) + expression[cursor:]
        number = re.compile(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"|"
                            r"(?P<logical>\.(?:true|false)\.)(?:_(?P<logical_kind>[a-z_]\w*|\d+))?|"
                            r"(?<![\w.])(?P<num>(?:\d+(?:\.\d*)?|\.\d+)(?:[ed][+-]?\d+)?)"
                            r"(?:_(?P<kind>[a-z_]\w*|\d+))?", re.I)
        def literal(match):
            if match.group('logical'):
                kind = match.group('logical_kind')
                return placeholder(('logical', self.translate_expr(kind, arrays) if kind else '4'))
            if match.group('num') is None:
                return match.group()
            text = match.group('num').lower()
            family = 'real' if any(c in text for c in '.ed') else 'integer'
            kind = self.translate_expr(match.group('kind'), arrays) if match.group('kind') else ('8' if 'd' in text else '4')
            return placeholder((family, kind))
        prepared = number.sub(literal, expression)
        try:
            tree = ast.parse(self.translate_expr(prepared, arrays), mode='eval').body
        except (SyntaxError, ValueError):
            return None

        def reference(node):
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                base = reference(node.value)
                return base + '.' + node.attr if base else None
            if isinstance(node, ast.Subscript):
                return reference(node.value)

        combine = self._combine_expression_models

        def infer(node):
            if isinstance(node, ast.Name) and node.id in models:
                return models[node.id]
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    return ('character', '1')
                if isinstance(node.value, bool):
                    return ('logical', '4')
            name = reference(node)
            if name:
                info = self._component_spec(name) if '.' in name else next(
                    (scope[name.lower()] for scope, _ in reversed(self._host_scopes) if name.lower() in scope), None)
                kind = self._declared_value_kind(info) if info else None
                return (info['ftype'], kind) if kind else None
            if isinstance(node, ast.UnaryOp):
                return infer(node.operand)
            if isinstance(node, ast.BinOp):
                left, right = infer(node.left), infer(node.right)
                return (left if isinstance(node.op, ast.Pow) and left and left[0] in {'real', 'complex'}
                        and right and right[0] == 'integer' else combine(left, right))
            if isinstance(node, ast.Compare):
                operands = [infer(node.left)] + [infer(value) for value in node.comparators]
                if all(model and model[0] == 'logical' for model in operands):
                    # EQV/NEQV are translated as comparisons, but retain the
                    # logical operands' kind rather than default LOGICAL.
                    result = operands[0]
                    for model in operands[1:]:
                        result = combine(result, model)
                    return result
                return ('logical', '4')
            if isinstance(node, ast.BoolOp):
                result = infer(node.values[0])
                for value in node.values[1:]:
                    result = combine(result, infer(value))
                return result
            if isinstance(node, ast.List):
                result = None
                for value in node.elts:
                    model = infer(value)
                    if model is None:
                        return None
                    result = model if result is None else combine(result, model)
                return result
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name in {'np.asarray', 'np.array', '_xf2p_div', '_xf2p_min', '_xf2p_max', '_xf2p_concat'}:
                    result = infer(node.args[0]) if node.args else None
                    for arg in node.args[1:]:
                        result = combine(result, infer(arg))
                    return result
                if name in {'np.sqrt', 'np.exp', 'np.log', 'np.sin', 'np.cos', 'np.abs', 'np.sum', '_f_reshape', '_f_maxval', '_f_minval'}:
                    return infer(node.args[0]) if node.args else None
                if name == '_xf2p_real':
                    return ('real', '4')
                if name == '_xf2p_cmplx':
                    # Intrinsic CMPLX calls were modeled before translation;
                    # remaining calls come from complex literal syntax.
                    kinds = []
                    for arg in node.args:
                        model = infer(arg)
                        if not model:
                            return None
                        kinds.append(model[1] if model[0] == 'real' else '4')
                    return ('complex', kinds[0] if len(set(kinds)) == 1 else f'max({", ".join(kinds)})') if kinds else None
                return self._function_result_models.get(name.lower())
        return infer(tree)

    def _translate_bit_size_inquiry(self, inner, arrays):
        argument = _bind_intrinsic_arguments('bit_size', inner, ('i',), 1)['i']
        model = self._generic_expression_model(argument, arrays)
        if model is None or model[0] != 'integer':
            raise ValueError(f'BIT_SIZE requires an argument with a known Fortran integer type/kind: {argument}')
        return f'_f_bit_size({model[1]})'

    def _translate_kind_inquiry(self, inner, arrays):
        argument = _bind_intrinsic_arguments('kind', inner, ('x',), 1)['x']
        model = self._generic_expression_model(argument, arrays)
        if model is None:
            raise ValueError(f'cannot determine Fortran KIND of expression: {argument}')
        # KIND is an inquiry: do not evaluate an unallocated array, invalid
        # subscript, or side-effecting function merely to discover its type.
        return f'({model[1]})'

    def _translate_generic_call(self, name, inner, arrays):
        parts = split_args(inner)
        # Calls already translated by an enclosing expression must not be tagged twice.
        if any(re.match(rf'\s*{re.escape(self._generic_kind_keyword)}\s*=', p) for p in parts):
            return f'{name}({inner})'
        arguments, kinds = [], []
        for part in parts:
            keyword = re.match(r'^\s*([a-z_]\w*)\s*=(?!=)\s*(.*)$', part, re.I)
            raw = keyword.group(2) if keyword else part
            model = self._generic_expression_model(raw, arrays)
            kinds.append(model[1] if model else '-1')
            value = self.translate_expr(raw, arrays)
            arguments.append((keyword.group(1) + '=' if keyword else '') + value)
        arguments.append(f'{self._generic_kind_keyword}=[{", ".join(kinds)}]')
        return f'{name}({", ".join(arguments)})'

    def _pointer_initializer_expr(self, target, arrays_1d, symbols):
        # Initializers are emitted before the executable pass installs the
        # scope's declaration bounds. Use local bounds, not a previous scope's.
        previous_lower, previous_upper = self._decl_lbounds, self._decl_ubounds
        local_names = {name.lower() for name in symbols}
        self._decl_lbounds = {**{name: value for name, value in previous_lower.items()
                                if name not in local_names}, **{
            name.lower(): [lo for lo, _ in self._shape_bounds(info['shape'])]
            for name, info in symbols.items() if info.get('shape') is not None}}
        self._decl_ubounds = {**{name: value for name, value in previous_upper.items()
                                if name not in local_names}, **{
            name.lower(): [hi for _, hi in self._shape_bounds(info['shape'])]
            for name, info in symbols.items() if info.get('shape') is not None}}
        self._register_allocatable_array_bounds(symbols)
        try:
            return self._pointer_association_expr(target, arrays_1d)
        finally:
            self._decl_lbounds, self._decl_ubounds = previous_lower, previous_upper

    def _pointer_association_expr(self, target, arrays_1d, lower=None, rank=None):
        rhs = self._translate_pointer_target(target, arrays_1d)
        # A whole target retains its bounds; a section/expression has lower
        # bounds one. Pointer bounds must never overwrite the target's metadata.
        if lower is None and re.fullmatch(r'[a-z_]\w*(?:%[a-z_]\w*)*', target, re.I):
            name = target.replace('%', '.')
            spec = self._component_spec(name) if '.' in name else None
            count = (len(self._shape_bounds(spec['shape'])) if spec and spec.get('shape')
                     else len(self._decl_lbounds.get(name.lower(), [])))
            if count:
                lower = [self._decl_bound_expr(name, axis, 'lo', arrays_1d) or '1'
                         for axis in range(count)]
        args = [rhs]
        if lower is not None:
            args.append('lower=[' + ', '.join(lower) + ']')
        if rank is not None:
            args.append(f'rank={rank}')
        return '_f_pointer_associate(' + ', '.join(args) + ')'

    def _translate_pointer_target(self, expr: str, arrays_1d: set[str]) -> str:
        """Keep a scalar array element as a storage view, not a NumPy scalar."""
        translated = self.translate_expr(expr, arrays_1d)
        node = ast.parse(translated, mode='eval').body
        if not isinstance(node, ast.Subscript):
            return translated

        def index_text(index):
            if isinstance(index, ast.Slice):
                return 'slice(' + ', '.join(ast.unparse(value) if value is not None else 'None'
                                           for value in (index.lower, index.upper, index.step)) + ')'
            if isinstance(index, ast.Tuple):
                return '(' + ', '.join(index_text(value) for value in index.elts) + ',)'
            return ast.unparse(index)

        return f'_f_pointer_target({ast.unparse(node.value)}, {index_text(node.slice)})'

    def translate_expr(self, expr: str, arrays_1d: set[str]) -> str:
        s = expr.strip()
        keyword = re.match(r"^([a-z_]\w*)\s*=(?!=)\s*(.+)$", s, re.I)
        if keyword:
            return f"{keyword.group(1)}={self.translate_expr(keyword.group(2), arrays_1d)}"
        inquiry_pattern = re.compile(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"|\b(kind|bit_size)\s*\(", re.I)
        chunks, cursor = [], 0
        while match := inquiry_pattern.search(s, cursor):
            chunks.append(s[cursor:match.start()])
            name = match.group(1).lower() if match.group(1) else None
            shadowed = name in self._binding_targets or any(name in scope for scope, _ in self._host_scopes)
            if name and not shadowed:
                opening = s.find('(', match.start())
                closing = find_matching_paren(s, opening)
                if closing < 0:
                    raise ValueError(f'unbalanced {name.upper()} inquiry')
                translator = self._translate_kind_inquiry if name == 'kind' else self._translate_bit_size_inquiry
                chunks.append(translator(s[opening+1:closing], arrays_1d))
                cursor = closing + 1
            else:
                chunks.append(match.group())
                cursor = match.end()
        s = ''.join(chunks) + s[cursor:]
        generic_pattern = re.compile(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"|\b([a-z_]\w*)\s*\(", re.I)
        generic_out, generic_cursor = [], 0
        while match := generic_pattern.search(s, generic_cursor):
            generic_out.append(s[generic_cursor:match.start()])
            if match.group(1) and match.group(1).lower() in self._generic_names:
                opening = s.find('(', match.start())
                closing = find_matching_paren(s, opening)
                if closing < 0:
                    raise ValueError('unbalanced generic call')
                generic_out.append(self._translate_generic_call(match.group(1), s[opening+1:closing], arrays_1d))
                generic_cursor = closing + 1
            else:
                generic_out.append(match.group())
                generic_cursor = match.end()
        s = ''.join(generic_out) + s[generic_cursor:]
        # Bit widths and integer models must be recovered before kind suffixes
        # are removed. Scan nested calls too, without matching string contents.
        bit_pattern = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|"
            r"\b(btest|ibset|ibclr|ibits|iand|ior|ieor|shiftl|shiftr|huge|digits|range|radix)\s*\(", re.I)
        out, cursor = [], 0
        while match := bit_pattern.search(s, cursor):
            out.append(s[cursor:match.start()])
            if match.group(1):
                opening = s.find('(', match.start())
                closing = find_matching_paren(s, opening)
                if closing < 0:
                    raise ValueError('unbalanced intrinsic call')
                name = match.group(1).lower()
                translator = self._translate_model_inquiry if name in {"huge", "digits", "range", "radix"} else self._translate_bit_call
                out.append(translator(name, s[opening + 1:closing], arrays_1d))
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
                   r"\.(true|false)\.(?:_(?:[a-z_]\w*|\d+))?|"
                   r"\.(eqv|neqv|eq|ne|lt|le|gt|ge|and|or|not)\.",
                   lambda m: operators[(m.group(1) or m.group(2)).lower()] if m.group(1) or m.group(2) else m.group(),
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
        s = re.sub(r"\bpresent\s*\(\s*([a-z_]\w*)\s*\)",
                   lambda match: '(' + self._optional_allocatable_presence.get(match.group(1).lower(),
                                       match.group(1) + ' is not None') + ')', s, flags=re.I)
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
                axis_expr = None
                mask_expr = None
                for ptxt in parts[1:]:
                    mk = re.match(r"^([a-z_]\w*)\s*=\s*(.+)$", ptxt, re.I)
                    if mk:
                        key = mk.group(1).lower()
                        val = mk.group(2).strip()
                        if key == "dim":
                            dim_expr = val
                        elif key == "axis":
                            # Recursive translation can revisit an already
                            # lowered SUM. Keep its zero-based NumPy axis.
                            axis_expr = val
                        elif key == "mask":
                            mask_expr = val
                    elif dim_expr is None:
                        dim_expr = ptxt
                if mask_expr is not None:
                    arr_eff = f"np.where({mask_expr}, {arr}, 0.0)"
                else:
                    arr_eff = arr
                if dim_expr is not None:
                    axis_expr = f"({dim_expr}) - 1"
                if axis_expr is not None:
                    repl = f"np.sum({arr_eff}, axis={axis_expr})"
                else:
                    repl = f"np.sum({arr_eff})"
                out.append(repl)
                i = p1 + 1
            return "".join(out)

        s = _rewrite_np_sum_calls(s)

        def _translate_special_call(name: str, inner: str) -> str | None:
            lname = name.lower()
            if lname == 'dprod' and (lname in self._binding_targets
                    or any(lname in scope for scope, _ in self._host_scopes)):
                return None
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
                bound = {k: (self._translate_pointer_target(v, arrays_1d)
                             if lname == 'associated' else self.translate_expr(v, arrays_1d))
                         for k, v in raw.items()}
                if lname in {"maxval", "minval"}:
                    arguments = [bound["array"]]
                    arguments.extend(f"{k}={bound[k]}" for k in ("dim", "mask") if k in bound)
                    kind = self._integer_model_kind(raw["array"], arrays_1d)
                    if kind is not None:
                        arguments.append(f"integer_kind={kind}")
                    return f"_f_{lname}({', '.join(arguments)})"
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
                component = self._component_spec(base_raw) if '.' in base_raw else None
                if (component and component.get('shape') and 'pointer' in component.get('attrs_l', '')
                        and re.fullmatch(r'[a-z_]\w*(?:\([^()]*\))?(?:\.[a-z_]\w*)+', base_raw, re.I)):
                    helper = '_f_array_lbound' if lname == 'lbound' else '_f_array_ubound'
                    return f'{helper}({base_py}' + (f', dim={dim_py})' if dim_py is not None else ')')
                if re.fullmatch(r"[a-z_]\w*(?:\.[a-z_]\w*)*", base_raw, flags=re.I):
                    key = base_raw.split(".", 1)[0].lower()
                    vals = self._decl_lbounds.get(key) if lname == "lbound" else self._decl_ubounds.get(key)
                    if vals:
                        helper = '_f_array_lbound' if lname == 'lbound' else '_f_array_ubound'
                        if '.' not in base_raw and all(str(value).startswith(helper + '(') for value in vals):
                            return f'{helper}({base_py}' + (f', dim={dim_py})' if dim_py is not None else ')')
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
                                out.append(self._cartesian_array_reference(name, parts, arrays_1d, full_name))
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
                    spec = self._component_spec(name)
                    if spec and spec.get('shape'):
                        raise ValueError('array components of an array parent require explicit subscripts')
                    dtype = _type_dtype.get(spec['ftype']) if spec else None
                    argument = f', dtype={dtype}' if dtype else ''
                    out.append(f"_xf2p_component_array({root_name}, {path_name!r}{argument})")
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
        # Indexed arrays may retain rank through vector subscripts even
        # without a colon. NumPy's elementwise conversion also handles a
        # scalar RHS for either scalar-element or section assignment.
        if is_array:
            return f"np.asarray({rhs_py}, dtype=int)"
        return f"int({rhs_py})"

    def _character_assignment_rhs(self, rhs_py: str, length: str, arrays_1d: set[str], *, deferred_array: bool = False) -> str:
        if str(length).strip() == ":":
            if deferred_array:
                raise ValueError("deferred-length CHARACTER array assignment is not yet supported")
            # Intrinsic assignment to an allocatable scalar acquires the RHS LEN.
            return rhs_py
        return f"_f_str_assign({rhs_py}, {self.translate_expr(str(length), arrays_1d)})"

    def transpile_assignment(self, lhs: str, rhs_py: str, arrays_1d: set[str]) -> None:
        if self._where_masked_assignment(lhs, rhs_py, arrays_1d):
            return
        # An array expression/section has one-based bounds. A whole-array
        # variable uses the bounds of its current Fortran association, which
        # may differ from the allocation bounds stored on the NumPy object.
        rhs_lower = '1'
        if re.fullmatch(r'[a-z_]\w*', rhs_py, re.I) and rhs_py.lower() in self._decl_lbounds:
            lows = [self._decl_bound_expr(rhs_py, d, 'lo', arrays_1d) or '1'
                    for d in range(len(self._decl_lbounds[rhs_py.lower()]))]
            rhs_lower = '[' + ', '.join(lows) + ']'
        lhs = lhs.replace("%", ".")
        if self._assign_projected_component(lhs, rhs_py, arrays_1d):
            return
        if self._is_chained_subscript(lhs):
            target = self.translate_expr(lhs, arrays_1d)
            spec = self._component_spec(lhs)
            whole_array = bool(spec and spec.get("shape") and not lhs.rstrip().endswith(")"))
            if spec and spec["ftype"] == "integer":
                rhs_py = f"np.asarray({rhs_py}, dtype=int)" if whole_array or ":" in lhs else f"int({rhs_py})"
            if spec and spec.get("char_len") is not None:
                rhs_py = self._character_assignment_rhs(rhs_py, spec['char_len'], arrays_1d,
                                                        deferred_array=bool(spec.get('shape')))
            value = f"_f_assign_array({target}, {rhs_py})" if whole_array else f"_xf2p_copy_value({rhs_py})"
            self.emit(f"{target} = {value}")
            return
        mb = re.match(r"\s*([A-Za-z_]\w*)", lhs)
        lhs_base = mb.group(1).lower() if mb else lhs.split(".", 1)[0].strip().lower()
        rhs_py = self._integer_assignment_rhs(lhs, rhs_py, arrays_1d)
        char_len_raw = self._decl_char_len.get(lhs_base)
        if char_len_raw is not None:
            if char_len_raw == ":" and lhs_base in self._decl_pointer:
                raise ValueError("deferred-length CHARACTER pointer assignment is not yet supported")
            if char_len_raw == "*" and lhs_base not in arrays_1d:
                # Assumed-length scalar dummies retain the actual argument's LEN.
                rhs_py = f"_f_str_assign({rhs_py}, len({lhs_base}))"
            else:
                rhs_py = self._character_assignment_rhs(rhs_py, char_len_raw, arrays_1d,
                                                        deferred_array=lhs_base in arrays_1d)
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
                    target = self._cartesian_array_reference(name, parts, arrays_1d)
                    self.emit(f"{target} = {rhs_py}")
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
                self.emit(f"{lhs} = _f_assign_array({lhs}, {rhs_py}, lower_bounds={rhs_lower})")
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
            self._emit_procedure_return()
            return
        if "=" in s and _find_top_level_double_colon(s) == -1:
            lhs, rhs = s.split("=", 1)
            lhs = lhs.strip()
            rhs_py = self.translate_expr(rhs, arrays_1d)
            if lhs in arrays_1d and rhs_py in ("True", "False") and not self._where_stack:
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

            if info.get('data_initialized'):
                self.emit(f"{name} = {self._data_init_expr(info, arrays_1d)}")
                continue

            # Arrays
            if is_array:
                # Pointer arrays: start disassociated (None) unless explicitly initialized.
                if is_ptr:
                    if init is None or re.match(r"^null\s*\(\s*\)\s*$", str(init), re.I):
                        self.emit(f"{name} = None")
                    else:
                        init_py = self._pointer_initializer_expr(str(init), arrays_1d, sym)
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
                    initializer = self.translate_expr(str(init), arrays_1d) if init is not None else f"{ftype_name or 'SimpleNamespace'}()"
                    self.emit(f"{name} = _f_init_component_array({shape_py}, {initializer}, object)")
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
                    if init is None:
                        self.emit(f"{name} = {cls}()")
                    else:
                        init_py = self.translate_expr(str(init), arrays_1d)
                        self.emit(f"{name} = _xf2p_copy_value({init_py})")
                continue

            # Pointer scalars start disassociated unless explicitly initialized.
            if is_ptr:
                if init is None or re.match(r"^null\s*\(\s*\)\s*$", str(init), re.I):
                    self.emit(f"{name} = None")
                else:
                    init_py = self._pointer_initializer_expr(str(init), arrays_1d, sym)
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
        component = self._component_spec(name_raw)
        if root not in arrays_1d and not (component and component.get('shape')):
            return None
        if ":" in idx_raw:
            return None
        name_py = name_raw.replace("%", ".")
        parts = []
        for axis, index in enumerate(split_args(idx_raw)):
            index_py = self._index_expr_from_decl_bounds(name_py, index, axis, arrays_1d)
            parts.append(f'({index_py}):(({index_py}) + 1)')
        return f"{name_py}[{', '.join(parts)}].reshape(())"

    def _associate_alias_metadata(self, selector: str, arrays_1d: set[str]) -> tuple[bool, bool, str | None]:
        sel = selector.strip()
        mm_name = re.fullmatch(r"[a-z_]\w*(?:%[a-z_]\w*)*", sel, re.I)
        if mm_name:
            root = sel.split("%", 1)[0].lower()
            component = self._component_spec(sel)
            is_array = root in arrays_1d or bool(component and component.get('shape'))
            return True, is_array, root
        mm = re.match(r"^([a-z_]\w*(?:%[a-z_]\w*)*)\s*\((.*)\)\s*$", sel, re.I)
        if mm:
            root = mm.group(1).split("%", 1)[0].lower()
            component = self._component_spec(mm.group(1))
            if root not in arrays_1d and not (component and component.get('shape')):
                return False, False, None
            idx = mm.group(2).strip()
            is_array = any(':' in part or part.strip().lower() in arrays_1d
                           for part in split_args(idx))
            return True, is_array, root
        return False, False, None

    def _associate_expression_array_type(self, expression):
        """Recognize array-valued arithmetic selectors without making aliases."""
        def infer(node):
            if isinstance(node, ast.Name):
                return self._decl_array_types.get(node.id.lower())
            if isinstance(node, ast.Attribute):
                component = self._component_spec(ast.unparse(node))
                return component['ftype'] if component and component.get('shape') else None
            if isinstance(node, ast.BinOp):
                return infer(node.left) or infer(node.right)
            if isinstance(node, ast.UnaryOp):
                return infer(node.operand)
            if isinstance(node, ast.Subscript) and any(isinstance(child, ast.Slice) for child in ast.walk(node.slice)):
                return infer(node.value)
            return None
        node = ast.parse(expression, mode='eval').body
        result = infer(node)
        if result == 'integer' and any(isinstance(child, ast.Constant) and isinstance(child.value, float) for child in ast.walk(node)):
            result = 'real'
        return result

    def _start_associate_block(self, raw: str, arrays_1d: set[str]) -> None:
        self.emit("if True:")
        self.indent += 1
        frame: dict[str, object] = {
            "code_start": self._code_emit_count,
            "names": set(),
            "saved_bindings": {},
            "saved_arrays": set(arrays_1d),
            "saved_pointer": set(self._decl_pointer),
            "saved_maps": {attr: dict(getattr(self, attr)) for attr in
                           ('_decl_types', '_decl_array_types', '_decl_type_names',
                            '_decl_lbounds', '_decl_ubounds')},
        }
        selected = []
        # Every selector is evaluated in the enclosing scope, before any
        # associate name can shadow a variable used by a subsequent selector.
        for assoc_name, selector in self._associate_bindings(raw):
            can_alias, is_array_alias, root = self._associate_alias_metadata(selector, arrays_1d)
            component = self._component_spec(selector) if can_alias else None
            expression_type = None
            if can_alias and not is_array_alias:
                rhs_py = self._associate_array_element_ref(selector, arrays_1d)
                if rhs_py is None:
                    rhs_py = self.translate_expr(selector, arrays_1d)
                    if re.fullmatch(r'[a-z_]\w*', selector.strip(), re.I):
                        self.emit(f'if not isinstance({rhs_py}, np.ndarray):')
                        self.indent += 1
                        self.emit(f'{rhs_py} = np.asarray({rhs_py})')
                        self.indent -= 1
            else:
                rhs_py = self.translate_expr(selector, arrays_1d)
                if not can_alias:
                    expression_type = self._associate_expression_array_type(rhs_py)
                if not can_alias:
                    rhs_py = f'_xf2p_copy_value({rhs_py})'
            self._allocation_counter += 1
            temporary = _choose_fresh_identifier(self._allocation_source, f'_xf2p_associate_selector_{self._allocation_counter}')
            self.emit(f'{temporary} = {rhs_py}')
            base_type = component['ftype'] if component else self._decl_array_types.get(root or '', self._decl_types.get(root or '', 'real'))
            type_name = component.get('type_name') if component else self._decl_type_names.get(root or '')
            selected.append((assoc_name, selector, can_alias, is_array_alias, root, component, temporary, base_type, type_name,
                             expression_type if not can_alias else None))
        for assoc_name, selector, can_alias, is_array_alias, root, component, temporary, base_type, type_name, expression_type in selected:
            assoc_l = assoc_name.lower()
            if assoc_l in self._decl_types or any(assoc_l in outer['names'] for outer in self._associate_stack):
                self._allocation_counter += 1
                saved = _choose_fresh_identifier(self._allocation_source, f'_xf2p_associate_saved_{self._allocation_counter}')
                self.emit(f'{saved} = {assoc_name}')
                frame['saved_bindings'][assoc_name] = saved
            frame['names'].add(assoc_l)
            arrays_1d.discard(assoc_l)
            self._decl_pointer.discard(assoc_l)
            for attr in frame['saved_maps']:
                getattr(self, attr).pop(assoc_l, None)
            if can_alias:
                self.emit(f"{assoc_name} = {temporary}")
                self._decl_pointer.add(assoc_l)
                self._decl_types[assoc_l] = base_type
                if type_name:
                    self._decl_type_names[assoc_l] = type_name
                if is_array_alias:
                    self._decl_array_types[assoc_l] = base_type
                    arrays_1d.add(assoc_l)
                    # Section associate names have unit lower bounds, even if
                    # a shadowed outer variable had different declared bounds.
                    section = re.fullmatch(r'[a-z_]\w*(?:%[a-z_]\w*)*\s*\((.*)\)', selector, re.I)
                    if section:
                        rank = sum(':' in part or part.strip().lower() in frame['saved_arrays']
                                   for part in split_args(section.group(1)))
                        self._decl_lbounds[assoc_l] = ['1'] * rank
                        self._decl_ubounds[assoc_l] = [''] * rank
                    elif component and component.get('shape'):
                        bounds = self._shape_bounds(component['shape'])
                        self._decl_lbounds[assoc_l] = [lo for lo, _hi in bounds]
                        self._decl_ubounds[assoc_l] = [hi for _lo, hi in bounds]
                    else:
                        self._decl_lbounds[assoc_l] = list(frame['saved_maps']['_decl_lbounds'].get(root, []))
                        self._decl_ubounds[assoc_l] = list(frame['saved_maps']['_decl_ubounds'].get(root, []))
                else:
                    self._decl_types[assoc_l] = base_type
            else:
                self.emit(f"{assoc_name} = {temporary}")
                if expression_type:
                    arrays_1d.add(assoc_l)
                    self._decl_types[assoc_l] = expression_type
                    self._decl_array_types[assoc_l] = expression_type
        self._associate_stack.append(frame)

    def _end_associate_block(self, arrays_1d: set[str]) -> None:
        if not self._associate_stack:
            return
        frame = self._associate_stack.pop()
        for name, saved in frame['saved_bindings'].items():
            self.emit(f'{name} = {saved}')
        self._decl_pointer = frame['saved_pointer']
        for attr, values in frame['saved_maps'].items():
            setattr(self, attr, values)
        arrays_1d.clear()
        arrays_1d.update(frame['saved_arrays'])
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

    def _start_where_block(self, cond_raw: str, arrays_1d: set[str], name: str | None = None) -> None:
        cond_py = self.translate_expr(cond_raw, arrays_1d)
        tag = f"{len(self._where_stack) + 1}_{self._code_emit_count + 1}"
        active_name = _choose_fresh_identifier(self._allocation_source, f"_xf2p_where_mask_{tag}")
        matched_name = _choose_fresh_identifier(self._allocation_source, f"_xf2p_where_matched_{tag}")
        outer = self._where_current_mask_expr()
        if outer is None:
            active_expr = f"np.asarray({cond_py}, dtype=bool)"
        else:
            active_expr = f"(np.asarray({outer}, dtype=bool) & np.asarray({cond_py}, dtype=bool))"
        self.emit(f"{active_name} = np.array({active_expr}, dtype=bool, copy=True)")
        self.emit(f"{matched_name} = np.array({active_name}, copy=True)")
        self._where_stack.append({"active": active_name, "matched": matched_name, "name": name or ''})

    def _validate_where_name(self, name: str | None = None) -> None:
        if not self._where_stack:
            raise ValueError('ELSEWHERE/END WHERE without an active WHERE construct')
        if name is not None and name.lower() != self._where_stack[-1]['name'].lower():
            raise ValueError(f'WHERE construct name mismatch: {name}')

    def _where_elsewhere(self, cond_raw: str | None, arrays_1d: set[str]) -> None:
        if not self._where_stack:
            raise ValueError('ELSEWHERE without an active WHERE construct')
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

    def _assign_projected_component(self, lhs, rhs_py, arrays_1d, mask=None):
        match = re.fullmatch(r'([a-z_]\w*)\.([a-z_]\w*(?:\.[a-z_]\w*)*)', lhs, re.I)
        if not match or match.group(1) not in arrays_1d or self._decl_types.get(match.group(1).lower()) != 'type':
            return False
        spec = self._component_spec(lhs)
        if spec:
            if spec.get('shape'):
                raise ValueError('array components of an array parent require explicit subscripts')
            dtype = _type_dtype.get(spec['ftype'])
            if dtype and spec['ftype'] != 'character':
                rhs_py = f'np.asarray({rhs_py}, dtype={dtype})'
            if spec.get('char_len') is not None:
                rhs_py = self._character_assignment_rhs(rhs_py, spec['char_len'], arrays_1d)
        mask_argument = f', mask={mask}' if mask is not None else ''
        self.emit(f"_f_assign_component_array({match.group(1)}, {match.group(2)!r}, {rhs_py}{mask_argument})")
        return True

    def _where_masked_assignment(self, lhs: str, rhs_py: str, arrays_1d: set[str]) -> bool:
        mask_expr = self._where_current_mask_expr()
        if mask_expr is None:
            return False
        lhs = lhs.replace("%", ".")
        if self._assign_projected_component(lhs, rhs_py, arrays_1d, mask=mask_expr):
            return True
        if self._is_chained_subscript(lhs):
            target = self.translate_expr(lhs, arrays_1d)
            spec = self._component_spec(lhs)
            if spec and spec["ftype"] == "integer":
                rhs_py = f"np.asarray({rhs_py}, dtype=int)"
            if spec and spec.get("char_len") is not None:
                rhs_py = self._character_assignment_rhs(rhs_py, spec['char_len'], arrays_1d,
                                                        deferred_array=bool(spec.get('shape')))
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
        if idx_name is not None and idx is not None and (
                idx_name in arrays_1d or ":" in idx or "," in idx):
            name = idx_name
            parts = [p.strip() for p in split_args(idx)]
            target = self._cartesian_array_reference(name, parts, arrays_1d)
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

    def _emit_simultaneous_forall(self, header, statements, arrays_1d):
        """Freeze the iteration set, then gather/apply each assignment separately."""
        loops, mask = self._parse_forall_header(header, arrays_1d)
        if not loops:
            raise ValueError('FORALL requires an index triplet')

        def fresh(label):
            self._allocation_counter += 1
            return _choose_fresh_identifier(self._allocation_source,
                                           f'_xf2p_forall_{label}_{self._allocation_counter}')

        indices = {name: fresh(name) for name, _lo, _hi, _step in loops}
        if len(indices) != len(loops):
            raise ValueError('duplicate FORALL index')

        class RenameIndices(ast.NodeTransformer):
            def visit_Name(visitor, node):
                if node.id in indices:
                    return ast.copy_location(ast.Name(id=indices[node.id], ctx=node.ctx), node)
                return node

        def mapped(expression):
            return ast.unparse(RenameIndices().visit(ast.parse(expression, mode='eval').body))

        ranges = []
        for name, lo, hi, step in loops:
            step = step or '1'
            if any(isinstance(node, ast.Name) and node.id in indices
                   for expression in (lo, hi, step) for node in ast.walk(ast.parse(expression, mode='eval'))):
                raise ValueError('FORALL triplet bounds cannot depend on a FORALL index')
            low, high, stride, iteration_range = (fresh(part) for part in ('lo', 'hi', 'step', 'range'))
            self.emit(f'{low}, {high}, {stride} = {lo}, {hi}, {step}')
            self.emit(f'{iteration_range} = range({low}, {high} + (1 if {stride} > 0 else -1), {stride})')
            ranges.append(iteration_range)

        selected = fresh('indices')
        self.emit(f'{selected} = []')
        for name, iteration_range in zip(indices.values(), ranges):
            self.emit(f'for {name} in {iteration_range}:')
            self.indent += 1
        if mask is not None:
            self.emit(f'if {mapped(mask)}:')
            self.indent += 1
        tuple_indices = ', '.join(indices.values()) + (',' if len(indices) == 1 else '')
        self.emit(f'{selected}.append(({tuple_indices}))')
        self.indent -= len(indices) + (mask is not None)

        def index_value(node):
            if isinstance(node, ast.Slice):
                parts = [ast.unparse(part) if part is not None else 'None'
                         for part in (node.lower, node.upper, node.step)]
                return f"slice({', '.join(parts)})"
            if isinstance(node, ast.Tuple):
                return '(' + ', '.join(index_value(item) for item in node.elts) + ',)'
            return f'_xf2p_copy_value({ast.unparse(node)})'

        for statement in statements:
            assignment = split_top_level(statement, '=')
            if len(assignment) != 2 or assignment[1].lstrip().startswith('>') or re.match(r'(?:forall|where)\b', statement, re.I):
                raise ValueError(f'unsupported FORALL body statement: {statement}; only intrinsic assignments are supported')
            lhs, rhs = assignment
            # Reuse normal assignment conversion/indexing, without emitting the
            # actual writes until all values and destination selectors are saved.
            original_out, original_count = self.out, self._code_emit_count
            self.out = []
            try:
                self.transpile_assignment(lhs.strip(), self.translate_expr(rhs.strip(), arrays_1d), arrays_1d)
                translated = '\n'.join(line.strip() for line in self.out)
            finally:
                self.out, self._code_emit_count = original_out, original_count
            nodes = ast.parse(translated).body
            if len(nodes) != 1 or not isinstance(nodes[0], ast.Assign) or len(nodes[0].targets) != 1:
                raise ValueError(f'unsupported FORALL assignment target: {lhs.strip()}')
            node = RenameIndices().visit(nodes[0])
            target, value = node.targets[0], ast.unparse(node.value)
            pending, obj, key, item = (fresh(part) for part in ('pending', 'object', 'key', 'value'))
            self.emit(f'{pending} = []')
            self.emit(f'for {tuple_indices} in {selected}:')
            self.indent += 1
            if isinstance(target, ast.Subscript):
                self.emit(f'{pending}.append(({ast.unparse(target.value)}, {index_value(target.slice)}, _xf2p_copy_value({value})))')
                writeback = f'{obj}[{key}] = {item}'
                unpack = f'{obj}, {key}, {item}'
            elif isinstance(target, ast.Attribute):
                self.emit(f'{pending}.append(({ast.unparse(target.value)}, _xf2p_copy_value({value})))')
                writeback = f'{obj}.{target.attr} = {item}'
                unpack = f'{obj}, {item}'
            elif isinstance(target, ast.Name):
                self.emit(f'{pending}.append(_xf2p_copy_value({value}))')
                writeback = f'{target.id} = {item}'
                unpack = item
            else:
                raise ValueError(f'unsupported FORALL assignment target: {lhs.strip()}')
            self.indent -= 1
            self.emit(f'for {unpack} in {pending}:')
            self.indent += 1
            self.emit(writeback)
            self.indent -= 1

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

    def _formatted_internal_read(self, spec: dict[str, str], rest: str, arrays_1d: set[str]) -> bool:
        fmt = spec.get('fmt')
        if fmt is None:
            raise ValueError('Internal READ requires FMT')
        if fmt == '*':
            if 'iomsg' in spec:
                raise ValueError('List-directed internal READ with IOMSG is not yet supported')
            if not rest:
                raise ValueError('Internal READ without an input list is not yet supported')
            return False  # Existing list-directed lowering.
        if not _is_fortran_string_literal(fmt):
            raise ValueError('Formatted internal READ currently requires a literal format')
        format_text = _fortran_unquote(fmt).strip().lower()
        if not (format_text.startswith('(') and format_text.endswith(')')):
            raise ValueError('Formatted internal READ requires a parenthesized format')
        descriptors = []
        for part in split_args(format_text[1:-1]):
            match = re.fullmatch(r'(\d*)([ifedglax])(\d*)(?:\.(\d+))?', part.replace(' ', ''))
            if not match:
                raise ValueError(f'unsupported internal READ format descriptor: {part}')
            repeat, code, width, decimals = match.groups()
            repeat = int(repeat or 1)
            width = int(width) if width else None
            if repeat < 1 or repeat > 10000:
                raise ValueError('unsupported internal READ format repeat count')
            if code == 'x':
                if width is not None or decimals is not None:
                    raise ValueError(f'unsupported internal READ format descriptor: {part}')
                descriptors.append(('x', repeat, None))
                continue
            if ((code != 'a' and width is None) or (width is not None and width < 1)
                    or (code in 'fedg' and decimals is None)
                    or (code in 'al' and decimals is not None)):
                raise ValueError(f'unsupported internal READ format descriptor: {part}')
            descriptors.extend([(code, width, int(decimals) if decimals is not None else None)] * repeat)
        targets = [target.strip() for target in split_args(rest) if target.strip()]
        fields = [item for item in descriptors if item[0] != 'x']
        if not targets or len(targets) > len(fields):
            raise ValueError('Internal READ format reversion/empty input lists are not yet supported')
        unit_raw = spec['unit']
        unit_py = self.translate_expr(unit_raw, arrays_1d)
        base = re.match(r'[a-z_]\w*', unit_raw, re.I)
        unit_name = base.group().lower() if base else ''
        source_component = self._component_spec(unit_raw) if '%' in unit_raw else None
        source_array = bool(source_component.get('shape')) if source_component else unit_name in self._decl_array_types
        if source_array and (not isinstance(ast.parse(unit_py, mode='eval').body, ast.Subscript)
                             or ':' in unit_raw):
            raise ValueError('Formatted internal READ currently requires a scalar character source')
        target_exprs, lengths = [], []
        for target, (code, width, decimals) in zip(targets, fields):
            expr = self.translate_expr(target, arrays_1d)
            node = ast.parse(expr, mode='eval').body
            base = re.match(r'[a-z_]\w*', target, re.I)
            name = base.group().lower() if base else ''
            component = self._component_spec(target) if '%' in target else None
            kind = component['ftype'] if component else self._decl_types.get(name, self._decl_array_types.get(name))
            expected = {'i': 'integer', 'f': 'real', 'e': 'real', 'd': 'real', 'g': 'real', 'l': 'logical', 'a': 'character'}[code]
            array = bool(component.get('shape')) if component else name in self._decl_array_types
            if (not isinstance(node, (ast.Name, ast.Attribute, ast.Subscript))
                    or (array and not isinstance(node, ast.Subscript))
                    or any(isinstance(item, ast.Slice) for item in ast.walk(node))
                    or (isinstance(node, ast.Subscript) and any(
                        isinstance(item, (ast.List, ast.ListComp))
                        or (isinstance(item, ast.Name) and item.id in self._decl_array_types)
                        for item in ast.walk(node.slice)))
                    or kind != expected):
                raise ValueError(f'Internal READ {code.upper()} descriptor currently requires a scalar {expected} target: {target}')
            target_exprs.append(expr)
            lengths.append(f'len({expr})' if kind == 'character' else 'None')
        self._allocation_counter += 1
        temporary = _choose_fresh_identifier(self._allocation_source, f'_xf2p_internal_read_{self._allocation_counter}')
        ios = self.translate_expr(spec['iostat'], arrays_1d) if 'iostat' in spec else None
        message = self.translate_expr(spec['iomsg'], arrays_1d) if 'iomsg' in spec else None
        if message is not None and ios is None:
            raise ValueError('Internal READ IOMSG currently requires IOSTAT')
        if ios is not None:
            self.emit('try:')
            self.indent += 1
        self.emit(f'{temporary} = _f_internal_read({unit_py}, {descriptors!r}, [{", ".join(lengths)}])')
        for index, expr in enumerate(target_exprs):
            self.emit(f'{expr} = {temporary}[{index}]')
        if ios is not None:
            self.emit(f'{ios} = 0')
            self.indent -= 1
            self.emit('except (ValueError, OverflowError) as _xf2p_io_error:')
            self.indent += 1
            self.emit(f'{ios} = 1')
            if message is not None:
                self.emit(f'{message} = _f_str_assign(str(_xf2p_io_error), len({message}))')
            self.indent -= 1
        return True

    def _external_file_io(self, s: str, arrays_1d: set[str]) -> bool:
        match = re.match(r"(open|close|rewind|read)\b", s, re.I)
        if not match:
            return False
        operation = match.group(1).lower()
        opening = s.find("(")
        if opening < 0:
            if operation != "rewind":
                raise ValueError(f"unsupported {operation.upper()} form: {s}")
            parts, rest = [s[match.end():].strip()], ""
        else:
            closing = find_matching_paren(s, opening)
            if closing < 0:
                raise ValueError(f"invalid {operation.upper()} control list: {s}")
            parts, rest = split_args(s[opening + 1:closing]), s[closing + 1:].strip()
        spec = {}
        for index, part in enumerate(parts):
            kw = re.fullmatch(r"\s*([a-z_]\w*)\s*=\s*(.+)", part, re.I)
            key, value = (kw.group(1).lower(), kw.group(2)) if kw else (
                "unit" if index == 0 else "fmt", part.strip())
            if key in spec:
                raise ValueError(f"duplicate {operation.upper()} specifier: {key}")
            spec[key] = value
        unit_raw = spec.get("unit", spec.get("newunit"))
        if unit_raw is None:
            raise ValueError(f"{operation.upper()} requires UNIT or NEWUNIT")
        if operation == "read":
            base = re.match(r"[a-z_]\w*", unit_raw, re.I)
            name = base.group().lower() if base else ""
            source_component = self._component_spec(unit_raw) if '%' in unit_raw else None
            if (self._decl_types.get(name) == "character" or self._decl_array_types.get(name) == "character"
                    or (source_component and source_component['ftype'] == 'character')):
                unknown = set(spec) - {'unit', 'fmt', 'iostat', 'iomsg'}
                if unknown:
                    raise ValueError(f"unsupported internal READ specifier(s): {', '.join(sorted(unknown))}")
                return self._formatted_internal_read(spec, rest, arrays_1d)
            if "fmt" not in spec:
                raise ValueError("Unformatted READ is not yet supported")
        allowed = {
            "open": {"unit", "newunit", "file", "status", "action", "position", "access", "form", "iostat", "iomsg"},
            "close": {"unit", "status", "iostat", "iomsg"},
            "rewind": {"unit", "iostat", "iomsg"},
            "read": {"unit", "fmt", "iostat", "iomsg"},
        }[operation]
        unknown = set(spec) - allowed
        if unknown:
            raise ValueError(f"unsupported {operation.upper()} specifier(s): {', '.join(sorted(unknown))}")
        py = lambda value: self.translate_expr(value, arrays_1d)
        unit = "5" if unit_raw == "*" else py(unit_raw)
        lines = []
        if operation == "open":
            if "unit" in spec and "newunit" in spec:
                raise ValueError("OPEN cannot specify both UNIT and NEWUNIT")
            if "newunit" in spec and not re.fullmatch(r"[a-z_]\w*", unit_raw, re.I):
                raise ValueError("NEWUNIT currently requires a named integer variable")
            for key, expected in (("access", "sequential"), ("form", "formatted")):
                value = spec.get(key)
                if value is not None and _is_fortran_string_literal(value) and _fortran_unquote(value).strip().lower() != expected:
                    raise ValueError("Only sequential formatted file I/O is supported")
            arguments = [f"{key}={py(value)}" for key, value in spec.items()
                         if key not in {"unit", "newunit", "iostat", "iomsg"}]
            call = f"_f_file_open({', '.join(([] if 'newunit' in spec else [unit]) + arguments)})"
            lines.append(f"{unit} = {call}" if "newunit" in spec else call)
        elif operation == "close":
            status = f", status={py(spec['status'])}" if "status" in spec else ""
            lines.append(f"_f_file_close({unit}{status})")
        elif operation == "rewind":
            lines.append(f"_f_file_rewind({unit})")
        else:
            fmt = spec.get("fmt", "*")
            targets = [part.strip() for part in split_args(rest) if part.strip()]
            if not targets:
                raise ValueError("READ without an input list is not yet supported")
            target_exprs = [py(target) for target in targets]
            self._allocation_counter += 1
            temporary = _choose_fresh_identifier(self._allocation_source, f"_xf2p_read_{self._allocation_counter}")
            if fmt == "*":
                kinds = []
                for target in targets:
                    base = re.match(r"[a-z_]\w*", target, re.I)
                    name = base.group().lower() if base else ""
                    kind = self._decl_types.get(name, self._decl_array_types.get(name, ""))
                    if kind not in {"integer", "real", "logical"} or "%" in target:
                        raise ValueError("External list-directed READ currently supports numeric/logical variables and sections")
                    kinds.append(kind)
                counts = ', '.join(f"np.size({target})" for target in target_exprs)
                lines.append(f"{temporary} = _f_file_read({unit}, [{counts}], {kinds!r})")
                lines.extend(f"{target} = _f_file_read_assign({target}, {temporary}[{index}])"
                             for index, target in enumerate(target_exprs))
            elif _is_fortran_string_literal(fmt) and _fortran_unquote(fmt).strip().lower() == "(a)" and len(targets) == 1:
                base = re.match(r"[a-z_]\w*", targets[0], re.I)
                name = base.group().lower() if base else ""
                if self._decl_types.get(name) != "character" or name in self._decl_array_types or not re.fullmatch(r"[a-z_]\w*", targets[0], re.I):
                    raise ValueError("External '(a)' READ currently requires a scalar character target")
                lines.append(f"{temporary} = _f_file({unit}, 'read').readline()")
                lines.append(f"if {temporary} == '': raise EOFError('End of file')")
                lines.append(f"{target_exprs[0]} = _f_str_assign({temporary}.rstrip('\\r\\n'), len({target_exprs[0]}))")
            else:
                raise ValueError("External formatted READ currently supports only '(a)' and list-directed input")
        ios = py(spec["iostat"]) if "iostat" in spec else None
        message = py(spec["iomsg"]) if "iomsg" in spec else None
        if message is not None and ios is None:
            raise ValueError("IOMSG currently requires IOSTAT")
        if ios is not None:
            self.emit("try:")
            self.indent += 1
        for line in lines:
            self.emit(line)
        if ios is not None:
            self.emit(f"{ios} = 0")
            self.indent -= 1
            self.emit("except (OSError, ValueError, EOFError, OverflowError) as _xf2p_io_error:")
            self.indent += 1
            self.emit(f"{ios} = -1 if isinstance(_xf2p_io_error, EOFError) else 1")
            if message is not None:
                self.emit(f"{message} = _f_str_assign(str(_xf2p_io_error), len({message}))")
            self.indent -= 1
        return True

    def handle_exec_line(self, s: str, arrays_1d: set[str]) -> bool:
        if self._forall_stack:
            if re.fullmatch(r'end\s*forall(?:\s+\w+)?', s.strip(), re.I):
                context = self._forall_stack.pop()
                self._emit_simultaneous_forall(context['header'], context['body'], arrays_1d)
            else:
                self._forall_stack[-1]['body'].append(s)
            return True
        sl = s.lower()
        if re.match(r"(open|close|rewind|read|write)\b", s, re.I) and len(split_top_level(s, "=")) > 1:
            parts = split_top_level(s, "=")
            self.transpile_assignment(parts[0].strip(), self.translate_expr("=".join(parts[1:]).strip(), arrays_1d), arrays_1d)
            return True  # Assignment to a variable named like an I/O keyword.
        if self._external_file_io(s, arrays_1d):
            return True
        # Existing WRITE format lowering expects positional UNIT and FMT.
        if re.match(r"write\s*\(", s, re.I) and len(split_top_level(s, "=")) == 1:
            opening = s.find("(")
            closing = find_matching_paren(s, opening)
            if closing >= 0:
                controls = split_args(s[opening + 1:closing])
                if any(re.match(r"\s*(unit|fmt)\s*=", part, re.I) for part in controls):
                    spec = {}
                    for index, part in enumerate(controls):
                        kw = re.fullmatch(r"\s*([a-z_]\w*)\s*=\s*(.+)", part, re.I)
                        key, value = (kw.group(1).lower(), kw.group(2)) if kw else (
                            "unit" if index == 0 else "fmt", part.strip())
                        if key in spec or key not in {"unit", "fmt"}:
                            raise ValueError(f"unsupported or duplicate WRITE specifier: {key}")
                        spec[key] = value
                    if set(spec) != {"unit", "fmt"}:
                        raise ValueError("WRITE requires UNIT and FMT")
                    s = f"write({spec['unit']}, {spec['fmt']}) {s[closing + 1:]}"
                    sl = s.lower()
        if next(data_statements([(s, '')]), None) is not None:
            # DATA was applied in the specification pass, never at runtime.
            return True
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

        where_name = None
        named_where = re.match(r'^([a-z_]\w*)\s*:\s*(where\b.*)$', s, re.I)
        if named_where:
            where_name, s = named_where.groups()
            sl = s.lower()
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

        mm = re.fullmatch(r"end\s*where(?:\s+([a-z_]\w*))?", s, re.I)
        if mm:
            self._validate_where_name(mm.group(1))
            self._end_where_block()
            return True

        mm = re.fullmatch(r"else\s*where\s*(?:\(\s*(.+)\s*\))?(?:\s+([a-z_]\w*))?", s, re.I)
        if mm:
            self._validate_where_name(mm.group(2))
            self._where_elsewhere(mm.group(1), arrays_1d)
            return True

        if pwhere is not None:
            p0, p1 = pwhere
            cond_raw = s[p0 + 1 : p1].strip()
            tail = s[p1 + 1 :].strip()
            if tail:
                self._start_where_block(cond_raw, arrays_1d, where_name)
                self.transpile_simple_stmt(tail, arrays_1d)
                self._end_where_block()
            else:
                self._start_where_block(cond_raw, arrays_1d, where_name)
            return True

        if re.match(r"end\s+forall", s, re.I):
            raise ValueError('END FORALL without an active FORALL construct')

        if pforall is not None:
            p0, p1 = pforall
            header_raw = s[p0 + 1 : p1].strip()
            tail = s[p1 + 1 :].strip()
            if tail:
                self._emit_simultaneous_forall(header_raw, [tail], arrays_1d)
            else:
                self._forall_stack.append({'header': header_raw, 'body': []})
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

        mm = re.match(r"else\s*if\s*\(\s*(.+)\s*\)\s*then$", s, re.I)
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

        if re.match(r"end\s*if\b", s, re.I):
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

        if re.match(r"end\s*do(?:\s+[a-z_]\w*)?$", s, re.I):
            entry = self._do_stack.pop() if self._do_stack else 1
            end_name = re.fullmatch(r"end\s*do\s+([a-z_]\w*)", s, re.I)
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
                if rank:
                    self.emit(f"{name} = _f_set_array_bounds({name}, [{', '.join(lows)}])")
                if "." not in name:
                    self._set_allocatable_array_bounds(name, rank)
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


        # call random_number(x)
        mm = re.match(r"call\s+random_number\s*\(\s*([a-z_]\w*)\s*\)\s*$", s, re.I)
        if mm:
            name = mm.group(1)
            if name in arrays_1d:
                self.emit(f"{name} = _f_assign_array({name}, np.random.random(size={name}.shape))")
            else:
                self.emit(f"{name} = np.float64(np.random.random())")
            return True


        # read(unit, "(a)", iostat=ios) text
        if re.match(r'read\b', sl):
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
                            character_targets = []
                            for tgt in items:
                                base = re.match(r'^([a-z_]\w*)', tgt, re.I)
                                name = base.group(1).lower() if base else ''
                                character_targets.append(self._decl_types.get(name, self._decl_array_types.get(name, '')) == 'character')
                            self.emit("try:")
                            self.indent += 1
                            self.emit(f"__xf2p_read_parts = _f_internal_read_parts({unit_py}, {character_targets!r})")
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

            raise ValueError(f'unsupported READ statement: {s}')


        # call foo(...)
        mm = re.match(r"call\s+([a-z_]\w*(?:\s*%\s*[a-z_]\w*)*)\s*(?:\((.*)\))?\s*$", s, re.I)
        if mm:
            opening = s.find("(")
            if opening != -1 and find_matching_paren(s, opening) != len(s) - 1:
                raise ValueError(f"unsupported CALL statement: {s}")
            cname = re.sub(r"\s*%\s*", ".", mm.group(1))
            cname_l = cname.lower()
            argtxt = (mm.group(2) or "").strip()
            if (cname_l == 'cpu_time' and cname_l not in self._binding_targets
                    and cname_l not in self._generic_names):
                output = _bind_intrinsic_arguments(cname_l, argtxt, ('time',), 1)['time']
                target = self.translate_expr(output, arrays_1d)
                node = ast.parse(target, mode='eval').body
                if not isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)) or ':' in output or '[' in output:
                    raise ValueError('CPU_TIME requires a scalar REAL variable, component or array element')
                base = re.match(r'[a-z_]\w*', output, re.I)
                name = base.group().lower() if base else ''
                spec = self._component_spec(output) if '%' in output else None
                ftype = spec['ftype'] if spec else self._decl_types.get(name)
                if ftype != 'real':
                    raise ValueError('CPU_TIME requires a declared REAL output')
                if ((isinstance(node, ast.Name) and name in arrays_1d)
                        or (spec and spec.get('shape') and not output.rstrip().endswith(')'))
                        or (spec and name in arrays_1d and re.match(r'\w+\s*%', output))):
                    raise ValueError('CPU_TIME requires a scalar output')
                if spec and 'pointer' in spec.get('attrs_l', '') and not spec.get('shape'):
                    self.emit(f'{target}[...] = _f_cpu_time()')
                else:
                    self.transpile_assignment(output, '_f_cpu_time()', arrays_1d)
                return True
            if cname_l in self._generic_names:
                self.emit(self._translate_generic_call(cname, argtxt, arrays_1d))
                return True
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
                    self._set_allocatable_array_bounds(destination, rank_a)
                self.emit(f'{destination}, {source} = {source}, None')
                if 'stat' in raw:
                    self.emit(f"{self.translate_expr(raw['stat'], arrays_1d)} = 0")
                return True
            if cname_l == 'execute_command_line':
                raw = _bind_intrinsic_arguments(cname_l, argtxt,
                    ('command', 'wait', 'exitstat', 'cmdstat', 'cmdmsg'), 1)
                wait = self.translate_expr(raw.get('wait', '.true.'), arrays_1d)
                wait_node = ast.parse(wait, mode='eval').body
                if isinstance(wait_node, ast.Constant) and wait_node.value is False:
                    raise ValueError('asynchronous EXECUTE_COMMAND_LINE (WAIT=.FALSE.) is not supported')
                targets = {}
                for key in ('exitstat', 'cmdstat', 'cmdmsg'):
                    if key not in raw:
                        continue
                    target = self.translate_expr(raw[key], arrays_1d)
                    node = ast.parse(target, mode='eval').body
                    if not isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)) or ':' in raw[key]:
                        raise ValueError(f'EXECUTE_COMMAND_LINE {key.upper()} requires a scalar variable, component or array element')
                    base = re.match(r'[a-z_]\w*', raw[key], re.I)
                    name = base.group().lower() if base else ''
                    spec = self._component_spec(raw[key]) if '%' in raw[key] else None
                    ftype = spec['ftype'] if spec else self._decl_types.get(name)
                    expected = 'character' if key == 'cmdmsg' else 'integer'
                    if ftype is not None and ftype != expected:
                        raise ValueError(f'EXECUTE_COMMAND_LINE {key.upper()} requires {expected.upper()}')
                    if ((isinstance(node, ast.Name) and name in arrays_1d)
                            or (spec and spec.get('shape') and not raw[key].rstrip().endswith(')'))):
                        raise ValueError(f'EXECUTE_COMMAND_LINE {key.upper()} requires a scalar output')
                    targets[key] = target
                self._allocation_counter += 1
                temporary = _choose_fresh_identifier(self._allocation_source, f'_xf2p_execute_{self._allocation_counter}')
                command = self.translate_expr(raw['command'], arrays_1d)
                self.emit(f'{temporary} = _f_execute_command_line({command}, wait={wait}, has_cmdstat={"cmdstat" in raw})')
                for index, key in enumerate(('exitstat', 'cmdstat', 'cmdmsg')):
                    if key not in targets:
                        continue
                    if key != 'cmdstat':
                        self.emit(f'if {temporary}[{index}] is not None:')
                        self.indent += 1
                    if key == 'cmdmsg':
                        spec = self._component_spec(raw[key])
                        base = re.match(r'[a-z_]\w*', raw[key], re.I).group().lower()
                        length = spec.get('char_len') if spec else self._decl_char_len.get(base)
                        length_py = (self.translate_expr(str(length), arrays_1d)
                                     if length not in (None, ':', '*') else f'len({targets[key]})')
                        self.emit(f'{targets[key]} = _f_str_assign({temporary}[{index}], {length_py})')
                    else:
                        self.transpile_assignment(raw[key], f'{temporary}[{index}]', arrays_1d)
                    if key != 'cmdstat':
                        self.indent -= 1
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
                if out_actuals:
                    targets = []
                    for actual in out_actuals:
                        if not actual:
                            self._allocation_counter += 1
                            actual = _choose_fresh_identifier(self._allocation_source, f'_xf2p_unused_output_{self._allocation_counter}')
                        elif not isinstance(ast.parse(actual, mode='eval').body, (ast.Name, ast.Attribute, ast.Subscript)):
                            raise ValueError(f'modified dummy argument of {cname} requires a definable actual, not {actual}')
                        targets.append(actual)
                    self.emit(f"{', '.join(targets)} = {cname}({', '.join(merged)})")
                    return True
            self.emit(f"{cname}({', '.join(merged)})")
            return True

        if re.match(r"^call\b", s, re.I):
            raise ValueError(f"unsupported CALL statement: {s}")

        # return
        if sl == "return":
            self._emit_procedure_return()
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
        mm = re.match(r"^([a-z_]\w*(?:\([^()]*\)(?=\s*%))?(?:%[a-z_]\w*)*)\s*(?:\((.*?)\))?\s*=>\s*(.+)$", s, re.I)
        if mm:
            lhs = mm.group(1).replace("%", ".")
            lhs_py = self.translate_expr(lhs, arrays_1d)
            bounds_raw = mm.group(2)
            rhs_raw = mm.group(3).strip()
            lower = None
            if bounds_raw is not None:
                lower = []
                for bound in split_args(bounds_raw):
                    parts = split_top_level(bound, ':', preserve_empty=True)
                    if len(parts) != 2 or not parts[0].strip() or parts[1].strip():
                        raise ValueError('rank-changing pointer bounds remapping is not yet supported; use lower-bound-only association')
                    lower.append(self.translate_expr(parts[0], arrays_1d))
            component = self._component_spec(lhs) if '.' in lhs else None
            rank = (len(self._shape_bounds(component['shape'])) if component and component.get('shape')
                    else len(self._decl_lbounds.get(lhs.lower(), [])))
            if lower is not None and len(lower) != rank:
                raise ValueError('pointer association lower bounds must match the pointer rank')
            if re.match(r"^null\s*\(\s*\)\s*$", rhs_raw, re.I):
                self.emit(f"{lhs_py} = None")
            else:
                rhs_py = self._pointer_association_expr(rhs_raw, arrays_1d, lower, rank)
                self.emit(f"{lhs_py} = {rhs_py}")
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

        # A formatted PRINT with no output list still executes literal and
        # control edit descriptors. Do not silently discard the statement.
        mm = re.fullmatch(r"print\s*((?:\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'))\s*", s, re.I)
        if mm:
            fmt_expr = _fortran_format_expr(mm.group(1), [])
            if fmt_expr is None:
                raise ValueError(f'unsupported itemless PRINT format: {mm.group(1)}')
            self.emit(f'print({fmt_expr})')
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
                        file_txt = "" if unit_raw == "*" else f", file=_f_file({self.translate_expr(unit_raw, arrays_1d)}, 'write')"
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
                        file_txt = "" if unit_raw == "*" else f", file=_f_file({self.translate_expr(unit_raw, arrays_1d)}, 'write')"
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
                        file_txt = "" if unit_raw == "*" else f", file=_f_file({self.translate_expr(unit_raw, arrays_1d)}, 'write')"
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
        mm = re.match(r"write\s*\(\s*([a-z_]\w*|\d+)\s*,\s*\*\s*\)\s*(.*)$", s, re.I)
        if mm:
            unit = f"_f_file({self.translate_expr(mm.group(1), arrays_1d)}, 'write')"
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
            unit = f"_f_file({self.translate_expr(mm.group(1).strip(), arrays_1d)}, 'write')"
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
                        file_txt = "" if unit_raw == "*" else f", file=_f_file({self.translate_expr(unit_raw, arrays_1d)}, 'write')"
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
                        file_txt = "" if unit_raw == "*" else f", file=_f_file({self.translate_expr(unit_raw, arrays_1d)}, 'write')"
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
                        file_txt = "" if unit_raw == "*" else f", file=_f_file({self.translate_expr(unit_raw, arrays_1d)}, 'write')"
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
            if lhs in arrays_1d and rhs_py in ("True", "False") and not self._where_stack:
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
                    "kind_expr": self._numeric_declared_kind(info, sym),
                    "rank": len(self._shape_bounds(info['shape'])) if info.get('shape') else 0,
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
                args_annot.append(f"{a}: {hint} = {self._optional_dummy_default(info)}")
            else:
                args_annot.append(f"{a}: {hint}")

        self._apply_data_initializers(main_lines, sym, args)
        save_names = self._collect_save_names(main_lines, sym, args)
        save_dict_name = f"_{fname}_save"
        self.emit(f"{save_dict_name} = {{}}")
        contiguous = [(a, 'intent(in)' not in str(sym[a].get('attrs_l', '')).replace(' ', ''))
                      for a in args if a in sym and sym[a].get('is_array')
                      and 'contiguous' in sym[a].get('attrs_l', '')
                      and not sym[a].get('pointer') and 'allocatable' not in sym[a].get('attrs_l', '')]
        if contiguous:
            self.emit(f"@_f_contiguous_arguments({', '.join(repr(spec) for spec in contiguous)})")
        function_outputs = self._binding_targets.get(fname.lower(), {}).get('out', [])
        if function_outputs:
            output_hints = []
            for name in function_outputs:
                info = sym.get(name, {})
                hint = self._type_hint(info.get('ftype', 'integer'), info.get('type_name'),
                                       is_array=bool(info.get('is_array')))
                if 'optional' in info.get('attrs_l', ''):
                    hint += ' | None'
                output_hints.append(hint)
            result_hint = f"tuple[{result_hint}, {', '.join(output_hints)}]"
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
        self._emit_value_dummy_copies(args, sym)
        previous_presence = self._optional_allocatable_presence
        self._optional_allocatable_presence = {name: flag for name, flag in previous_presence.items() if name not in sym}
        self._emit_allocatable_dummy_entry(args, sym)
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
        self._register_allocatable_array_bounds(scope_sym)

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
        self._optional_allocatable_presence = previous_presence
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

        self._apply_data_initializers(body_lines, sym)
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
        self._register_allocatable_array_bounds(sym)

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
        self.emit(f"def {generic_name}(*args, {self._generic_kind_keyword}=None, **kwargs):")
        self.indent += 1
        for proc, sig in candidates:
            arg_specs = list(sig.get("arg_specs", []))
            self.emit(f"bound = _xf2p_generic_bind(args, kwargs, {list(sig['args'])!r}, {self._generic_kind_keyword})")
            conds = ["bound is not None"]
            for j, spec in enumerate(arg_specs):
                cond = self._xf2p_generic_arg_cond(f"bound[0][{j}]", spec)
                if cond != "True":
                    conds.append(cond)
                if spec.get('is_array'):
                    conds.append(f"np.ndim(bound[0][{j}]) == {spec.get('rank', 1)}")
                if spec.get('kind_expr'):
                    conds.append(f"_xf2p_generic_kind(bound[0][{j}], bound[1][{j}]) == ({spec['kind_expr']})")
            call_args = [self._xf2p_generic_call_arg(f"bound[0][{j}]", spec) for j, spec in enumerate(arg_specs)]
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

        self._apply_data_initializers(decl_lines, sym)
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
        enum_names = set().union(*self._module_enum_names.values()) if self._module_enum_names else set()
        for name, info in sym.items():
            if name.lower() in enum_names:
                owner = self._module_enum_storage_owners.setdefault(name.lower(), module_name)
                if owner != module_name:
                    raise ValueError(f"enumerator/module name '{name}' is declared in both {owner} and {module_name}; separate module namespaces are not yet supported")
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
        m = re.match(r"(?:(?:pure|impure|elemental|recursive)\s+)*subroutine\s+(\w+)\s*\(\s*([^\)]*)\s*\)", hdr, re.I)
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
                args_annot.append(f"{a}: {hint} = {self._optional_dummy_default(info)}")
            else:
                args_annot.append(f"{a}: {hint}")
        out_formals: list[str] = []
        pure_out_formals: list[str] = []
        out_otypes: list[str] = []
        inferred_outputs = set(self._binding_targets.get(sname.lower(), {}).get('out', []))
        for a in args:
            info = sym.get(a, {})
            attrs_l = re.sub(r"\s+", "", info.get("attrs_l", ""))
            if not self._has_value_attribute(attrs_l) and ("intent(out" in attrs_l or "intent(inout" in attrs_l or a.lower() in inferred_outputs):
                out_formals.append(a)
                out_otypes.append(self._scalar_otype_expr(cast(str, info.get("ftype")), cast(str | None, info.get("type_name"))))
            if "intent(out" in attrs_l and "intent(inout" not in attrs_l:
                pure_out_formals.append(a)
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
                    "kind_expr": self._numeric_declared_kind(info, sym),
                    "rank": len(self._shape_bounds(info['shape'])) if info.get('shape') else 0,
                })
        self._subr_sigs[sname.lower()] = {"args": list(args), "out": list(out_formals), "arg_specs": arg_specs}

        self._apply_data_initializers(main_lines, sym, args)
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

        self._emit_value_dummy_copies(args, sym)
        previous_presence = self._optional_allocatable_presence
        self._optional_allocatable_presence = {name: flag for name, flag in previous_presence.items() if name not in sym}
        self._emit_allocatable_dummy_entry(args, sym)

        for kind, header, ibody in internals:
            if kind == "function":
                self.transpile_function(header, ibody)
            else:
                self.transpile_subroutine(header, ibody)

        if is_elemental and args:
            _xf2p_elem_guard = " or ".join(f"_xf2p_is_arraylike({a})" for a in args)
            self.emit(f"if {_xf2p_elem_guard}:")
            self.indent += 1
            output_indices = [args.index(a) for a in out_formals]
            pure_output_indices = [args.index(a) for a in pure_out_formals]
            self.emit(f"return _f_elemental_subroutine({sname}, [{', '.join(args)}], {output_indices!r}, [{', '.join(out_otypes)}], {pure_output_indices!r})")
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
        self._register_allocatable_array_bounds(scope_sym)

        previous_outputs = self._current_subroutine_outputs
        self._current_subroutine_outputs = out_formals
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

        self._current_subroutine_outputs = previous_outputs
        self._optional_allocatable_presence = previous_presence

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

    def _resolve_module_procedure_names(self, lines):
        """Resolve same-source procedure USE/host association before flattening.

        Only colliding module definitions need new Python names. Resolve bare
        references lexically, not component names, strings, or keyword labels.
        """
        root = dict(kind='file', name='', parent=None, locals=set(), procedures={}, uses=[], access=[], children=[])
        stack, owners, scopes, modules = [root], [], [root], {}
        for index, (code, _comment) in enumerate(lines):
            s = code.strip()
            end = re.match(r'^end\s*(module|program|function|subroutine|type|interface|block)\b', s, re.I)
            if end or s.lower() == 'end':
                owners.append(stack[-1])
                if len(stack) > 1:
                    stack.pop()
                continue
            kind, name, args, result = None, '', [], None
            module = re.fullmatch(r'module\s+([a-z_]\w*)', s, re.I)
            program = re.match(r'^program\s+([a-z_]\w*)', s, re.I)
            procedure = re.search(r'\b(function|subroutine)\s+([a-z_]\w*)\s*\(([^)]*)\)', s, re.I)
            derived = re.match(r'^type\b(?!\s*\()(?:\s*,[^:]*)?(?:\s*::\s*|\s+)([a-z_]\w*)\s*$', s, re.I)
            interface = re.fullmatch(r'(?:abstract\s+)?interface(?:\s+([a-z_]\w*))?', s, re.I)
            if module:
                kind, name = 'module', module.group(1).lower()
            elif program:
                kind, name = 'program', program.group(1).lower()
            elif derived:
                kind, name = 'type', derived.group(1).lower()
            elif interface:
                kind, name = 'interface', (interface.group(1) or '').lower()
                if name and stack[-1]['kind'] == 'module':
                    stack[-1]['procedures'][name] = name
            elif s.lower() == 'block':
                kind, name = 'block', ''
            elif procedure and stack[-1]['kind'] != 'type' and (self._is_function_header(s) or self._is_subroutine_header(s)):
                kind, name = procedure.group(1).lower(), procedure.group(2).lower()
                args = [a.strip().lower() for a in split_args(procedure.group(3))]
                res = re.search(r'\bresult\s*\(\s*(\w+)\s*\)', s, re.I)
                result = res.group(1).lower() if res else (name if kind == 'function' else None)
                stack[-1]['procedures'][name] = name
            if kind:
                scope = dict(kind=kind, name=name, parent=stack[-1], locals=set(args) | ({result} if result else set()),
                             result=result, procedures={}, uses=[], access=[], children=[])
                stack[-1]['children'].append(scope)
                scopes.append(scope)
                stack.append(scope)
                if kind == 'module':
                    modules[name] = scope
            owners.append(stack[-1])
            scope = stack[-1]
            declaration = self._parse_decl_line(s)
            if declaration:
                scope['locals'].update(name.lower() for name, _shape, _init in declaration[3])
            use = re.fullmatch(r'use\s*(?:,\s*(intrinsic|non_intrinsic)\s*)?(?:::)?\s*(\w+)\s*(.*)', s, re.I)
            if use and (use.group(1) or '').lower() != 'intrinsic':
                scope['uses'].append((use.group(2).lower(), use.group(3)))
            if scope['kind'] == 'module':
                access = re.fullmatch(r'(public|private)(?:\s*(?:::)?\s+(.+))?', s, re.I)
                if access:
                    scope['access'].append((access.group(1).lower(), access.group(2)))

        definitions = {}
        for scope in scopes:
            if scope['kind'] in ('module', 'file'):
                for name in scope['procedures']:
                    definitions.setdefault(name, []).append(scope)
        source = '\n'.join(code for code, _ in lines)
        for name, providers in definitions.items():
            if len(providers) > 1:
                for scope in providers:
                    if scope['kind'] == 'module':
                        canonical = _choose_fresh_identifier(source, f'xf2p_{scope["name"]}_{name}')
                        scope['procedures'][name] = canonical
                        source += '\n' + canonical

        exports = {name: {} for name in modules}

        def imported(scope):
            resolved = {}
            for module, tail in scope['uses']:
                available = exports.get(module, {})
                only = re.match(r'\s*,?\s*only\s*:\s*(.*)', tail, re.I)
                selected = {} if only else dict(available)
                for item in split_args(only.group(1) if only else tail.lstrip(',').strip()):
                    pair = [p.strip().lower() for p in item.split('=>', 1)]
                    local, remote = pair[0], pair[-1]
                    if remote in available:
                        if not only and local != remote:
                            selected.pop(remote, None)
                        selected[local] = available[remote]
                for local, canonical in selected.items():
                    resolved[local] = canonical if local not in resolved or resolved[local] == canonical else None
            return resolved

        # Modules can re-export USE-associated procedures, including renames.
        for _ in range(len(modules) + 1):
            changed = False
            for name, scope in modules.items():
                visible = {**imported(scope), **scope['procedures']}
                public, private, default_private = set(), set(), False
                for access, names in scope['access']:
                    if names is None:
                        default_private = access == 'private'
                    else:
                        (public if access == 'public' else private).update(p.strip().lower() for p in split_args(names))
                visible = {n: v for n, v in visible.items() if n not in private and (not default_private or n in public)}
                if exports[name] != visible:
                    exports[name] = visible
                    changed = True
            if not changed:
                break
        self._module_procedure_exports = exports

        def namespace(scope):
            if 'resolved' in scope:
                return scope['resolved']
            visible = dict(namespace(scope['parent'])) if scope['parent'] else {}
            visible.update(imported(scope))
            for local in scope['locals']:
                visible.pop(local, None)
            visible.update(scope['procedures'])
            if scope['kind'] in ('function', 'subroutine'):
                canonical = scope['parent']['procedures'][scope['name']]
                visible[scope['name']] = canonical
            scope['resolved'] = visible
            return visible

        token = re.compile(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"|\b[a-z_]\w*\b", re.I)
        rewritten = []
        for (code, comment), scope in zip(lines, owners):
            visible = namespace(scope)
            if re.match(r'\s*(?:use|module|end\s*module|program|end\s*program)\b', code, re.I) and not re.match(r'\s*module\s+procedure\b', code, re.I):
                rewritten.append((code, comment))
                continue
            # A shorthand binding keeps its member name but changes its target.
            if scope['kind'] == 'type' and re.match(r'\s*procedure\b', code, re.I) and '::' in code:
                head, items = code.split('::', 1)
                code = head + ':: ' + ', '.join(
                    item.strip() + ' => ' + visible[item.strip().lower()]
                    if '=>' not in item and visible.get(item.strip().lower(), item.strip()) != item.strip()
                    else item for item in split_args(items))
            binding_names = set()
            if scope['kind'] == 'type' and re.match(r'\s*procedure\b', code, re.I) and '::' in code:
                start = code.index('::') + 2
                binding_names = {start + m.start(1) for m in re.finditer(r'\b(\w+)\s*(?==>|,|$)', code[start:])}
            def rename(match):
                name = match.group(0)
                if (name.startswith(('"', "'")) or match.start() in binding_names
                        or code[:match.start()].rstrip().endswith('%')):
                    return name
                # Dummy keyword names belong to the callee, not this scope.
                if re.match(r'\s*=(?!=|>)', code[match.end():]) and '(' in code[:match.start()]:
                    prefix = token.sub(lambda m: '' if m.group(0).startswith(('"', "'")) else m.group(0), code[:match.start()])
                    if prefix.count('(') > prefix.count(')'):
                        return name
                canonical = visible.get(name.lower(), name)
                if canonical is None:
                    raise ValueError(f"ambiguous USE-associated procedure '{name}' in {scope['name'] or 'main program'}")
                return canonical
            rewritten.append((token.sub(rename, code), comment))
        return rewritten

    def transpile(self, src: str) -> str:
        self._host_scopes = []
        self._forall_stack = []
        self._where_stack = []
        self._optional_allocatable_presence = {}
        self._optional_absent_name = _choose_fresh_identifier(src, '_xf2p_absent_allocatable')
        self._module_variable_symbols: dict[str, dict[str, dict]] = {}
        self._module_storage_owners: dict[str, str] = {}
        raw = [split_fortran_comment(l) for l in src.splitlines()]
        raw = collapse_fortran_continuations(raw)
        raw = self._resolve_module_procedure_names(raw)
        self._generic_names = {item['name'].lower() for item in _extract_generic_interfaces(raw)[1]}
        self._generic_kind_keyword = _choose_fresh_identifier(src, '_xf2p_kind_hints')
        self._function_result_models = {}
        raw, self._module_enum_names = lower_enum_declarations(raw)
        self._module_enum_storage_owners: dict[str, str] = {}
        reject_defined_operations(raw)
        reject_goto_statements(raw)
        self._data_statement_count = sum(1 for _ in data_statements(raw))
        self._data_handled_count = 0
        raw = self._lower_lexical_blocks(raw)
        self._type_bindings = {}
        self._derived_types = set()
        self._type_components = {}
        self._component_specs = {}
        self._allocation_counter = 0
        self._allocation_bound_names = {}
        self._allocation_source = src
        self._decl_type_names = {}
        # Bindings precede their implementations; collect signatures before
        # emitting dataclass forwarding methods and resolving bound CALLs.
        self._binding_targets = {}
        inference_units = {}
        self._subr_sigs = {}
        for i, (code, _comment) in enumerate(raw):
            header = re.search(r"\b(function|subroutine)\s+(\w+)\s*\(([^)]*)\)", code, re.I)
            if not header or re.match(r"\s*end\b", code, re.I):
                continue
            kind, name = header.group(1).lower(), header.group(2).lower()
            args = [a.strip().lower() for a in split_args(header.group(3)) if a.strip()]
            body, _end = self._collect_subprogram_body(raw, i + 1, kind)
            main_lines, _internals = self._split_internal_subprograms(body)
            outputs, optional, symbols = set(), set(), {}
            for statement, _ in main_lines:
                declaration = self._parse_decl_line(statement.strip())
                if not declaration:
                    continue
                _ftype, _type_name, attrs, items = declaration
                for arg, _shape, _init in items:
                    symbols[arg.lower()] = dict(ftype=_ftype, type_name=_type_name,
                        is_array=_shape is not None, attrs=attrs, attrs_l=attrs.lower(), init=_init)
                    if not self._has_value_attribute(attrs) and re.search(r"intent\s*\(\s*(?:out|inout)\s*\)", attrs):
                        outputs.add(arg.lower())
                    if "optional" in attrs:
                        optional.add(arg.lower())
            self._binding_targets[name] = {"kind": kind, "args": args,
                "out": [a for a in args if a in outputs], "optional": optional,
                "optional_allocatable": {a for a in args if a in optional
                    and 'allocatable' in split_args(re.sub(r'\s+', '', symbols.get(a, {}).get('attrs', '')))}}
            eligible = {a for a in args if not re.search(r'intent\s*\(', symbols.get(a, {}).get('attrs', ''))
                        and not self._has_value_attribute(symbols.get(a, {}).get('attrs', ''))
                        and not symbols.get(a, {}).get('is_array')
                        and symbols.get(a, {}).get('ftype') != 'type'}
            inference_units[name] = (main_lines, eligible, symbols)
            if kind == 'function':
                result = re.search(r'\bresult\s*\(\s*(\w+)\s*\)', code, re.I)
                info = symbols.get(result.group(1).lower() if result else name)
                if info is None:
                    ftype = infer_function_result_ftype(code)
                    selector = re.search(r'\b(?:real|integer|complex)\s*(\([^)]*\)|\*\s*\d+)?', code[:header.start()], re.I)
                    info = dict(ftype=ftype, attrs_l=(selector.group(1) or '') if selector else '')
                    if re.search(r'\bdouble\s+(?:precision|complex)\b', code[:header.start()], re.I):
                        info['attrs_l'] = '(kind=8)'
                model_kind = self._declared_value_kind(info, symbols)
                if model_kind:
                    self._function_result_models[name] = (info['ftype'], model_kind)
        # CALL chains can define a dummy even when its own body has no assignment.
        changed = True
        while changed:
            changed = False
            for name, (lines, eligible, _symbols) in inference_units.items():
                signature = self._binding_targets[name]
                writes = set(signature['out']) | self._scalar_dummy_writes(lines, eligible, self._binding_targets, _symbols)
                outputs = [a for a in signature['args'] if a in writes]
                if outputs != signature['out']:
                    signature['out'] = outputs
                    changed = True
        for name, (_lines, _eligible, symbols) in inference_units.items():
            signature = self._binding_targets[name]
            if signature['kind'] != 'subroutine':
                continue
            self._subr_sigs[name] = dict(args=list(signature['args']), out=list(signature['out']),
                arg_specs=[{key: symbols.get(arg, {}).get(key, False if key == 'is_array' else None)
                            for key in ('ftype', 'type_name', 'is_array')} for arg in signature['args']])
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
        for helper_line in '''def _xf2p_generic_bind(args, kwargs, names, hints):
    if len(args) + len(kwargs) != len(names):
        return None
    values = list(args)
    kinds = list(hints) if hints is not None else [None] * (len(args) + len(kwargs))
    if len(kinds) != len(names):
        raise TypeError('invalid generic kind metadata')
    actual_names = list(kwargs)
    if any(name not in names[len(args):] for name in actual_names):
        return None
    ordered_kinds = kinds[:len(args)]
    for name in names[len(args):]:
        if name not in kwargs:
            return None
        values.append(kwargs[name])
        ordered_kinds.append(kinds[len(args) + actual_names.index(name)])
    return values, ordered_kinds

def _xf2p_generic_kind(value, hint):
    if hint is not None:
        if hint < 0:
            raise TypeError('cannot determine Fortran kind of generic argument')
        return hint
    # Untagged calls from Python use NumPy kinds, or Python scalar defaults.
    if isinstance(value, (np.ndarray, np.generic)):
        size = value.dtype.itemsize
        return size // 2 if value.dtype.kind == 'c' else size
    if isinstance(value, (int, float, complex)):
        return 4
    if isinstance(value, (list, tuple)) and value:
        return _xf2p_generic_kind(value[0], None)
    return -1
'''.splitlines():
            self.emit(helper_line)
        if any(spec['optional_allocatable'] for spec in self._binding_targets.values()):
            self.emit(f'{self._optional_absent_name} = object()')
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
        self.emit("class _xf2p_complex_text(str):")
        self.indent += 1
        self.emit('"""Numeric output text, distinct from Fortran CHARACTER values."""')
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
        self.emit("return _xf2p_complex_text(f'({float(np.real(x))!r},{float(np.imag(x))!r})')")
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
        self.emit("return np.asarray(x).dtype.kind in 'USO' if v is None else _xf2p_is_char_scalar(v)")
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
        self.emit("return np.asarray(x).dtype.kind in 'iu' if v is None else _xf2p_is_integer_scalar(v)")
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
        self.emit("return np.asarray(x).dtype.kind == 'f' if v is None else _xf2p_is_real_scalar(v)")
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
        self.emit("return np.asarray(x).dtype.kind == 'b' if v is None else _xf2p_is_logical_scalar(v)")
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
        self.emit("return np.asarray(x).dtype.kind == 'c' if v is None else _xf2p_is_complex_scalar(v)")
        self.indent -= 1
        self.emit("")

        self.emit("def _xf2p_io_items(x):")
        self.indent += 1
        self.emit('"""Flatten list-directed output items the way Fortran prints arrays."""')
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("out = []")
        self.emit("for item in np.ravel(x, order='F'):")
        self.indent += 1
        self.emit("out.extend(_xf2p_io_items(item))")
        self.indent -= 1
        self.emit("return out")
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
        self.emit("if hasattr(x, '__dataclass_fields__') and not isinstance(x, type):")
        self.indent += 1
        self.emit("out = []")
        self.emit("for name in x.__dataclass_fields__:")
        self.indent += 1
        self.emit("out.extend(_xf2p_io_items(getattr(x, name)))")
        self.indent -= 1
        self.emit("return out")
        self.indent -= 1
        self.emit("return [_xf2p_io_scalar(x)]")
        self.indent -= 1
        self.emit("")

        for helper_line in '''def _xf2p_unlimited_format(values, width, final_renderers, more_renderer):
    if not values:
        return final_renderers[0]([])
    pieces = []
    for start in range(0, len(values), width):
        group = values[start:start + width]
        if start + width < len(values):
            pieces.append(more_renderer(group))
        else:
            pieces.append(final_renderers[len(group)](group))
    return ''.join(pieces)
'''.splitlines():
            self.emit(helper_line)
        self.emit("def _xf2p_print_star(*args, file=None):")
        self.indent += 1
        self.emit('"""Approximate Fortran list-directed PRINT/WRITE to stdout or a file."""')
        self.emit("items = []")
        self.emit("for arg in args:")
        self.indent += 1
        self.emit("items.extend(_xf2p_io_items(arg))")
        self.indent -= 1
        self.emit("if not items:")
        self.indent += 1
        self.emit("print(file=file)")
        self.emit("return")
        self.indent -= 1
        self.emit("if all(isinstance(x, str) and not isinstance(x, _xf2p_complex_text) for x in items):")
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
        self.emit("items.extend(_xf2p_io_items(arg))")
        self.indent -= 1
        self.emit("if not items:")
        self.indent += 1
        self.emit("return ''")
        self.indent -= 1
        self.emit("if all(isinstance(x, str) and not isinstance(x, _xf2p_complex_text) for x in items):")
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
        self.emit("def _xf2p_component_array(obj, path, dtype=None):")
        self.indent += 1
        self.emit('"""Project a component path over an array of derived-type values."""')
        self.emit("return _f_component_array(obj, path, dtype=dtype)")
        self.indent -= 1
        self.emit("")
        self.emit("def _xf2p_copy_value(x):")
        self.indent += 1
        self.emit('"""Fortran-style assignment copy for arrays and derived-type values."""')
        self.emit("if isinstance(x, np.ndarray):")
        self.indent += 1
        self.emit("return _f_assign_array(None, x)")
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

        if self._data_handled_count != self._data_statement_count:
            raise ValueError("DATA initialization in an unrecognized or unsupported program unit cannot be translated safely")
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
        if self._forall_stack:
            raise ValueError('FORALL construct without END FORALL')
        if self._where_stack:
            raise ValueError('WHERE construct without END WHERE')
        return self._function_scalar_copyback("\n".join(out_lines).rstrip() + "\n")


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
        file_module_procedures: dict[Path, dict[str, dict[str, str]]] = {}
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
            file_module_procedures[p] = t._module_procedure_exports

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
                procedures = file_module_procedures[provider].get(us.module.lower(), {})
                if any(remote in referenced and canonical != remote for remote, canonical in procedures.items()):
                    print("Transpile: FAIL (USE-associated procedures with qualified module names across separate Python files are not yet supported; combine the module and program into a single Fortran input file)")
                    return 1
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
