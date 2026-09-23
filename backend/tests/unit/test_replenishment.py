from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
import unittest

from app.engine.contracts import Inbound, ReplenishmentInput
from app.engine.replenishment import calculate


class ReplenishmentTests(unittest.TestCase):
    def setUp(self):
        self.inputs = ReplenishmentInput(date(2026, 9, 23), 2, 3, (D(10),) * 5,
                                        D(15), D(5), (), D(1), D(0), D(1))

    def test_arithmetic(self):
        result = calculate(self.inputs)
        self.assertEqual(result.raw_requirement, D(40))
        self.assertEqual(result.order_quantity, D(40))
        self.assertEqual(result.first_deficit_date, date(2026, 9, 24))
        self.assertEqual(result.urgency, "expedite")

    def test_late_receipt_does_not_remove_early_shortage(self):
        result = calculate(replace(self.inputs, inbound=(Inbound(date(2026, 9, 27), D(100)),)))
        self.assertEqual(result.order_quantity, 0)
        self.assertEqual(result.first_deficit_date, date(2026, 9, 24))
        self.assertEqual(result.urgency, "expedite")

    def test_horizon_boundary_unconfirmed_and_overdue_receipts(self):
        inbound = (Inbound(date(2026, 9, 28), D(100)), Inbound(date(2026, 9, 22), D(100)),
                   Inbound(date(2026, 9, 24), D(100), False))
        result = calculate(replace(self.inputs, inbound=inbound))
        self.assertEqual(result.eligible_inbound, 0)
        self.assertEqual(result.order_quantity, 40)
        self.assertTrue(result.limitations)

    def test_zero_requirement_does_not_trigger_moq(self):
        result = calculate(replace(self.inputs, available_stock=D(100), minimum_order=D(200)))
        self.assertEqual(result.order_quantity, 0)

    def test_conversion_moq_and_multiple(self):
        result = calculate(replace(self.inputs, storage_units_per_order_unit=D(3),
                                   minimum_order=D(15), order_multiple=D(4)))
        self.assertEqual(result.order_quantity, 16)

    def test_unknown_stock_is_not_zero(self):
        result = calculate(replace(self.inputs, available_stock=None))
        self.assertEqual(result.status, "insufficient_data")
        self.assertIsNone(result.order_quantity)

    def test_unknown_conversion_blocks_positive_order(self):
        result = calculate(replace(self.inputs, storage_units_per_order_unit=None))
        self.assertIsNone(result.order_quantity)
        self.assertEqual(result.raw_requirement, 40)

    def test_negative_free_stock_is_preserved(self):
        result = calculate(replace(self.inputs, available_stock=D(-5)))
        self.assertEqual(result.order_quantity, 60)
        self.assertEqual(result.first_deficit_date, self.inputs.calculation_date)

    def test_invalid_forecast_or_policy_rejected(self):
        for patch in ({"daily_forecast": (D(10),)}, {"safety_stock": D("NaN")},
                      {"order_multiple": D(0)}, {"lead_days": -1}):
            with self.assertRaises(ValueError):
                calculate(replace(self.inputs, **patch))

    def test_receipt_at_start_is_available_before_demand(self):
        result = calculate(replace(self.inputs, inbound=(Inbound(self.inputs.calculation_date, D(100)),)))
        self.assertIsNone(result.first_deficit_date)
        self.assertEqual(result.order_quantity, 0)


if __name__ == "__main__":
    unittest.main()
