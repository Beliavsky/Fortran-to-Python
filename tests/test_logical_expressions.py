import numpy as np
import pytest

from xf2p import basic_f2p


def evaluate(expression, **values):
    translated = basic_f2p().translate_expr(expression, set(values))
    return eval(translated, {'np': np, **values})


@pytest.mark.parametrize('expression, expected', [
    ('x >= 0.0 .and. x < 1.0', [False, True, True, False]),
    ('x < 0.0 .or. x >= 1.0', [True, False, False, True]),
    ('.not. x >= 0.0', [True, False, False, False]),
    ('.not. (x >= 0.0 .and. x < 1.0)', [True, False, False, True]),
    ('x < 0 .or. x >= 0 .and. x < 1', [True, True, True, False]),
    ('(x < 0 .or. x >= 0) .and. x < 1', [True, True, True, False]),
    ('.not. (.not. (x < 0))', [True, False, False, False]),
    ('.NOT. (x .LT. 0 .OR. x .GE. 1)', [False, True, True, False]),
])
def test_compound_array_comparisons(expression, expected):
    np.testing.assert_array_equal(evaluate(expression, x=np.array([-1., 0., .5, 1.])), expected)


@pytest.mark.parametrize('shape', [(4,), (2, 2), (1, 2, 2), (0, 2)])
def test_elementwise_operations_preserve_rank(shape):
    a = (np.arange(np.prod(shape)).reshape(shape) % 2 == 0)
    b = np.zeros(shape, dtype=bool)
    np.testing.assert_array_equal(evaluate('a .and. .not. b', a=a, b=b), a)
    np.testing.assert_array_equal(evaluate('a .or. b', a=a, b=b), a)
    np.testing.assert_array_equal(evaluate('.not. a', a=a), np.logical_not(a))


@pytest.mark.parametrize('expression, expected', [
    ('a .and. .true.', [True, False]), ('.true. .and. a', [True, False]),
    ('a .or. .false.', [True, False]), ('.false. .or. a', [True, False]),
    ('a .and. .false.', [False, False]), ('.true. .or. a', [True, True]),
])
def test_mixed_scalar_array_operands(expression, expected):
    np.testing.assert_array_equal(evaluate(expression, a=np.array([True, False])), expected)


@pytest.mark.parametrize('expression, expected', [
    ('.true. .and. .false.', False), ('.true. .or. .false.', True),
    ('.not. .true.', False), ('.not. .false.', True),
    ('.true. .or. .false. .and. .false.', True),
    ('(.true. .or. .false.) .and. .false.', False),
    ('.not. 3 < 2', True),
])
def test_scalar_truth_and_precedence(expression, expected):
    assert bool(evaluate(expression)) is expected


def test_nested_function_arguments_and_strings():
    x = np.array([0., .5])
    assert evaluate('all(x >= 0 .and. x < 1)', x=x)
    translated = basic_f2p().translate_expr("inspect('.and. .or. .not.', a .and. b)", set())
    text, value = eval(translated, {'np': np, 'a': True, 'b': False,
                                  'inspect': lambda *args: args})
    assert text == '.and. .or. .not.'
    assert not value


def test_scalar_operands_are_evaluated_once_without_short_circuit():
    calls = []
    def mark(value):
        calls.append(value)
        return value
    translated = basic_f2p().translate_expr('mark(.false.) .and. mark(.true.)', set())
    assert not eval(translated, {'np': np, 'mark': mark})
    assert calls == [False, True]
