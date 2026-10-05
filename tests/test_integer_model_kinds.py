import contextlib
import io
from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_numeric_model
from xf2p import basic_f2p


@pytest.mark.parametrize("kind", [1, 2, 4, 8])
def test_integer_model_uses_kind_not_value(kind):
    info = np.iinfo(f"int{8 * kind}")
    assert _f_numeric_model(None, "huge", integer_kind=kind) == info.max
    assert _f_numeric_model(np.int64(0), "digits", integer_kind=kind) == info.bits - 1
    assert _f_numeric_model(None, "range", integer_kind=kind) == len(str(info.max)) - 1
    assert _f_numeric_model(None, "radix", integer_kind=kind) == 2


def test_unsupported_integer_model_kind_is_explicit():
    with pytest.raises(ValueError, match="unsupported Fortran integer kind"):
        _f_numeric_model(None, "huge", integer_kind=16)


@pytest.mark.parametrize("declaration, argument, expected", [
    ("integer :: i", "i", 2147483647),
    ("integer*4 :: i", "i", 2147483647),
    ("integer*8 :: i", "i", 9223372036854775807),
    ("integer(kind=1) :: i", "i", 127),
    ("integer(2) :: i", "i", 32767),
    ("integer(kind=int32) :: i", "i", 2147483647),
    ("integer(kind=wide) :: i", "i", 9223372036854775807),
    ("integer(kind=int16) :: i(0:2)", "i", 32767),
    ("integer(kind=int16) :: i(0:2)", "i(0)", 32767),
    ("integer(kind=int16), allocatable :: i(:)", "i", 32767),
    ("integer(kind=int64) :: i", "i+1", 9223372036854775807),
    ("integer :: i", "i+1_int64", 9223372036854775807),
    ("integer :: i", "1_int64+i", 9223372036854775807),
    ("integer(kind=int64) :: i", "-i", 9223372036854775807),
    ("integer(kind=int16) :: i", "i**2", 2147483647),
    ("integer(kind=int16) :: i", "i**2_int16", 32767),
    ("integer(kind=int64) :: i", "i/2", 9223372036854775807),
    ("integer :: i", "0", 2147483647),
    ("integer :: i", "0_int8", 127),
    ("integer :: i", "0_int64", 9223372036854775807),
    ("integer :: i", "x=0_2", 32767),
])
def test_declared_and_literal_integer_models(declaration, argument, expected):
    source = ("program demo\n"
              "use iso_fortran_env, only: int8,int16,int32,int64,wide=>int64\n"
              "implicit none\n" + declaration + "\n"
              f"print *, huge({argument})\nend program\n")
    generated = basic_f2p().transpile(source)
    assert "integer_kind=" in generated
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(generated, {"__name__": "__main__"})
    assert int(output.getvalue()) == expected


def test_native_integer_model_fixture(capsys):
    source = (Path(__file__).parent / "cases/features/integer_model_kinds.f90").read_text()
    generated = basic_f2p().transpile(source)
    exec(generated, {"__name__": "__main__"})
    assert "integer model checks passed" in capsys.readouterr().out


def test_model_inquiry_spelling_in_strings_is_unchanged(capsys):
    source = "program demo\nprint *, 'huge(0_int64) digits(i) range(i) radix(i)'\nend program"
    exec(basic_f2p().transpile(source), {"__name__": "__main__"})
    assert capsys.readouterr().out.strip() == "huge(0_int64) digits(i) range(i) radix(i)"
