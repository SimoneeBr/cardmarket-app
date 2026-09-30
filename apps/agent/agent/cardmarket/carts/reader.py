from collections.abc import Awaitable, Callable

from cmc_shared.models import NormalizedCart, NormalizedCartSummary

from agent.cardmarket.parsers.carts import parse_cart_detail, parse_cart_list
from agent.cardmarket.urls import CardmarketUrls

Loader = Callable[[str], Awaitable[str]]


class CartsReader:
    def __init__(self, load: Loader, urls: CardmarketUrls) -> None:
        self.load, self.urls = load, urls

    async def list(self) -> list[NormalizedCartSummary]:
        out = []
        for summary in parse_cart_list(await self.load(self.urls.carts)):
            if summary.source_url:
                summary = summary.model_copy(
                    update={"source_url": self.urls.absolute(summary.source_url)}
                )
            out.append(summary)
        return out

    async def detail(self, summary: NormalizedCartSummary) -> NormalizedCart:
        if not summary.source_url:
            # TODO: VERIFY AGAINST LIVE CARDMARKET - cart detail URL scheme unknown.
            return NormalizedCart(**summary.model_dump())
        return parse_cart_detail(await self.load(summary.source_url), summary, summary.source_url)
