import pytest

from xf2p import basic_f2p


def test_unit_contains_ignores_binding_section():
    lines = [(s, "") for s in ["type :: counter", "contains",
             "procedure :: increment", "end type counter", "contains"]]
    assert basic_f2p._unit_contains_index(lines) == 4


@pytest.mark.parametrize("statement", ["call value%missing(3)",
                                     "call values(1)%increment(3)"])
def test_unresolved_calls_are_not_silently_dropped(statement):
    with pytest.raises(ValueError, match="unsupported"):
        basic_f2p().handle_exec_line(statement, set())


def test_unsupported_binding_reports_error():
    source = """module m
type :: counter
contains
procedure(interface_name), deferred :: increment
end type counter
end module m
"""
    with pytest.raises(ValueError, match="unsupported deferred binding"):
        basic_f2p().transpile(source)


def test_binding_section_without_module_procedures_is_not_lost():
    source = """module m
type :: counter
contains
procedure :: increment => missing
end type counter
end module m
"""
    with pytest.raises(ValueError, match="no translated procedure"):
        basic_f2p().transpile(source)
