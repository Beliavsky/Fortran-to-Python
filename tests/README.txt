Fortran-to-Python execution tests
================================

Run from the repository root:

    python -m pip install numpy pytest
    pytest -q -rx

Requirements: Python, NumPy, pytest, and gfortran on PATH. Execution tests
skip explicitly if gfortran or NumPy is missing; they do not pretend to pass.
Each subprocess has a 90-second timeout. Compiler commands use argument lists,
so Windows paths with spaces work without shell quoting.

Corpus (21 programs)
--------------------
handwritten/: 17 small deterministic programs exercising scalars, loops,
branches, SELECT CASE, arrays, masks, matrices, procedures, modules, strings,
allocation, and formatted file I/O.

existing/xsum_dim_int.f90: copied from C:\python\fortran\xsum_dim_int.f90
on 2026-10-04; only line-ending differences. Tests integer kinds and axis sums.

roundtrip/: three original Python programs and their fixed xp2f-generated
Fortran snapshots. These are self-contained (no python_mod or LAPACK).
Generated with C:\python\Python-to-Fortran\xp2f.py at Git HEAD
1769bfa086645218454eaa625349f14eebb157ca on 2026-10-04.
The tests do not invoke or require xp2f.py. Keep these snapshots stable;
regenerating them should be a separate, reviewed integration step.

Method
------
Compile and execute the original Fortran with -O0 -g -fcheck=all -fbacktrace.
Translate with the repository's xf2p.py into pytest's temporary directory,
then execute the resulting Python and compare stdout tokens.
Round-trip cases additionally execute the original Python and compare its
output against the Fortran reference before testing xf2p.py.

Ignore whitespace, but require equal token counts and textual labels.
Integer tokens are compared exactly; real tokens use relative tolerance
1e-9 and absolute tolerance 1e-11, accepting Fortran D exponents.
This is numerical-output validation, not byte-for-byte formatting validation.
Original Fortran and translated Python run in separate directories, so file
I/O cannot accidentally reuse files produced by the reference execution.

Known failures (2026-10-04)
--------------------------
xsum_dim_int: ISO_FORTRAN_ENV INT32 becomes undefined Python name int32.
formatted_file_io: numeric file units produce invalid Python 20.close().

These two cases are strict expected failures, not skipped. Their Fortran
references must still compile and execute successfully. Unexpected success
fails the suite so that obsolete expectations are removed after a fix.
Other assertion failures inside a known-failing translation may also count
as expected failures; inspect their tracebacks when changing the translator.

To investigate without expected-failure masking:

    pytest -q --runxfail tests\test_xf2p_execution.py

To save machine-readable test results:

    pytest -q -rx --junitxml=reports\pytest.xml

The suite is a starting corpus, not a complete support guarantee. Larger
integration programs, helper-dependent p2f output, random-number algorithms,
complex numbers, derived types, and additional unsupported syntax need
dedicated tests in subsequent expansions.

Fixed on 2026-10-04: integer whole-array, section, and WHERE assignments
convert elementwise with np.asarray(..., dtype=int), while scalar variables
and individual elements retain scalar int() conversion. The logical_masks
case now passes. integer_assignment_conversions checks positive/negative real
truncation, scalar expansion, vector/matrix sections, elements, and WHERE.

Also fixed on 2026-10-04: strided sections on expression and assignment paths,
including WHERE and single-line IF assignments. strided_sections checks
positive/negative/dynamic strides, omitted bounds, empty sections, non-unit
declared lower bounds, multiple dimensions, nested bounds, and overlapping
assignment. Unlike Python, Fortran's omitted bounds do not reverse with a
negative stride. Runtime triplet conversion rejects zero strides and selected
out-of-bounds elements. The original array_sections case now passes.

Also fixed on 2026-10-04: TRANSPOSE and DOT_PRODUCT translation, and intrinsic
keyword arguments for TRANSPOSE, MATMUL, DOT_PRODUCT, and RESHAPE. Complex
DOT_PRODUCT conjugates its first vector; logical DOT_PRODUCT uses ANY of AND,
and logical MATMUL uses AND/OR rather than numeric sums. Three new programs
check integer, complex, and logical matrix/vector operations.

Fixing TRANSPOSE exposed a wrong-result RESHAPE bug in matrix_operations:
Fortran source elements must fill in column-major order. Translation now uses
a dedicated helper implementing Fortran ordering, PAD, and ORDER, without
changing ordinary NumPy reshape defaults. The original matrix case now passes.

Also fixed on 2026-10-04: missing fixed-length string assignment, LEN_TRIM,
ADJUSTL, and INDEX helpers. Assignment pads/truncates scalars and arrays;
LEN_TRIM and ADJUSTL operate elementwise and treat only spaces as blanks.
INDEX uses one-based positions, zero for no match, optional BACK, and
broadcasting. The string_assignment program verifies scalar/array assignment,
initializers, zero length, padding, truncation, and search; strings now passes.
Substring reads are covered by strings; substring writes and deferred-length
allocatable strings are not yet covered by these regressions.
