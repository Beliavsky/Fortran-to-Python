"""Remove progress-only lines from a saved xf2p_batch.py console log."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import tempfile


PROGRESS = re.compile(r"^\s*\[\d+/\d+\]\s+Checking\.\.\.\s*$")


def terse_text(text: str) -> str:
    """Preserve diagnostics and summaries, collapsing runs of blank lines."""
    lines = []
    for line in text.splitlines():
        if PROGRESS.fullmatch(line):
            continue
        if not line.strip():
            if lines and lines[-1] != "":
                lines.append("")
        else:
            lines.append(line)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Saved batch console log")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--out", type=Path, help="Output file (default: INPUT_STEM_terse.INPUT_SUFFIX)")
    destination.add_argument("--overwrite", action="store_true",
                             help="Replace the original log with the filtered text")
    args = parser.parse_args(argv)
    output = (args.input.resolve() if args.overwrite else
              args.out or args.input.with_name(args.input.stem + "_terse" + args.input.suffix))
    if not args.overwrite and output.resolve() == args.input.resolve():
        parser.error("Output must differ from input")
    try:
        filtered = terse_text(args.input.read_text(encoding="utf-8-sig", errors="replace"))
        if args.overwrite:
            temporary = None
            try:
                # Same-directory replacement stays on the same filesystem.
                # Close the temporary file before replacing it on Windows.
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                 dir=output.parent, prefix=".xbatch_terse_",
                                                 suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(filtered)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, output)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        else:
            # Separate output files are still never overwritten.
            with output.open("x", encoding="utf-8") as stream:
                stream.write(filtered)
    except OSError as exc:
        parser.error(str(exc))
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
