"""Read-only selector health check against the live site.

Visits the known Cardmarket pages with the persisted session and reports, for
every selector in the registry, how many elements each strategy matches. It
never clicks or types. Screenshots + HTML are saved to the artifacts dir so
selectors can be adjusted offline. Use it:

- once after the first pairing, to calibrate the registry;
- as a smoke test after Cardmarket UI changes (CARDMARKET_CHANGED errors).
"""

from typing import Any

from agent.cardmarket import selectors
from agent.cardmarket.auth.detector import detect_session
from agent.cardmarket.browser.session import BrowserSession
from agent.cardmarket.parsers.common import parse_html
from agent.cardmarket.urls import CardmarketUrls
from agent.config import AgentSettings

_PAGES: dict[str, tuple[str, ...]] = {
    "home": ("session.",),
    "orders": ("orders.list", "orders.row", "orders.next_page"),
    "messages": ("messages.list", "messages.thread_"),
    "carts": ("carts.",),
}


async def run_calibration(settings: AgentSettings) -> dict[str, Any]:
    urls = CardmarketUrls.from_settings(settings)
    capture = settings.model_copy(update={"debug_capture_html": True})
    browser = BrowserSession(capture)
    await browser.start()
    report: dict[str, Any] = {"registry_version": selectors.REGISTRY_VERSION, "pages": {}}
    targets = {
        "home": urls.home,
        "orders": urls.order_lists[0],
        "messages": urls.messages,
        "carts": urls.carts,
    }
    try:
        for page_name, url in targets.items():
            html = await browser.goto(url)
            tree = parse_html(html)
            artifacts = await browser.capture_failure(f"calibrate-{page_name}")
            matches: dict[str, dict[str, int]] = {}
            for key, spec in selectors.REGISTRY.items():
                if not key.startswith(_PAGES[page_name]):
                    continue
                matches[key] = {s: len(tree.css(s)) for s in spec.css}
            report["pages"][page_name] = {
                "url": url,
                "session": str(detect_session(html).status),
                "artifacts": artifacts,
                "selectors": matches,
            }
    finally:
        await browser.close()
    report["critical_unverified"] = selectors.critical_unverified()
    return report
