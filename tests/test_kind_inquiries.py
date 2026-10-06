from pathlib import Path

import numpy as np
import pytest

from xf2p import basic_f2p


def execute(source):
    translated = basic_f2p().transpile(source)
    namespace = {'__name__': '__main__'}
    exec(translated, namespace)
    return translated


def test_inquiries_do_not_evaluate_arguments(capsys):
    source = (Path(__file__).parent / 'cases/features/kind_inquiries.f90').read_text()
    generated = execute(source)
    assert capsys.readouterr().out.splitlines() == [
        '4 8 4 8 8', '4 8 8 8 8', '4 8 16 1 8', '1 8 4 1 1 1',
        '8 8 4', '8 8 8 8', '8 8 8', '8 0 8 8', '4 8 4 8',
    ]
    main_body = generated.split('def main()', 1)[1]
    assert 'value()' not in main_body
    assert 'matmul(' not in main_body


@pytest.mark.parametrize('expression,expected', [
    ('kind(1.0)', 4), ('kind(1.0d0)', 8), ('kind(-2_8)', 8),
    ('kind(.true.)', 4), ('kind(.false._2)', 2), ('kind("world")', 1),
    ('kind(4_"world")', 4), ('kind((1.0d0, 2.0d0))', 8),
    ('kind(sqrt(1.0d0))', 8), ('kind(abs((1.0d0, 2.0d0)))', 8),
    ('kind(real(1,kind=8) + 2.0)', 8), ('kind(1.0 < 2.0)', 4),
    ('kind(kind(1.0d0))', 4), ('kind(x=1.0d0)', 8),
    ('kind(max(1.0d0, 2.0d0))', 8), ('kind(aimag(z=(1.0d0, 2.0d0)))', 8),
    ('kind(1 / 0)', 4), ('kind(huge(1_8))', 8), ('kind(exponent(1.0d0))', 4),
    ('kind((1.0d0, 2.0d0) + (3.0, 4.0))', 8), ('kind("a" // "b")', 1),
    ('kind(any(mask=[.true._8]))', 8), ('kind(all([.true._1]))', 1),
    ('kind(aint(1.0d0, kind=4))', 4), ('kind(anint(1.0d0, 4))', 4),
    ('kind(dot_product([.true._8], [.false._8]))', 8),
    ('kind(matmul(reshape([.true._8],[1,1]),reshape([.false._8],[1,1])))', 4),
    ('kind(.true._8 .eqv. .false._8)', 8),
])
def test_literal_and_expression_kinds(expression, expected):
    assert eval(basic_f2p().translate_expr(expression, set()), {'np': np}) == expected


def test_old_regex_did_not_mean_any_d_in_argument_was_double(capsys):
    execute('''program main
real :: default_value
print *, kind(default_value), 'kind(1.0d0)', kind('word')
end program
''')
    assert capsys.readouterr().out.splitlines() == ['4 kind(1.0d0) 1']


def test_unknown_kind_is_diagnosed():
    with pytest.raises(ValueError, match='cannot determine Fortran KIND'):
        basic_f2p().translate_expr('kind(mystery())', set())


def test_user_function_named_kind_is_not_intrinsic(capsys):
    execute('''program main
print *, kind(2)
contains
integer function kind(x)
integer, intent(in) :: x
kind=x+10
end function
end program
''')
    assert capsys.readouterr().out.splitlines() == ['12']


def test_array_named_kind_is_not_intrinsic(capsys):
    execute('''program main
integer :: kind(2)=[11,12]
print *, kind(1)
end program
''')
    assert capsys.readouterr().out.splitlines() == ['11']


def test_components_and_named_character_kind(capsys):
    execute('''program main
type box
real(8) :: number
character(len=3,kind=1) :: text
end type
type(box) :: b
print *, kind(b%number), kind(b%text)
end program
''')
    assert capsys.readouterr().out.splitlines() == ['8 1']
