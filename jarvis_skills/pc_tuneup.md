# PC Tune-Up

A careful maintenance routine.

1. Run `diagnostics_operation(action="full")` and note every failed check.
2. Run `system_operation(action="info")`, `system_operation(action="processes", value="memory", limit=12)`.
3. Run `file_operation(action="disk")` and `file_operation(action="duplicates", path="Downloads")`.
4. Report the biggest space users and any process using abnormal memory.
5. Suggest, but do NOT perform, deletions. Only run `system_operation(action="clean_temp", confirmed=true)`
   if the user explicitly approves in this conversation.
6. Save a short Markdown report and speak the top three findings.
