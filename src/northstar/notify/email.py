"""Email adapter (spec section 7).

Real delivery needs a transactional provider (Postmark, Resend, SES) and an
API key -- a Phase 0/2 decision the operator has to make (cost, DKIM/SPF
setup, webhook endpoint for delivery tracking). Until that's wired up,
ConsoleEmailSender is the default: it writes the message to stdout/log and
returns a fake message id, so the rest of the pipeline (ledger writes,
review page generation, rate limiting) can be built and tested end-to-end
without live credentials or risking a real send.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("northstar.notify")


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    body_text: str


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> str:
        """Returns a provider message id."""
        ...


@dataclass(slots=True)
class ConsoleEmailSender:
    """Default sender: logs the email instead of delivering it.

    Use this for local development, backtests, and paper trading until a
    real provider is configured. Swapping in a real sender later means
    writing one small adapter class -- nothing else in notify/ changes.
    """

    sent: list[EmailMessage] | None = None

    def __post_init__(self) -> None:
        if self.sent is None:
            self.sent = []

    def send(self, message: EmailMessage) -> str:
        logger.info("EMAIL to=%s subject=%r\n%s", message.to, message.subject, message.body_text)
        self.sent.append(message)
        return f"console-{len(self.sent)}"


class KillSwitchEngaged(RuntimeError):
    pass


@dataclass(slots=True)
class KillSwitchGuardedSender:
    """Wraps any EmailSender; refuses to send while the kill switch is on
    (spec section 11: "Kill switch disables sends without data loss.")."""

    inner: EmailSender
    enabled: bool = True

    def send(self, message: EmailMessage) -> str:
        if not self.enabled:
            raise KillSwitchEngaged("Northstar kill switch is engaged; no email was sent.")
        return self.inner.send(message)
