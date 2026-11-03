"""Project exception hierarchy and exit-code mapping."""

from __future__ import annotations

exitOk = 0
exitFailure = 1
exitUsage = 2
exitAuth = 3
exitIncomplete = 4


class SteamError(RuntimeError):
    """Base class for runtime failures talking to Steam."""


class AuthError(SteamError):
    """The login session is missing, expired, or rejected."""


class ConfigError(SteamError, ValueError):
    """Configuration or local input files are invalid."""


class UsageError(ConfigError):
    """Command-line usage is invalid."""


def exitCodeFor(exc: BaseException) -> int:
    """Map an exception to the documented process exit code."""
    if isinstance(exc, AuthError):
        return exitAuth
    if isinstance(exc, ConfigError):
        return exitUsage
    return exitFailure
