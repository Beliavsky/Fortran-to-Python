import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize("statement, expected", [
    ("use iso_fortran_env", {"int8":1,"int16":2,"int32":4,"int64":8,"real32":4,"real64":8}),
    ("use :: iso_fortran_env, only: int32", {"int32":4}),
    ("use, intrinsic :: iso_fortran_env, only: ik => int64, rk => real64", {"ik":8,"rk":8}),
    ("use iso_fortran_env, only: int8, int16", {"int8":1,"int16":2}),
    ("use iso_fortran_env, ik => int32", {"int8":1,"int16":2,"ik":4,"int64":8,"real32":4,"real64":8}),
    ("use, non_intrinsic :: iso_fortran_env, only: int32", {}),
    ("use my_module, only: int32", {}),
])
def test_kind_import_forms(statement, expected):
    translator = basic_f2p()
    translator._emit_intrinsic_use_aliases([(statement, "")])
    namespace = {}
    exec("\n".join(translator.out), {}, namespace)
    assert namespace == expected
