import itertools
from pathlib import Path

import numpy as np
import pytest

from fortran_py_runtime import _f_array_indices
from xf2p import basic_f2p


@pytest.mark.parametrize("indices", [
    ([2, 0], [3, 1], slice(None)),
    ([2, 0], [3, 1], [4, 0, 2]),
    (slice(None), [3, 1], [4, 0]),
    ([2, 0], slice(None), [4, 0]),
    ([2, 0], 1, [4, 0]),
    (1, [3, 1], slice(None, None, -1)),
    (slice(None, None, -1), 1, [4, 0]),
    ([2, 2, 0], [3, 1], 1),
    (np.array([], dtype=int), [3, 1], slice(None)),
])
def test_cartesian_selection_matches_explicit_product(indices):
    a = np.arange(60).reshape((3, 4, 5))
    axes = [np.arange(a.shape[d])[i] if isinstance(i, slice) else np.asarray(i)
            for d, i in enumerate(indices)]
    shape = tuple(i.size for i in axes if i.ndim)
    expected = np.array([a[tuple(pos)] for pos in itertools.product(
        *(i.tolist() if i.ndim else [i.item()] for i in axes))]).reshape(shape)
    actual = a[_f_array_indices(a, *indices)]
    np.testing.assert_array_equal(actual, expected)


def test_basic_section_stays_a_view():
    a = np.arange(60).reshape((3, 4, 5))
    section = a[_f_array_indices(a, slice(None), 1, slice(None, None, 2))]
    assert np.shares_memory(a, section)
    section[:] = -1
    assert np.all(a[:, 1, ::2] == -1)


def test_cartesian_assignment_writes_original():
    a = np.zeros((3, 4, 5), dtype=int)
    a[_f_array_indices(a, [2, 0], 1, [4, 0])] = [[11, 12], [21, 22]]
    assert (a[2, 1, 4], a[2, 1, 0], a[0, 1, 4], a[0, 1, 0]) == (11, 12, 21, 22)
    assert np.count_nonzero(a) == 4


@pytest.mark.parametrize("index", [[-1], [3], [1.5], [[0, 1]]])
def test_invalid_vectors_rejected(index):
    with pytest.raises((TypeError, IndexError)):
        _f_array_indices(np.zeros((3, 4)), index, slice(None))


def test_translated_vector_subscripts(capsys):
    source = (Path(__file__).parent / "cases/features/vector_subscripts.f90").read_text()
    generated = basic_f2p().transpile(source)
    namespace = {"__name__": "vector_test"}
    exec(generated, namespace)
    namespace["main"]()
    output = capsys.readouterr().out
    assert "vector checks passed" in output
