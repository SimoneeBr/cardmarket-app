"""Message template rendering: ``{{variable}}`` placeholders.

Unknown or missing variables are left untouched so the operator notices them
before sending instead of silently sending an empty value.
"""

import re

TEMPLATE_VARIABLES: frozenset[str] = frozenset(
    {"buyer_name", "order_id", "tracking_number", "shop_name", "total_amount"}
)

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def find_variables(body: str) -> set[str]:
    return {m.group(1) for m in _PLACEHOLDER.finditer(body)}


def unknown_variables(body: str) -> set[str]:
    return find_variables(body) - TEMPLATE_VARIABLES


def render_template(body: str, context: dict[str, str | None]) -> tuple[str, set[str]]:
    """Return the rendered text and the set of variables left unresolved."""
    missing: set[str] = set()

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = context.get(name)
        if value is None or value == "":
            missing.add(name)
            return match.group(0)
        return value

    return _PLACEHOLDER.sub(_sub, body), missing
