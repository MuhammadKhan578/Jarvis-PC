# Weekly Review

Build a concise weekly review for the user.

Steps:
1. Call `mission_operation(action="list")` and `schedule_operation(action="list")`.
2. Call `memory_operation(action="recent", limit=10)`.
3. Call `file_operation(action="recent", days=7, limit=20)` to see what was worked on.
4. Write a Markdown report with: Wins, Things finished, Open loops, Blockers,
   Next week's top 3 priorities.
5. Save it as a Word document named `Weekly Review <date>` using
   `document_operation(action="create_word", ...)`.

Speak only a three-sentence summary. The document is the real deliverable.
