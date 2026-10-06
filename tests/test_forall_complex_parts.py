from pathlib import Path

from xf2p import basic_f2p


def test_fixture(capsys):
    source = (Path(__file__).parent / 'cases/features/forall_complex_parts.f90').read_text()
    exec(basic_f2p().transpile(source), {'__name__': '__main__'})
    assert capsys.readouterr().out.splitlines() == [
        '1.0 1.0 2.0 3.0 10.0 20.0 30.0 40.0',
        '1.0 1.0 -2.0 -3.0 10.0 20.0 18.0 7.0',
        '1.0 2.0 3.0 4.0 10.0 30.0 20.0 40.0',
        '3.0 4.0 1.0 2.0 10.0 30.0 20.0 40.0',
        '1.0 1.0 2.0 3.0 40.0 30.0 20.0 10.0',
        '4.0 1.0 2.0 3.0 10.0 20.0 30.0 40.0',
        '4.0 1.0 2.0 3.0 10.0 20.0 30.0 40.0',
        '3.0 2.0 1.0 4.0 10.0 20.0 30.0 40.0',
    ]
