1. if a deal is mapped to multiple locations, we should create a separate
normalized deal for each location
2. to determine if a deal is active, the llm when parsing the deal can determine
the start/end date, leaving it as null if it isn't specified. for the mvp,
just assume if end date is not specified, the deal is always active
past the start date
3. number pins should be ephemeral, based on the current viewport.

