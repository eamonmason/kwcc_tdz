"""Custom exceptions for ZwiftPower fetcher."""


class ZwiftPowerError(Exception):
    """Base exception for ZwiftPower errors."""


class ZwiftPowerAuthError(ZwiftPowerError):
    """Authentication failed."""


class ZwiftPowerRateLimitError(ZwiftPowerError):
    """Rate limited by ZwiftPower."""


class ZwiftPowerEventNotFoundError(ZwiftPowerError):
    """Event not found on ZwiftPower."""


class ZwiftPowerConnectionError(ZwiftPowerError):
    """Network connection error."""


class ZwiftPowerParseError(ZwiftPowerError):
    """Failed to parse ZwiftPower response."""
