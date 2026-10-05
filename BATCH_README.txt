Fortran-to-Python batch surveys
==============================

Translation only:

    python xf2p_batch.py "tests\cases\**\*.f90"

Compile and run both versions, comparing numeric stdout tokens:

    python xf2p_batch.py "tests\cases\**\*.f90" --run-diff

Survey five files with a per-stage 30-second timeout:

    python xf2p_batch.py "C:\python\fortran\x*.f90" --run-diff --limit 5 --timeout 30

An explicit ordered source group (dependencies before the main):

    python xf2p_batch.py --run-diff --group my_module.f90 my_program.f90

Repeat --group to specify more programs. Each ordinary glob match is its own
case; the runner does not infer dependencies or group unrelated main programs.
For grouped translation it combines the supplied files in their given order
into a temporary combined.f90 because xf2p --out requires a single input.
The Fortran compiler receives the original source files in that same order.

Additional options:
  --verbose      Print each stage's command, working directory, duration, stdout,
                 and nonempty stderr after that stage completes. Works with
                 --run-both and --run-diff; does not change comparisons.
  --compile      Compile original Fortran without running it.
  --run          Run translated Python only.
  --run-both     Run both versions without asserting output equivalence.
  --compiler    Quoted compiler command, default gfortran with debug checks.
  --data         File to copy into both execution directories; repeatable.
  --out-dir      Report/work parent directory, default reports.
  --rtol, --atol Floating-point comparison tolerances, defaults 1e-9 and 1e-11.
  --diff-exact   Compare normalized stdout text exactly (implies --run-diff).

The CLI and batch runner share fortran_output_compare.py. Default comparisons
ignore whitespace/line wrapping and compare standalone real tokens numerically,
including Fortran D exponents. Standalone T/True and F/False tokens compare
as equivalent logical values. Integer tokens and other text compare exactly.
Stdout has no type information: character output consisting of those same
standalone words is also treated as logical. Use --diff-exact when their
spelling matters. Embedded text such as flag=T is not normalized.
Matching NaNs and same-sign infinities compare equal. Only stdout is compared;
stderr is displayed/saved separately and process failures remain failures.
--diff-exact retains xf2p.py's former normalized-line comparison: whitespace
runs and trailing blank lines are normalized, but number spelling and line
structure must agree. It is not a byte-for-byte file comparison.
Both commands return nonzero on a genuine output mismatch.

Equivalent single-program CLI commands:

    python xf2p.py xintrinsics.f90 --run-diff
    python xf2p.py xintrinsics.f90 --run-diff --rtol 1e-12 --atol 0
    python xf2p.py xintrinsics.f90 --diff-exact

Numerical tolerances can hide ULP-level differences such as NEAREST results;
keep exact value/boundary regression checks for those operations. Zero
tolerances compare parsed numeric values, not their printed spelling; use
--diff-exact when spelling matters.

For example, to inspect both programs' output:

    python xf2p_batch.py "tests\cases\**\*.f90" --run-both --verbose

This initial version uses GNU-style '-o executable' compiler syntax. Compiler
commands are split into arguments without invoking a shell. On Windows quote
an executable path containing spaces inside the compiler command.

Reports and artifacts
---------------------
Each invocation creates a unique reports\xf2p_batch_TIMESTAMP_RANDOM directory
containing results.txt, results.json, and isolated per-case build/run files.
Reports are refreshed after each completed case; JSON's 'complete' indicates
whether all requested cases finished. All paths, commands, stage durations,
stdout, stderr, UTC start/end times, options, and summary counts are retained.
Successful output is omitted from text but retained in JSON. Mismatch text
includes both execution outputs and the first differing token.

Stage statuses distinguish pass, fail, error (e.g. missing compiler), timeout,
blocked, not_requested, match, mismatch, and not_compared. Summary 'pass'
means all requested stages passed, not necessarily that outputs were compared.
--run-diff is required to establish an output match.

Use --failures-only for concise console output: successful case details are
suppressed, but a short progress line remains for each case. Failures, timeouts,
comparison mismatches, warnings, and library-only skips remain visible, followed
by report locations, counts, and timings. Any nonempty stage stderr is retained
as a diagnostic, even when the stage passes. Warning lines on stdout are also
shown. With --verbose, full stage output is buffered and shown only for cases
needing attention. JSON and text reports are unaffected by console filtering.

Example:
python xf2p_batch.py "tests/cases/features/*.f90" --run-diff --failures-only

Library-only files are conservatively identified and skipped, not counted as
translation failures. Ambiguous source proceeds through the normal stages.
Compilation diagnostics for missing .mod files get a separate dependency
classification. No promise is made to classify all fixed-form/legacy sources.
The first failing stage determines the overall outcome, but JSON retains all
stage results (including translation even when compilation failed).

Source files are never overwritten. Source-adjacent data files are NOT copied
automatically: supply --data. Programs execute in separate working directories
and read no stdin supplied by the runner. Random or time-dependent results may
differ legitimately; use --run-both rather than --run-diff for those cases.
Output comparison ignores whitespace but preserves textual tokens, compares
integers exactly, and uses tolerances for floating-point tokens. Array-output
layout differences can still cause mismatches and need human review.

Exit code: 0 if all cases pass or are skipped libraries; 1 for any case failure,
timeout, execution error, or mismatch; 2 for invalid command-line inputs.
No pytest expected-failure suppression applies to batch results.

The final console line shows overall elapsed time, cumulative Fortran compile,
Fortran run, translation, Python run, comparison, and other overhead times.
Stages not requested contribute zero; failed/timed-out stages still contribute
their elapsed time. Execution timings include process startup and imports.

Security: this is a local diagnostic tool, not a sandbox. --run and --run-both
execute source programs; use trusted programs. A subprocess timeout is not a
security boundary or a guarantee that descendant processes have terminated.
Retained artifacts can consume disk space; remove unwanted run directories
only after inspecting their reports.
