import pytest

from xf2p import basic_f2p


@pytest.mark.parametrize("target, expected", [
    ("a", "np.asarray(value, dtype=int)"),
    ("a(2:3)", "np.asarray(value, dtype=int)"),
    ("a(:,1)", "np.asarray(value, dtype=int)"),
    ("a(2)", "int(value)"),
    ("a(1,2)", "int(value)"),
    ("scalar", "int(value)"),
    ("real_value", "value"),
])
def test_integer_conversion_depends_on_target_rank(target, expected):
    translator = basic_f2p()
    translator._decl_types = {"a": "integer", "scalar": "integer", "real_value": "real"}
    translator._decl_array_types = {"a": "integer"}
    assert translator._integer_assignment_rhs(target, "value", {"a"}) == expected
