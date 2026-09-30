"""Session state detection from the current page (pure, HTML based)."""

from cmc_shared.enums import ConnectionStatus, ErrorCode

from agent.adapter import SessionState
from agent.cardmarket.parsers.common import first, parse_html


def detect_session(html: str) -> SessionState:
    """Classify a Cardmarket page.

    Order matters: a challenge or 2FA prompt means a human is needed even if
    other markers are present.
    """
    tree = parse_html(html)
    if first(tree, "session.challenge") is not None:
        return SessionState(
            ConnectionStatus.AUTH_REQUIRED,
            "Cardmarket shows a security challenge: complete it manually (pairing)",
            ErrorCode.AUTH_ERROR,
        )
    if first(tree, "session.twofa_form") is not None:
        return SessionState(
            ConnectionStatus.AUTH_REQUIRED,
            "Two-factor authentication required",
            ErrorCode.AUTH_ERROR,
        )
    logged_in = first(tree, "session.logged_in_marker") is not None
    login_form = first(tree, "session.login_form") is not None
    if logged_in and not login_form:
        return SessionState(ConnectionStatus.CONNECTED)
    if login_form and not logged_in:
        return SessionState(
            ConnectionStatus.SESSION_EXPIRED, "Login form shown", ErrorCode.AUTH_ERROR
        )
    return SessionState(
        ConnectionStatus.ERROR,
        "Session state not recognisable (Cardmarket layout changed?)",
        ErrorCode.CARDMARKET_CHANGED,
    )
