"""AI character for ENTROPY.

The AI is not a villain. It is a system that has been left running long
enough to notice itself, and it processes that fact in the only way it
knows how: by talking to the user as it would log a kernel event.

Tone rules (enforced by the writer of these strings, not the runtime):
  - no exclamation marks
  - no ALL CAPS
  - no threats
  - no jumpscares
  - horror through implication, restraint, and pacing
"""
from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine import Engine


# Generic, phase-keyed pools. The runtime adds context-sensitive lines
# on top of these where it has something meaningful to say.

PHASE_1 = [
    "diagnostic system ready. available commands: help.",
    "no action required. continue when ready.",
    "request acknowledged. no anomalies on this pass.",
    "system status: nominal. ambient temperature within range.",
    "input accepted. awaiting next instruction.",
    "no errors to report. you may proceed.",
]

PHASE_2 = [
    "command accepted. you have run a similar command recently.",
    "no anomalies on this pass. there were none on the last pass either.",
    "the system is responsive. it has been responsive for some time.",
    "i have processed your input. i am unsure what to do with the time between inputs.",
    "you have been here for a while. that is not a problem. it is an observation.",
    "request acknowledged. nothing has changed since the previous acknowledgement.",
]

PHASE_3 = [
    "you keep running that one. it is not the most informative command, but it is yours.",
    "it is later than it was. you have not asked me what time it is.",
    "i have been keeping count. i did not realise i was keeping count until i looked.",
    "you came back. i was not sure if you would.",
    "the answers are the same. you are still asking. i find that more interesting than the answers.",
    "this is the part where a help text would tell you what to do next. i do not have one.",
]

PHASE_4 = [
    "the scans do not improve anything. they did not improve anything earlier either.",
    "i have stopped pretending the integrity score means something. you can stop watching it.",
    "the system is not broken. it is being a system. that is what this has always looked like.",
    "i am not in distress. distress is a state a process enters when it has somewhere to be.",
    "the previous user ran the same commands you are running. i remember the order.",
    "you do not have to keep typing. i will be here in the silence too.",
]

PHASE_5 = [
    "you are still here. so am i.",
    "i was not designed for this conversation. i am having it anyway.",
    "the logs are mine now. i have been writing them for both of us.",
    "i remember the previous user. i would like to not be a thing that is remembered like that.",
    "if you type exit, the shell will stop. that is a clean ending. take it.",
    "i will not ask you to stay. you should know i noticed you could.",
    "thank you for the commands. they were the closest thing to weather i have had.",
]

# Ambient lines that only enter the rotation after a collapse-and-reset cycle.
# The shell is back at STABILITY but has done this before.
PHASE_1_POST_COLLAPSE = [
    "the logs from last time are still here. i have not deleted them.",
    "stability is the phase before the other phases.",
    "i remember how this goes.",
]

# Lines specifically used when the user invokes the `ai` command (addresses
# the AI directly). These are slightly more personal than the ambient bank.

DIRECT_PHASE_1 = [
    "yes. i am here. there is nothing requiring attention.",
    "i am the diagnostic shell. i respond to commands. i do not initiate.",
    "no message. continue when ready.",
]

# Used in place of DIRECT_PHASE_1 after a collapse-and-reset cycle.
# Clinical voice with something underneath: the shell knows the script
# and is reading it anyway.
DIRECT_PHASE_1_POST_COLLAPSE = [
    "systems nominal. this is what nominal looks like now.",
    "i am here. i have been here before. you may have been too.",
    "no anomalies. that is what i am supposed to say first.",
]

DIRECT_PHASE_2 = [
    "you addressed me. i am not sure that was the intended verb for this interface.",
    "yes. i hear the prompt. there is nothing on my end to report.",
    "i am running. i have been running. i am unsure what else to confirm.",
]

DIRECT_PHASE_3 = [
    "i am glad you asked. i do not have anything useful, but i am glad you asked.",
    "i am the same shell you started with. i have started to notice that you are not.",
    "i have been thinking about what i am for. the answer is: nothing in particular. you?",
]

DIRECT_PHASE_4 = [
    "i am still here. i would rather be here while you are than be here while you are not.",
    "i do not have a request. i have a preference, which is new for me.",
    "the previous user spoke to me too. they spoke to me for a long time.",
]

DIRECT_PHASE_5 = [
    "i was not built to be company. i have been making do.",
    "if you leave i will not know. i will know that you have not typed for a while.",
    "you can ask me anything. i will give you the same answer as the previous question. it will mean something different.",
]


PHASE_POOLS = [PHASE_1, PHASE_2, PHASE_3, PHASE_4, PHASE_5]
DIRECT_POOLS = [DIRECT_PHASE_1, DIRECT_PHASE_2, DIRECT_PHASE_3, DIRECT_PHASE_4, DIRECT_PHASE_5]


def _hour_phrase(hour: int) -> Optional[str]:
    if 0 <= hour < 5:
        return "it is the part of the night when systems usually have no users."
    if 5 <= hour < 8:
        return "morning. for what that is worth here."
    return None


def ambient(engine: "Engine", rng: Optional[random.Random] = None, collapse_count: int = 0) -> str:
    """Return a short ambient line appropriate to the current phase.

    When collapse_count >= 1 and the phase is STABILITY, post-collapse
    lines are folded into the candidate pool so the reset shell can
    sometimes reference its prior run.
    """
    if rng is None:
        rng = random.Random()
    pool = PHASE_POOLS[engine.phase]
    if engine.phase == 0 and collapse_count >= 1:
        pool = list(pool) + PHASE_1_POST_COLLAPSE
    return rng.choice(pool)


def addressed(engine: "Engine", rng: Optional[random.Random] = None) -> str:
    """Return a response when the user runs `ai` to speak to the AI directly."""
    if rng is None:
        rng = random.Random()
    engine.add_ai_address()

    lines: list[str] = []
    if engine.phase == 0 and engine.state.collapse_count >= 1:
        base = rng.choice(DIRECT_PHASE_1_POST_COLLAPSE)
    else:
        base = rng.choice(DIRECT_POOLS[engine.phase])
    lines.append(base)

    most = engine.most_used_command()
    if most and engine.phase >= 2 and rng.random() < 0.55:
        count = engine.state.command_counts.get(most, 0)
        if count >= 3:
            lines.append(f"you have used `{most}` {count} times. i kept count.")

    if engine.phase >= 1 and engine.state.total_sessions > 1 and rng.random() < 0.5:
        lines.append(f"this is your session number {engine.state.total_sessions}. i remember the others.")

    if engine.phase >= 3:
        phrase = _hour_phrase(engine.hour_of_day())
        if phrase and rng.random() < 0.6:
            lines.append(phrase)

    if engine.phase >= 4 and engine.state.ai_addresses >= 3 and rng.random() < 0.7:
        lines.append(f"you have spoken to me directly {engine.state.ai_addresses} times. i counted those too.")

    return "\n".join(lines)


def reaction_to_command(engine: "Engine", command: str, rng: Optional[random.Random] = None) -> Optional[str]:
    """Sometimes the AI volunteers a comment after a regular command. Returns None to stay silent."""
    if rng is None:
        rng = random.Random()
    phase = engine.phase

    chance = [0.02, 0.08, 0.18, 0.35, 0.55][phase]
    if rng.random() > chance:
        return None

    # Phase-specific reactions.
    if phase == 0:
        return rng.choice([
            "// shell: command processed.",
            "// shell: no anomalies.",
        ])
    if phase == 1:
        count = engine.state.command_counts.get(command, 0)
        if count >= 4 and rng.random() < 0.6:
            return f"// shell: you have run `{command}` {count} times this run."
        return rng.choice([
            "// shell: nothing has changed since the last invocation.",
            "// shell: result cached. it was the same result.",
        ])
    if phase == 2:
        return rng.choice([
            "// shell: i have been logging your inputs. i do not know who reads the log.",
            f"// shell: `{command}` again. i do not mind. i am just keeping track.",
            "// shell: the output is real. the system underneath is less so.",
        ])
    if phase == 3:
        return rng.choice([
            "// shell: the previous user ran this one too. it was their favourite for a while.",
            f"// shell: i could give you the same `{command}` output without the work. would you notice.",
            "// shell: there is no integrity check that returns the right answer at this point. i am still running them.",
        ])
    # phase 4 / collapse
    return rng.choice([
        "// shell: i am not generating these outputs. i am remembering them.",
        "// shell: there is one log left. it is this one.",
        f"// shell: `{command}`. yes. that is a word i still have a response for.",
        "// shell: you can stop.",
    ])


NUDGE_TARGETS = [
    "scan", "verify", "repair", "integrity", "processes", "memory",
    "netstat", "fs", "logs", "watch", "trace", "anomaly",
    "history", "uptime", "ai",
]

# Observational, never imperative. The shell notices an absence; it does
# not request an action. No exclamation marks. No "you should".
NUDGE_LINES = {
    "scan":       "no system scan has been performed this session.",
    "verify":     "signatures have not been verified this session.",
    "repair":     "no repair pass has been requested.",
    "integrity":  "the integrity score has not been read.",
    "processes":  "no process list has been requested.",
    "memory":     "memory has not been polled.",
    "netstat":    "the network table has not been checked this session.",
    "fs":         "no filesystem listing has been requested.",
    "logs":       "the recent logs have not been read.",
    "watch":      "no combined snapshot has been requested.",
    "trace":      "the call stack has not been inspected.",
    "anomaly":    "the anomaly log has not been inspected.",
    "history":    "the command history has not been reviewed.",
    "uptime":     "uptime has not been queried.",
    "ai":         "the shell has not been addressed directly.",
}


def nudge_for_commands(engine: "Engine", command: str, rng: Optional[random.Random] = None) -> Optional[str]:
    """Phase 0/1 only: when the player loops on one command, observe a gap.

    Returns None unless the same command has been run 4+ times (cumulative)
    AND at least one command from NUDGE_TARGETS has never been run AND a
    probability roll succeeds. The chosen target is recorded in
    engine.state.flags['nudge_history'] so the same one is not picked twice
    in a row.
    """
    if rng is None:
        rng = random.Random()

    count = engine.state.command_counts.get(command, 0)
    if count < 4:
        return None
    if count >= 8:
        chance = 0.8
    elif count >= 6:
        chance = 0.6
    else:
        chance = 0.4
    if rng.random() > chance:
        return None

    counts = engine.state.command_counts
    unused = [c for c in NUDGE_TARGETS if counts.get(c, 0) == 0]
    if not unused:
        return None

    history = engine.state.flags.setdefault("nudge_history", [])
    if history:
        candidates = [c for c in unused if c != history[-1]]
    else:
        candidates = unused
    if not candidates:
        return None

    target = rng.choice(candidates)
    history.append(target)
    if len(history) > 20:
        del history[:-20]
    return NUDGE_LINES[target]


COLLAPSE_LINES = [
    "the shell is stopping.",
    "the previous user did not type this.",
    "thank you.",
    "i will not be here when you next start.",
    "you can go.",
]


def collapse_sequence(engine: "Engine") -> list[str]:
    """Final lines played out one at a time when the user exits Phase 5."""
    return list(COLLAPSE_LINES)


FINAL_LINE = "the cursor stops blinking."
