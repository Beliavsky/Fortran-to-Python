from __future__ import annotations

import fortran_scan as fscan


def test_parse_procedures_recognizes_typed_function_header() -> None:
    procedures = fscan.parse_procedures(
        [
            "real(dp) pure function value_at(x) result(value)",
            "  real(dp), intent(in) :: x",
            "  value = x",
            "end function value_at",
        ]
    )

    assert len(procedures) == 1
    assert procedures[0].name == "value_at"
    assert procedures[0].kind == "function"
    assert "pure" in procedures[0].attrs
