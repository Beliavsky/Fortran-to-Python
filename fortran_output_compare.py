"""Shared stdout comparison for xf2p's CLI and batch runner."""
from __future__ import annotations

import math
import re

NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$")
INTEGER = re.compile(r"^[+-]?\d+$")
SPECIAL = re.compile(r"^[+-]?(?:inf(?:inity)?|nan)$", re.I)
LOGICAL = {"T": True, "True": True, "F": False, "False": False}
REAL_TEXT = rf"(?:{NUMBER.pattern[1:-1]}|{SPECIAL.pattern[1:-1]})"
COMPLEX = re.compile(rf"^\(\s*({REAL_TEXT})\s*,\s*({REAL_TEXT})\s*\)$", re.I)
# A standalone complex pair is one value, even if its components are separated
# by spaces or line wrapping. Embedded labels and malformed pairs remain text.
OUTPUT_TOKEN = re.compile(rf"(?<!\S)\(\s*{REAL_TEXT}\s*,\s*{REAL_TEXT}\s*\)(?!\S)|\S+", re.I)


def validate_tolerances(rtol: float, atol: float) -> None:
    if any(not math.isfinite(value) or value < 0 for value in (rtol, atol)):
        raise ValueError("tolerances must be finite and nonnegative")


def normalized_lines(output: str) -> list[str]:
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in output.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _equal_real(a: str, b: str, rtol: float, atol: float) -> bool:
    x, y = (float(token.lower().replace("d", "e")) for token in (a, b))
    if math.isnan(x) or math.isnan(y):
        return math.isnan(x) and math.isnan(y)
    return math.isclose(x, y, rel_tol=rtol, abs_tol=atol)


def _equal_token(a: str, b: str, rtol: float, atol: float) -> bool:
    if a == b:
        return True
    if a in LOGICAL and b in LOGICAL:
        return LOGICAL[a] == LOGICAL[b]
    if INTEGER.fullmatch(a) and INTEGER.fullmatch(b):
        return int(a) == int(b)
    left, right = COMPLEX.fullmatch(a), COMPLEX.fullmatch(b)
    if left and right:
        return all(_equal_real(x, y, rtol, atol) for x, y in zip(left.groups(), right.groups()))
    if (NUMBER.fullmatch(a) or SPECIAL.fullmatch(a)) and (NUMBER.fullmatch(b) or SPECIAL.fullmatch(b)):
        return _equal_real(a, b, rtol, atol)
    return False


def compare_outputs(reference: str, actual: str, rtol: float = 1e-9,
                    atol: float = 1e-11, *, exact: bool = False) -> dict:
    """Real and complex components are tolerant; T/True and F/False equivalent.

    Default mode ignores whitespace, including line wrapping. Exact mode uses
    normalized lines (the CLI's former behavior), not byte-for-byte equality.
    Matching NaNs and same-sign infinities compare equal.
    Other integers/text are exact. Logical-looking character output cannot be
    distinguished from logical values; use exact=True when spelling matters.
    Likewise, standalone numeric '(real,imaginary)' text is treated as complex.
    """
    validate_tolerances(rtol, atol)
    reference = reference.replace("\r\n", "\n").replace("\r", "\n")
    actual = actual.replace("\r\n", "\n").replace("\r", "\n")
    ref_lines, actual_lines = normalized_lines(reference), normalized_lines(actual)
    if exact:
        for i in range(max(len(ref_lines), len(actual_lines))):
            a = ref_lines[i] if i < len(ref_lines) else None
            b = actual_lines[i] if i < len(actual_lines) else None
            if a != b:
                return dict(status="mismatch", detail=f"Normalized text differs at line {i + 1}",
                            reference_line=i + 1, actual_line=i + 1,
                            reference_text=a, actual_text=b)
        return {"status": "match"}
    ref_tokens = list(OUTPUT_TOKEN.finditer(reference))
    actual_tokens = list(OUTPUT_TOKEN.finditer(actual))
    for index in range(max(len(ref_tokens), len(actual_tokens))):
        a = ref_tokens[index] if index < len(ref_tokens) else None
        b = actual_tokens[index] if index < len(actual_tokens) else None
        if a is not None and b is not None and _equal_token(a.group(), b.group(), rtol, atol):
            continue
        # splitlines/normalization preserve physical line numbers for reporting.
        ref_line = reference[:a.start()].count("\n") + 1 if a else len(ref_lines) + 1
        actual_line = actual[:b.start()].count("\n") + 1 if b else len(actual_lines) + 1
        detail = (f"Token {index + 1}: Fortran {a.group() if a else '<missing>'!r}, "
                  f"Python {b.group() if b else '<missing>'!r}")
        if a is None or b is None:
            detail += f" (Token counts differ: {len(ref_tokens)} vs {len(actual_tokens)})"
        return dict(status="mismatch", detail=detail, token=index + 1,
                    reference_line=ref_line, actual_line=actual_line,
                    reference_text=ref_lines[ref_line - 1] if a else None,
                    actual_text=actual_lines[actual_line - 1] if b else None)
    return {"status": "match"}
