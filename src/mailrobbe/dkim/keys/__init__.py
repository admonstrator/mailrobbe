"""Keys of deleted selectors (D100 to D104, docs/DKIM-RECOVERY.md).

A signature whose selector is gone from DNS is no_key. Keys from other sources make it
verifiable again; each carries its origin, and a key counts for a signature only when it
verifies the signature's header hash:

- identity.py: a key's identity across sources (SHA-256 of the public key), records made for
  reconstructed keys
- store.py: dkim_key, dkim_key_lookup and dkim_key_evidence, the one place that writes them, and
  the candidate keys by name for the checker
- model.py: the tasks of `mailrobbe dkim-keys` and their job options and figures
- reconstruct.py: the RSA modulus from signatures of one key (GCD with gmpy2), Batch-GCD
- archive.py: key records quoted in the archive's own mails and attachment texts
- zkemail.py: the ZK Email DKIM archive, one request per domain, only on request
- run.py, cli.py: `mailrobbe dkim-keys`, one run per task, ending with a check of the mails
  concerned
"""
