from collections.abc import Awaitable, Callable

from cmc_shared.models import NormalizedOrder, NormalizedOrderSummary

from agent.cardmarket.parsers.orders import parse_order_detail, parse_order_list
from agent.cardmarket.urls import CardmarketUrls

Loader = Callable[[str], Awaitable[str]]


class OrdersReader:
    def __init__(self, load: Loader, urls: CardmarketUrls, max_pages: int) -> None:
        self.load, self.urls, self.max_pages = load, urls, max_pages

    async def list(self) -> list[NormalizedOrderSummary]:
        """Scan the first pages of every status list (newest first)."""
        seen: dict[str, NormalizedOrderSummary] = {}
        for list_url in self.urls.order_lists:
            url: str | None = list_url
            for _ in range(self.max_pages):
                if url is None:
                    break
                summaries, next_href = parse_order_list(await self.load(url), url)
                for summary in summaries:
                    if summary.source_url:
                        summary = summary.model_copy(
                            update={"source_url": self.urls.absolute(summary.source_url)}
                        )
                    seen.setdefault(summary.cardmarket_id, summary)
                url = self.urls.absolute(next_href) if next_href else None
        return list(seen.values())

    async def detail(self, summary: NormalizedOrderSummary) -> NormalizedOrder:
        url = self.detail_url(summary)
        return parse_order_detail(await self.load(url), url, summary.cardmarket_id)

    def detail_url(self, summary: NormalizedOrderSummary) -> str:
        if summary.source_url and self.urls.is_cardmarket(summary.source_url):
            return summary.source_url
        return self.urls.order_detail(summary.cardmarket_id)
