# Fortran-to-Python

An experimental, partial Fortran-to-Python transpiler written in Python.
`xf2p.py` translates a subset of free-form Fortran into Python, using NumPy
for array operations and a companion runtime for Fortran-specific semantics.
SciPy is used for selected special functions when needed.

The project aims to make numerical Fortran programs usable from Python and
to support inspection, experimentation, and round-trip workflows with
[Python-to-Fortran](https://github.com/Beliavsky/python-to-fortran).
It is not a complete Fortran implementation. Review and test every translation;
successful translation or execution alone does not establish correctness.
Loop-heavy translations may be substantially slower than compiled Fortran.

See the [Fortran-to-Python syntax guide](fortran_to_python_syntax_guide.md)
for side-by-side examples, array indexing and memory-order differences,
procedure calling conventions, runtime helpers, and translation caveats.

## Requirements

- Python (development and testing currently use Python 3.13).
- NumPy for running translated numerical programs.
- SciPy for translations that use its special functions.
- A Fortran compiler on `PATH` for compiling or comparing the original program.
  The default compiler is `gfortran`.
- pytest for the test suite.

```console
python -m pip install numpy scipy pytest
```

Translation-only use does not require a Fortran compiler. The tools are scripts;
run them from a checkout rather than installing a package.

## Quick start

Translate one program:

```console
python xf2p.py tests/cases/handwritten/scalar_arithmetic.f90
```

By default, the output is named `<source_stem>_f.py` beside the source. Set a
different destination with `--out`:

```console
python xf2p.py tests/cases/handwritten/scalar_arithmetic.f90 --out translated.py
python translated.py
```

The CLI copies `fortran_py_runtime.py` beside the output if it is not already
there. Keep that file with translations that import it. Existing runtime copies
are not overwritten: refresh an older copy when updating the translator, or
use a fresh output directory.

Compile and run the original Fortran, run the translation, and compare output:

```console
python xf2p.py tests/cases/handwritten/scalar_arithmetic.f90 --run-diff
```

Other useful options:

| Option | Purpose |
| --- | --- |
| `--run` | Run the translated Python. |
| `--compile` | Compile the original Fortran. |
| `--run-both` | Run both versions without requiring matching output. |
| `--run-diff` | Run both and compare stdout. |
| `--diff-exact` | Compare normalized output text exactly; implies `--run-diff`. |
| `--rtol`, `--atol` | Set real-output comparison tolerances. |
| `--compiler "gfortran -O0 -g -fcheck=all"` | Choose a compiler command and flags. |
| `--time` | Report timings and run translated Python. |
| `--time-both` | Report timings for both versions and compare output. |
| `--mode-each` | Translate supplied files independently. |

Run `python xf2p.py --help` for the full interface. Compiler commands currently
use GNU-style `-o executable` syntax. Paths in these examples use `/`, which
also works with Python on Windows.

### Output comparison

Default comparison ignores whitespace and line wrapping. Integers and ordinary
text must agree; standalone real tokens use relative tolerance `1e-9` and
absolute tolerance `1e-11`. Fortran `D` exponents, matching NaNs, and same-sign
infinities are supported. Standalone `T`/`True` and `F`/`False` are equivalent,
so generated Python can retain idiomatic logical output.

Stdout contains no type information: character output consisting of those
logical-looking words is treated the same way. Use `--diff-exact` when spelling
matters. Exact mode still normalizes whitespace within lines and trailing blank
lines; it is not byte-for-byte comparison. Complex-token comparison and numeric
kind fidelity remain limitations. Nonzero process exits remain failures.

Random, time-dependent, or otherwise nondeterministic programs may differ
legitimately. Use `--run-both` to inspect their output without asserting equality.

## Batch testing

`xf2p_batch.py` surveys programs and saves diagnostics:

```console
python xf2p_batch.py "tests/cases/handwritten/*.f90" --run-diff --verbose
python xf2p_batch.py "tests/cases/features/*.f90" --run-diff
python xf2p_batch.py --run-diff --group my_module.f90 my_program.f90
```

Each ordinary file match is a separate case. Use `--group` to supply a program
and its dependencies in order. The batch runner does not infer dependencies.
Library-only files are conservatively classified and skipped.

Each run creates an isolated directory under `reports/` containing `results.txt`,
`results.json`, and per-case artifacts. Reports retain commands, stdout/stderr,
stage timings, start/end times, and outcome counts. `--verbose` also displays
successful execution output. Use `--data` for required input files; they are
not copied automatically. See [the batch guide](BATCH_README.txt).

Use `--failures-only` to suppress successful case details while retaining progress,
warnings, library-only skips, and the final summary. With `--verbose`, full stage
output is displayed only for cases needing attention. Saved reports remain complete.

## Supported features and limitations

`ENUM, BIND(C)` enumerators become integer named constants, not Python enum
objects. Explicit values and implicit numbering (starting at zero) are supported,
including procedure, host, module, and `BLOCK` scopes. This does not add C ABI
bindings or support Fortran's newer named enumeration types. The existing
restrictions on renamed `USE` imports and colliding module namespaces apply.

Tested examples cover scalar arithmetic, loops and branches, array constructors
and sections, allocation with `SOURCE`/`MOLD`, masks and `WHERE`, matrix operations,
many numerical intrinsics, procedures, optional and keyword arguments, internal
procedures and host association, named loop control, lexical `BLOCK` scopes,
and selected derived-type and type-bound procedure features. Elemental functions
and elementwise logical expressions have focused tests. `SHAPE` and `RANK`
inquiries are supported independently of `SELECT RANK`.
Other tested intrinsics include `PRODUCT`, `UNPACK`, `CSHIFT`/`EOSHIFT`,
`ADJUSTR`, `SCAN`/`VERIFY`, `REPEAT`, and selected integer bit operations.
Named allocatable variables support `MOVE_ALLOC`; command-argument intrinsics
use Python's command line (argument zero names the Python script).

Sequential formatted file I/O supports integer `UNIT`/`NEWUNIT` connections,
named and scratch files, `REWIND`, and `CLOSE`. External `READ` supports numeric
and logical list-directed input and scalar character `'(a)'` input, with
`IOSTAT` and `IOMSG`. Units are shared across procedures. This is not a complete
Fortran I/O implementation; other input formats, direct/unformatted access,
and advanced list-directed input syntax remain unsupported.

Support is incomplete and varies by construct and context. In particular:

- Numeric kinds are not fully preserved; default Fortran real arithmetic may
  differ from Python's double-precision arithmetic.
- `SELECT RANK`, coarrays, polymorphic allocation, finalization, and parameterized
  derived types are not generally supported.
- Some intrinsics and formatted external I/O forms remain unsupported.
- `IS_CONTIGUOUS` uses NumPy storage flags, which do not fully reproduce Fortran
  descriptors when multidimensional storage layouts differ. Nonpointer,
  nonallocatable `CONTIGUOUS` array dummies use temporaries when needed.
- Same-source modules and programs can share mutable module state. Cross-file
  mutable `USE` state and renamed `USE` variables have explicit restrictions;
  combining sources into one input can help with the former.
- Not every unsupported construct is diagnosed during translation. Generated
  code can still fail at execution or produce incorrect results.

Consult [feature coverage](tests/FEATURE_COVERAGE.txt) and
[test documentation](tests/README.txt) for detailed, dated results and caveats.

## Tests

List-directed complex output preserves component precision using Python float
representations. Numerical output comparison checks standalone `(real,imaginary)`
pairs component by component, using the same tolerances as real values, even
when spaces or line wrapping separate the components. Use `--diff-exact` when
the literal spelling matters (including character strings that look numeric).

```console
pytest -q -rx
```

Tests include runtime and translation unit checks plus execution comparisons
against independently compiled Fortran. Execution tests skip when their required
compiler or dependencies are unavailable. Known failures are marked explicitly;
strict expected-failure checks expose unexpected passes.

Local exploratory cases under `tests/cases/more/` are excluded by default.
To include them (with ordinary failure reporting), run:

```console
pytest -q --include-exploratory
```

For a survey independent of pytest, use
`python xf2p_batch.py "tests/cases/more/*.f90" --run-diff --failures-only`.
Other Fortran files beneath `tests/cases/` are discovered normally;
`tests/cases/stash/` is always excluded, even with `--include-exploratory`.

## Related tools

`xarray.py` identifies simple Fortran loops that may be replaceable with array
operations. It is an optional preparation tool, not a required translation step
or a general optimizer. Its supporting scanner and transformation scripts are
included in this repository. Run `python xarray.py --help` for its options.
