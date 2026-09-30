"""Session state detection from the current page (pure, HTML based)."""

from cmc_shared.enums import ConnectionStatus, ErrorCode
from selectolax.lexbor import LexborHTMLParser, LexborNode

from agent.adapter import SessionState
from agent.cardmarket.parsers.common import first, parse_html

# Cloudflare firewall block page ("Sorry, you have been blocked"). These markers
# are Cloudflare's, not Cardmarket's, so they live here rather than in the
# Cardmarket selector registry. Observed on 2026-09-30 (see the
# tests/fixtures/cardmarket/cloudflare_blocked.html capture).
_CF_BLOCK_CONTAINERS = ("#cf-error-details", "#cf-wrapper")
_CF_BLOCK_TITLE = "attention required! | cloudflare"
_CF_BLOCK_PHRASES = ("sorry, you have been blocked", "you are unable to access")


def _normalized_text(node: LexborNode | None) -> str:
    text = node.text(separator=" ") if node is not None else ""
    return " ".join(text.split()).lower()


def cloudflare_block_ray_id(tree: LexborHTMLParser) -> str | None:
    """Return the Cloudflare Ray ID if the page is a Cloudflare *block* page.

    Requires a Cloudflare error container AND a block-specific title or heading,
    so a page that merely mentions "Cloudflare" is never treated as blocked.
    Returns "" when the page is a block page without a readable Ray ID.
    """
    if not any(tree.css_first(css) is not None for css in _CF_BLOCK_CONTAINERS):
        return None
    title = _normalized_text(tree.css_first("title"))
    headings = " ".join(_normalized_text(h) for h in tree.css("h1, h2"))
    if title != _CF_BLOCK_TITLE and not any(p in headings for p in _CF_BLOCK_PHRASES):
        return None
    ray = tree.css_first(".ray-id strong, .cf-footer-item strong")
    return _normalized_text(ray) if ray is not None else ""


def detect_session(html: str) -> SessionState:
    """Classify a Cardmarket page.

    Order matters: a Cloudflare block page is recognised first (Cardmarket was not
    reached at all); a challenge or 2FA prompt means a human is needed even if
    other markers are present.
    """
    tree = parse_html(html)
    ray_id = cloudflare_block_ray_id(tree)
    if ray_id is not None:
        # A firewall refusal, not a challenge to complete and not a session problem:
        # Cardmarket was never reached, so the session state is unknown.
        return SessionState(
            ConnectionStatus.ERROR,
            "Access blocked by Cloudflare before reaching Cardmarket; session state unknown"
            + (f" (Cloudflare Ray ID {ray_id})" if ray_id else ""),
            ErrorCode.ACCESS_BLOCKED,
        )
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
