"""Shared loader for the `layout/analog` test modules (issue #355).

Imported by the per-generator test modules (`test_drc_guard.py`,
`test_gen_blocks.py`, `test_integrator_summing_pair.py`,
`test_anchor_collection.py`), which discover places beside it on `sys.path`
exactly as they do for `layout_common`. The module name is deliberately NOT
`test_`-prefixed, so neither `python3 -I -m unittest discover -s layout/analog
-p 'test_*.py'` nor any wider discovery may collect it: there is nothing to
test here.

`layout/analog/` is a directory name, not an importable package path under
`python3 -I` (isolated mode drops CWD and PYTHONPATH), and the generators
import their siblings (`layout_common`) as top-level modules -- loading them
under a package-relative name would double-import those siblings. So each
generator is executed from its path under a synthetic module name instead,
the `sim/` benches' `runner_test_common.load_runner` pattern.

Before #355 each test module pasted its own copy of this helper; the copies
were byte-identical, so a fix to one (a leak, a naming collision) never
reached the other three. One definition each, in one place, same behaviour:
the synthetic module name is unchanged, so anything naming it -- a
`mock.patch` target, an error message -- sees what it saw before.
"""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def load_generator(rel: str):
    """Load a generator module by path: 'layout/analog/...' is not importable."""
    spec = importlib.util.spec_from_file_location(
        rel.replace("/", "_") + "_under_test", HERE / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
