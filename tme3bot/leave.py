from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from tme3bot.tdl import SubprocessRunner, TDLCommandError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeaveResult:
    succeeded: list[str]
    failed: dict[str, str]


class LeaveService:
    def __init__(self, config, runner: SubprocessRunner | None = None) -> None:
        self.config = config
        self.runner = runner or SubprocessRunner()

    def leave(self, chat_refs: list[str]) -> LeaveResult:
        command = [
            self.config.leave_helper_binary,
            "--storage", str(self.config.tdl_export_storage / "data"),
            "--namespace", self.config.tdl_export_namespace,
        ]
        for chat_ref in chat_refs:
            command.extend(("--chat", chat_ref))
        if self.config.tdl_export_user != "root":
            command = ["runuser", "-u", self.config.tdl_export_user, "--"] + command
        env = dict(os.environ)
        env["HOME"] = str(self.config.tdl_export_home)
        env["TDL_FORCE_PTY"] = "0"
        result = self.runner.run(command, env=env, log_prefix="tdl-leave")
        if result.returncode != 0:
            raise TDLCommandError(command, result.returncode, result.stdout, result.stderr)
        succeeded: list[str] = []
        failed: dict[str, str] = {}
        for raw_line in result.stdout.splitlines():
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            chat_ref = str(item.get("chat_ref", ""))
            if item.get("ok"):
                succeeded.append(chat_ref)
            elif chat_ref:
                failed[chat_ref] = str(item.get("error") or "unknown error")
        for chat_ref in chat_refs:
            if chat_ref not in succeeded and chat_ref not in failed:
                failed[chat_ref] = "helper tidak mengembalikan hasil"
        return LeaveResult(succeeded, failed)
