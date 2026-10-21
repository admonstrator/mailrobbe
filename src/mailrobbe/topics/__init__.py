"""Topic discovery (milestone 13, D140 to D148): words that stand out per period, per selection
and as clusters of words that stand together.

    terms      a term is a lexeme of mail.tsv (the German stem PostgreSQL indexes) in the subject
               and text of mails that are no duplicates; the vocabulary (topic_term) keeps the
               usable ones (model.usable_lexeme, D141) with their most used spelling as label
    keyness    keyness.keyness: whether a term stands out in a scope against the rest of the
               archive, with its figures (D142); pure
    phase      the import's last phase (phase.compute_topics, D146): when the archive changed
               (phase.waiting), counts every term per month in one pass over mail.tsv, reads the
               spellings, ranks the terms of every month, quarter and year, groups the clusters
               (clusters.find_clusters), all in temporary tables, and replaces the stored results
               (topic_term, topic_period, topic_period_term, topic_cluster, topic_cluster_term,
               topic_cluster_month, topic_state) in one transaction at the end
    API        api/topics.py: the periods and clusters as stored, and the terms of any selection
               of the mail list counted on request against the stored vocabulary (D144)

Modules: model (constants, periods, the vocabulary and clusters handed between the modules),
keyness, phase, clusters.
"""
