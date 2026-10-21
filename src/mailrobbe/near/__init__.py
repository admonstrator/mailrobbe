"""Near duplicates (milestone 14, D152, D153): mails with the same subject and text.

    mail.subject, mail.body_text
          |  model.fingerprint (quotes.split_text: a mail that only forwards or quotes takes
          v  the fingerprint of what it forwards)
    mail_near.fingerprint      phase, step near_texts: mails without one or of an older
          |                    NEAR_VERSION, from the database alone
          v
    mail_near.group_id         phase, step near_groups: the smallest id of the mails that are
                               no duplicates and share a fingerprint; duplicates take the group
                               of their original; figures in global_stats 'near'

- model.py: the fingerprint rule (MIN_WORDS, fingerprint_text, fingerprint) and NearFigures
- phase.py: the import's near phase (waiting, fingerprint_mails, group_mails)

api/near.py shows the groups in the mail list and the detail; api/filters.py filters them
(collapse_near, near_group).
"""
