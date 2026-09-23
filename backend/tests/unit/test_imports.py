from datetime import date, datetime
from decimal import Decimal
import unittest

from app.modules.imports.normalization import identifier, month, number, timestamp
from app.modules.imports.adapters.common import detect_layout, normalize_row


class NormalizationTests(unittest.TestCase):
    def test_identifiers_preserve_symbols_and_leading_zeroes(self):
        self.assertEqual(identifier(" 030200874_ "), "030200874_")
        self.assertEqual(identifier("щт23054819"), "щт23054819")
        with self.assertRaises(ValueError):
            identifier(30200874)

    def test_unknown_zero_and_negative_are_distinct(self):
        self.assertIsNone(number(None))
        self.assertIsNone(number(" "))
        self.assertEqual(number(0), Decimal(0))
        self.assertEqual(number("-1\u00a0234,50"), Decimal("-1234.50"))
        for value in (True, "#DIV/0!", "nan", "inf"):
            with self.assertRaises(ValueError):
                number(value)

    def test_month_headers_exclude_totals(self):
        self.assertEqual(month("сент. 2026"), date(2026, 9, 1))
        self.assertEqual(month("Январь 2024 г."), date(2024, 1, 1))
        self.assertIsNone(month("Продажи 2024"))
        self.assertIsNone(month("Итого"))

    def test_dates_from_values_not_filename(self):
        self.assertEqual(timestamp("18.01.2023 16:00:11"), datetime(2023, 1, 18, 16, 0, 11))

    def test_summary_header_after_banner_and_numeric_errors(self):
        layout = detect_layout([(None, "СКЛАДЫ"), ("Код 1с", "Свободный остаток", "Январь 2024 г.")])
        code, fields, errors = normalize_row(("001_", "#VALUE!", -5), layout)
        self.assertEqual(layout.kind, "summary")
        self.assertEqual(layout.header_row, 2)
        self.assertEqual(code, "001_")
        self.assertEqual(fields["2024-01-01"], -5)
        self.assertEqual(len(errors), 1)

    def test_moq_and_multiple_are_separate_fields(self):
        for title in ("Мин. разр. к отгр.", "Кратность"):
            layout = detect_layout([("Код 1с", title)])
            _, fields, _ = normalize_row(("001", 10), layout)
            self.assertEqual(list(fields), ["код 1с", title.casefold()])

    def test_monthly_inventory_and_sales_recognition(self):
        self.assertEqual(detect_layout([("Номенклатура.Код", "Ед.", "янв. 2024")]).kind, "inventory_monthly")
        self.assertEqual(detect_layout([("Номенклатура.Код", "янв. 2024")]).kind, "sales_monthly")

    def test_array_formula_audit_serialization(self):
        from openpyxl.worksheet.formula import ArrayFormula
        from app.modules.imports.profiling import dumps
        import json
        self.assertEqual(json.loads(dumps(ArrayFormula("A1:A2", "=ROW(A1:A2)"))),
                         {"formula": "=ROW(A1:A2)", "ref": "A1:A2"})


if __name__ == "__main__":
    unittest.main()
