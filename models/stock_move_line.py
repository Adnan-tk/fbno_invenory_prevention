from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _fbno_check_negative_stock(self):
        """Reject a stock operation if its net effect makes stock negative.

        The check is done before Odoo updates stock.quant, so a UserError rolls
        back the complete workflow, including automated work in the same DB
        transaction. Internal and transit locations are checked; supplier,
        customer, inventory and production locations are not treated as stock
        locations for this rule.
        """
        relevant_lines = self.filtered(
            lambda line: line.product_id.is_storable
            and line.quantity_product_uom > 0
        )
        if not relevant_lines:
            return

        # Net quantity changes are expressed in the product's default UoM.
        # Aggregating the batch allows a valid internal transfer to subtract
        # from its source and add to its destination in the same operation.
        deltas = defaultdict(float)
        products = {}
        locations = {}
        references = defaultdict(set)

        stock_usages = ("internal", "transit")
        for line in relevant_lines:
            product = line.product_id
            quantity = line.quantity_product_uom
            reference = (
                line.picking_id.name
                or line.move_id.reference
                or line.move_id.origin
                or _("Stock Operation")
            )

            if line.location_id.usage in stock_usages:
                key = (product.id, line.location_id.id)
                deltas[key] -= quantity
                products[key] = product
                locations[key] = line.location_id
                references[key].add(reference)

            if line.location_dest_id.usage in stock_usages:
                key = (product.id, line.location_dest_id.id)
                deltas[key] += quantity
                products[key] = product
                locations[key] = line.location_dest_id
                references[key].add(reference)

        # Use transaction-scoped advisory locks to serialize validations for
        # the same product/location pair, including when no quant row exists yet.
        # Sorted key order reduces the risk of deadlocks for multi-location moves.
        keys = sorted(key for key, delta in deltas.items() if delta)
        for product_id, location_id in keys:
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                (
                    "fbno_invenory_prevention",
                    f"{product_id}:{location_id}",
                ),
            )

        product_ids = list({key[0] for key in keys})
        location_ids = list({key[1] for key in keys})
        current_quantities = defaultdict(float)
        if product_ids and location_ids:
            quants = self.env["stock.quant"].sudo().search([
                ("product_id", "in", product_ids),
                ("location_id", "in", location_ids),
            ])
            # Stock is checked at product/location level, regardless of lot,
            # package, or owner, matching the overall on-hand figure shown for
            # the product in that exact stock location.
            for quant in quants:
                current_quantities[(quant.product_id.id, quant.location_id.id)] += quant.quantity

        for key in keys:
            product = products[key]
            location = locations[key]
            current_qty = current_quantities[key]
            change_qty = deltas[key]
            projected_qty = current_qty + change_qty

            # Do not block receipts that are improving a legacy negative balance.
            # Block the operation only when this operation further decreases stock
            # and would leave the location negative.
            if change_qty < 0 and product.uom_id.compare(projected_qty, 0.0) < 0:
                uom_name = product.uom_id.name
                doc_reference = ", ".join(sorted(references[key]))
                raise UserError(_(
                    "Negative stock is not allowed. This operation cannot be "
                    "validated because it would reduce the stock below zero.\n\n"
                    "Product: %(product)s\n"
                    "Location: %(location)s\n"
                    "Current on-hand quantity: %(current)s %(uom)s\n"
                    "Quantity change in this operation: %(change)s %(uom)s\n"
                    "Projected on-hand quantity: %(projected)s %(uom)s\n"
                    "Document: %(document)s\n\n"
                    "Receive or transfer sufficient stock before validating this operation.",
                    product=product.display_name,
                    location=location.complete_name,
                    current=self._fbno_format_quantity(current_qty),
                    change=self._fbno_format_quantity(change_qty),
                    projected=self._fbno_format_quantity(projected_qty),
                    uom=uom_name,
                    document=doc_reference,
                ))

    @staticmethod
    def _fbno_format_quantity(quantity):
        """Format quantities cleanly for the validation error."""
        return f"{quantity:.4f}".rstrip("0").rstrip(".") or "0"

    def _action_done(self):
        # This is a server-side guard, not a UI-only Validate-button check.
        # It therefore also runs for automated workflows that call Odoo's
        # standard stock move completion methods.
        self._fbno_check_negative_stock()
        return super()._action_done()
