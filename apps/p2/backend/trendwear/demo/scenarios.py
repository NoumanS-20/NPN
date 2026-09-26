"""Two moments the P2 demo lands on, written down rather than typed live."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoScenario:
    key: str
    name: str
    description: str
    say_this: str
    page: str


PRELOADED: dict[str, DemoScenario] = {
    "baseline": DemoScenario(
        key="baseline",
        name="The reconciliation",
        description="The cockpit and the reconciliation screen, as the cycle stands.",
        say_this=(
            "Merchandising wants to sell 696,000 units this quarter. The forecast says less, and "
            "the plants can make 652,000. That gap is 5.6 million in revenue, and reconciling it "
            "is the entire point of an S&OP cycle. The number at the bottom is what the business "
            "commits to, and it can never be higher than what the plants can actually make."
        ),
        page="/pages/reconcile.html",
    ),
    "markdown": DemoScenario(
        key="markdown",
        name="Markdown, and what we could not measure",
        description="The markdown screen, including the elasticity we had to assume.",
        say_this=(
            "Ten styles are tracking below their sell-through target, so the model recommends a "
            "markdown week and depth for each. One thing to be straight about: we tried to fit the "
            "price response from the data and it explains none of the variation, so this uses a "
            "published apparel elasticity and says so on the screen. We would rather show you the "
            "assumption than a curve fitted to noise."
        ),
        page="/pages/markdown.html",
    ),
}
