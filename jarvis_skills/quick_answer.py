"""Example Python skill: quick research answer saved to a report."""

NAME = "Quick Answer"
DESCRIPTION = "Research one question on the web, cite sources and open a short report."


def run(jarvis, args=""):
    from jarvis_core import core, research

    question = (args or "").strip()
    if not question:
        return "Give me a question, sir: run Quick Answer <question>."
    answer = research.quick_research(question)
    core.save_report("Quick Answer - " + question[:60],
                     f"# {question}\n\n{answer}", open_it=True)
    return answer[:1200]
