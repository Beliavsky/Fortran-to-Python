import re
import sys
from pathlib import Path


def strip_comment(line: str) -> str:
    in_str = False
    quote = ""
    out = []
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
                break
            else:
                out.append(ch)
    return "".join(out).rstrip()


def split_args(s: str) -> list[str]:
    args: list[str] = []
    buf: list[str] = []
    depth = 0
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
            depth += 1
            buf.append(ch)
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
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


_type_scalar_hint = {
    "integer": "int",
    "real": "float",
    "logical": "bool",
    "complex": "complex",
}

_type_default_scalar_value = {
    "integer": "0",
    "real": "0.0",
    "logical": "False",
    "complex": "0j",
}

_type_dtype = {
    "integer": "np.int_",
    "real": "np.float64",
    "logical": "np.bool_",
    "complex": "np.complex128",
}

_type_ndarray_hint = {
    "integer": "npt.NDArray[np.int_]",
    "real": "npt.NDArray[np.float64]",
    "logical": "npt.NDArray[np.bool_]",
    "complex": "npt.NDArray[np.complex128]",
}

_decl_re = re.compile(r"^(integer|real|logical|complex)\b(.*)::(.*)$", re.I)


def parse_decl(line: str):
    m = _decl_re.match(line.strip())
    if not m:
        return None
    ftype = m.group(1).lower()
    attrs = m.group(2).strip()
    rest = m.group(3).strip()
    return ftype, attrs, rest


def parse_decl_items(rest: str):
    items = []
    for part in split_args(rest):
        part = part.strip()
        if not part:
            continue
        init = None
        if "=" in part:
            left, init = part.split("=", 1)
            left = left.strip()
            init = init.strip()
        else:
            left = part.strip()

        shape = None
        mm = re.match(r"^([a-z_]\w*)\s*\(\s*(.+)\s*\)\s*$", left, re.I)
        if mm:
            name = mm.group(1)
            shape = mm.group(2).strip()
        else:
            name = left

        items.append((name, shape, init))
    return items


class basic_f2p:
    def __init__(self) -> None:
        self.out: list[str] = []
        self.indent = 0
        self.seen_parameter = False

    def emit(self, s: str = "") -> None:
        self.out.append((" " * 4 * self.indent) + s if s else "")

    def translate_expr(self, expr: str, arrays_1d: set[str]) -> str:
        s = expr.strip()

        # kind(...) used as a kind selector
        # basic rule: if it uses a d exponent constant, treat it as double precision -> 8
        s = re.sub(r"\bkind\s*\(\s*[^)]*[dD][^)]*\)\s*", "8", s, flags=re.I)

        # fortran d exponent literal -> python e exponent literal
        s = re.sub(
            r"(?i)(\d+(?:\.\d*)?|\.\d+)[d]([+-]?\d+)",
            r"\1e\2",
            s,
        )

        s = re.sub(r"\.true\.", "True", s, flags=re.I)
        s = re.sub(r"\.false\.", "False", s, flags=re.I)
        s = re.sub(r"\.and\.", " and ", s, flags=re.I)
        s = re.sub(r"\.or\.", " or ", s, flags=re.I)
        s = re.sub(r"\.not\.", " not ", s, flags=re.I)

        s = re.sub(r"\bsqrt\s*\(", "np.sqrt(", s, flags=re.I)
        s = re.sub(r"\breal\s*\(", "float(", s, flags=re.I)
        s = re.sub(r"\bint\s*\(", "int(", s, flags=re.I)
        s = re.sub(r"\bsum\s*\(", "np.sum(", s, flags=re.I)

        s = re.sub(r"\bsize\s*\(\s*([a-z_]\w*)\s*\)", r"\1.size", s, flags=re.I)

        # 1d array element: a(i) -> a[(i)-1] (assume 1-based fortran indexing)
        def repl_arr(m: re.Match) -> str:
            name = m.group(1)
            idx = m.group(2)
            if name in arrays_1d:
                idx_py = self.translate_expr(idx, arrays_1d)
                return f"{name}[({idx_py}) - 1]"
            return m.group(0)

        s = re.sub(r"\b([a-z_]\w*)\s*\(\s*([^)]+?)\s*\)", repl_arr, s, flags=re.I)
        return s

    def transpile_assignment(self, lhs: str, rhs_py: str, arrays_1d: set[str]) -> None:
        mm = re.match(r"([a-z_]\w*)\s*\(\s*([^)]+)\s*\)$", lhs, re.I)
        if mm:
            name = mm.group(1)
            idx = mm.group(2)
            if name in arrays_1d:
                idx_py = self.translate_expr(idx, arrays_1d)
                self.emit(f"{name}[({idx_py}) - 1] = {rhs_py}")
                return
        self.emit(f"{lhs} = {rhs_py}")

    def transpile_simple_stmt(self, stmt: str, arrays_1d: set[str]) -> None:
        s = stmt.strip()
        if "=" in s and "::" not in s:
            lhs, rhs = s.split("=", 1)
            lhs = lhs.strip()
            rhs_py = self.translate_expr(rhs, arrays_1d)
            if lhs in arrays_1d and rhs_py in ("True", "False"):
                self.emit(f"{lhs}[:] = {rhs_py}")
                return
            self.transpile_assignment(lhs, rhs_py, arrays_1d)
        else:
            self.emit("# unsupported inline statement")

    def emit_parameters_from_decl(self, ftype: str, attrs_l: str, rest: str, arrays_1d: set[str]) -> set[str]:
        names: set[str] = set()
        if "parameter" not in attrs_l:
            return names
        for name, shape, init in parse_decl_items(rest):
            if init is None:
                continue
            # parameters are named constants: method (2) -> Final
            hint = _type_scalar_hint.get(ftype, "int")
            val = self.translate_expr(init, arrays_1d)
            self.emit(f"{name}: Final[{hint}] = {val}")
            names.add(name)
        return names

    def emit_var_inits_from_sym(self, sym: dict[str, dict], arrays_1d: set[str], parameter_names: set[str]) -> None:
        # allocate explicit-shape arrays and initialize scalars so python is always valid
        for name, info in sym.items():
            if name in parameter_names:
                continue
            ftype = info["ftype"]
            is_array = info["is_array"]
            shape = info["shape"]
            init = info["init"]
            alloc = info["alloc"]

            if is_array:
                # only allocate explicit-shape, non-allocatable arrays
                if alloc:
                    continue
                if shape is None:
                    continue
                if shape.strip() == ":":
                    continue
                dtype = _type_dtype[ftype]
                shape_py = self.translate_expr(shape, arrays_1d)
                hint = _type_ndarray_hint[ftype]
                if init is None:
                    self.emit(f"{name}: {hint} = np.empty({shape_py}, dtype={dtype})")
                else:
                    init_py = self.translate_expr(init, arrays_1d)
                    self.emit(f"{name}: {hint} = np.full({shape_py}, {init_py}, dtype={dtype})")
            else:
                # scalar
                hint = _type_scalar_hint.get(ftype, "int")
                if init is None:
                    default_val = _type_default_scalar_value.get(ftype, "0")
                    self.emit(f"{name}: {hint} = {default_val}")
                else:
                    init_py = self.translate_expr(init, arrays_1d)
                    self.emit(f"{name}: {hint} = {init_py}")

    def handle_exec_line(self, s: str, arrays_1d: set[str]) -> bool:
        sl = s.lower()

        # ignore some non-exec lines
        if sl in ("implicit none", "contains"):
            return True
        if sl.startswith("use "):
            return True
        if sl.startswith("end function") or sl.startswith("end program") or sl.startswith("end module"):
            return True
        if sl == "end":
            return True

        # if (...) then
        mm = re.match(r"if\s*\(\s*(.+)\s*\)\s*then$", s, re.I)
        if mm:
            cond = self.translate_expr(mm.group(1), arrays_1d)
            self.emit(f"if {cond}:")
            self.indent += 1
            return True

        if sl == "else":
            self.indent = max(0, self.indent - 1)
            self.emit("else:")
            self.indent += 1
            return True

        if sl.startswith("end if"):
            self.indent = max(0, self.indent - 1)
            return True

        # do while (...)
        mm = re.match(r"do\s+while\s*\(\s*(.+)\s*\)$", s, re.I)
        if mm:
            cond = self.translate_expr(mm.group(1), arrays_1d)
            self.emit(f"while {cond}:")
            self.indent += 1
            return True

        # do i = a, b
        mm = re.match(r"do\s+([a-z_]\w*)\s*=\s*(.+?)\s*,\s*(.+)$", s, re.I)
        if mm:
            var = mm.group(1)
            a = self.translate_expr(mm.group(2), arrays_1d)
            b = self.translate_expr(mm.group(3), arrays_1d)
            self.emit(f"for {var} in range({a}, ({b}) + 1):")
            self.indent += 1
            return True

        if sl.startswith("end do"):
            self.indent = max(0, self.indent - 1)
            return True

        # allocate(a(n))
        mm = re.match(r"allocate\s*\(\s*([a-z_]\w*)\s*\(\s*([^)]+)\s*\)\s*\)", s, re.I)
        if mm:
            name = mm.group(1)
            sz = self.translate_expr(mm.group(2), arrays_1d)
            # dtype unknown here in exec pass; keep generic if not declared earlier
            self.emit(f"{name} = np.empty({sz})")
            return True

        # call random_number(x)
        mm = re.match(r"call\s+random_number\s*\(\s*([a-z_]\w*)\s*\)\s*$", s, re.I)
        if mm:
            name = mm.group(1)
            if name in arrays_1d:
                self.emit(f"{name}[:] = np.random.random(size={name}.shape)")
            else:
                self.emit(f"{name} = float(np.random.random())")
            return True

        # return
        if sl == "return":
            self.emit("return")
            return True

        # print *, ...
        mm = re.match(r"print\s*\*\s*,\s*(.+)$", s, re.I)
        if mm:
            args2 = []
            for a in split_args(mm.group(1)):
                a = a.strip()
                if a.startswith(("'", '"')):
                    args2.append(a)
                else:
                    args2.append(self.translate_expr(a, arrays_1d))
            self.emit(f"print({', '.join(args2)})")
            return True

        # write(*,*) ...
        mm = re.match(r"write\s*\(\s*\*\s*,\s*\*\s*\)\s*(.+)$", s, re.I)
        if mm:
            args2 = []
            for a in split_args(mm.group(1)):
                a = a.strip()
                if a.startswith(("'", '"')):
                    args2.append(a)
                else:
                    args2.append(self.translate_expr(a, arrays_1d))
            self.emit(f"print({', '.join(args2)})")
            return True

        # single-line if: if (cond) stmt
        mm = re.match(r"if\s*\(\s*(.+?)\s*\)\s+(.+)$", s, re.I)
        if mm and not sl.endswith("then"):
            cond = self.translate_expr(mm.group(1), arrays_1d)
            stmt = mm.group(2).strip()
            self.emit(f"if {cond}:")
            self.indent += 1
            self.transpile_simple_stmt(stmt, arrays_1d)
            self.indent = max(0, self.indent - 1)
            return True

        # assignment
        if "=" in s and "::" not in s:
            lhs, rhs = s.split("=", 1)
            lhs = lhs.strip()
            rhs_py = self.translate_expr(rhs, arrays_1d)
            if lhs in arrays_1d and rhs_py in ("True", "False"):
                self.emit(f"{lhs}[:] = {rhs_py}")
                return True
            self.transpile_assignment(lhs, rhs_py, arrays_1d)
            return True

        return False

    def transpile_function(self, header: str, body_lines: list[str]) -> None:
        m = re.match(
            r"pure\s+function\s+(\w+)\s*\(\s*([^\)]*)\s*\)\s*result\s*\(\s*(\w+)\s*\)",
            header,
            re.I,
        )
        if not m:
            return

        fname = m.group(1)
        args = [a.strip() for a in m.group(2).split(",") if a.strip()]
        result_name = m.group(3)

        sym: dict[str, dict] = {}
        arrays_1d: set[str] = set()
        arg_hints: dict[str, str] = {}
        result_hint = "None"

        # declarations pass
        for line in body_lines:
            s = line.strip()
            pd = parse_decl(s)
            if not pd:
                continue
            ftype, attrs, rest = pd
            attrs_l = attrs.lower()
            items = parse_decl_items(rest)

            for name, shape, init in items:
                is_array = shape is not None
                is_alloc = "allocatable" in attrs_l
                sym[name] = {
                    "ftype": ftype,
                    "is_array": is_array,
                    "shape": shape,
                    "init": init,
                    "alloc": is_alloc,
                    "attrs_l": attrs_l,
                }
                if is_array:
                    arrays_1d.add(name)

                if name in args and "intent(in" in attrs_l:
                    if is_array:
                        arg_hints[name] = _type_ndarray_hint[ftype]
                    else:
                        arg_hints[name] = _type_scalar_hint[ftype]

                if name == result_name:
                    if is_array:
                        result_hint = _type_ndarray_hint[ftype]
                    else:
                        result_hint = _type_scalar_hint[ftype]

        args_annot = []
        for a in args:
            hint = arg_hints.get(a, "int")
            args_annot.append(f"{a}: {hint}")

        self.emit(f"def {fname}({', '.join(args_annot)}) -> {result_hint}:")
        self.indent += 1

        # parameters inside function (if any)
        parameter_names: set[str] = set()
        for line in body_lines:
            s = line.strip()
            pd = parse_decl(s)
            if not pd:
                continue
            ftype, attrs, rest = pd
            attrs_l = attrs.lower()
            if "parameter" in attrs_l:
                parameter_names |= self.emit_parameters_from_decl(ftype, attrs_l, rest, arrays_1d)

        # allocate/init explicit-shape arrays and scalars
        self.emit_var_inits_from_sym(sym, arrays_1d, parameter_names)

        # exec pass
        for line in body_lines:
            s = line.strip()
            if not s:
                continue
            if parse_decl(s):
                continue
            self.handle_exec_line(s, arrays_1d)

        # basic default return (safe)
        self.emit(f"return {result_name}")
        self.indent = max(0, self.indent - 1)
        self.emit("")

    def transpile_program_body(self, body_lines: list[str]) -> None:
        # gather decls and arrays
        sym: dict[str, dict] = {}
        arrays_1d: set[str] = set()

        for line in body_lines:
            s = line.strip()
            if not s:
                continue
            pd = parse_decl(s)
            if not pd:
                continue
            ftype, attrs, rest = pd
            attrs_l = attrs.lower()
            if "parameter" in attrs_l:
                continue
            items = parse_decl_items(rest)
            for name, shape, init in items:
                is_array = shape is not None
                is_alloc = "allocatable" in attrs_l
                sym[name] = {
                    "ftype": ftype,
                    "is_array": is_array,
                    "shape": shape,
                    "init": init,
                    "alloc": is_alloc,
                    "attrs_l": attrs_l,
                }
                if is_array:
                    arrays_1d.add(name)

        # parameters
        parameter_names: set[str] = set()
        for line in body_lines:
            s = line.strip()
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

        # exec statements
        for line in body_lines:
            s = line.strip()
            if not s:
                continue
            if parse_decl(s):
                continue
            self.handle_exec_line(s, arrays_1d)

    def transpile_program(self, body_lines: list[str]) -> None:
        self.emit("def main() -> None:")
        self.indent += 1
        self.transpile_program_body(body_lines)
        self.indent = max(0, self.indent - 1)
        self.emit("")
        self.emit('if __name__ == "__main__":')
        self.emit("    main()")

    def transpile(self, src: str) -> str:
        raw = [strip_comment(l) for l in src.splitlines()]
        self.seen_parameter = any(re.search(r"\bparameter\b", l, re.I) for l in raw)

        self.out = []
        self.indent = 0

        self.emit("import numpy as np")
        self.emit("import numpy.typing as npt")
        if self.seen_parameter:
            self.emit("from typing import Final")
        self.emit("")

        i = 0
        n = len(raw)

        in_module = False
        found_program = False
        loose_main: list[str] = []

        while i < n:
            line = raw[i].strip()
            if not line:
                i += 1
                continue

            if re.match(r"module\b", line, re.I):
                in_module = True
                i += 1
                continue

            if re.match(r"end\s+module\b", line, re.I):
                in_module = False
                i += 1
                continue

            if re.match(r"pure\s+function\b", line, re.I):
                header = line
                body: list[str] = []
                i += 1
                while i < n and not re.match(r"\s*end\s+function\b", raw[i], re.I):
                    body.append(raw[i])
                    i += 1
                if i < n:
                    i += 1
                self.transpile_function(header, body)
                continue

            if re.match(r"program\b", line, re.I):
                found_program = True
                body: list[str] = []
                i += 1
                while i < n and not re.match(r"\s*end\s+program\b", raw[i], re.I):
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
            if any(l.strip() for l in loose_main):
                self.transpile_program(loose_main)

        return "\n".join(self.out).rstrip() + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python xf2p.py input.f90 [output.py]")
        return 2

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else in_path.with_suffix(".py")

    src = in_path.read_text(encoding="utf-8")
    t = basic_f2p()
    py = t.transpile(src)
    out_path.write_text(py, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
