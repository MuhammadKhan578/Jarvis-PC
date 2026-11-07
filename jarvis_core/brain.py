"""J.A.R.V.I.S. Ultimate Reasoning Core.

A separate multi-pass "brain" for hard questions, decisions, code review and
debate.  It uses the same Gemini API but a different reasoning pipeline:
decompose -> draft -> critique -> revise, with a second independent draft in
max mode.  It never exposes hidden chain-of-thought; it returns a conclusion,
the key reasoning, confidence and assumptions.
"""
from __future__ import annotations

import time

from . import core, memory

_SYSTEM = (
    "You are the J.A.R.V.I.S. Ultimate Reasoning Core. You are rigorous, calm, "
    "evidence-driven and honest about uncertainty. You never invent facts, "
    "citations or numbers. You separate what is known from what is assumed. "
    "You reason for quality, not for length. Never reveal private chain-of-thought; "
    "give a concise reasoning summary instead."
)

_QUICK = """Question: {question}

{memory}

Think carefully, then answer. Use exactly this structure:

## Conclusion
A direct, complete answer in 1-2 short paragraphs.

## Key reasoning
- 3-5 bullets with the decisive logic, evidence or calculations.

## Confidence
High / medium / low, with one sentence explaining why.

## Assumptions and unknowns
Anything you had to assume, or facts that would change the answer. If the question
needs current data you do not have, say so instead of guessing."""

_PLAN = """Question: {question}

Break this question down for rigorous analysis. Return ONLY JSON:
{{
  "subquestions": ["the key sub-questions that must be answered"],
  "constraints": ["important constraints, definitions or requirements"],
  "evidence_needed": ["facts, data or checks needed"],
  "pitfalls": ["likely mistakes, biases or ambiguities"]
}}"""

_DRAFT = """Question: {question}

{memory}

ANALYSIS PLAN:
{plan}

Write the best possible answer. Be precise, concrete and honest. Use this structure:

## Conclusion
## Key reasoning
- decisive steps, evidence, calculations or comparisons
## Confidence
High / medium / low, with the reason
## Assumptions and unknowns
What you assumed and what could change the answer.

Do not pad. Do not invent sources. If a claim needs current data, mark it as unverified."""

_CRITIQUE = """Question: {question}

DRAFT ANSWER:
{draft}

Act as a hostile but fair reviewer. Find real errors, unsupported claims, missing
evidence, hidden assumptions, arithmetic mistakes and alternative explanations.
Return ONLY JSON:
{{
  "issues": ["specific problems"],
  "missing": ["evidence or considerations that are missing"],
  "corrections": ["exact corrections to make"],
  "confidence": 0-100
}}"""

_REVISE = """Question: {question}

DRAFT:
{draft}

REVIEWER FINDINGS:
{critique}

Rewrite the answer so it fixes every valid finding. Keep what is correct, remove
unsupported claims, and state uncertainty honestly. Use the same structure:
## Conclusion
## Key reasoning
## Confidence
## Assumptions and unknowns"""

_SECOND = """Question: {question}

{memory}

Give an independent second opinion. Do not read or reuse any previous draft.
Reason from first principles, consider an alternative interpretation, and use:
## Conclusion
## Key reasoning
## Confidence
## Assumptions and unknowns"""

_MERGE = """Question: {question}

FIRST ANSWER:
{first}

SECOND OPINION:
{second}

REVIEWER FINDINGS:
{critique}

Merge the strongest, most truthful parts of both answers. Resolve disagreements
explicitly. Do not average contradictions; choose the better-supported position
and say why. Use:
## Conclusion
## Key reasoning
## Confidence
## Assumptions and unknowns"""

_DECIDE = """Decision: {question}

Options / context:
{options}

{memory}

Build a decision analysis:
1. Restate the real decision and constraints.
2. List 4-7 criteria with weights.
3. Score each option on each criterion (brief table).
4. Identify the biggest uncertainty and the cost of being wrong.
5. Give one clear recommendation, a fallback, and the first concrete next step.

Be practical. Do not invent data; mark estimates as estimates."""

_CODE = """Code or technical question:
{question}

{memory}

Review it like a senior engineer:
## Verdict
Is it correct? What is the main risk?
## Bugs and failure modes
Concrete issues, with why they happen.
## Security and data safety
Only real issues, not generic warnings.
## Performance
Where it will hurt at scale, if relevant.
## Better implementation
A corrected or improved version, with explanation.
## Tests
The smallest set of tests that would catch the important failures."""

_DEBATE = """Question or proposition: {question}

{memory}

Argue both sides properly.
## Strongest case FOR
The best honest argument, with evidence and assumptions.
## Strongest case AGAINST
The best honest counter-argument, with evidence and assumptions.
## Verdict
Which side is stronger, why, and what evidence would change the conclusion."""


def _ask(prompt: str, system: str = _SYSTEM, smart: bool = True,
         max_tokens: int = 2200, json_mode: bool = False) -> str:
    try:
        text = core.llm_text(prompt, system=system, json_mode=json_mode,
                             smart=smart, max_tokens=max_tokens)
        if text and text.strip():
            return text.strip()
    except Exception as e:
        core.log(f"brain call failed (smart={smart}): {e}")
    if smart:
        try:
            text = core.llm_text(prompt, system=system, json_mode=json_mode,
                                 smart=False, max_tokens=max_tokens)
            if text and text.strip():
                return text.strip()
        except Exception as e:
            core.log(f"brain fast fallback failed: {e}")
    return ""


def _json(prompt: str, max_tokens: int = 800, fallback=None):
    try:
        data = core.llm_json(prompt, system="Return JSON only. Be precise.",
                             smart=True, fallback=fallback, max_tokens=max_tokens)
        return data if data is not None else fallback
    except Exception:
        return fallback


def _memory_block(question: str) -> str:
    try:
        block = memory.context_for(question, limit=8)
        return block or "(no relevant long-term memory)"
    except Exception:
        return "(memory unavailable)"


def think(question: str, depth: str = "deep", context: str = "") -> str:
    """Run the multi-pass reasoning pipeline and return a structured answer."""
    question = (question or "").strip()
    if not question:
        return "No question was given to the reasoning core."
    depth = (depth or "deep").lower().strip()
    mem = _memory_block(question)
    if context:
        mem += "\n\nEXTRA CONTEXT:\n" + core.truncate(context, 3000)

    if depth in ("quick", "fast", "1"):
        answer = _ask(_QUICK.format(question=question, memory=mem), max_tokens=1200)
        return answer or "The reasoning core could not reach the model. Please try again."

    plan = _json(_PLAN.format(question=question), max_tokens=700, fallback={})
    import json as _jsonmod
    plan_text = _jsonmod.dumps(plan, ensure_ascii=False, indent=2) if plan else "(no plan)"
    draft = _ask(_DRAFT.format(question=question, memory=mem, plan=plan_text),
                 max_tokens=2600)
    if not draft:
        return "The reasoning core could not produce a draft. Please try again."

    critique = _json(_CRITIQUE.format(question=question, draft=core.truncate(draft, 9000)),
                     max_tokens=1000, fallback={})
    critique_text = _jsonmod.dumps(critique, ensure_ascii=False, indent=2) if critique else "(no review)"

    if depth in ("max", "maximum", "ultimate", "3"):
        second = _ask(_SECOND.format(question=question, memory=mem), max_tokens=2200)
        if second:
            final = _ask(_MERGE.format(question=question, first=core.truncate(draft, 7000),
                                       second=core.truncate(second, 7000),
                                       critique=critique_text), max_tokens=3000)
            if final:
                return final
        # fall through to a normal revision if the second opinion failed

    final = _ask(_REVISE.format(question=question, draft=core.truncate(draft, 9000),
                                critique=critique_text), max_tokens=2800)
    return final or draft


def decide(question: str, options: str = "") -> str:
    question = (question or "").strip()
    if not question:
        return "No decision was given."
    prompt = _DECIDE.format(question=question, options=options or "(not specified)",
                            memory=_memory_block(question))
    first = _ask(prompt, max_tokens=2200)
    if not first:
        return "The reasoning core could not analyse that decision right now."
    review = _json(_CRITIQUE.format(question=question, draft=core.truncate(first, 9000)),
                   max_tokens=900, fallback={})
    import json as _jsonmod
    final = _ask(_REVISE.format(question=question, draft=core.truncate(first, 9000),
                                critique=_jsonmod.dumps(review, ensure_ascii=False, indent=2)
                                if review else "(no review)"), max_tokens=2400)
    return final or first


def review_code(question: str) -> str:
    question = (question or "").strip()
    if not question:
        return "No code or technical question was given."
    answer = _ask(_CODE.format(question=question, memory=_memory_block(question)),
                  max_tokens=2800)
    return answer or "The code review could not be completed right now."


def debate(question: str) -> str:
    question = (question or "").strip()
    if not question:
        return "No proposition was given."
    answer = _ask(_DEBATE.format(question=question, memory=_memory_block(question)),
                  max_tokens=2600)
    return answer or "The debate could not be completed right now."


def brain_operation(action: str = "think", question: str = "", depth: str = "deep",
                    wait: bool = False, options: str = "") -> str:
    """Run the separate Ultimate Reasoning Core.

    action:
      think    - deep multi-pass reasoning on a hard question
      decide   - structured decision analysis (options may be supplied)
      review_code - senior-engineer code/technical review
      debate   - strongest case for and against, then a verdict
      status   - describe the reasoning core and its settings
    depth: quick, standard/deep or max.  deep/max run in the background by default.
    wait: True blocks until the answer is ready (can take a few minutes).
    """
    a = (action or "think").lower().strip().replace("-", "_")
    q = (question or "").strip()
    if a in ("status", "info", "about"):
        return (
            "Ultimate Reasoning Core: online.\n"
            "- Pipeline: decompose -> draft -> hostile review -> revise"
            + " -> independent second opinion -> merge (max mode)\n"
            "- Modes: quick, deep, max; decisions, code review, debate\n"
            "- Memory: reads the permanent archive and structured facts before reasoning\n"
            "- Deep/max runs in the background and speaks the conclusion when ready\n"
            "This is a rigorous reasoning module, not a claim of consciousness."
        )
    if not q:
        return "No question was given to the reasoning core."

    if a in ("decide", "decision", "choose"):
        return decide(q, options)

    if a in ("review_code", "code", "code_review", "review"):
        return review_code(q)

    if a in ("debate", "argue", "both_sides"):
        return debate(q)

    if a not in ("think", "reason", "analyze", "analyse", "solve", "plan"):
        return f"Unknown brain action '{action}'."

    depth = (depth or "deep").lower().strip()
    if depth in ("deep", "max", "maximum", "ultimate") and not wait:
        core.say_async("Deep reasoning core engaged, sir. I am working through it.")
        question_copy = q

        def _job():
            try:
                answer = think(question_copy, depth)
                md_path, html_path = core.save_report(
                    "Deep Reasoning - " + question_copy[:70],
                    f"# Deep Reasoning\n\n**Question:** {question_copy}\n\n{answer}",
                    open_it=False)
                core.say_async("Sir, my conclusion: " + core.truncate(answer, 900) +
                               f" Full reasoning saved to {html_path or md_path}.")
                memory.add_episode("Deep reasoning: " + core.truncate(question_copy, 180),
                                   ["brain", "reasoning"], 3)
            except Exception as e:
                core.log(f"deep reasoning failed: {e}")
                core.say_async("Sir, the reasoning core failed: " + core.truncate(str(e), 180))

        core.run_bg(_job)
        return ("Deep reasoning is running in the background, sir. I will speak the conclusion "
                "and save the full analysis to a report when it is ready.")

    return think(q, depth)


def status() -> str:
    return brain_operation("status")
