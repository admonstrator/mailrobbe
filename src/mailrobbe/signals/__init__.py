"""Signals (milestone 12, D130 to D139): simple conditions that point to mails worth reading.

    rules     model.SignalRules: MAILROBBE_INTERNAL_DOMAINS, MAILROBBE_PRIVATE_DOMAINS and
              MAILROBBE_TIMEZONE, the table [signals] of themes.toml and its research themes;
              the keys, groups and labels of the signals and the address classes (D131)
    phase     the import's phase signals after entities (phase): every rule applied to every
              mail in the database again (mail_signal, D132, D133), the senders' figures and
              the persons fallen silent (person_signal, D134), the figures and rules of the run
              (global_stats 'signals', model.SignalFigures); nothing is read from the MBOX files
    API       api/signals.py: the overview, the facets of the mail list, the signals of one
              mail and of one person; api/filters.py: the mail list's signal filter (D136)

Signals rate nothing: they say what holds (a private address, a Bcc, an hour of the night, a
word of a research theme), and reading the mails stays with the journalists.

Modules: model (the contract between phase, API and export), phase.
"""
