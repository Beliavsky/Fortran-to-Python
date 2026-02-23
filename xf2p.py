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
    args = []
    buf = []
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


class transpiler:
    def __init__(self) -> None:
        self.out: list[str] = []
        self.indent = 0
        self.block_stack: list[dict] = []
        self.arr_index_style: dict[str, str] = {}
        self.seen_parameter = False
        self.in_main = False
        self.current_result_var = None

    def emit(self, s: str = "") -> None:
        self.out.append((" " * 4 * self.indent) + s if s else "")

    def translate_index(self, name: str, idx: str) -> str:
        style = self.arr_index_style.get(name, "same")
        idx_py = self.translate_expr(idx)
        if style == "minus1":
            return f"{name}[{idx_py} - 1]"
        return f"{name}[{idx_py}]"

    def translate_expr(self, expr: str) -> str:
        e = expr.strip()

        # booleans
        e = re.sub(r"\.true\.", "True", e, flags=re.I)
        e = re.sub(r"\.false\.", "False", e, flags=re.I)

        # logical ops (not used in your sample, but cheap to include)
        e = re.sub(r"\.and\.", " and ", e, flags=re.I)
        e = re.sub(r"\.or\.", " or ", e, flags=re.I)
        e = re.sub(r"\.not\.", " not ", e, flags=re.I)

        # intrinsics
        e = re.sub(r"\bsqrt\s*\(", "np.sqrt(", e, flags=re.I)
        e = re.sub(r"\breal\s*\(", "float(", e, flags=re.I)
        e = re.sub(r"\bint\s*\(", "int(", e, flags=re.I)

        # size(x) -> x.size  (only handles simple var arg)
        def repl_size(m: re.match) -> str:
            var = m.group(1)
            return f"{var}.size"

        e = re.sub(r"\bsize\s*\(\s*([a-z_]\w*)\s*\)", repl_size, e, flags=re.I)

        # array element references: name(i) -> name[i] or name[i-1]
        # only for names we have marked as arrays
        def repl_arr(m: re.match) -> str:
            name = m.group(1)
            idx = m.group(2)
            if name in self.arr_index_style:
                return self.translate_index(name, idx)
            return m.group(0)

        e = re.sub(r"\b([a-z_]\w*)\s*\(\s*([^)]+?)\s*\)", repl_arr, e, flags=re.I)

        return e

    def handle_line(self, line: str) -> None:
        raw = strip_comment(line)
        if not raw.strip():
            return

        s = raw.strip()
        sl = s.lower()

        # ignore module scaffolding
        if sl.startswith("module "):
            return
        if sl == "contains":
            return
        if sl.startswith("end module"):
            return
        if sl.startswith("use "):
            return
        if sl == "implicit none":
            return

        # function start
        m = re.match(r"pure\s+function\s+(\w+)\s*\(\s*([^\)]*)\s*\)\s*result\s*\(\s*(\w+)\s*\)", s, flags=re.I)
        if m:
            name = m.group(1)
            args = [a.strip() for a in m.group(2).split(",") if a.strip()]
            result_var = m.group(3)
            self.current_result_var = result_var
            arglist = ", ".join(args) if args else ""
            self.emit(f"def {name}({arglist}):")
            self.indent += 1
            self.block_stack.append({"type": "function", "result": result_var})
            return

        # function end
        if sl.startswith("end function"):
            # ensure function returns its result variable
            if self.current_result_var:
                self.emit(f"return {self.current_result_var}")
            self.current_result_var = None
            self.indent = max(0, self.indent - 1)
            if self.block_stack and self.block_stack[-1]["type"] == "function":
                self.block_stack.pop()
            self.emit("")
            return

        # program start/end
        m = re.match(r"program\s+(\w+)", s, flags=re.I)
        if m:
            self.in_main = True
            self.emit("def main():")
            self.indent += 1
            self.block_stack.append({"type": "program"})
            return

        if sl.startswith("end program"):
            self.indent = max(0, self.indent - 1)
            if self.block_stack and self.block_stack[-1]["type"] == "program":
                self.block_stack.pop()
            self.emit("")
            self.emit('if __name__ == "__main__":')
            self.emit("    main()")
            self.in_main = False
            return

        # parameter (named constant) -> method (2): Final
        m = re.match(r"integer\s*,\s*parameter\s*::\s*([a-z_]\w*)\s*=\s*(.+)$", s, flags=re.I)
        if m:
            name = m.group(1)
            val = self.translate_expr(m.group(2))
            self.seen_parameter = True
            self.emit(f"{name}: Final[int] = {val}")
            return

        # declarations: record allocatable arrays we must index-adjust
        # for this example:
        # - is_prime is allocated as n but used with indices 1..n; we will allocate n+1 and use direct indices
        # - p is allocated as cnt but used with indices 1..cnt; we store 0-based and translate p(i) -> p[i-1]
        if re.match(r"(integer|logical)\s*,\s*allocatable\s*::", s, flags=re.I):
            # try to pull names like "p(:)" or "is_prime(:)"
            after = s.split("::", 1)[1]
            names = [x.strip() for x in after.split(",")]
            for nm in names:
                nm0 = nm.split("(", 1)[0].strip()
                if nm0.lower() == "p":
                    self.arr_index_style["p"] = "minus1"
                elif nm0.lower() == "is_prime":
                    self.arr_index_style["is_prime"] = "same"
            return

        # allocate(var(expr))
        m = re.match(r"allocate\s*\(\s*([a-z_]\w*)\s*\(\s*([^)]+)\s*\)\s*\)", s, flags=re.I)
        if m:
            var = m.group(1)
            sz = self.translate_expr(m.group(2))
            if var.lower() == "is_prime":
                # allocate n+1 so we can use fortran indices directly (1..n) as python indices
                self.arr_index_style.setdefault(var, "same")
                self.emit(f"{var} = np.empty(({sz}) + 1, dtype=bool)")
            elif var.lower() == "p":
                self.arr_index_style.setdefault(var, "minus1")
                self.emit(f"{var} = np.empty({sz}, dtype=int)")
            else:
                self.emit(f"{var} = np.empty({sz})")
            return

        # if (...) then
        m = re.match(r"if\s*\(\s*(.+)\s*\)\s*then$", s, flags=re.I)
        if m:
            cond = self.translate_expr(m.group(1))
            self.emit(f"if {cond}:")
            self.indent += 1
            self.block_stack.append({"type": "if"})
            return

        # else
        if sl == "else":
            self.indent = max(0, self.indent - 1)
            self.emit("else:")
            self.indent += 1
            return

        # end if
        if sl.startswith("end if"):
            self.indent = max(0, self.indent - 1)
            if self.block_stack and self.block_stack[-1]["type"] == "if":
                self.block_stack.pop()
            return

        # do while (...)
        m = re.match(r"do\s+while\s*\(\s*(.+)\s*\)$", s, flags=re.I)
        if m:
            cond = self.translate_expr(m.group(1))
            self.emit(f"while {cond}:")
            self.indent += 1
            self.block_stack.append({"type": "do"})
            return

        # do i = a, b  (no step needed for your sample)
        m = re.match(r"do\s+([a-z_]\w*)\s*=\s*(.+?)\s*,\s*(.+)$", s, flags=re.I)
        if m:
            var = m.group(1)
            a = self.translate_expr(m.group(2))
            b = self.translate_expr(m.group(3))
            self.emit(f"for {var} in range({a}, ({b}) + 1):")
            self.indent += 1
            self.block_stack.append({"type": "do"})
            return

        # end do
        if sl.startswith("end do"):
            self.indent = max(0, self.indent - 1)
            if self.block_stack and self.block_stack[-1]["type"] == "do":
                self.block_stack.pop()
            return

        # return (inside function)
        if sl == "return":
            rv = self.current_result_var if self.current_result_var else ""
            self.emit(f"return {rv}".rstrip())
            return

        # print *, ...
        m = re.match(r"print\s*\*\s*,\s*(.+)$", s, flags=re.I)
        if m:
            args = [self.translate_expr(a) if not a.strip().startswith(('"', "'")) else a.strip() for a in split_args(m.group(1))]
            self.emit(f"print({', '.join(args)})")
            return

        # write(*,*) ...
        m = re.match(r"write\s*\(\s*\*\s*,\s*\*\s*\)\s*(.+)$", s, flags=re.I)
        if m:
            args = [self.translate_expr(a) if not a.strip().startswith(('"', "'")) else a.strip() for a in split_args(m.group(1))]
            self.emit(f"print({', '.join(args)})")
            return

        # single-line if: if (cond) stmt
        m = re.match(r"if\s*\(\s*(.+?)\s*\)\s+(.+)$", s, flags=re.I)
        if m and not s.lower().endswith("then"):
            cond = self.translate_expr(m.group(1))
            stmt = m.group(2).strip()
            self.emit(f"if {cond}:")
            self.indent += 1
            self.handle_line(stmt)
            self.indent = max(0, self.indent - 1)
            return

        # assignment
        if "=" in s and "::" not in s:
            lhs, rhs = s.split("=", 1)
            lhs = lhs.strip()
            rhs = rhs.strip()

            # whole-array assignment to True/False
            rhs_py = self.translate_expr(rhs)
            lhs_py = lhs

            m = re.match(r"([a-z_]\w*)\s*\(\s*([^)]+)\s*\)$", lhs, flags=re.I)
            if m:
                name = m.group(1)
                idx = m.group(2)
                lhs_py = self.translate_index(name, idx)

            # is_prime = True -> is_prime[:] = True
            if lhs.lower() in self.arr_index_style and rhs_py in ("True", "False"):
                self.emit(f"{lhs}[:] = {rhs_py}")
                if lhs.lower() == "is_prime":
                    # make index 0 safe
                    self.emit(f"{lhs}[0] = False")
                return

            self.emit(f"{lhs_py} = {rhs_py}")
            return

        # everything else: ignore (or raise)
        return

    def transpile(self, src: str) -> str:
        self.out = []
        self.indent = 0
        self.block_stack = []
        self.arr_index_style = {}
        self.seen_parameter = False
        self.in_main = False
        self.current_result_var = None

        lines = src.splitlines()

        # first pass (cheap): detect allocatable arrays so indexing rules exist early
        for line in lines:
            raw = strip_comment(line).strip()
            if not raw:
                continue
            if re.match(r"(integer|logical)\s*,\s*allocatable\s*::", raw, flags=re.I):
                after = raw.split("::", 1)[1]
                names = [x.strip() for x in after.split(",")]
                for nm in names:
                    nm0 = nm.split("(", 1)[0].strip().lower()
                    if nm0 == "p":
                        self.arr_index_style["p"] = "minus1"
                    if nm0 == "is_prime":
                        self.arr_index_style["is_prime"] = "same"
            if re.match(r"integer\s*,\s*parameter\s*::", raw, flags=re.I):
                self.seen_parameter = True

        # header
        self.emit("import numpy as np")
        if self.seen_parameter:
            self.emit("from typing import Final")
        self.emit("")

        # main pass
        for line in lines:
            self.handle_line(line)

        return "\n".join(self.out).rstrip() + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python f2py_basic.py input.f90 [output.py]")
        return 2

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else in_path.with_suffix(".py")

    src = in_path.read_text(encoding="utf-8")
    t = transpiler()
    py = t.transpile(src)
    out_path.write_text(py, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())