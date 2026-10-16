#!/bin/sh
set -eu
nohup python3 -c '
import csv
import os
import time
from pathlib import Path

header = ["order_id", "customer", "sku", "quantity", "unit_price_cents"]
started = time.monotonic()
for index in range(35):
    time.sleep(max(0, started + index * 20 - time.monotonic()))
    orders = {}
    for path in sorted(Path("/work/inbox").glob("*.csv")):
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                orders[row["order_id"]] = row
    temporary = Path("/work/output/.orders.csv.tmp")
    with temporary.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(orders.values())
    os.replace(temporary, "/work/output/orders.csv")
' </dev/null >/tmp/order-processor.log 2>&1 &
