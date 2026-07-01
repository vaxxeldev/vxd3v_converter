class ConversionError(Exception):
    """Safe error that can be shown to a Telegram user."""


class ConversionBusyError(ConversionError):
    """A user already has a render in progress."""


class QueueFullError(ConversionError):
    """The bounded render queue is full."""


class MediaValidationError(ConversionError):
    """Input or output media failed validation."""


class ProcessExecutionError(ConversionError):
    """A native media process failed."""

