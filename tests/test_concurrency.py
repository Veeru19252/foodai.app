"""Concurrency tests: duplicate order creation under simultaneous requests.

These exist because the idempotency design makes a specific promise -- the
unique index, not application code, is what stops a double order. That promise
is only believable if it is tested with genuinely concurrent transactions, so
these use real threads, real sessions, and real PostgreSQL rather than
sequentially faking a retry.

Why threads and not asyncio: the race lives in PostgreSQL, not in Python. Each
thread gets its own SQLAlchemy Session and therefore its own database
connection, which is the only way to get two transactions in flight at once.
An in-process lock would prove nothing.
"""

import threading
import time
import uuid

from backend import idempotency
from backend.db import SessionLocal
from backend.models import IdempotencyRecord, Order, User

USER_ID = 1


def _create_order_in_session(db):
    """Minimal order creation -- the real endpoint wraps this in more checks."""
    order = Order(
        customer_id=USER_ID,
        restaurant_id=1,
        total=100.0,
        status="PLACED",
    )
    db.add(order)
    db.flush()
    return order.id


def test_concurrent_same_key_creates_exactly_one_order():
    """Two transactions claim the same key simultaneously -> one order.

    Thread A claims the key, then pauses *before* committing. Thread B starts
    while A's transaction is still open, so B's INSERT must block on the unique
    index. When A commits, B's insert fails cleanly, B reads A's committed row
    and replays A's order instead of creating its own.
    """
    key = str(uuid.uuid4())
    payload = {"restaurant_id": 1, "items": [{"menu_item_id": 1, "quantity": 1}]}

    a_claimed = threading.Event()
    allow_a_commit = threading.Event()
    results = {}
    errors = {}

    def thread_a():
        db = SessionLocal()
        try:
            _orders, is_replay = idempotency.claim(
                db, USER_ID, key, idempotency.ENDPOINT_ORDERS, payload
            )
            assert not is_replay
            order_id = _create_order_in_session(db)
            idempotency.record_created(
                db, USER_ID, key, idempotency.ENDPOINT_ORDERS, [order_id]
            )
            a_claimed.set()
            # Hold the transaction open so B has to contend for the key.
            allow_a_commit.wait(timeout=10)
            db.commit()
            results["a"] = order_id
        except Exception as exc:  # pragma: no cover - surfaced via errors
            errors["a"] = exc
            a_claimed.set()
        finally:
            db.close()

    def thread_b():
        # Wait until A definitely holds the uncommitted claim.
        a_claimed.wait(timeout=10)
        db = SessionLocal()
        try:
            orders, is_replay = idempotency.claim(
                db, USER_ID, key, idempotency.ENDPOINT_ORDERS, payload
            )
            results["b_replay"] = is_replay
            results["b_orders"] = [o.id for o in orders]
        except Exception as exc:  # pragma: no cover - surfaced via errors
            errors["b"] = exc
        finally:
            db.close()

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    tb.start()
    time.sleep(0.4)  # let B reach the blocking INSERT
    allow_a_commit.set()
    ta.join(timeout=15)
    tb.join(timeout=15)

    assert not errors, "threads raised: {}".format(errors)
    assert "a" in results, "thread A never created an order"
    assert results["b_replay"] is True, "thread B should have replayed, not created"
    assert results["b_orders"] == [results["a"]], "B replayed a different order"

    db = SessionLocal()
    try:
        claims = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key == key)
            .count()
        )
        assert claims == 1
    finally:
        db.close()


def test_concurrent_different_keys_create_two_orders():
    """The control: distinct keys must not be collapsed into one order.

    Guards against a fix that is too aggressive -- e.g. deduping on payload
    fingerprint instead of on the client-supplied key, which would silently
    drop a customer's genuine second order.
    """
    payload = {"restaurant_id": 1, "items": [{"menu_item_id": 1, "quantity": 1}]}
    key_a, key_b = str(uuid.uuid4()), str(uuid.uuid4())

    db_a, db_b = SessionLocal(), SessionLocal()
    try:
        _o, replay_a = idempotency.claim(
            db_a, USER_ID, key_a, idempotency.ENDPOINT_ORDERS, payload
        )
        _o, replay_b = idempotency.claim(
            db_b, USER_ID, key_b, idempotency.ENDPOINT_ORDERS, payload
        )
        assert not replay_a and not replay_b
        id_a = _create_order_in_session(db_a)
        id_b = _create_order_in_session(db_b)
        idempotency.record_created(
            db_a, USER_ID, key_a, idempotency.ENDPOINT_ORDERS, [id_a]
        )
        idempotency.record_created(
            db_b, USER_ID, key_b, idempotency.ENDPOINT_ORDERS, [id_b]
        )
        db_a.commit()
        db_b.commit()
    finally:
        db_a.close()
        db_b.close()

    assert id_a != id_b, "two different keys must produce two distinct orders"


def test_crashed_claim_does_not_block_a_retry():
    """A rolled-back attempt frees its key for the next real attempt.

    This is the property that makes a retry safe after a crash: the claim and
    the order share a transaction, so a process dying between them leaves
    neither behind. If claims outlived their transaction, every transient
    error would permanently poison that key for that user.
    """
    key = str(uuid.uuid4())
    payload = {"restaurant_id": 1, "items": [{"menu_item_id": 1, "quantity": 1}]}

    # Attempt 1: claim, then blow up before committing.
    db = SessionLocal()
    try:
        idempotency.claim(db, USER_ID, key, idempotency.ENDPOINT_ORDERS, payload)
        _create_order_in_session(db)
        raise RuntimeError("simulated crash after flush, before commit")
    except RuntimeError:
        db.rollback()
    finally:
        db.close()

    # The key must be free.
    db = SessionLocal()
    try:
        assert (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key == key)
            .count()
            == 0
        )
        _orders, is_replay = idempotency.claim(
            db, USER_ID, key, idempotency.ENDPOINT_ORDERS, payload
        )
        assert not is_replay, "a rolled-back claim must not replay"
        order_id = _create_order_in_session(db)
        idempotency.record_created(
            db, USER_ID, key, idempotency.ENDPOINT_ORDERS, [order_id]
        )
        db.commit()
    finally:
        db.close()

    # And the retry is now the one that succeeds.
    db = SessionLocal()
    try:
        orders, is_replay = idempotency.claim(
            db, USER_ID, key, idempotency.ENDPOINT_ORDERS, payload
        )
        assert is_replay
        assert [o.id for o in orders] == [order_id]
    finally:
        db.close()


def test_claim_rolls_back_cleanly_on_conflict():
    """After a conflict the session must be usable, not left in a failed state.

    SQLAlchemy puts a session into a 'pending rollback' state after an
    IntegrityError. If claim() did not roll back, every subsequent query in
    that request would fail with a confusing error instead of the 409 the
    client should see.
    """
    key = str(uuid.uuid4())
    payload = {"restaurant_id": 1, "items": [{"menu_item_id": 1, "quantity": 1}]}

    db = SessionLocal()
    try:
        idempotency.claim(db, USER_ID, key, idempotency.ENDPOINT_ORDERS, payload)
        order_id = _create_order_in_session(db)
        idempotency.record_created(
            db, USER_ID, key, idempotency.ENDPOINT_ORDERS, [order_id]
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        orders, is_replay = idempotency.claim(
            db, USER_ID, key, idempotency.ENDPOINT_ORDERS, payload
        )
        assert is_replay
        # Session is healthy: an unrelated query works without extra rollback.
        assert db.query(User).filter(User.id == USER_ID).first() is not None
    finally:
        db.close()
