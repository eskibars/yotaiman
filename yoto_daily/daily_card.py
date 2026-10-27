"""Which card is the daily card.

A Yoto card is paired with a player in the Yoto app.  The card the player
is paired with is the one that matters: content written to a card nobody
has paired is a card nobody will ever hear.

So the daily card is *adopted*, not invented.  The order is:

1. the id in the configuration, which is the strongest statement of intent
2. the id remembered from the last run
3. an existing card whose title looks like the daily card, for the case
   where the state was lost but the card is still there
4. only then, a new card

Step three is what stops the project from quietly starting a new card
every time the state file goes missing, which is how a whole morning of
work ends up on a card that is not in anybody's hand.
"""

from __future__ import annotations

from typing import Any

#: The card title to look for when the state has been lost.
DEFAULT_TITLE_HINT = "daily"


def _looks_like_daily_card(title: str, hint: str) -> bool:
    if not title:
        return False
    return hint.lower() in title.lower()


def find_daily_card(yoto: Any, hint: str = DEFAULT_TITLE_HINT) -> str:
    """An existing card that looks like the daily card, if there is one."""
    try:
        cards = yoto.cards.list()
    except Exception:
        return ""
    for card in cards:
        if _looks_like_daily_card(getattr(card, "title", "") or "", hint):
            return getattr(card, "card_id", "")
    return ""


def daily_card_id(
    yoto: Any,
    state: Any,
    settings: Any,
    *,
    title: str = "",
    hint: str = DEFAULT_TITLE_HINT,
) -> str:
    """The card to write the day's content to.

    It is created only when there is nothing to adopt.
    """
    configured = str(getattr(settings, "daily_card_id", "") or "")
    if configured:
        return configured

    stored = str(state.get("daily_card_id", "") or "")
    if stored:
        try:
            if yoto.cards.exists(stored):
                return stored
        except Exception:
            pass

    adopted = find_daily_card(yoto, hint)
    if adopted:
        state.set("daily_card_id", adopted)
        return adopted

    card = yoto.cards.create(title=title or f"Daily")
    state.set("daily_card_id", card.card_id)
    return card.card_id


__all__ = ["DEFAULT_TITLE_HINT", "daily_card_id", "find_daily_card"]
