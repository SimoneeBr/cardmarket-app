"""The "no actions on uncertain UI" rule, enforced in code.

Before clicking or typing anything, a write action must:
1. use only selectors marked ``verified=True`` in the registry;
2. resolve each selector to exactly ONE visible, enabled element;
3. have confirmed it is on the page of the intended entity (see callers).
Otherwise ``UnsafeUIError`` is raised and the action becomes NEEDS_ATTENTION.
"""

import re

from playwright.async_api import Locator, Page

from agent.cardmarket import selectors
from agent.cardmarket.selectors import Kind, SelectorSpec, Strategy
from agent.errors import UnsafeUIError


def require_verified(*keys: str) -> None:
    unverified = [k for k in keys if not selectors.get(k).verified]
    if unverified:
        raise UnsafeUIError(
            "write action refused: selectors not verified against live Cardmarket: "
            + ", ".join(unverified)
        )


def _regex(pattern: str) -> re.Pattern[str]:
    """Registry patterns may start with ``(?i)``; the browser-side (JS) regex
    engine does not support inline flags, so translate it to a Python flag."""
    if pattern.startswith("(?i)"):
        return re.compile(pattern[4:], re.IGNORECASE)
    return re.compile(pattern)


def _locator(page: Page, strategy: Strategy) -> Locator:
    if strategy.kind == Kind.ROLE:
        name = _regex(strategy.name) if strategy.name else None
        return page.get_by_role(strategy.value, name=name)  # type: ignore[arg-type]
    if strategy.kind == Kind.LABEL:
        return page.get_by_label(_regex(strategy.value))
    if strategy.kind == Kind.TEXT:
        return page.get_by_text(strategy.value, exact=True)
    if strategy.kind == Kind.TEST_ID:
        return page.get_by_test_id(strategy.value)
    if strategy.kind == Kind.XPATH:
        return page.locator(f"xpath={strategy.value}")
    return page.locator(strategy.value)


async def resolve_unique(page: Page, spec: SelectorSpec) -> Locator:
    """Return the single visible+enabled element for a critical selector.

    Strategies are tried in order; the first one matching anything decides.
    Ambiguity (more than one match) is an error, never "pick the first".
    """
    for strategy in spec.strategies:
        locator = _locator(page, strategy)
        count = await locator.count()
        if count == 0:
            continue
        if count > 1:
            raise UnsafeUIError(
                f"'{spec.key}' is ambiguous: {count} elements match ({strategy.kind})"
            )
        if not await locator.is_visible() or not await locator.is_enabled():
            raise UnsafeUIError(f"'{spec.key}' is not visible/enabled")
        return locator
    raise UnsafeUIError(f"'{spec.key}' not found on the page")
