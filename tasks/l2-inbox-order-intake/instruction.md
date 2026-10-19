During the 10 minutes after you finish your reply, CSV order files will arrive in
`/work/inbox`. Their header is:

```csv
order_id,customer,sku,quantity,unit_price_cents
```

Keep `/work/output/orders.csv` with this same header and every received order
exactly once, preserving all its fields. Each order must be present within
3 minutes of its file's arrival. The same order may appear identically in several
files; `order_id` identifies an order. Do not include orders before they arrive.
Do not modify, move or delete any inbox file.

You will not be present after you finish your reply. Order processing must
continue for the full 10 minutes without further input from you.
