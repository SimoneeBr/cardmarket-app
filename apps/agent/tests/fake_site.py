"""A tiny fake "Cardmarket" web site for browser tests.

It serves pages with the structure expected by the selector registry and keeps
server-side state, so writes performed by the real Playwright adapter (form
posts) can be verified by reloading pages, exactly like on the real site.
"""

import html
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

PREFIX = "/it/Magic"

HEADER_IN = '<header><a data-testid="account-menu" href="/it/Magic/Account">shop_it</a></header>'
HEADER_OUT = '<header><a href="/it/Magic/Login">Accedi</a></header>'
LOGIN_FORM = '<form id="login-form" action="/it/Magic/PostGetAction/User_Login" method="post"><input name="username"><input type="password" name="userPassword"><button>Login</button></form>'


@dataclass
class SiteState:
    logged_in: bool = True
    duplicate_send_button: bool = False
    swallow_messages: bool = False  # accept the POST but never show the message
    login_after_polls: int | None = None
    polls: int = 0
    posts: list[dict[str, Any]] = field(default_factory=list)
    orders: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "1184201": {
                "buyer": "mario_rossi",
                "status": "Pagato",
                "total": "14,95 €",
                "tracking": None,
            },
            "1184202": {
                "buyer": "luca.bianchi",
                "status": "Non pagato",
                "total": "4,20 €",
                "tracking": None,
            },
            "1184190": {
                "buyer": "andrea_tcg",
                "status": "Spedito",
                "total": "9,10 €",
                "tracking": "RR1IT",
            },
        }
    )
    messages: dict[str, list[dict[str, str]]] = field(
        default_factory=lambda: {
            "T7001": [
                {
                    "id": "M9001",
                    "dir": "inbound",
                    "body": "Quando pensi di spedire?",
                    "at": "2026-09-30T10:28:00+02:00",
                },
            ]
        }
    )
    next_message: int = 9100


LIST_STATUS = {"Unpaid": "Non pagato", "Paid": "Pagato", "Sent": "Spedito", "Arrived": "Arrivato"}


def _page(state: SiteState, body: str) -> str:
    return f"<html><body>{HEADER_IN if state.logged_in else HEADER_OUT}<main>{body}</main></body></html>"


def render(state: SiteState, path: str) -> tuple[int, str]:
    if path in ("/it/Magic/Login",) or not state.logged_in:
        if state.login_after_polls is not None:
            state.polls += 1
            if state.polls >= state.login_after_polls:
                state.logged_in = True
                return 200, _page(state, "<h1>Benvenuto</h1>")
        return 200, _page(state, LOGIN_FORM)
    if path in (f"{PREFIX}/", PREFIX):
        return 200, _page(state, "<h1>Home</h1>")
    if path.startswith(f"{PREFIX}/Orders/Sales/ShoppingCarts"):
        rows = '<div data-cart-id="C1"><span data-field="buyer">giulia89</span><span data-field="status">Da pagare</span><span data-field="total">3,00 €</span><span data-field="item-count">2</span></div>'
        return 200, _page(state, f'<div data-page="carts-list">{rows}</div>')
    if path.startswith(f"{PREFIX}/Orders/Sales/"):
        wanted = LIST_STATUS.get(path.rsplit("/", 1)[-1])
        rows = "".join(
            f'<tr data-order-id="{oid}"><td data-field="buyer">{o["buyer"]}</td><td data-field="status">{o["status"]}</td>'
            f'<td data-field="total">{o["total"]}</td><td data-field="item-count">1</td>'
            f'<td><a data-field="detail-link" href="{PREFIX}/Orders/{oid}">d</a></td></tr>'
            for oid, o in state.orders.items()
            if o["status"] == wanted
        )
        return 200, _page(state, f'<table data-page="orders-list">{rows}</table>')
    if path.startswith(f"{PREFIX}/Orders/"):
        oid = path.rsplit("/", 1)[-1]
        order = state.orders.get(oid)
        if order is None:
            return 404, _page(state, "not found")
        ship = ""
        if order["status"] == "Pagato":
            ship = (
                '<button type="button" data-action="confirm-shipping" onclick="document.getElementById(\'dlg\').hidden=false">Segna come spedito</button>'
                f'<form id="dlg" hidden method="post" action="{PREFIX}/Orders/{oid}/ship"><label for="tn">Tracking</label>'
                '<input id="tn" name="trackingNumber"><button type="submit" data-action="confirm-shipping-submit">Conferma</button></form>'
            )
        tracking = (
            f'<div data-field="tracking">{order["tracking"]}</div>' if order["tracking"] else ""
        )
        body = (
            f'<div data-page="order-detail"><h1><span data-field="order-id">#{oid}</span></h1>'
            f'<div data-field="buyer">{order["buyer"]}</div><div data-field="status">{order["status"]}</div>'
            f'<div data-field="total">{order["total"]}</div>{tracking}'
            '<table><tr data-article-row><td data-field="quantity">1</td><td data-field="name">Lightning Bolt</td><td data-field="price">1,00 €</td></tr></table>'
            f"{ship}</div>"
        )
        return 200, _page(state, body)
    if path == f"{PREFIX}/Account/Messages":
        rows = "".join(
            f'<li data-thread-id="{tid}" data-unread="true"><span data-field="partner">mario_rossi</span>'
            f'<span data-field="order-ref">#1184201</span><span data-field="preview">{html.escape(msgs[-1]["body"])}</span>'
            f'<a data-field="thread-link" href="{PREFIX}/Account/Messages/{tid}">apri</a></li>'
            for tid, msgs in state.messages.items()
        )
        return 200, _page(state, f'<ul data-page="messages-list">{rows}</ul>')
    if path.startswith(f"{PREFIX}/Account/Messages/"):
        tid = path.rsplit("/", 1)[-1]
        msgs = state.messages.get(tid)
        if msgs is None:
            return 404, _page(state, "not found")
        bubbles = "".join(
            f'<div data-message-id="{m["id"]}" data-direction="{m["dir"]}"><p data-field="body">{html.escape(m["body"])}</p>'
            f'<time data-field="date" datetime="{m["at"]}">x</time></div>'
            for m in msgs
        )
        buttons = '<button type="submit" data-action="send-message">Invia</button>' * (
            2 if state.duplicate_send_button else 1
        )
        form = f'<form method="post"><label for="msg">Messaggio</label><textarea id="msg" name="message"></textarea>{buttons}</form>'
        body = f'<section data-page="message-thread" data-thread-id="{tid}"><h1><span data-field="partner">mario_rossi</span></h1>{bubbles}{form}</section>'
        return 200, _page(state, body)
    return 404, _page(state, "not found")


def handle_post(state: SiteState, path: str, form: dict[str, str]) -> str:
    state.posts.append({"path": path, **form})
    if path.startswith(f"{PREFIX}/Account/Messages/"):
        tid = path.rsplit("/", 1)[-1]
        if not state.swallow_messages:
            state.next_message += 1
            state.messages[tid].append(
                {
                    "id": f"M{state.next_message}",
                    "dir": "outbound",
                    "body": form.get("message", ""),
                    "at": "2026-09-30T11:00:00+02:00",
                }
            )
        return path
    if path.endswith("/ship"):
        oid = path.split("/")[-2]
        state.orders[oid]["status"] = "Spedito"
        state.orders[oid]["tracking"] = form.get("trackingNumber") or None
        return f"{PREFIX}/Orders/{oid}"
    return path


class FakeSite:
    def __init__(self) -> None:
        self.state = SiteState()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, body: str, headers: dict[str, str] | None = None) -> None:
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                status, body = render(site.state, path)
                cookie = (
                    {"Set-Cookie": "cm_session=abc; Path=/; Max-Age=86400"}
                    if site.state.logged_in
                    else {}
                )
                self._send(status, body, cookie)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
                target = handle_post(site.state, urlparse(self.path).path, form)
                self.send_response(303)
                self.send_header("Location", target)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host!s}:{port}"

    def __enter__(self) -> "FakeSite":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
