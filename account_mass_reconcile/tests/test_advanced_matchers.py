# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAdvancedMatchers(TransactionCase):
    def test_concrete_comparator_override(self):
        reconciler = self.env["mass.reconcile.advanced.ref"]
        default_compare = reconciler._compare_values

        def compare_prefix(key, value, opposite_value):
            if key == "ref":
                return bool(
                    value and opposite_value and opposite_value.startswith(value)
                )
            return default_compare(key, value, opposite_value)

        with patch.object(
            type(reconciler), "_compare_values", staticmethod(compare_prefix)
        ):
            self.assertTrue(
                reconciler._compare_matchers(("ref", "invoice"), ("ref", "invoice-1"))
            )
            self.assertTrue(
                reconciler._compare_matchers(
                    ("ref", ("credit", "invoice")), ("ref", ("none", "invoice-1"))
                )
            )
            candidates = [
                {"id": 1, "partner_id": 1, "ref": "INVOICE-1", "name": ""},
                {"id": 2, "partner_id": 2, "ref": "invoice-2", "name": ""},
                {"id": 3, "partner_id": 1, "ref": "none", "name": "invoice-3"},
                {"id": 4, "partner_id": 1, "ref": "none", "name": ""},
            ]
            self.assertEqual(
                reconciler._search_opposites(
                    {"partner_id": 1, "ref": " Invoice "}, candidates
                ),
                [candidates[0], candidates[2]],
            )

    def test_default_equality_and_empty_values(self):
        reconciler = self.env["mass.reconcile.advanced.ref"]
        for value, opposite, expected in (
            ("same", "same", True),
            ("invoice", "invoice-1", False),
            ("", "", False),
            (False, False, False),
            (None, None, False),
            (("", "same"), (False, "same"), True),
            (("", None), ("", False), False),
        ):
            with self.subTest(value=value, opposite=opposite):
                self.assertEqual(
                    reconciler._compare_matchers(("ref", value), ("ref", opposite)),
                    expected,
                )
