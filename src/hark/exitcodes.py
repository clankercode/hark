"""CLI exit codes (docs/SPEC.md §4)."""

OK = 0
ERROR = 1
USAGE = 2
HERDR = 3
PROVIDER = 4
AUDIO = 5
TIMEOUT = 6
ABORT = 7  # stale / policy / user cancel


def normalize_failure_exit(code: object, *, fallback: int = ERROR) -> int:
    """Return a canonical Hark exit code for a reported failure.

    ``docs/SPEC.md`` defines the complete public range as ``0`` through ``7``.
    Failures may use only the exact built-in integers ``1`` through ``7``;
    everything else becomes the caller's contextual canonical fallback.
    """
    if type(fallback) is not int or not 1 <= fallback <= ABORT:
        raise ValueError("fallback must be a canonical failure exit from 1 through 7")
    if type(code) is int and 1 <= code <= ABORT:
        return code
    return fallback
