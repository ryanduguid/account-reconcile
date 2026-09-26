# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import date, timedelta
from itertools import permutations, product

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAdvancedGroups(AccountTestInvoicingCommon):
    def _make_case(self, residual=0.0, reverse_maturity=False):
        company = self.company_data["company"]
        company.reconciliation_commit_every = 0
        account = self.company_data["default_account_receivable"]
        offset = self.company_data["default_account_revenue"]
        journal = self.company_data["default_journal_misc"]
        partner = self.env["res.partner"].create(
            {"name": "Reconciliation group fixture"}
        )
        date_at = date(2026, 1, 1)
        entries = [
            ("A", "Credit A", -40.0, 0),
            ("B", "Credit B", -99.95 + residual, 0),
            ("C", "Credit C", -60.05, 0),
            ("A", "C", 100.0, 2 if reverse_maturity else 1),
            ("B", "C", 100.0, 1 if reverse_maturity else 2),
        ]
        lines = self.env["account.move.line"]
        for reference, name, balance, maturity_days in entries:
            move = self.env["account.move"].create(
                {
                    "journal_id": journal.id,
                    "date": date_at,
                    "ref": reference,
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "name": name,
                                "account_id": account.id,
                                "partner_id": partner.id,
                                "date_maturity": date_at
                                + timedelta(days=maturity_days),
                                "debit": max(balance, 0),
                                "credit": max(-balance, 0),
                                "currency_id": company.currency_id.id,
                                "amount_currency": balance,
                            },
                        ),
                        (
                            0,
                            0,
                            {
                                "name": "Fixture counterpart",
                                "account_id": offset.id,
                                "debit": max(-balance, 0),
                                "credit": max(balance, 0),
                            },
                        ),
                    ],
                }
            )
            move.action_post()
            lines |= move.line_ids.filtered(lambda line: line.account_id == account)
        reconciler = self.env["mass.reconcile.advanced.ref"].create(
            {
                "account_id": account.id,
                "partner_ids": [(6, 0, partner.ids)],
                "company_id": company.id,
                "write_off": 0.10,
                "account_lost_id": self.company_data["default_account_expense"].id,
                "account_profit_id": offset.id,
                "journal_id": journal.id,
                "date_base_on": "newest",
            }
        )
        return reconciler, lines

    def _writeoffs(self, lines):
        return self.env["account.move"].search(
            [
                ("line_ids.partner_id", "in", lines.partner_id.ids),
                ("id", "not in", lines.move_id.ids),
            ]
        )

    def _check_case(self, credit_order, reverse_debits, residual=0.0, **kwargs):
        reconciler, lines = self._make_case(residual=residual, **kwargs)
        self.env.flush_all()
        credits_by_ref = {line["ref"]: line for line in reconciler._query_credit()}
        debits = sorted(reconciler._query_debit(), key=lambda line: line["id"])
        if reverse_debits:
            debits.reverse()
        result = reconciler._rec_auto_lines_advanced(
            [credits_by_ref[reference] for reference in credit_order], debits
        )
        writeoffs = self._writeoffs(lines)
        if abs(residual) > reconciler.write_off:
            self.assertFalse(result)
            self.assertFalse(writeoffs)
            self.assertAlmostEqual(sum(lines.mapped("amount_residual")), residual, 2)
            self.assertAlmostEqual(
                sum(lines.mapped("amount_residual_currency")), residual, 2
            )
            return

        self.assertEqual(set(result), set(lines.ids))
        self.assertEqual(len(result), len(lines))
        self.assertTrue(all(line.full_reconcile_id for line in lines))
        self.assertEqual(len(writeoffs), int(bool(residual)))
        for line in lines:
            self.assertTrue(line.reconciled)
            self.assertAlmostEqual(line.amount_residual, 0, 2)
            self.assertAlmostEqual(line.amount_residual_currency, 0, 2)
        if writeoffs:
            self.assertEqual(writeoffs.state, "posted")
            self.assertEqual(writeoffs.date, date(2026, 1, 1))
            self.assertEqual(writeoffs.journal_id, reconciler.journal_id)
            self.assertAlmostEqual(sum(writeoffs.line_ids.mapped("balance")), 0, 2)
            expected_account = (
                reconciler.account_lost_id
                if residual > 0
                else reconciler.account_profit_id
            )
            adjustment = writeoffs.line_ids.filtered(
                lambda line: line.account_id == expected_account
            )
            counterpart = writeoffs.line_ids - adjustment
            self.assertEqual(len(adjustment), 1)
            self.assertEqual(len(counterpart), 1)
            self.assertAlmostEqual(adjustment.balance, residual, 2)
            self.assertAlmostEqual(counterpart.balance, -residual, 2)
            self.assertEqual(counterpart.account_id, reconciler.account_id)
            self.assertEqual(counterpart.currency_id, reconciler.company_id.currency_id)
            self.assertTrue(counterpart.reconciled)
        self.assertFalse(reconciler.automatic_reconcile())
        self.assertEqual(self._writeoffs(lines), writeoffs)

    def test_balanced_bridge_has_no_writeoff(self):
        for order, reverse_debits, reverse_maturity in product(
            permutations("ABC"), (False, True), (False, True)
        ):
            with self.subTest(
                order=order, reverse_debits=reverse_debits, maturity=reverse_maturity
            ):
                self._check_case(
                    order, reverse_debits, reverse_maturity=reverse_maturity
                )

    def test_component_writeoff_is_applied_once(self):
        for order, reverse_debits, residual in product(
            permutations("ABC"), (False, True), (0.05, -0.05)
        ):
            with self.subTest(
                order=order, reverse_debits=reverse_debits, residual=residual
            ):
                self._check_case(order, reverse_debits, residual=residual)

    def test_above_limit_component_stays_partial(self):
        for order, reverse_debits, residual in product(
            permutations("ABC"), (False, True), (0.11, -0.11)
        ):
            with self.subTest(
                order=order, reverse_debits=reverse_debits, residual=residual
            ):
                self._check_case(order, reverse_debits, residual=residual)
