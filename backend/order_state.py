"""Order lifecycle state machine.

Why this module exists
----------------------
Before it, `PATCH /orders/{id}/status` accepted any status string that appeared
in ``VALID_ORDER_STATUSES`` and overwrote ``order.status`` unconditionally. That
allowed transitions that are meaningless in the real world -- ``DELIVERED ->
PLACED``, ``CANCELLED -> OUT_FOR_DELIVERY`` -- and the second one was actively
dangerous: the simulation loop advances any ``OUT_FOR_DELIVERY`` order to
``DELIVERED``, so a cancelled order could be resurrected, "delivered", and
billed.

The rule is now explicit: a transition is legal only if it is an edge in the
graph below. Terminal states have no outgoing edges, so they cannot be left.

    PLACED ──> CONFIRMED ──> PREPARING ──> OUT_FOR_DELIVERY ──> DELIVERED
       │            │             │                                 (terminal)
       └────────────┴─────────────┴──> CANCELLED
                                             (terminal)

Two deliberate design choices:

* ``PLACED -> OUT_FOR_DELIVERY`` and ``CONFIRMED -> OUT_FOR_DELIVERY`` are
  allowed so a kitchen that is ahead of schedule can dispatch without first
  pressing "confirm" and "preparing". The restaurant UI's ``NEXT_STATUS`` map
  walks the strict path; these edges mean the strict path is not the only legal
  one. This preserves the app's existing dispatch behaviour (pre-packed items,
  and the flow the tests and the seeded demo rely on) while still refusing
  every transition that would actually be wrong. Note this is a *laxness in the
  business flow*, not an authorization hole: dispatching still requires the
  restaurant to own the order and a driver to be assigned, and only the assigned
  driver or an admin can mark it DELIVERED.
* ``CANCELLED`` is reachable from any pre-delivery state, but *only* through
  ``POST /orders/{id}/cancel``, which enforces its own actor check (the
  customer who owns the order, or an admin). It is deliberately not reachable
  through the generic status endpoint -- otherwise a restaurant could cancel a
  customer's order and sidestep that check.
"""

from __future__ import annotations

#: Legal transitions. A status not present as a key is terminal.
ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    "PLACED": frozenset({"CONFIRMED", "OUT_FOR_DELIVERY", "CANCELLED"}),
    "CONFIRMED": frozenset({"PREPARING", "OUT_FOR_DELIVERY", "CANCELLED"}),
    "PREPARING": frozenset({"OUT_FOR_DELIVERY", "CANCELLED"}),
    "OUT_FOR_DELIVERY": frozenset({"DELIVERED"}),
    "DELIVERED": frozenset(),
    "CANCELLED": frozenset(),
}

#: States from which nothing further may happen.
TERMINAL_ORDER_STATUSES = frozenset(
    status for status, nexts in ORDER_TRANSITIONS.items() if not nexts
)


def can_transition(current: str, target: str) -> bool:
    """Return True if ``current -> target`` is a legal edge."""
    return target in ORDER_TRANSITIONS.get(current, frozenset())


def legal_targets(current: str) -> frozenset[str]:
    """Statuses reachable from ``current`` (empty for terminal states)."""
    return ORDER_TRANSITIONS.get(current, frozenset())


def describe_illegal_transition(current: str, target: str) -> str:
    """Build a 400-worthy message explaining why a transition was refused."""
    if current in TERMINAL_ORDER_STATUSES:
        return (
            f"Cannot change status from {current} to {target}: "
            f"{current} is a final state."
        )
    if target == "CANCELLED":
        # CANCELLED is the one target that is routed elsewhere on purpose:
        # it carries its own actor check that this endpoint does not.
        return (
            f"Cannot change status from {current} to {target}: "
            f"cancel via POST /orders/{{id}}/cancel."
        )
    allowed = sorted(legal_targets(current))
    allowed_text = ", ".join(allowed) if allowed else "nothing"
    return (
        f"Cannot change status from {current} to {target}. "
        f"Allowed next: {allowed_text}."
    )
