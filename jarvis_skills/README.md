# J.A.R.V.I.S. Skills

A skill is a small extension Jarvis can list and run. Put files in this folder
(`jarvis_skills/`). Jarvis loads them automatically and shows them in its prompt.

## Markdown skill (easiest)

Create `something.md`:

```markdown
# Weekly Review

Collect this week's missions, scheduled jobs and memory episodes, then write a
short weekly review with wins, blockers and next actions. Save it as a Word
document on the Desktop.
```

The first line is the title. The body is the instruction Jarvis follows when the
skill runs. Markdown skills can use every Jarvis tool.

## Python skill (powerful)

Create `something.py`:

```python
NAME = "Disk Report"
DESCRIPTION = "Shows the five biggest folders on a drive."

def run(jarvis, args=""):
    # jarvis is the jarvis.py module globals dict
    from jarvis_core import computer
    return computer.file_operation("disk")
```

`run` may accept zero, one or two arguments:

- `run()` — no arguments
- `run(args)` — the text after the skill name
- `run(jarvis, args)` — full access to the running Jarvis module

Return a string. Jarvis speaks or displays it. Keep it short; long output belongs
in a report.

## Using a skill

Say or type:

- “list skills”
- “run Weekly Review”
- “run Disk Report on D drive”

Jarvis calls `skill_operation(action='run', name='...', args='...')`.

## Safety

Skills run inside your Jarvis process with your permissions. Only install skills
you wrote or trust.
