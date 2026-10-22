# FBNO Inventory Negative Stock Prevention

**Technical name:** `fbno_invenory_prevention`  
**Target:** Odoo 19 Enterprise (also compatible with Odoo 19 Community where the `stock` app is installed)  
**Dependency:** `stock`

## What it does

This standalone addon prevents stock-move completion from reducing the net on-hand quantity of a storable product below zero in an internal or transit location. It checks stock on the server, before Odoo applies the stock move, and raises a `UserError` with the product, location, current quantity, quantity change, projected quantity, and document reference.

Because the guard is implemented in `stock.move.line._action_done()`, it applies to the standard Odoo stock completion path, including:

- customer deliveries and other outgoing stock movements;
- vendor returns / inventory returns that move goods from an internal location to a vendor location;
- scrap and internal transfers;
- stock moves completed by automated actions or custom workflows that use Odoo's standard stock completion methods.

Incoming receipts are allowed when they increase stock. The check evaluates the net effect of all lines in the same completion batch, so a valid internal transfer can reduce the source location and increase the destination location together.

## Installation

1. Copy the `fbno_invenory_prevention` folder into a directory included in your Odoo `addons_path`.
2. Restart the Odoo 19 service.
3. Enable Developer Mode, open **Apps**, and click **Update Apps List**.
4. Search for **FBNO Inventory Negative Stock Prevention** (technical name: `fbno_invenory_prevention`) and install it.
5. Test in a staging database before installing on a live database.

No menu, configuration screen, or manual server action is required.

## Example

If `test product5` has `0.00 Units` in `OB/Stock` and a vendor return attempts to move `1.00 Unit` from `OB/Stock` to `Vendors`, the operation raises a `UserError` and the stock movement is not completed. If the vendor-return movement is part of the same database transaction as an automation, the error also rolls back the operations in that transaction.

## Important workflow boundary

This addon blocks the **stock movement** that would create negative inventory. In standard Odoo, posting an accounting vendor credit note and validating a stock return can be separate actions. If a credit note is posted independently and does not call stock-move completion in the same transaction, this addon does not block the accounting entry by itself. To stop credit-note posting as well, the custom billing workflow must explicitly link the credit note to the associated return picking and call a stock-availability check before posting; blocking every vendor credit note based only on stock quantity would incorrectly affect financial-only credit notes.

## Stock calculation

The guard calculates stock by **product and exact stock location**, summing the location's quants across lot, package, and owner dimensions. It considers `internal` and `transit` locations and storable products. It does not add per-product, category, or location exceptions.

## Suggested staging tests

1. Zero stock, outgoing quantity 1: validation must raise `UserError`.
2. Stock 1, outgoing quantity 1: validation must succeed and stock becomes 0.
3. Stock 1, outgoing quantity 2: validation must raise `UserError`.
4. Stock 0, receipt quantity 1: validation must succeed and stock becomes 1.
5. Stock 1, internal transfer quantity 1: source becomes 0 and destination increases by 1.
6. Trigger a vendor return through the real automation and confirm that the stock operation is blocked when the source quantity is insufficient.

The package was syntax-checked, but it has not been installed or integration-tested against your specific Odoo Enterprise database. Test the full vendor-bill / purchase-order / GRN / vendor-return automation on a staging copy before production use.
