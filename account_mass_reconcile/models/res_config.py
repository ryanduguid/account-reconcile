# Copyright 2014-2016 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    reconciliation_commit_every = fields.Integer(
        related="company_id.reconciliation_commit_every",
        string="How often to commit when performing automatic reconciliation.",
        help="Leave zero to commit only at the end of the process.",
        readonly=False,
    )


class Company(models.Model):
    _inherit = "res.company"

    reconciliation_commit_every = fields.Integer(
        string="How often to commit when performing automatic reconciliation.",
        help="Leave zero to commit only at the end of the process.",
    )

    @api.constrains("reconciliation_commit_every")
    def _check_reconciliation_commit_every(self):
        if any(company.reconciliation_commit_every < 0 for company in self):
            raise ValidationError(
                _("The reconciliation commit interval must be zero or greater.")
            )
