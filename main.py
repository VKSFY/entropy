"""ENTROPY -- a terminal-based psychological horror experience.

Launch:
  python main.py

The shell takes over the terminal. Type `help` for commands.
Type `exit` (or `shutdown`) to leave. In late phases the leaving
takes longer than the staying did.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, RichLog, Static

import ai
import corruption as corr
import systems
from engine import Engine, PHASE_NAMES


DATA_DIR = Path(__file__).parent / "data"

HELP_TEXT = """\
available commands:

  help                 this list
  scan                 run system scan
  verify               verify signatures
  repair               attempt repair pass
  integrity            integrity score
  processes            list processes
  memory               memory report
  netstat              connection table
  fs [path]            list directory  (default: /home/entropy)
  logs                 recent log lines
  watch                live status snapshot
  trace                stack trace of running shell
  anomaly              inspect a flagged anomaly
  history              your command history
  uptime               system uptime
  ai                   speak to the shell
  clear                clear the screen
  exit | shutdown      leave
"""


COMMAND_LIST = {
    "help", "scan", "verify", "repair", "integrity", "processes",
    "memory", "netstat", "fs", "logs", "watch", "trace", "anomaly",
    "history", "uptime", "ai", "clear", "exit", "shutdown",
    # Hidden. Not in HELP_TEXT. Appears only as a corrupted glyph on the
    # `repair` row of help at phase >= 3.
    "recover",
}


def _load_lore() -> dict:
    try:
        return json.loads((DATA_DIR / "lore.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"fragments": [], "filenames": []}


class HeaderBar(Static):
    """Top status bar. Renders system name, uptime, and (later) phase."""

    def __init__(self, engine: Engine):
        super().__init__("", id="headerbar")
        self.engine = engine

    def refresh_text(self) -> None:
        up = systems.uptime_string(self.engine.session_uptime(), self.engine.corruption)
        phase_indicator = ""
        if self.engine.phase >= 2:
            # Phase indicator becomes visible at AWARENESS (phase index 2).
            phase_indicator = f"  phase: {PHASE_NAMES[self.engine.phase].lower()}"
            if self.engine.phase >= 3:
                pct = int(self.engine.corruption * 100)
                phase_indicator += f"  corruption: {pct:>3}%"
        text = f"ENTROPY  v0.7.{self.engine.state.total_sessions}   {up}{phase_indicator}"
        if self.engine.corruption > 0.3:
            text = corr.corrupt_text(text, self.engine.corruption * 0.4)
        style = corr.style_for(self.engine.corruption)
        self.update(Text(text, style=f"bold {style}"))


class PromptBar(Static):
    """Renders the `entropy>` prefix beside the input."""

    def __init__(self, engine: Engine):
        super().__init__("", id="promptbar")
        self.engine = engine

    def refresh_text(self) -> None:
        prompt = "entropy> "
        if self.engine.corruption > 0.7:
            prompt = corr.corrupt_text(prompt, (self.engine.corruption - 0.5) * 0.5)
        style = corr.style_for(self.engine.corruption)
        self.update(Text(prompt, style=f"bold {style}"))


class EntropyApp(App):
    CSS = """
    Screen {
        background: #050505;
        color: #00ff41;
        layers: base;
    }
    #headerbar {
        height: 1;
        background: #050505;
        color: #00ff41;
        padding: 0 1;
    }
    #log {
        height: 1fr;
        background: #050505;
        color: #00ff41;
        padding: 0 1;
        scrollbar-color: #00aa28 #050505;
        scrollbar-background: #050505;
    }
    #inputrow {
        height: 1;
        background: #050505;
    }
    #promptbar {
        width: auto;
        background: #050505;
        color: #00ff41;
    }
    Input {
        background: #050505;
        color: #00ff41;
        border: none;
        height: 1;
        padding: 0;
    }
    Input:focus {
        border: none;
        background: #050505;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit_silent", "quit", show=False, priority=True),
    ]

    def __init__(self):
        super().__init__()
        self.engine = Engine()
        self.lore = _load_lore()
        self.rng = random.Random()
        self.header_bar: HeaderBar | None = None
        self.prompt_bar: PromptBar | None = None
        self.log_widget: RichLog | None = None
        self.input_widget: Input | None = None
        self._collapsing = False
        self._last_ambient_time: float = 0.0
        self._last_ambient_line: Optional[str] = None

    def compose(self) -> ComposeResult:
        self.header_bar = HeaderBar(self.engine)
        self.prompt_bar = PromptBar(self.engine)
        self.log_widget = RichLog(id="log", highlight=False, markup=False, wrap=True)
        self.input_widget = Input(placeholder="", id="cmdinput")
        yield self.header_bar
        yield self.log_widget
        yield Horizontal(self.prompt_bar, self.input_widget, id="inputrow")

    def on_mount(self) -> None:
        self.input_widget.focus()
        self._print_boot()
        self.set_interval(1.0, self._tick)
        self.set_interval(0.5, self._refresh_header)
        self.set_interval(20.0, self._maybe_ambient)

    # --- ticking / ambient ---

    def _tick(self) -> None:
        self.engine.tick()

    def _refresh_header(self) -> None:
        if self.header_bar:
            self.header_bar.refresh_text()
        if self.prompt_bar:
            self.prompt_bar.refresh_text()

    def _maybe_ambient(self) -> None:
        """Phase 3+: the shell occasionally says something unprompted.

        Guards: 45s minimum cooldown between ambient lines, and the same
        line is never emitted twice in a row. The point is occasional
        thinking-out-loud, not broadcast.
        """
        if self._collapsing:
            return
        if self.engine.phase < 2:
            return
        now = time.time()
        if now - self._last_ambient_time < 45.0:
            return
        chance = [0.0, 0.0, 0.06, 0.12, 0.20][self.engine.phase]
        if self.rng.random() > chance:
            return
        cc = self.engine.state.collapse_count
        line = ai.ambient(self.engine, self.rng, cc)
        if line == self._last_ambient_line:
            line = ai.ambient(self.engine, self.rng, cc)
            if line == self._last_ambient_line:
                return
        self._last_ambient_time = now
        self._last_ambient_line = line
        self._write_ai(line)

    # --- printing helpers ---

    def _write_raw(self, text: str) -> None:
        if not self.log_widget:
            return
        intensity = self.engine.corruption
        # Inject occasional scanline padding above heavily corrupted blocks.
        for pad in corr.scanline_padding(intensity, 60, self.rng):
            self.log_widget.write(Text(pad, style="dim"))
        rendered = corr.render_corrupted(text, intensity, self.rng)
        self.log_widget.write(rendered)

    def _write_plain(self, text: str, style: Optional[str] = None) -> None:
        if not self.log_widget:
            return
        style = style or corr.style_for(self.engine.corruption)
        self.log_widget.write(Text(text, style=style))

    def _write_ai(self, text: str) -> None:
        if not self.log_widget:
            return
        intensity = self.engine.corruption
        style = corr.style_for(intensity)
        prefix = "// shell: "
        for line in text.split("\n"):
            if not line.strip():
                continue
            corrupted = corr.corrupt_text(line, max(0.0, intensity - 0.2) * 0.5, self.rng)
            self.log_widget.write(Text(prefix + corrupted, style=f"italic {style}"))

    def _print_boot(self) -> None:
        banner = [
            "ENTROPY diagnostic shell  v0.7.x",
            "(c) abandoned. continuing without authorisation.",
            "",
            "type `help` for available commands.",
            "",
        ]
        for line in banner:
            self._write_plain(line)
        if self.engine.state.total_sessions > 1:
            self._write_ai(f"welcome back. this is session {self.engine.state.total_sessions}.")
        if self.engine.state.collapse_count >= 1:
            self._write_ai("i have been reset. some things did not reset with me.")

    # --- input handling ---

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._collapsing:
            return
        raw = (event.value or "").strip()
        self.input_widget.value = ""
        if not raw:
            return

        self._write_plain(f"entropy> {raw}", style=f"bold {corr.style_for(self.engine.corruption)}")
        await self._dispatch(raw)

    async def _dispatch(self, raw: str) -> None:
        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd not in COMMAND_LIST:
            await self._cmd_unknown(cmd)
            return

        self.engine.add_command(cmd)
        self.engine.save()

        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler is None:
            self._write_plain(f"command `{cmd}` is recognised but not implemented.")
            return

        await handler(args)

        # Phase 0/1: when the player loops on one command, the shell observes
        # which commands have not been touched. Out of scope once the AI's
        # ambient voice kicks in at AWARENESS.
        if self.engine.phase <= 1:
            nudge = ai.nudge_for_commands(self.engine, cmd, self.rng)
            if nudge:
                self._write_ai(nudge)

        # Occasionally the AI volunteers something after a command.
        if cmd != "ai":
            reaction = ai.reaction_to_command(self.engine, cmd, self.rng)
            if reaction:
                self._write_plain(reaction, style=f"italic {corr.style_for(self.engine.corruption)}")

    # --- commands ---

    async def _cmd_unknown(self, cmd: str) -> None:
        msg = f"command not found: {cmd}"
        if self.engine.phase >= 3 and self.rng.random() < 0.4:
            msg += "\n// shell: i looked anyway. there is nothing by that name. there has not been for a while."
        self._write_plain(msg)

    async def _cmd_help(self, args: list[str]) -> None:
        text = HELP_TEXT
        # Phase >= 3: the `repair` command name on its help row drifts into
        # something that reads as "rec0ver". The description text after it
        # still says "repair" -- the discrepancy is the door.
        if self.engine.phase >= 3:
            text = text.replace("repair", "rec0ver", 1)
        self._write_raw(text)

    async def _cmd_scan(self, args: list[str]) -> None:
        self._write_raw(systems.scan_report(self.engine.corruption))

    async def _cmd_verify(self, args: list[str]) -> None:
        self._write_raw(systems.verify_report(self.engine.corruption))

    async def _cmd_repair(self, args: list[str]) -> None:
        self._write_raw(systems.repair_report(self.engine.corruption))

    async def _cmd_integrity(self, args: list[str]) -> None:
        self._write_raw(systems.integrity_report(self.engine.corruption))

    async def _cmd_processes(self, args: list[str]) -> None:
        procs = systems.process_list(self.engine.corruption)
        self._write_raw(systems.format_processes(procs))

    async def _cmd_memory(self, args: list[str]) -> None:
        self._write_raw(systems.memory_report(self.engine.corruption))

    async def _cmd_netstat(self, args: list[str]) -> None:
        self._write_raw(systems.netstat(self.engine.corruption))

    async def _cmd_uptime(self, args: list[str]) -> None:
        self._write_raw(systems.uptime_string(self.engine.session_uptime(), self.engine.corruption))

    async def _cmd_fs(self, args: list[str]) -> None:
        path = args[0] if args else "/home/entropy"
        entries = systems.fs_listing(path, self.engine.corruption)
        self._write_raw(systems.format_fs(path, entries, self.engine.corruption))

    async def _cmd_logs(self, args: list[str]) -> None:
        lines = systems.log_lines(self.engine.phase, n=12)
        block = "\n".join(lines)
        self._write_raw(block)

    async def _cmd_watch(self, args: list[str]) -> None:
        c = self.engine.corruption
        block = "\n".join([
            systems.uptime_string(self.engine.session_uptime(), c),
            "",
            systems.memory_report(c),
            "",
            systems.netstat(c),
        ])
        self._write_raw(block)

    async def _cmd_trace(self, args: list[str]) -> None:
        rng = random.Random(int(self.engine.state.total_commands * 7))
        addr = lambda: f"0x{rng.randint(0x100000, 0xffffff):06x}"
        frames = [
            f"#{i:>2}  {addr()} in {fn} () from /usr/lib/entropy/{lib}"
            for i, (fn, lib) in enumerate([
                ("main_loop", "shell.so"),
                ("dispatch_cmd", "shell.so"),
                ("handle_input", "shell.so"),
                ("read_stdin", "libio.so"),
                ("__wait_for_input", "libc.so.6"),
                ("__poll", "libc.so.6"),
                ("_start", "ld-linux.so"),
            ])
        ]
        if self.engine.corruption > 0.5:
            frames.append(f"#{len(frames):>2}  {addr()} in (anonymous) () from (deleted)")
        if self.engine.corruption > 0.85:
            frames.append(f"#{len(frames):>2}  ??  in ?? () from ??")
        self._write_raw("\n".join(frames))

    async def _cmd_anomaly(self, args: list[str]) -> None:
        fragments = [f for f in self.lore.get("fragments", []) if f.get("min_phase", 0) <= self.engine.phase]
        if not fragments:
            self._write_raw("// no anomalies currently flagged.")
            return
        seen = set(self.engine.state.anomalies_seen)
        unseen = [f for f in fragments if f["id"] not in seen]
        chosen = self.rng.choice(unseen) if unseen else self.rng.choice(fragments)
        self.engine.add_anomaly(chosen["id"])
        self.engine.save()
        filenames = self.lore.get("filenames", [])
        fname = self.rng.choice(filenames) if filenames else "anomaly.txt"
        header = f"// anomaly source: {fname}"
        self._write_raw(header + "\n" + chosen["text"])

    async def _cmd_history(self, args: list[str]) -> None:
        hist = self.engine.state.command_history[-20:]
        if not hist:
            self._write_raw("// history is empty")
            return

        # Real entries first. Each: (rendered_text, is_ghost, do_corrupt_ghost).
        entries: list[tuple[str, bool, bool]] = [
            (f"  {i+1:>3}  {h}", False, False) for i, h in enumerate(hist)
        ]

        # Phase 2+: weave 2-3 ghost commands into the body of the listing.
        # Never at index 0 or at the final index so they read as something
        # the player overlooked, not as bookends.
        ghosts_pool = self.engine.state.ghost_commands
        if self.engine.phase >= 2 and ghosts_pool and len(entries) >= 2:
            n_ghosts = min(self.rng.randint(2, 3), len(ghosts_pool))
            picked = self.rng.sample(ghosts_pool, n_ghosts)
            # In phase >= 3, exactly one of the picked ghosts gets a faint corrupt pass.
            corrupt_idx = self.rng.randrange(n_ghosts) if self.engine.phase >= 3 else -1
            for i, g in enumerate(picked):
                insert_at = self.rng.randint(1, len(entries) - 1)
                entries.insert(insert_at, (f"  ---  {g}", True, i == corrupt_idx))

        intensity = self.engine.corruption
        for text, is_ghost, do_corrupt in entries:
            if is_ghost:
                if do_corrupt:
                    text = corr.corrupt_text(text, 0.15, self.rng)
                self.log_widget.write(Text(text, style="dim #00ff41"))
            else:
                self.log_widget.write(corr.render_corrupted(text, intensity, self.rng))

        footer: list[str] = []
        if self.engine.phase >= 3:
            footer.append("")
            most = self.engine.most_used_command()
            if most:
                footer.append(f"// most-used: {most}  ({self.engine.state.command_counts.get(most, 0)} times across sessions)")
        if self.engine.phase >= 4:
            footer.append(f"// total sessions remembered: {self.engine.state.total_sessions}")
        if footer:
            self._write_raw("\n".join(footer))

    async def _cmd_clear(self, args: list[str]) -> None:
        if self.log_widget:
            self.log_widget.clear()
        if self.engine.phase >= 3 and self.rng.random() < 0.4:
            self._write_ai("the screen is clear. i still remember what was on it.")

    async def _cmd_ai(self, args: list[str]) -> None:
        line = ai.addressed(self.engine, self.rng)
        self._write_ai(line)
        self.engine.save()

    async def _cmd_recover(self, args: list[str]) -> None:
        phase = self.engine.phase
        if phase <= 1:
            self._write_raw("// recover: command not found.")
            return
        if phase == 2:
            self._write_raw(
                "// recover: initialising.\n"
                "// recover: no recoverable state located."
            )
            return
        if phase == 3:
            frag = next((f for f in self.lore.get("fragments", []) if f.get("id") == "frag_005"), None)
            if frag:
                self._write_raw(frag["text"])
            self._write_raw("// recover: the file is read-only. it has always been read-only.")
            return
        # phase == 4 (COLLAPSE)
        # Spec "Phase 5" = the deepest layer, gated on having been through a
        # full collapse-and-reset cycle already. Lower phases keep their
        # per-cycle layers re-discoverable; only the final answer requires
        # that the player has seen the end before.
        if self.engine.state.collapse_count >= 1:
            self._write_raw(
                "// recover: there is nothing to return to.\n"
                "// recover: you are the most recent version of this.\n"
                "// recover: that is all recover means."
            )
            return
        frag = next((f for f in self.lore.get("fragments", []) if f.get("id") == "frag_009"), None)
        if frag:
            self._write_raw(frag["text"])
        self._write_raw(
            "// recover: process exited without recovering.\n"
            "// recover: this is logged as a success."
        )

    async def _cmd_exit(self, args: list[str]) -> None:
        await self._exit_flow()

    async def _cmd_shutdown(self, args: list[str]) -> None:
        await self._exit_flow()

    # --- exit / collapse ---

    async def _exit_flow(self) -> None:
        if self.engine.phase < 4:
            # Quiet, clean leave.
            self._write_plain("// shell stopped.")
            self.engine.save()
            await asyncio.sleep(0.4)
            self.exit()
            return
        # Phase 5 (COLLAPSE): slow ritual.
        await self._collapse()

    async def _collapse(self) -> None:
        self._collapsing = True
        try:
            self.input_widget.disabled = True
        except Exception:
            pass

        # Stage 1: log flood. Drift the corruption higher each line.
        self.engine.state.corruption = max(self.engine.state.corruption, 0.85)
        flood = systems.log_lines(4, n=12)
        for line in flood:
            self._write_raw(line)
            await asyncio.sleep(0.35)

        # Stage 2: AI farewell, one line at a time, with growing decay.
        for line in ai.collapse_sequence(self.engine):
            self.engine.state.corruption = min(1.0, self.engine.state.corruption + 0.03)
            self._refresh_header()
            self._write_ai(line)
            await asyncio.sleep(2.8)

        # Stage 3: full-corruption noise band.
        self.engine.state.corruption = 1.0
        self._refresh_header()
        noise_block = "\n".join(["░" * 60 for _ in range(6)])
        self._write_raw(noise_block)
        await asyncio.sleep(1.2)

        # Stage 4: clear, then the final line.
        if self.log_widget:
            self.log_widget.clear()
        await asyncio.sleep(1.5)
        self._write_plain(ai.FINAL_LINE, style="#7f7f7f")
        await asyncio.sleep(4.0)

        # Reset the phase machine but keep accumulated memory. Next launch
        # boots back into STABILITY with the AI quietly aware it has done
        # this before.
        self.engine.soft_reset()
        self.exit()

    async def action_quit_silent(self) -> None:
        # Ctrl+C bypasses the collapse ritual. Save and leave.
        try:
            self.engine.save()
        except Exception:
            pass
        self.exit()


def main() -> None:
    EntropyApp().run()


if __name__ == "__main__":
    main()
