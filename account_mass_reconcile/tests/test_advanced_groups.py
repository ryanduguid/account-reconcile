# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from datetime import date, timedelta
from itertools import permutations, product
from unittest.mock import patch

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
            self.assertAlmostEqual(
                sum(abs(line.amount_residual) for line in lines), abs(residual), 2
            )
            self.assertAlmostEqual(
                sum(abs(line.amount_residual_currency) for line in lines),
                abs(residual),
                2,
            )
            self.assertTrue(lines.matched_debit_ids | lines.matched_credit_ids)
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

    def test_bridge_merges_all_groups_before_chunking(self):
        reconciler = self.env["mass.reconcile.advanced.ref"].new(
            {"account_id": self.company_data["default_account_receivable"].id}
        )
        credit_lines = [
            {"id": index, "ref": reference, "partner_id": 1}
            for index, reference in enumerate(("A", "X", "B", "C", "Z", "?"), 1)
        ]
        credit_lines.append({"id": 7, "ref": "A", "partner_id": False})
        debit_lines = [
            {"id": 10, "ref": "A", "name": "Z", "partner_id": 1},
            {"id": 11, "ref": "X", "name": "X", "partner_id": 1},
            {"id": 12, "ref": "B", "name": "Z", "partner_id": 1},
            {"id": 13, "ref": "C", "name": "Z", "partner_id": 1},
            {"id": 14, "ref": "A", "name": "Z", "partner_id": 2},
        ]
        expected = [{1, 3, 4, 5, 10, 12, 13}, {2, 11}]
        for chunk_size in (0, 1, 2):
            with self.subTest(chunk_size=chunk_size):
                self.company_data["company"].reconciliation_commit_every = chunk_size
                with (
                    patch.object(
                        type(reconciler), "_rec_group", return_value=[]
                    ) as run,
                    patch.object(
                        type(reconciler), "_rec_group_by_chunk", return_value=[]
                    ) as run_chunks,
                ):
                    reconciler._rec_auto_lines_advanced(credit_lines, debit_lines)
                active = run_chunks if chunk_size else run
                inactive = run if chunk_size else run_chunks
                active.assert_called_once()
                inactive.assert_not_called()
                groups, lines_by_id, *chunk_args = active.call_args.args
                self.assertEqual(groups, expected)
                self.assertEqual(chunk_args, [chunk_size] if chunk_size else [])
                self.assertEqual(
                    set(lines_by_id),
                    {line["id"] for line in credit_lines + debit_lines},
                )

    def test_profile_history_reports_only_full_reconciliations(self):
        for residual in (0.0, 0.11, -0.11):
            with self.subTest(residual=residual):
                reconciler, lines = self._make_case(residual=residual)
                profile = self.env["account.mass.reconcile"].create(
                    {
                        "name": "Connected group fixture",
                        "account_id": reconciler.account_id.id,
                        "company_id": reconciler.company_id.id,
                    }
                )
                self.env["account.mass.reconcile.method"].create(
                    {
                        "task_id": profile.id,
                        "name": "mass.reconcile.advanced.ref",
                        "write_off": reconciler.write_off,
                        "account_lost_id": reconciler.account_lost_id.id,
                        "account_profit_id": reconciler.account_profit_id.id,
                        "journal_id": reconciler.journal_id.id,
                        "date_base_on": reconciler.date_base_on,
                        "_filter": str([("id", "in", lines.ids)]),
                    }
                )
                with self.assertNoLogs(
                    "odoo.addons.account_mass_reconcile.models.mass_reconcile",
                    level="ERROR",
                ):
                    profile.run_reconcile()
                self.assertEqual(len(profile.history_ids), 1)
                self.assertEqual(
                    set(profile.history_ids.reconcile_line_ids.ids),
                    set() if residual else set(lines.ids),
                )
                self.assertFalse(self._writeoffs(lines))
                self.assertAlmostEqual(
                    sum(lines.mapped("amount_residual")), residual, 2
                )
                self.assertAlmostEqual(
                    sum(abs(line.amount_residual) for line in lines), abs(residual), 2
                )
                self.assertAlmostEqual(
                    sum(abs(line.amount_residual_currency) for line in lines),
                    abs(residual),
                    2,
                )
                self.assertTrue(lines.matched_debit_ids | lines.matched_credit_ids)
