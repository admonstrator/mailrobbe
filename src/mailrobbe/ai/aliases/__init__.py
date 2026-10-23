"""The alias check (D321 to D323): the text model judges whether two persons are one.

    candidates  ai.aliases.candidates: the open uncertain alias suggestions and the pairs of a
                loose name key (surname and first initial) that no rule suggests, without the
                pairs checked or dismissed; the busiest first
    material    ai.aliases.material: what the model reads about a pair, from the database only:
                names, addresses, period and figures, frequent contacts, subjects and closing
                lines of the newest own mails, the contacts both share and the mails between them
    step        ai.aliases.step: the step aliases of an AI run started with --aliases (ai.run),
                one request per pair to a text service on this machine; the verdict in
                alias_check
    show        api/persons.py: the verdict beside each suggestion, and the pairs judged one
                person as a view of the suggestions; merging stays a click of the team (D2)

The check never merges, never changes a suggestion's tier and never sends anything to a service
outside this machine.
"""
