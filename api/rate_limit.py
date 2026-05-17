"""Shared slowapi limiter + a globals-preserving wrapper.

The single ``Limiter`` instance lives here so every route module shares
the same per-request counter backend. ``api/main.py`` mounts it on
``app.state.limiter`` and registers the rate-limit exception handler.

``limit(rate)`` is a thin wrapper around ``Limiter.limit(rate)`` that
copies the decorated function's ``__globals__`` onto the slowapi
wrapper. This is necessary for routes that use forward-refs (i.e.
``from __future__ import annotations``) with body Pydantic models —
otherwise FastAPI's ``get_typed_signature`` reads the wrapper's
``__globals__`` (slowapi's module globals) and fails to resolve names
like ``CreateGoalBody`` that only exist in the route module's globals.
"""

from __future__ import annotations

from typing import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address

# Default 100/minute applies to every limiter-decorated route that
# doesn't override; routes that DO override (heavy LLM endpoints,
# OAuth flow init) get stricter limits to protect quota.
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


def limit(rate: str) -> Callable:
    """Decorator: apply ``rate`` to a FastAPI route handler.

    Equivalent to ``@limiter.limit(rate)`` but copies the original
    function's ``__globals__`` onto the wrapper so FastAPI can resolve
    PEP 563 forward refs in the route's body parameters.
    """

    base = limiter.limit(rate)

    def _wrap(func):
        wrapper = base(func)
        # Make FastAPI's get_typed_signature see the original module's
        # globals when it resolves forward-ref'd annotations on the
        # decorated function. slowapi uses functools.wraps which copies
        # __wrapped__/__name__/__doc__ but NOT __globals__ (that's bound
        # to the wrapping function at definition time, not standard
        # WRAPPER_ASSIGNMENTS). Override via __globals__ attribute is
        # not allowed on function objects, but FastAPI uses
        # getattr(call, "__globals__", {}) so we can shadow it via a
        # custom __getattr__-equivalent on the wrapper itself.
        try:
            wrapper.__globals__.update(getattr(func, "__globals__", {}))
        except Exception:  # noqa: BLE001 — fall through; FastAPI will surface its own error
            pass
        return wrapper

    return _wrap
