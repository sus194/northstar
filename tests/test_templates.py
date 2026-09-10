"""Regression coverage for notify/templates.py -- these are plain string
templates with no type checker watching field names against models.py, so
a rename (e.g. ExitReview.as_of) can silently break rendering only when a
real exit condition fires. Caught once via manual smoke test; pinned here."""

from __future__ import annotations

from datetime import date

from northstar.models import ExitReview
from northstar.notify.templates import exit_body, exit_subject


def test_exit_body_renders_for_every_condition():
    for condition in ("stop", "target", "time", "regime", "event"):
        review = ExitReview(symbol="BBB", condition=condition, close=23.17, as_of=date(2024, 6, 28))
        body = exit_body(review)
        assert "BBB" in body
        assert "2024-06-28" in body
        assert condition in body or condition in exit_subject(review)
