"""Unit tests for the order lifecycle graph.

These pin the transition rules themselves, independent of HTTP/auth. The
behavioural consequences (who can cancel, who can mark delivered) are covered
in tests/test_api_e2e.py.
"""

from backend.models import VALID_ORDER_STATUSES
from backend.order_state import (
    ORDER_TRANSITIONS,
    TERMINAL_ORDER_STATUSES,
    can_transition,
    describe_illegal_transition,
    legal_targets,
)


def test_every_status_appears_in_the_graph():
    """A status missing from ORDER_TRANSITIONS would be silently terminal."""
    assert set(ORDER_TRANSITIONS) == set(VALID_ORDER_STATUSES)


def test_terminal_states_have_no_outgoing_edges():
    assert TERMINAL_ORDER_STATUSES == {"DELIVERED", "CANCELLED"}
    for status in TERMINAL_ORDER_STATUSES:
        assert legal_targets(status) == frozenset()


def test_nothing_leaves_a_terminal_state():
    for terminal in TERMINAL_ORDER_STATUSES:
        for target in VALID_ORDER_STATUSES:
            assert not can_transition(terminal, target), (
                f"{terminal} must not be able to reach {target}"
            )


def test_strict_happy_path_is_legal():
    path = [
        ("PLACED", "CONFIRMED"),
        ("CONFIRMED", "PREPARING"),
        ("PREPARING", "OUT_FOR_DELIVERY"),
        ("OUT_FOR_DELIVERY", "DELIVERED"),
    ]
    for current, target in path:
        assert can_transition(current, target), f"{current} -> {target} should be legal"


def test_dispatch_can_skip_ahead():
    """Pre-packed items dispatch without a confirm/prepare press."""
    assert can_transition("PLACED", "OUT_FOR_DELIVERY")
    assert can_transition("CONFIRMED", "OUT_FOR_DELIVERY")


def test_cancellable_until_dispatch():
    """Once a rider has the food, cancelling is no longer the customer's call."""
    for current in ("PLACED", "CONFIRMED", "PREPARING"):
        assert can_transition(current, "CANCELLED")
    for current in ("OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"):
        assert not can_transition(current, "CANCELLED")


def test_cannot_go_backwards():
    assert not can_transition("PREPARING", "PLACED")
    assert not can_transition("OUT_FOR_DELIVERY", "CONFIRMED")
    assert not can_transition("PREPARING", "DELIVERED")


def test_unknown_status_is_refused():
    """An unrecognised current status must not look like a valid terminal."""
    assert not can_transition("TOTALLY_MADE_UP", "DELIVERED")
    assert legal_targets("TOTALLY_MADE_UP") == frozenset()


def test_error_message_explains_why():
    msg = describe_illegal_transition("DELIVERED", "PLACED")
    assert "DELIVERED" in msg and "PLACED" in msg and "final state" in msg

    # Non-terminal current state: list what *is* reachable.
    msg = describe_illegal_transition("PLACED", "DELIVERED")
    assert "DELIVERED" in msg
    assert "Allowed next: CANCELLED, CONFIRMED, OUT_FOR_DELIVERY." in msg

    # A terminal *target* is explained as a routing problem, not a "final state"
    # claim about the current status (PLACED is not final).
    msg = describe_illegal_transition("PLACED", "CANCELLED")
    assert "PLACED is a final state" not in msg
    assert "/cancel" in msg
