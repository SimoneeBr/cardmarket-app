"""Persistent Chromium context: the Cardmarket session lives in the profile dir.

The profile directory must be on a persistent, private volume
(``/data/browser-profile``): losing it means pairing again.
"""

import asyncio
import contextlib
import logging
import random
import re
import time
from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from agent.config import AgentSettings
from agent.errors import NavigationTimeoutError, NetworkError

log = logging.getLogger("cmc.agent.browser")

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_.-]+")


def _prepare_profile(profile: Path) -> Path:
    profile.mkdir(parents=True, exist_ok=True)
    profile.chmod(0o700)  # cookies live here: keep it private
    return profile


class BrowserSession:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._headless = settings.headless
        self._tracing = False

    # ---------------------------------------------------------- lifecycle

    async def start(self, *, headless: bool | None = None) -> None:
        if self._context is not None:
            return
        self._headless = self.settings.headless if headless is None else headless
        profile = _prepare_profile(Path(self.settings.browser_profile_dir))
        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=self._headless,
            locale=self.settings.browser_locale,
            timezone_id=self.settings.browser_timezone,
            viewport={"width": 1366, "height": 900},
            accept_downloads=False,
            args=["--disable-dev-shm-usage"],
        )
        self._context.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        self._context.set_default_timeout(self.settings.action_timeout_ms)
        if self.settings.trace_on_failure:
            await self._context.tracing.start(screenshots=True, snapshots=True)
            self._tracing = True
        self._page = (
            self._context.pages[0] if self._context.pages else await self._context.new_page()
        )
        log.info("browser started", extra={"headless": self._headless, "profile": str(profile)})

    async def close(self) -> None:
        if self._context is not None:
            with contextlib.suppress(PlaywrightError):
                if self._tracing:
                    await self._context.tracing.stop()
                await self._context.close()  # flushes cookies to the profile
        if self._pw is not None:
            await self._pw.stop()
        self._context = self._page = self._pw = None
        self._tracing = False

    async def restart(self, *, headless: bool) -> None:
        await self.close()
        await self.start(headless=headless)

    @property
    def headless(self) -> bool:
        return self._headless

    @property
    def page(self) -> Page:
        if self._page is None or self._page.is_closed():
            raise RuntimeError("browser not started")
        return self._page

    # --------------------------------------------------------- navigation

    async def polite_pause(self) -> None:
        low, high = self.settings.min_navigation_delay_ms, self.settings.max_navigation_delay_ms
        if high > 0:
            await asyncio.sleep(random.uniform(low, max(low, high)) / 1000)  # noqa: S311

    async def goto(self, url: str) -> str:
        """Navigate and return the page HTML. Network problems are classified."""
        await self.polite_pause()
        try:
            response = await self.page.goto(url, wait_until="domcontentloaded")
        except PlaywrightTimeout as exc:
            raise NavigationTimeoutError(f"timeout loading {url}") from exc
        except PlaywrightError as exc:
            raise NetworkError(f"navigation to {url} failed: {exc.message[:200]}") from exc
        if response is not None and response.status >= 500:
            raise NetworkError(f"{url} returned HTTP {response.status}")
        return await self.content()

    async def content(self) -> str:
        html = await self.page.content()
        if self.settings.debug_capture_html:
            await self._save_text(f"html-{int(time.time() * 1000)}.html", html)
        return html

    # ---------------------------------------------------------- artifacts

    def _artifact_path(self, name: str) -> Path:
        directory = Path(self.settings.artifacts_dir)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / _SAFE_NAME.sub("_", name)[:120]

    async def _save_text(self, name: str, data: str) -> str:
        path = self._artifact_path(name)
        path.write_text(data)
        return path.name

    async def capture_failure(self, label: str) -> list[str]:
        """Screenshot (+ trace, + HTML in debug) for post-mortem analysis."""
        if self._page is None or self._page.is_closed():
            return []
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = f"{stamp}-{label}"
        saved: list[str] = []
        try:
            shot = self._artifact_path(f"{base}.png")
            await self.page.screenshot(path=str(shot), full_page=True)
            saved.append(shot.name)
            if self.settings.debug_capture_html:
                saved.append(await self._save_text(f"{base}.html", await self.page.content()))
            if self._tracing and self._context is not None:
                trace = self._artifact_path(f"{base}.trace.zip")
                await self._context.tracing.stop(path=str(trace))
                await self._context.tracing.start(screenshots=True, snapshots=True)
                saved.append(trace.name)
        except PlaywrightError:
            log.warning("could not capture failure artifacts", exc_info=True)
        self._prune_artifacts()
        log.info("failure artifacts saved", extra={"files": saved})
        return saved

    def _prune_artifacts(self) -> None:
        directory = Path(self.settings.artifacts_dir)
        files = sorted(directory.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[self.settings.artifacts_keep :]:
            with contextlib.suppress(OSError):
                old.unlink()
