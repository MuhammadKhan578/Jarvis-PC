"""Example Python skill: a one-page daily stand-up report."""

NAME = "Standup Report"
DESCRIPTION = "Create a short daily stand-up report from missions, schedule and recent files."


def run(jarvis, args=""):
    from jarvis_core import agent, core, memory

    lines = ["# Daily Stand-up", "", f"**{core.now_str()}**", ""]

    missions = agent._load_missions()
    active = [m for m in missions.values() if m.get("status") in ("running", "planning")]
    done = [m for m in missions.values() if m.get("status") == "done"]
    lines += ["## Missions", ""]
    if active:
        lines += [f"- Running: {m.get('goal', '')}" for m in active]
    if done[-3:]:
        lines += [f"- Finished: {m.get('goal', '')}" for m in done[-3:]]
    if not active and not done:
        lines.append("- No missions yet.")

    jobs = agent._load_schedule()
    upcoming = sorted((j for j in jobs.values() if j.get("enabled", True)),
                      key=lambda j: j.get("next") or 0)[:5]
    lines += ["", "## Upcoming", ""]
    lines += [f"- {j.get('label', '')}: {j.get('prompt', '')}" for j in upcoming] or ["- Nothing scheduled."]

    episodes = memory.recent_episodes(4)
    lines += ["", "## Recently", ""]
    lines += [f"- {e.get('summary', '')}" for e in episodes] or ["- No episodes recorded."]

    md = "\n".join(lines)
    md_path, html_path = core.save_report("Standup Report", md, open_it=True)
    return "Stand-up report ready, sir. " + (html_path or md_path)
