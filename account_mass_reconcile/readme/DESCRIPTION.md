This is a shared work between Akretion and Camptocamp in order to
provide:

- Reconciliation facilities for big volume of transactions.
- Setup different profiles of reconciliation by account.
- Each profile can use many methods of reconciliation.
- This module is also a base to create others reconciliation methods
  which can plug in the profiles.
- A profile a reconciliation can be run manually or by a cron.
- Monitoring of reconciliation runs with an history which keep track of
  the reconciled Journal items.

Three simple reconciliation methods match by partner, journal item name or
reference. Each reconciles two lines, one debit and one credit, without partial
reconciliation. Choose the most recent or oldest move line when more than one
matches.
