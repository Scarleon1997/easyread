"""Claude Code / Codex CLI / Command Code 能选哪些模型，给设置页的下拉框用。

- Codex：读 ~/.codex/models_cache.json（Codex 自己从服务端拉的名单），只要 /model 里列出来的那些，按它的顺序；
  默认模型是 ~/.codex/config.toml 里的 model。
- Command Code：跑 cmdc --list-models，解析出名单（标 (default) 的是默认模型），缓存 10 分钟。
- Claude：opus / sonnet / haiku 是 Claude Code 的别名，会用它支持的最新版；
  实际是哪个版本记在 .models-seen.json（见 chat_models.remember）：每次回答时记一次；
  另外 probe_claude() 在服务启动时把还没记过的别名查一遍（Claude Code 升级后重查），名单里一开始就有版本号。
  不指定模型时 Claude Code 用哪个（“跟随默认”）：~/.claude/settings.json 里写了 model 就是它，没写就看探测时记下的 _default。
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import chat_models, engines
from .log import log

_probing = threading.Lock()
CLAUDE_ALIASES = [("opus", "Opus", "最强"), ("sonnet", "Sonnet", "快、省"), ("haiku", "Haiku", "最快最省")]


def codex() -> dict:
    """{"default": slug, "models": [{"id", "name", "desc"}]}；Codex 没装或没登录过就是空名单。"""
    out: list[dict] = []
    try:
        data = json.loads((Path.home() / ".codex" / "models_cache.json").read_text(encoding="utf-8"))
        ms = [m for m in data.get("models") or [] if m.get("visibility") == "list" and m.get("slug")]
        ms.sort(key=lambda m: m.get("priority", 99))
        out = [{"id": m["slug"], "name": m.get("display_name") or m["slug"], "desc": m.get("description") or ""} for m in ms]
    except (OSError, ValueError, AttributeError):
        pass
    return {"default": chat_models.codex_default_model(), "models": out}


def claude_default() -> str:
    """Claude Code 不指定模型时用的那个，显示名（Claude Opus 5.5）；不知道就空。"""
    try:
        model = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8")).get("model") or ""
    except (OSError, ValueError, AttributeError):
        model = ""
    actual = (chat_models.actual_of(model) or model) if model else chat_models.actual_of("_default")
    if actual in ("opus", "sonnet", "haiku", "fable"):  # 别名还没查到对应版本
        return "Claude " + actual.capitalize()
    return chat_models.pretty(actual) if actual else ""


def claude() -> dict:
    """{"default": "Claude Opus 5.5", "models": [{"id": "opus", "name": "Opus", "desc": "最强", "actual": "Claude Opus 5.5"}]}"""
    return {"default": claude_default(), "models": [{"id": a, "name": n, "desc": d, "actual": chat_models.pretty(chat_models.actual_of(a)) if chat_models.actual_of(a) else ""}
                       for a, n, d in CLAUDE_ALIASES]}


_CMDC_CACHE: dict = {"at": 0.0, "data": {"default": "", "models": []}}
_CMDC_LINE = re.compile(r"^(\S+)\s{2,}(\S.*)$")


def cmdc(c: dict | None = None) -> dict:
    """{"default": slug, "models": [{"id", "name", "desc"}]}：cmdc --list-models 的名单，缓存 10 分钟；没装就是空名单。"""
    if time.time() - _CMDC_CACHE["at"] < 600:
        return _CMDC_CACHE["data"]
    out: dict = {"default": "", "models": []}
    exe = engines.cmdc_path(c or {})
    if exe:
        try:
            r = subprocess.run([exe, "--list-models"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
                               encoding="utf-8", errors="replace", creationflags=engines._NO_WINDOW)
            for line in (r.stdout or "").splitlines():
                if line.startswith(("Pass the full id", "Docs:")):  # 名单后面的用法说明
                    break
                m = _CMDC_LINE.match(line)
                if not m or m.group(1) == "Available":  # “Available models  ·  N models” 标题行
                    continue
                desc = m.group(2)
                if desc.endswith("(default)"):
                    out["default"] = m.group(1)
                    desc = desc[:-len("(default)")].rstrip()
                out["models"].append({"id": m.group(1), "name": m.group(1), "desc": desc})
        except (OSError, subprocess.SubprocessError):  # 超时或跑不起来：当作没装，名单为空
            log.info("cmdc --list-models 失败", exc_info=True)
    _CMDC_CACHE.update(at=time.time(), data=out)
    return out


def probe_claude(c: dict, version: str) -> None:
    """让 Claude Code 报一下 opus / sonnet / haiku 现在各指向哪个版本。
    它启动时第一行（init 事件）就带着实际模型名，这时还没发请求；读到就结束进程，不花 token。"""
    exe = engines.claude_path(c)
    if not exe or (chat_models.actual_of("_claude_version") == version
                   and all(chat_models.actual_of(a) for a in [x for x, _, _ in CLAUDE_ALIASES] + ["_default"])):
        return
    if not _probing.acquire(blocking=False):  # 上一轮还没查完
        return
    try:
        _probe(exe, version)
    finally:
        _probing.release()


def _probe(exe: str, version: str) -> None:
    for alias in [a for a, _, _ in CLAUDE_ALIASES] + ["_default"]:  # _default：不带 --model，看它默认用哪个
        proc = engines._popen([exe, "-p", *([] if alias == "_default" else ["--model", alias]), "--output-format", "stream-json", "--verbose",
                               "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"],
                              Path(tempfile.gettempdir()))
        try:
            proc.stdin.write(".")
            proc.stdin.close()
            for _, line in zip(range(20), proc.stdout):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "system" and ev.get("subtype") == "init":
                    chat_models.remember(alias, ev.get("model", ""))
                    break
        except Exception:  # noqa: BLE001 —— 查不到就等第一次回答时再记
            log.info("查 Claude 别名 %s 失败", alias, exc_info=True)
        finally:
            proc.kill()
    chat_models.remember("_claude_version", version)


def listing(cfg: dict | None = None) -> dict:
    return {"claude": claude(), "codex": codex(), "cmdc": cmdc((cfg or {}).get("cmdc"))}
