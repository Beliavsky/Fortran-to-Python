Fortran-to-Python execution tests
================================

Run from the repository root:

    python -m pip install numpy scipy pytest
    pytest -q -rx

Requirements: Python, NumPy, pytest, and gfortran on PATH. Execution tests
skip explicitly if gfortran or NumPy is missing; they do not pretend to pass.
SciPy is optional for the translator/runtime and ordinary translated programs;
special-function programs require it. The math_intrinsics execution comparison
and SciPy-specific unit test skip explicitly when SciPy is unavailable.
Each subprocess has a 90-second timeout. Compiler commands use argument lists,
so Windows paths with spaces work without shell quoting.

Corpus (43 programs)
--------------------
handwritten/: 18 small deterministic programs exercising scalars, loops,
branches, SELECT CASE, arrays, masks, matrices, procedures, modules, strings,
allocation, and formatted file I/O.

features/: 21 focused programs covering OPTIONAL/PRESENT, keyword calls,
explicit SAVE, EXIT, EQV/NEQV, elemental and impure elemental procedures,
DO CONCURRENT, derived-type assignment/arguments/results, type extension,
type-bound procedures, labeled FORMAT, selected-kind intrinsics, and a
controlled EXECUTE_COMMAND_LINE call. See FEATURE_COVERAGE.txt for results.
array_component_initializers also verifies default component values and
independent storage between objects and between derived-type array elements.
location_intrinsics verifies MINLOC/MAXLOC/FINDLOC, DIM, MASK, BACK, KIND,
Fortran array-element order, empty arrays, and character/logical searches.
math_intrinsics is based on the user's xintrinsics_all.f90, with the checker
counters passed explicitly (unmodified host-scope counter updates remain a
separate translator limitation). It exercises all 73 original checks. Its
Fortran reference uses -O3: the local MinGW compiler/library combination lacks
the runtime sinpi symbol used at -O0 for the constant elemental test vector.
All other reference programs continue to use -O0. The generated Python still
evaluates its array expressions at runtime.

stash/: manual probes retained for reference; excluded from automated discovery.

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
formatted_file_io: numeric file units produce invalid Python 20.close().
execute_command_line: missing EXECUTE_COMMAND_LINE helper.
impure_elemental: updating module state lacks a Python global declaration.
selected_integer_kind, selected_logical_kind, selected_real_kind: missing
kind-selection intrinsic helpers.
type_extension: missing parent component of an extended type.

These cases are strict expected failures, not skipped. Their Fortran
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
more complex-number and derived-type cases, and additional unsupported syntax need
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

Also fixed on 2026-10-04: ISO_FORTRAN_ENV kind imports with or without
INTRINSIC/ONLY and with renamed imports. NON_INTRINSIC modules are not treated
as the built-in module. The existing xsum_dim_int case and new iso_kind_imports
case both pass, including module and procedure-local aliases.
Kind-number values use the existing GNU-style convention (1/2/4/8 for integer
storage sizes). They are not portable processor-independent kind identifiers.
Resolving these constants does not yet guarantee exact kind-sized integer
storage or overflow semantics throughout translated Python/NumPy operations.

Also fixed on 2026-10-04: type-bound calls no longer disappear. Derived types
emit forwarding methods for explicit procedure bindings, including renamed
bindings, default/named PASS, NOPASS, optional arguments, function results,
and explicit scalar OUT arguments. CLASS(type) dummies retain derived-type
metadata. CONTAINS inside a type is distinguished from the enclosing unit's
CONTAINS. The expanded type_bound_procedure case checks nested objects and
calls from one bound procedure to another as well as ordinary component-array
indexing. Unsupported/unresolved CALL statements fail explicitly rather than
being silently discarded. Deferred/generic bindings and indexed-object calls
are not yet supported by this implementation; type extension remains failing.

Also fixed on 2026-10-04: explicit-shape array-component initialization in
derived types. Factories preserve initial values, shape, element type, scalar
expansion, and CHARACTER padding/truncation. Derived-type array components
construct default elements or copy explicit initializers independently, so
mutating one element/object does not modify siblings, other instances, or the
initializer. Uninitialized intrinsic arrays remain np.empty; allocatable and
pointer components keep their existing unallocated/disassociated behavior.
Complex scalar and vector initialization are tested. Complex-pair literals
nested inside array constructors and chained component-array indexing were
fixed in the follow-up described below.

Also fixed on 2026-10-04: complex literals within untyped/typed array
constructors, complex arithmetic and nested calls, and keyword constructor
arguments. Parenthesized argument lists and strings are not complex literals.
Chained component-array reads and writes now retain every subscript, including
matrix indices, sections/strides, integer conversion, and masked assignments.
Component bounds are taken from the component declaration, not its root
object's array bounds. The expanded array_component_initializers regression
checks non-default bounds for both components and arrays of derived objects.
Indexed-object bound CALLs and general inheritance remain outside this fix.

Also fixed on 2026-10-04: ALLOCATE with SOURCE= and MOLD=. SOURCE copies
values into independent storage; MOLD supplies shape without copying values.
Explicit bounds, scalar SOURCE expansion, scalar allocation, multiple objects,
intrinsic element types, fixed-length CHARACTER, derived-type defaults/copies,
and default-bound allocatable components are covered by allocate_models.
Whole-array model bounds and explicit bounds are captured within the current
unit, so later changes to extent variables do not change allocated bounds.
Zero extents return LBOUND=1/UBOUND=0. STAT is zero on success and nonzero on
allocation errors; its numeric error codes and ERRMSG text are not intended
to duplicate a particular Fortran compiler. Existing allocation is retained
when an already-allocated object fails allocation with STAT.
Type-spec ALLOCATE, deferred-length CHARACTER, and non-default bounds for
allocated components remain unsupported with explicit diagnostics. General
cross-procedure preservation of allocatable-dummy bounds is not guaranteed.

Mathematical intrinsic dependencies
----------------------------------
Gamma, LOG_GAMMA, ERF, ERFC, ERFC_SCALED, and Bessel functions use scipy.special.
ERFC_SCALED maps to erfcx rather than exp(x*x)*erfc(x), avoiding intermediate
overflow for large positive x. Reference:
  https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.erfcx.html
Only special-function programs import SciPy, and missing installations receive
an explicit 'python -m pip install scipy' message. NumPy/runtime helpers handle
hyperbolic functions, HYPOT, NORM2, degree/PI-scaled trigonometric functions,
and EPSILON. NORM2 supports DIM and scaled accumulation. PI-scaled helpers
reduce their arguments before multiplication and preserve exact cardinal values.
EPSILON reflects the translated value's dtype; the translator's existing
promotion of Fortran REAL declarations/literals to float64 remains a kind-
fidelity limitation outside the real64 regression used here.
