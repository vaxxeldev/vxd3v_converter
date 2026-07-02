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


class InsufficientBalanceError(ConversionError):
    """A paid render cannot be reserved from the current balance."""


class PaymentStateError(ConversionError):
    """A payment request is missing or in an incompatible state."""
