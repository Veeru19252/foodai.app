"""
FoodAI - Order Simulator (Person B)

Generates 500+ realistic food-delivery orders and saves them to
data/orders.csv. This file becomes the training data for your two ML models:
- ETA prediction (target column: delivery_min)
- Demand forecasting (group orders by zone + hour, then predict counts)

Run from the foodai/ directory:
    python scripts/simulate_orders.py

Output columns:
    order_id        : unique id
    restaurant_id   : which restaurant (1-5)
    customer_zone   : where the food is going (A-E)
    distance_km     : how far the order travels
    hour            : hour of day the order was placed (0-23)
    day_of_week     : 0 = Monday ... 6 = Sunday
    is_weekend      : 1 if Saturday/Sunday, else 0
    prep_time_min   : how long the kitchen takes
    traffic_factor  : rush-hour multiplier (>1 = busy, <1 = quiet)
    delivery_min    : total time from order to delivery (your ETA target)

We use random.seed(42) so the data is reproducible (same output every run).
"""
import csv
import math
import random
from pathlib import Path

# --- Settings ----------------------------------------------------------
NUM_DAYS = 10          # 10 days of orders
TARGET_ORDERS = 600    # aim for 600+ rows
SEED = 42
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "orders.csv"

# Zone centers on a fake city grid (x, y in km). Distance between zones
# is computed with the Pythagorean formula.
ZONES = {
    "A": (0.0, 0.0),
    "B": (4.0, 1.0),
    "C": (7.0, 4.0),
    "D": (2.0, 6.0),
    "E": (8.0, 0.0),
}

# Restaurant zone + average prep time (min).
RESTAURANTS = {
    1: {"zone": "A", "prep_min": 8},
    2: {"zone": "B", "prep_min": 10},
    3: {"zone": "C", "prep_min": 7},
    4: {"zone": "D", "prep_min": 12},
    5: {"zone": "E", "prep_min": 9},
}

# Restaurants are busier at lunch (11-14) and dinner (18-22).
def _hour_weight(hour: int) -> float:
    if 11 <= hour <= 14:
        return 1.8
    if 18 <= hour <= 22:
        return 1.6
    if 8 <= hour <= 10:
        return 1.2
    return 0.6


def _distance_km(zone1: str, zone2: str) -> float:
    """Straight-line distance between two zones (km)."""
    x1, y1 = ZONES[zone1]
    x2, y2 = ZONES[zone2]
    return round(math.hypot(x2 - x1, y2 - y1), 2)


def _traffic_factor(hour: int, is_weekend: int) -> float:
    """Rush hours make deliveries slower (multiplier > 1)."""
    base = 1.0
    if 8 <= hour <= 9 or 17 <= hour <= 19:
        base += 0.25
    if is_weekend and 12 <= hour <= 21:
        base += 0.15
    return round(random.uniform(0.85, base + 0.1), 2)


def generate_order(order_id: int, day: int) -> dict:
    """Build one order using realistic randomness."""
    restaurant_id = random.choice(list(RESTAURANTS.keys()))
    restaurant = RESTAURANTS[restaurant_id]

    hour = random.choices(
        range(24), weights=[_hour_weight(h) for h in range(24)], k=1
    )[0]
    day_of_week = day % 7
    is_weekend = 1 if day_of_week in (5, 6) else 0

    customer_zone = random.choice(list(ZONES.keys()))
    distance_km = _distance_km(restaurant["zone"], customer_zone)

    prep_time_min = restaurant["prep_min"] + random.randint(-2, 4)
    traffic = _traffic_factor(hour, is_weekend)

    # Base: 5 min to pick up, ~4 min per km, kitchen time, traffic multiplies
    # the driving part only.
    delivery_min = round(
        5 + (distance_km * 4) * traffic + prep_time_min + random.uniform(-2, 5),
        1,
    )

    return {
        "order_id": order_id,
        "restaurant_id": restaurant_id,
        "customer_zone": customer_zone,
        "distance_km": distance_km,
        "hour": hour,
        "day_of_week": day_of_week,
        "is_weekend": is_weekend,
        "prep_time_min": max(3, prep_time_min),
        "traffic_factor": traffic,
        "delivery_min": max(8, delivery_min),
    }


def main() -> None:
    random.seed(SEED)

    orders_per_day = math.ceil(TARGET_ORDERS / NUM_DAYS)
    rows = []
    order_id = 1
    for day in range(NUM_DAYS):
        for _ in range(orders_per_day):
            rows.append(generate_order(order_id, day))
            order_id += 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # --- Summary -------------------------------------------------------
    avg_delivery = sum(r["delivery_min"] for r in rows) / len(rows)
    avg_distance = sum(r["distance_km"] for r in rows) / len(rows)
    weekend_share = sum(r["is_weekend"] for r in rows) / len(rows)

    print(f"✅ Wrote {len(rows)} orders to {OUTPUT}")
    print(f"   Average delivery time : {avg_delivery:.1f} min")
    print(f"   Average distance      : {avg_distance:.1f} km")
    print(f"   Weekend order share   : {weekend_share * 100:.0f}%")
    print("   Orders per zone       :", end=" ")
    from collections import Counter
    print(dict(Counter(r["customer_zone"] for r in rows)))

    print("\n💡 Next step (Week 4): load this in your notebook:")
    print('   orders = pd.read_csv("../data/orders.csv")')


if __name__ == "__main__":
    main()
