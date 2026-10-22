"""Hide rules (milestone 18, D221 to D223): mails the team leaves out of lists and searches.

    the UI (api/hiding.py)   a rule saved: its mails computed at once (model.store_rule), the
                             figures counted again (model.refresh_figures), one transaction
    the import (phase.py)    the step hidden: every rule computed again, one transaction each,
                             so new mails and merged persons are covered
    the lists (filters.py)   VISIBLE (model.visible): no enabled rule matches the mail, or the
                             team keeps it (D203), decided when the list is asked

model.py   matches(): a rule as SQL; store_rule, kept(), visible(), the figures in global_stats
phase.py   the import's step hidden (D221)
"""
