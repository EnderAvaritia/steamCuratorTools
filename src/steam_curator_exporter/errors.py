"""Project exception hierarchy and exit-code mapping."""

from __future__ import annotations

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_INCOMPLETE = 4


class SteamError(RuntimeError):
    """Base class for runtime failures talking to Steam."""


class AuthError(SteamError):
    """The login session is missing, expired, or rejected."""


class ConfigError(SteamError, ValueError):
    """Configuration or local input files are invalid."""


class UsageError(ConfigError):
    """Command-line usage is invalid."""


def exit_code_for(exc: BaseException) -> int:
    """Map an exception to the documented process exit code."""
    if isinstance(exc, AuthError):
        return EXIT_AUTH
    if isinstance(exc, ConfigError):
        return EXIT_USAGE
    return EXIT_FAILURE
