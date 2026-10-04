import numpy as np
import pytest

from fortran_py_runtime import (
    _f_product, _f_unpack, _f_cshift, _f_eoshift, _f_adjustr, _f_scan,
    _f_verify, _f_repeat, _f_is_contiguous, _f_contiguous_arguments,
    _f_command_argument_count, _f_get_command_argument, _f_bits,
)
from xf2p import basic_f2p


@pytest.mark.parametrize('dtype', [np.int32, np.int64, np.float32, np.float64, np.complex128])
def test_product_type_dim_mask_and_empty(dtype):
    a = np.array([[1, 3, 5], [2, 4, 6]], dtype=dtype)
    assert _f_product(a).dtype == a.dtype
    assert _f_product(a) == 720
    np.testing.assert_array_equal(_f_product(a, dim=1), [2, 12, 30])
    np.testing.assert_array_equal(_f_product(a, dim=2), [15, 48])
    assert _f_product(a, mask=np.array([[True, True, False], [False, False, True]])) == 18
    assert _f_product(a, False) == 1
    assert _f_product(np.empty((0, 2), dtype=dtype)) == 1
    np.testing.assert_array_equal(_f_product(np.empty((0, 2), dtype=dtype), dim=1), [1, 1])
    with pytest.raises(ValueError): _f_product(a, mask=[True, False])
    with pytest.raises(ValueError): _f_product(a, dim=0)


def test_unpack_uses_fortran_element_order_and_field():
    mask = np.array([[True, False], [True, True]])
    np.testing.assert_array_equal(_f_unpack([10, 20, 30, 999], mask, -1), [[10, -1], [20, 30]])
    field = np.array([[1, 2], [3, 4]])
    np.testing.assert_array_equal(_f_unpack([10, 20, 30], mask, field), [[10, 2], [20, 30]])
    assert _f_unpack([], np.zeros((0, 2), dtype=bool), 0).shape == (0, 2)
    np.testing.assert_array_equal(_f_unpack([True], [False, True], False), [False, True])
    with pytest.raises(ValueError): _f_unpack([1], mask, 0)
    with pytest.raises(ValueError): _f_unpack([1, 2, 3], mask, [1, 2])


@pytest.mark.parametrize('shift, circular, endoff', [
    (1, [2, 3, 4, 1], [2, 3, 4, -1]),
    (-1, [4, 1, 2, 3], [-1, 1, 2, 3]),
    (0, [1, 2, 3, 4], [1, 2, 3, 4]),
    (5, [2, 3, 4, 1], [-1, -1, -1, -1]),
    (-5, [4, 1, 2, 3], [-1, -1, -1, -1]),
])
def test_scalar_shifts(shift, circular, endoff):
    np.testing.assert_array_equal(_f_cshift([1, 2, 3, 4], shift), circular)
    np.testing.assert_array_equal(_f_eoshift([1, 2, 3, 4], shift, -1), endoff)


def test_shift_arrays_dimensions_and_default_boundaries():
    a = np.array([[1, 3, 5], [2, 4, 6]])
    np.testing.assert_array_equal(_f_cshift(a, [1, -1], dim=2), [[3, 5, 1], [6, 2, 4]])
    np.testing.assert_array_equal(_f_eoshift(a, [1, -1], [9, 8], dim=2), [[3, 5, 9], [8, 2, 4]])
    np.testing.assert_array_equal(_f_cshift(a, [1, 0, -1]), [[2, 3, 6], [1, 4, 5]])
    np.testing.assert_array_equal(_f_eoshift(['ab', 'cd'], 1), ['cd', '  '])
    np.testing.assert_array_equal(_f_eoshift([True, True], -1), [False, True])
    assert _f_cshift(np.empty((2, 0)), 1, dim=2).shape == (2, 0)
    assert _f_eoshift(np.empty((0, 2)), 1).shape == (0, 2)
    with pytest.raises(ValueError): _f_cshift(a, [1, 2, 3], dim=2)
    with pytest.raises(ValueError): _f_eoshift(a, 1, [1, 2], dim=1)
    with pytest.raises(ValueError): _f_cshift(a, 1, dim=0)


def test_string_intrinsics_blanks_search_back_and_kind():
    assert _f_adjustr('  ab  ') == '    ab'
    np.testing.assert_array_equal(_f_adjustr(['ab ', ' c ']), [' ab', '  c'])
    assert _f_scan('banana', 'an') == 2
    assert _f_scan('banana', 'an', back=True) == 6
    assert _f_verify('123x5', '0123456789') == 4
    assert _f_verify('xx123x', '0123456789', back=True) == 6
    assert _f_scan('', '') == 0
    assert _f_verify('abc', '') == 1
    assert _f_verify('abc', '', back=True) == 3
    np.testing.assert_array_equal(_f_scan(['abc', 'bac'], 'a'), [1, 2])
    assert _f_scan('abc', 'a', kind=8).dtype == np.int64
    assert _f_repeat('a ', 2) == 'a a '
    assert _f_repeat('ab', 0) == ''
    with pytest.raises(ValueError): _f_repeat('a', -1)


def test_contiguous_temporary_copies_back_on_early_return():
    a = np.arange(8)
    assert _f_is_contiguous(a)
    assert not _f_is_contiguous(a[::2])
    assert _f_is_contiguous(a[:0])
    @_f_contiguous_arguments(('x', True))
    def update(x):
        assert _f_is_contiguous(x)
        x[:] = 99
        return 7
    assert update(x=a[::2]) == 7
    np.testing.assert_array_equal(a, [99, 1, 99, 3, 99, 5, 99, 7])
    @_f_contiguous_arguments(('x', False))
    def inspect(x):
        assert _f_is_contiguous(x)
        x[:] = -1
    inspect(a[::2])
    assert a[0] == 99


def test_command_argument_outputs(monkeypatch):
    monkeypatch.setattr('sys.argv', ['program.py', 'long argument', ''])
    assert _f_command_argument_count() == 2
    assert _f_get_command_argument(1, 4) == ('long', 13, -1)
    assert _f_get_command_argument(1) == ('long argument', 13, 0)
    assert _f_get_command_argument(2, 4) == ('    ', 0, 0)
    assert _f_get_command_argument(4, 4) == ('    ', 0, 1)
    assert _f_get_command_argument(0)[0] == 'program.py'


@pytest.mark.parametrize('bits', [8, 16, 32, 64])
def test_signed_word_bits_and_logical_right_shift(bits):
    assert _f_bits('btest', -1, pos=bits - 1, bits=bits)
    assert _f_bits('shiftr', -1, shift=bits - 1, bits=bits) == 1
    assert _f_bits('shiftl', 1, shift=bits - 1, bits=bits) == -(1 << (bits - 1))
    assert _f_bits('ibclr', -1, pos=bits - 1, bits=bits) == (1 << (bits - 1)) - 1
    assert _f_bits('ibits', -1, pos=0, length=bits, bits=bits) == -1
    assert _f_bits('shiftr', -1, shift=bits, bits=bits) == 0
    assert _f_bits('shiftl', 1, shift=bits, bits=bits) == 0


def test_bit_arrays_and_validation():
    np.testing.assert_array_equal(_f_bits('btest', [10, 11], pos=[0, 1]), [False, True])
    np.testing.assert_array_equal(_f_bits('ibset', [10, 12], pos=0), [11, 13])
    assert _f_bits('ibits', 10, pos=1, length=2) == 1
    assert _f_bits('iand', 12, j=10) == 8
    assert _f_bits('ior', 12, j=10) == 14
    assert _f_bits('ieor', 12, j=10) == 6
    assert _f_bits('ibits', 10, pos=32, length=0) == 0
    with pytest.raises(ValueError): _f_bits('btest', 1, pos=32)
    with pytest.raises(ValueError): _f_bits('ibits', 1, pos=31, length=2)


@pytest.mark.parametrize('expression', ['product()', 'cshift([1], 1, dim=1, dim=2)',
    'unpack([1], [.true.])', 'command_argument_count(1)', 'btest(1, unknown=2)'])
def test_invalid_intrinsic_arguments_are_diagnosed(expression):
    with pytest.raises(ValueError): basic_f2p().translate_expr(expression, set())


def test_move_alloc_preserves_identity_and_unallocates_source():
    source = '''program p
integer, allocatable :: a(:), b(:)
a = [1,2,3]
call move_alloc(from=a, to=b)
end program'''
    translated = basic_f2p().transpile(source)
    assert 'b, a = a, None' in translated
    assert 'move_alloc(' not in translated


def test_translated_command_argument_keywords(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['program.py', 'abcdef'])
    source = '''program p
character(len=3) :: arg
integer :: n, stat
call get_command_argument(status=stat, number=1, length=n, value=arg)
print *, arg, n, stat, command_argument_count()
call get_command_argument(number=1, length=n, status=stat)
print *, n, stat
end program'''
    namespace = {'__name__': 'argument_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['abc', '6', '-1', '1', '6', '0']


@pytest.mark.parametrize('kind, position', [('int8', 7), ('int16', 15), ('int32', 31), ('int64', 63)])
def test_translated_declared_integer_kind_bits(kind, position, capsys):
    source = f'''program p
use iso_fortran_env, only: {kind}
integer(kind={kind}) :: x
x = -1
print *, shiftr(i=x, shift={position}), merge(1,0,btest(i=x,pos={position}))
end program'''
    namespace = {'__name__': 'bit_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['1', '1']


def test_move_alloc_rejects_nonallocatable_and_components():
    for declarations, statement in [
        ('integer :: a(2), b(2)', 'call move_alloc(a,b)'),
        ('integer, allocatable :: a(:), b(:)', 'call move_alloc(a,a)'),
        ('integer, allocatable :: a(:), b(:)', 'call move_alloc(a%values,b)'),
    ]:
        with pytest.raises(ValueError, match='MOVE_ALLOC'):
            basic_f2p().transpile(f'program p\n{declarations}\n{statement}\nend program')


def test_move_alloc_scalar_and_identity_at_execution(capsys):
    source = '''program p
integer, allocatable :: a, b
allocate(a)
a = 17
call move_alloc(a,b)
print *, b, merge(1,0,allocated(a)), merge(1,0,allocated(b))
end program'''
    namespace = {'__name__': 'move_test'}
    exec(basic_f2p().transpile(source), namespace)
    namespace['main']()
    assert capsys.readouterr().out.split() == ['17', '0', '1']


def test_bit_literal_kinds_are_not_python_digit_separators():
    translated = basic_f2p().translate_expr('iand(-1_8, 1_8)', set())
    assert eval(translated, {'_f_bits': _f_bits}) == 1
    translated = basic_f2p().translate_expr('btest(2_4, 1_4)', set())
    assert eval(translated, {'_f_bits': _f_bits})
    translated = basic_f2p().translate_expr('shiftr(-1_8, 63)', set())
    assert eval(translated, {'_f_bits': _f_bits}) == 1
    translated = basic_f2p().translate_expr('inspect(shiftr(shift=63,i=-1_int64))', set())
    assert eval(translated, {'_f_bits': _f_bits, 'int64': 8, 'inspect': lambda x: x}) == 1
    translated = basic_f2p().translate_expr("inspect('1_8',shiftr(-1_8,63))", set())
    assert eval(translated, {'_f_bits': _f_bits, 'inspect': lambda *args: args}) == ('1_8', 1)
