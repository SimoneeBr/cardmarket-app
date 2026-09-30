from collections.abc import Awaitable, Callable

from cmc_shared.models import NormalizedConversation, NormalizedConversationSummary

from agent.cardmarket.parsers.messages import parse_conversation_list, parse_thread
from agent.cardmarket.urls import CardmarketUrls

Loader = Callable[[str], Awaitable[str]]


class MessagesReader:
    def __init__(self, load: Loader, urls: CardmarketUrls) -> None:
        self.load, self.urls = load, urls

    async def list(self) -> list[NormalizedConversationSummary]:
        out = []
        for summary in parse_conversation_list(await self.load(self.urls.messages)):
            if summary.source_url:
                summary = summary.model_copy(
                    update={"source_url": self.urls.absolute(summary.source_url)}
                )
            out.append(summary)
        return out

    def thread_url(self, summary: NormalizedConversationSummary) -> str:
        if summary.source_url and self.urls.is_cardmarket(summary.source_url):
            return summary.source_url
        return self.urls.thread(summary.cardmarket_id)

    async def thread(self, summary: NormalizedConversationSummary) -> NormalizedConversation:
        url = self.thread_url(summary)
        return parse_thread(await self.load(url), summary, url)
