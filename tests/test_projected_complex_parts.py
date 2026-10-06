from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from fortran_py_runtime import _f_assign_component_complex_part
from xf2p import basic_f2p


def test_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/projected_complex_parts.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '1 3.0 4.0 13.0 14.0', '9.0 4.0 13.0 -1.0',
        '7.0 8.0 7.0 8.0', '3.0 4.0 5.0 6.0 2.0 2.0 10.0 10.0',
        '11.0 12.0 13.0 13.0',
    ]


def test_pointer_storage_and_rhs_snapshot():
    storage = np.array([1+2j, 3+4j])
    records = np.array([SimpleNamespace(z=storage[i:i+1].reshape(())) for i in range(2)], dtype=object)
    first = records[0].z
    _f_assign_component_complex_part(records, 'z', storage.real[::-1], 'real')
    assert records[0].z is first
    np.testing.assert_array_equal(storage, [3+2j, 1+4j])
    _f_assign_component_complex_part(records, 'z', 9, 'imag', mask=[False, True])
    np.testing.assert_array_equal(storage, [3+2j, 1+9j])


@pytest.mark.parametrize('argument', ['rhs', 'mask'])
def test_nonconforming_shape_is_rejected_before_writes(argument):
    records = np.array([SimpleNamespace(z=1+2j), SimpleNamespace(z=3+4j)], dtype=object)
    with pytest.raises(ValueError, match='conformable'):
        _f_assign_component_complex_part(records, 'z',
                                        [[5, 6]] if argument == 'rhs' else 5,
                                        'real', mask=[[True, False]] if argument == 'mask' else None)
    assert [item.z for item in records] == [1+2j, 3+4j]


def test_empty_projection():
    _f_assign_component_complex_part(np.array([], dtype=object), 'z', [], 'real')


def test_array_components_remain_rejected():
    records = np.array([SimpleNamespace(z=np.array([1+2j]))], dtype=object)
    with pytest.raises(ValueError, match='explicit subscripts'):
        _f_assign_component_complex_part(records, 'z', 3, 'real')


def test_array_component_projection_is_diagnosed():
    with pytest.raises(ValueError, match='explicit subscripts'):
        basic_f2p().transpile('''program main
type :: box
complex :: z(2)
end type
type(box) :: records(2)
records%z%re = 3.0
end program
''')
