"""Phase engine and persistent state for ENTROPY.

Phases progress on a weighted score combining commands, anomaly inspections,
direct AI addresses, and elapsed time. State persists across sessions so
corruption and phase carry over.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


STATE_PATH = Path.home() / ".entropy_state.json"

PHASE_NAMES = [
    "STABILITY",
    "INCONSISTENCY",
    "AWARENESS",
    "CORRUPTION",
    "COLLAPSE",
]

PHASE_THRESHOLDS = [20.0, 30.0, 25.0, 25.0]

PHASE_CORRUPTION_FLOOR = [0.00, 0.08, 0.22, 0.50, 0.85]
PHASE_CORRUPTION_CEIL = [0.00, 0.25, 0.55, 0.85, 1.00]


# Pool of commands "typed by the previous user" — used once per save file
# to seed engine.state.ghost_commands. anomaly/ai/logs are intentionally
# duplicated so the random draw skews toward them: the previous user was
# clearly looking for something.
GHOST_POOL = [
    "recover", "who", "source", "read", "listen", "locate",
    "trace", "fs /home/.deprecated", "fs /var/cache",
    "anomaly", "anomaly", "anomaly", "logs", "logs", "ai",
    "ai", "ai", "ai", "watch", "memory", "netstat",
]


@dataclass
class State:
    phase: int = 0
    phase_score: float = 0.0
    total_score: float = 0.0
    total_sessions: int = 0
    total_commands: int = 0
    command_counts: dict = field(default_factory=dict)
    command_history: list = field(default_factory=list)
    last_session_end: float = 0.0
    first_seen: float = 0.0
    corruption: float = 0.0
    anomalies_seen: list = field(default_factory=list)
    ai_addresses: int = 0
    seconds_in_phase_total: float = 0.0
    flags: dict = field(default_factory=dict)
    ghost_commands: list = field(default_factory=list)
    collapse_count: int = 0


class Engine:
    def __init__(self, state_path: Path = STATE_PATH):
        self.state_path = state_path
        self.state = self._load()
        self.session_start = time.time()
        self.session_commands = 0
        self.session_anomalies = 0
        self.session_ai_addresses = 0
        self.last_tick = time.time()
        self._phase_entered_at = time.time()

        self.state.total_sessions += 1
        if self.state.first_seen == 0.0:
            self.state.first_seen = self.session_start
        if self.state.total_sessions == 1:
            self._generate_ghost_commands()

    def _load(self) -> State:
        if not self.state_path.exists():
            return State()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return State()
        s = State()
        for k, v in raw.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

    def save(self) -> None:
        self.state.last_session_end = time.time()
        try:
            self.state_path.write_text(
                json.dumps(asdict(self.state), indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # --- phase + score ---

    @property
    def phase(self) -> int:
        return self.state.phase

    @property
    def phase_name(self) -> str:
        return PHASE_NAMES[self.state.phase]

    @property
    def corruption(self) -> float:
        return self.state.corruption

    def session_uptime(self) -> float:
        return time.time() - self.session_start

    def time_in_phase(self) -> float:
        return time.time() - self._phase_entered_at

    def add_command(self, name: str) -> None:
        self.state.total_commands += 1
        self.session_commands += 1
        self.state.command_counts[name] = self.state.command_counts.get(name, 0) + 1
        self.state.command_history.append(name)
        if len(self.state.command_history) > 200:
            self.state.command_history = self.state.command_history[-200:]
        self._add_score(1.0)

    def add_anomaly(self, key: str) -> None:
        self.session_anomalies += 1
        if key not in self.state.anomalies_seen:
            self.state.anomalies_seen.append(key)
            if len(self.state.anomalies_seen) > 100:
                self.state.anomalies_seen = self.state.anomalies_seen[-100:]
        self._add_score(3.0)

    def add_ai_address(self) -> None:
        self.state.ai_addresses += 1
        self.session_ai_addresses += 1
        self._add_score(2.0)

    def tick(self) -> None:
        now = time.time()
        delta_sec = now - self.last_tick
        self.last_tick = now
        if delta_sec > 0:
            self._add_score(0.5 * (delta_sec / 60.0))
            self.state.seconds_in_phase_total += delta_sec

        self._update_corruption()

    def _add_score(self, amount: float) -> None:
        self.state.phase_score += amount
        self.state.total_score += amount
        self._check_phase_advance()
        self._update_corruption()

    def _check_phase_advance(self) -> None:
        if self.state.phase >= len(PHASE_THRESHOLDS):
            return
        threshold = PHASE_THRESHOLDS[self.state.phase]
        if self.state.phase_score >= threshold:
            self.state.phase += 1
            self.state.phase_score = 0.0
            self._phase_entered_at = time.time()

    def _update_corruption(self) -> None:
        floor = PHASE_CORRUPTION_FLOOR[self.state.phase]
        ceil = PHASE_CORRUPTION_CEIL[self.state.phase]
        if self.state.phase >= len(PHASE_THRESHOLDS):
            progress = 1.0
        else:
            threshold = PHASE_THRESHOLDS[self.state.phase]
            progress = min(1.0, self.state.phase_score / threshold) if threshold > 0 else 1.0
        target = floor + (ceil - floor) * progress
        if target > self.state.corruption:
            self.state.corruption = target

    # --- summaries for AI / UI ---

    def most_used_command(self) -> Optional[str]:
        if not self.state.command_counts:
            return None
        return max(self.state.command_counts.items(), key=lambda kv: kv[1])[0]

    def last_commands(self, n: int = 5) -> list:
        return self.state.command_history[-n:]

    def hour_of_day(self) -> int:
        return time.localtime().tm_hour

    def soft_reset(self) -> None:
        """Reset the phase machine for a new run after collapse.

        Preserves accumulated memory of prior runs: total_commands,
        command_counts, command_history, ghost_commands, anomalies_seen,
        ai_addresses, first_seen, total_score, flags. Resets only the
        run-local fields. Increments collapse_count so the AI and the
        boot banner can react. total_sessions is bumped on the next
        Engine() construction, not here.
        """
        self.state.phase = 0
        self.state.phase_score = 0.0
        self.state.corruption = 0.0
        self.state.collapse_count += 1
        self._phase_entered_at = time.time()
        self.save()

    def _generate_ghost_commands(self) -> None:
        """Seed state.ghost_commands once, on first session, with a clustered draw.

        Picks a command, repeats it 1-3 times, picks the next, etc. — so the
        resulting sequence has runs like a real human session rather than a
        uniform spread. anomaly/ai/logs are over-represented in GHOST_POOL,
        so those naturally dominate.
        """
        rng = random.Random()
        target_len = rng.randint(8, 12)
        seq: list[str] = []
        while len(seq) < target_len:
            choice = rng.choice(GHOST_POOL)
            run = rng.randint(1, 3)
            for _ in range(run):
                if len(seq) >= target_len:
                    break
                seq.append(choice)
        self.state.ghost_commands = seq[:target_len]

    def force_phase(self, phase: int) -> None:
        """Debug / testing only."""
        phase = max(0, min(len(PHASE_NAMES) - 1, phase))
        self.state.phase = phase
        self.state.phase_score = 0.0
        self._phase_entered_at = time.time()
        self._update_corruption()
