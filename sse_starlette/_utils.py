import sys
from contextlib import contextmanager
from typing import Generator

# Divergence #3 (see sse_starlette/sse.py module docstring): vendored copy of
# starlette._utils.collapse_excgroups. We do not import the upstream version
# because it lives in a private (underscore-prefixed) Starlette module, and
# the pinned floor (starlette>=0.41.3) makes that import surface unstable.
#
# Behaviour: AnyIO v4 wraps task-group failures in an ExceptionGroup; this
# helper unwraps single-exception groups so user middleware sees the bare
# exception (matching pre-v4 anyio and Starlette's StreamingResponse).
# Solution per https://anyio.readthedocs.io/en/stable/migration.html

has_exceptiongroups = True
if sys.version_info < (3, 11):
    try:
        from exceptiongroup import BaseExceptionGroup  # noqa: F401
    except ImportError:
        has_exceptiongroups = False


@contextmanager
def collapse_excgroups() -> Generator[None, None, None]:
    try:
        yield
    except BaseException as exc:
        if has_exceptiongroups:
            # `ty` does not narrow BaseExceptionGroup.exceptions; the runtime
            # contract is identical to starlette._utils.collapse_excgroups.
            while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:  # ty: ignore[unresolved-attribute]
                exc = exc.exceptions[0]  # ty: ignore[unresolved-attribute]

        raise exc


__all__ = ["collapse_excgroups"]
