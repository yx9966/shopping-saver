#!/usr/bin/env python3
"""Compare evidenced candidate orders. All amounts are integer CNY cents."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict), "Expected an object")
    require(set(required) <= value.keys(), f"Missing fields: {set(required) - value.keys()}")
    require(value.keys() <= set(required) | set(optional), f"Unknown fields: {value.keys() - set(required) - set(optional)}")


def integer(value, minimum=0):
    require(type(value) is int and value >= minimum, f"Expected integer >= {minimum}: {value!r}")
    return value


def label(value):
    require(isinstance(value, str) and bool(value.strip()), "Expected nonempty text")
    return value


def instant(value):
    parsed = datetime.fromisoformat(label(value).replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "Timestamps must include a timezone")
    return parsed


def identifiers(values):
    require(isinstance(values, list), "Expected an ID list")
    for value in values:
        label(value)
    require(len(values) == len(set(values)), "Duplicate IDs")
    return set(values)


def allocate(amount, keys, remaining):
    """Largest-remainder allocation keeps scoped discounts exact to the cent."""
    total = sum(remaining[key] for key in keys)
    if not amount:
        return
    shares = {key: amount * remaining[key] // total for key in keys}
    ranked = sorted(keys, key=lambda key: (-(amount * remaining[key] % total), key))
    for key in ranked[:amount - sum(shares.values())]:
        shares[key] += 1
    for key, share in shares.items():
        remaining[key] -= share


def discount(rule, original, remaining):
    fields(rule, ("id", "items", "basis", "threshold_cents", "off_cents", "repeat"))
    label(rule["id"])
    keys = identifiers(rule["items"])
    require(keys and keys <= original.keys(), "Discount items must name existing lines")
    require(rule["basis"] in ("original", "remaining"), "Unknown threshold basis")
    require(type(rule["repeat"]) is bool, "repeat must be boolean")
    threshold = integer(rule["threshold_cents"], 1 if rule["repeat"] else 0)
    off = integer(rule["off_cents"], 1)
    basis = original if rule["basis"] == "original" else remaining
    eligible = sum(basis[key] for key in keys)
    require(eligible >= threshold, f"Discount {rule['id']} threshold not met")
    amount = off * (eligible // threshold if rule["repeat"] else 1)
    amount = min(amount, sum(remaining[key] for key in keys))
    allocate(amount, keys, remaining)
    return {"id": rule["id"], "discount_cents": amount}


def price_order(order, needs, now):
    fields(order, ("id", "platform", "lines", "discounts", "shipping_cents", "resources", "evidence", "valid_until"),
           ("valid_from", "checkout_total_cents", "other_fees_cents"))
    label(order["id"])
    label(order["platform"])
    resources = identifiers(order["resources"])
    require(isinstance(order["lines"], list) and order["lines"], "Order needs lines")
    original, coverage, filler = {}, {}, 0
    for line in order["lines"]:
        fields(line, ("item", "quantity", "unit_cents", "url"))
        item = label(line["item"])
        label(line["url"])
        require(item not in original, "Duplicate item within order")
        qty = integer(line["quantity"], 1)
        original[item] = qty * integer(line["unit_cents"])
        if item in needs:
            require(qty <= needs[item], "Order exceeds requested quantity")
            coverage[item] = qty
        else:
            filler += original[item]
    require(coverage, "An order must include a requested item")
    evidence = order["evidence"]
    fields(evidence, ("source", "observed_at"))
    label(evidence["source"])
    observed = instant(evidence["observed_at"])
    require(observed <= now, "Evidence is in the future")
    begin = instant(order.get("valid_from", evidence["observed_at"]))
    end = instant(order["valid_until"])
    require(begin < end, "Invalid validity window")
    remaining = original.copy()
    require(isinstance(order["discounts"], list), "discounts must be a list")
    identifiers([rule["id"] for rule in order["discounts"]])
    applied = [discount(rule, original, remaining) for rule in order["discounts"]]
    shipping = integer(order["shipping_cents"])
    other_fees = integer(order.get("other_fees_cents", 0))
    total = sum(remaining.values()) + shipping + other_fees
    verified = "checkout_total_cents" in order
    if verified:
        require(integer(order["checkout_total_cents"]) == total, "Checkout total does not match calculated total")
    return {
        "id": order["id"], "platform": order["platform"], "coverage": coverage,
        "lines": order["lines"], "subtotal_cents": sum(original.values()),
        "discounts": applied, "shipping_cents": shipping, "total_cents": total,
        "other_fees_cents": other_fees,
        "filler_cents": filler, "resources": sorted(resources),
        "verification": "checkout_observed" if verified else "estimated",
        "evidence": evidence, "valid_until": order["valid_until"],
        "active": begin <= now < end,
    }


def plan(orders):
    return {
        "orders": sorted(orders, key=lambda order: order["id"]),
        "total_cents": sum(order["total_cents"] for order in orders),
        "order_count": len(orders),
        "filler_cents": sum(order["filler_cents"] for order in orders),
        "verification": "checkout_observed" if all(order["verification"] == "checkout_observed" for order in orders) else "estimated",
    }


def has_filler(order):
    return any(line["item"] not in order["coverage"] for line in order["lines"])


def search(needs, orders, max_filler):
    best = {"lowest_total": None, "lowest_verified": None, "fewest_orders": None, "without_filler": None}
    seen = set()

    def visit(remaining, chosen, used, filler):
        key = frozenset(order["id"] for order in chosen)
        if key in seen:
            return
        seen.add(key)
        require(len(seen) <= 100000, "Search exceeds 100000 combinations; reduce candidate orders")
        if not any(remaining.values()):
            result = plan(chosen)
            for name in best:
                if name == "lowest_verified" and result["verification"] != "checkout_observed":
                    continue
                if name == "without_filler" and any(has_filler(order) for order in chosen):
                    continue
                def rank(value):
                    cost, count = value["total_cents"], value["order_count"]
                    return (count, cost) if name == "fewest_orders" else (cost, count)
                if best[name] is None or rank(result) < rank(best[name]):
                    best[name] = result
            return
        item = next(item for item, qty in remaining.items() if qty)
        for order in orders:
            if item not in order["coverage"] or order["id"] in key:
                continue
            if max_filler == 0 and has_filler(order):
                continue
            if used.intersection(order["resources"]) or filler + order["filler_cents"] > max_filler:
                continue
            if any(qty > remaining[item] for item, qty in order["coverage"].items()):
                continue
            rest = remaining.copy()
            for item_id, qty in order["coverage"].items():
                rest[item_id] -= qty
            visit(rest, chosen + [order], used.union(order["resources"]), filler + order["filler_cents"])

    visit(needs, [], set(), 0)
    return best


def compare(data, now=None):
    fields(data, ("needs", "orders", "max_filler_cents"))
    now = instant(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
    require(isinstance(data["needs"], dict) and 1 <= len(data["needs"]) <= 5, "Supply 1–5 requested items")
    needs = {label(item): integer(qty, 1) for item, qty in data["needs"].items()}
    require(sum(needs.values()) <= 20, "Maximum 20 requested units")
    require(isinstance(data["orders"], list) and len(data["orders"]) <= 40, "Maximum 40 candidate orders")
    identifiers([order["id"] for order in data["orders"]])
    orders = [price_order(order, needs, now) for order in data["orders"]]
    active = [order for order in orders if order["active"]]
    plans = search(needs, active, integer(data["max_filler_cents"]))
    cheapest, baseline = plans["lowest_total"], plans["without_filler"]
    return {
        "status": "ok" if cheapest else "no_complete_plan", "currency": "CNY",
        "evaluated_at": now.isoformat(), "scope": "supplied_candidate_orders_only",
        "plans": plans,
        "saving_vs_without_filler_cents": baseline["total_cents"] - cheapest["total_cents"] if baseline and cheapest else None,
        "inactive_orders": [order["id"] for order in orders if not order["active"]],
        "uncovered_items": [item for item in needs if not any(item in order["coverage"] for order in active)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--at", help="Replay at a timezone-aware ISO timestamp; default: now")
    args = parser.parse_args()
    try:
        result = compare(json.loads(args.input.read_text(encoding="utf-8")), args.at)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0 if result["status"] == "ok" else 1
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
