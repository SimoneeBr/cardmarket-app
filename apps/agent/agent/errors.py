"""Error taxonomy of the agent. Every failure is classified into an ErrorCode."""

from cmc_shared.enums import ErrorCode


class AgentError(Exception):
    code: ErrorCode = ErrorCode.UNKNOWN
    retryable: bool = False

    def __init__(self, message: str, *, artifacts: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.artifacts = artifacts or []


class AuthRequiredError(AgentError):
    """Cardmarket shows a login form / asks to re-authenticate."""

    code = ErrorCode.AUTH_ERROR


class NetworkError(AgentError):
    code = ErrorCode.NETWORK_ERROR
    retryable = True


class NavigationTimeoutError(AgentError):
    code = ErrorCode.TIMEOUT
    retryable = True


class CardmarketChangedError(AgentError):
    """The page is not what the parser expects: fail safe, do nothing risky."""

    code = ErrorCode.CARDMARKET_CHANGED


class SelectorNotFoundError(AgentError):
    code = ErrorCode.SELECTOR_NOT_FOUND


class UnsafeUIError(AgentError):
    """The agent is not certain which element to interact with: refuse to act."""

    code = ErrorCode.SELECTOR_NOT_FOUND


class ActionFailedError(AgentError):
    code = ErrorCode.ACTION_FAILED


class VerificationFailedError(AgentError):
    code = ErrorCode.VERIFICATION_FAILED


class ApiUnavailableError(Exception):
    """The companion API cannot be reached (not a Cardmarket problem)."""


def classify(exc: BaseException) -> tuple[ErrorCode, bool]:
    """Map any exception to (error code, retryable)."""
    if isinstance(exc, AgentError):
        return exc.code, exc.retryable
    name = type(exc).__name__
    text = str(exc)
    if name == "TimeoutError" or "Timeout" in name:
        return ErrorCode.TIMEOUT, True
    if "net::" in text or "ERR_" in text or name in {"ConnectError", "ReadError"}:
        return ErrorCode.NETWORK_ERROR, True
    return ErrorCode.UNKNOWN, False
