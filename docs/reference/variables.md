---
title: Variables
icon: lucide/list
---

# Variables

Every variable a model, driver or coupling reads or writes, with the unit and frequency it is declared in, and the modules that produce and consume it.
catena connects a pipeline by name, so one name is one quantity: a test fails if two modules declare it in different units or at different frequencies.

A variable no module produces is read from a file.
One marked *internal* is produced and consumed within one model, an intermediate step of that model's own calculation.
A coarse variable that nothing produces at its own frequency, such as `temperature_weekly`, is made from the daily one by a `[[resample]]`; see [Node names](../models/index.md#node-names).

--8<-- "docs_tools/_generated/variables.md"
