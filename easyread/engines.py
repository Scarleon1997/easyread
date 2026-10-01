"""翻译 / 回答用的模型后端。

- claude：本机的 Claude Code 无头模式（claude -p），用你已有的登录，不需要 Key；能自己读原页图核对公式和表格。
- codex：本机的 Codex CLI（codex exec），同样用已有登录，原页图作为附件发过去。
- cmdc：本机的 Command Code 无头模式（cmdc -p），用你已有的登录，不需要 Key；和 claude 一样自己读原页图。
- openai：任何 OpenAI 兼容接口（Ollama、智谱、硅基流动、DeepSeek、Gemini……），在设置里填地址、模型和 Key；
  Chat Completions 和 Responses 两种格式都行（见 openai_api.py）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from . import netcheck


class EngineError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


ENGINE_NAMES = {"claude": "Claude Code", "codex": "Codex CLI", "cmdc": "Command Code", "openai": "API", "none": "不翻译"}


def run(cfg: dict, prompt: str, cwd: Path, images: list[Path] | None = None, cancel: threading.Event | None = None) -> str:
    bad = netcheck.problem(cfg)
    if bad:
        raise EngineError(bad)
    try:
        return _run(cfg, prompt, cwd, images, cancel)
    except EngineError as e:
        raise EngineError(netcheck.explain(cfg, str(e))) from None


def _run(cfg: dict, prompt: str, cwd: Path, images: list[Path] | None, cancel: threading.Event | None) -> str:
    engine = cfg.get("engine")
    if engine == "claude":
        return run_claude(cfg["claude"], prompt, cwd, cancel)
    if engine == "codex":
        return run_codex(cfg["codex"], prompt, cwd, images or [], cancel)
    if engine == "cmdc":
        return run_cmdc(cfg["cmdc"], prompt, cwd, cancel)
    if engine == "openai":
        return run_openai(cfg["openai"], prompt, images or [], cancel)
    raise EngineError("没有配置翻译引擎（设置 → 翻译引擎）")


def image_mode(cfg: dict) -> str:
    """提示词里怎么说原页图：claude / cmdc 自己用 Read 读；codex 和能看图的接口作为附件；其余没有图。"""
    engine = cfg.get("engine")
    if engine in ("claude", "cmdc"):
        return "claude"
    if engine == "codex" or (engine == "openai" and cfg["openai"].get("vision")):
        return "attached"
    return "text"


def who(cfg: dict) -> str:
    engine = cfg.get("engine")
    if engine == "openai":
        return cfg["openai"].get("model") or "API"
    return {"claude": "claude", "codex": "codex", "cmdc": "cmdc"}.get(engine, "")


# ---------- 本机 CLI ----------
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
_CLAUDE_ARGS = ["--output-format", "json", "--allowedTools", "Read", "--strict-mcp-config",
                "--disable-slash-commands", "--no-session-persistence"]


def claude_path(c: dict) -> str | None:
    return shutil.which(c.get("command") or "claude")


def codex_path(c: dict) -> str | None:
    return shutil.which(c.get("command") or "codex")


def cmdc_path(c: dict) -> str | None:
    return shutil.which(c.get("command") or "cmdc")


def _popen(args: list[str], cwd: Path):
    return subprocess.Popen(args, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
                            env=netcheck.proxy_env())


def run_claude(c: dict, prompt: str, cwd: Path, cancel=None) -> str:
    exe = claude_path(c)
    if not exe:
        raise EngineError(f"找不到 Claude Code 命令：{c.get('command') or 'claude'}（先装好并登录 Claude Code）")
    args = [exe, "-p", *_CLAUDE_ARGS]
    if c.get("model"):
        args += ["--model", c["model"]]
    args += list(c.get("extra_args") or [])
    out = _communicate(_popen(args, cwd), prompt, int(c.get("timeout") or 1200), cancel)
    try:
        res = json.loads(out)
    except json.JSONDecodeError:
        raise EngineError(f"Claude Code 输出不是 JSON：{out[:300]}")
    if res.get("is_error") or res.get("subtype", "success") != "success":
        msg = str(res.get("result") or res.get("terminal_reason") or res.get("subtype"))
        if "limit" in msg.lower():
            msg += "（用量到上限了，等额度恢复后点“重试”，或在设置里换个引擎）"
        raise EngineError(f"Claude Code 出错：{msg}")
    return res.get("result") or ""


def run_codex(c: dict, prompt: str, cwd: Path, images: list[Path], cancel=None) -> str:
    exe = codex_path(c)
    if not exe:
        raise EngineError(f"找不到 Codex 命令：{c.get('command') or 'codex'}（先装好并登录 Codex CLI）")
    fd, last = tempfile.mkstemp(suffix=".txt", prefix="easyread-codex-")
    os.close(fd)
    args = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral", "--color", "never", "-o", last]
    if c.get("model"):
        args += ["--model", c["model"]]
    for img in images:
        args += ["-i", str(img)]
    args += list(c.get("extra_args") or []) + ["-"]
    try:
        out = _communicate(_popen(args, cwd), prompt, int(c.get("timeout") or 1200), cancel)
        text = Path(last).read_text(encoding="utf-8", errors="replace").strip()
    finally:
        Path(last).unlink(missing_ok=True)
    if not text:
        raise EngineError("Codex 没有给出结果：" + (out or "")[-300:])
    return text


def run_cmdc(c: dict, prompt: str, cwd: Path, cancel=None) -> str:
    exe = cmdc_path(c)
    if not exe:
        raise EngineError(f"找不到 Command Code 命令：{c.get('command') or 'cmdc'}（先装好并登录 Command Code）")
    args = [exe, "-p", "--output-format", "json", "--skip-onboarding"]
    if c.get("model"):
        args += ["--model", c["model"]]
    args += list(c.get("extra_args") or [])
    out = _communicate(_popen(args, cwd), prompt, int(c.get("timeout") or 1200), cancel)
    res = None
    for line in out.splitlines():  # NDJSON 事件流，最后一行才是结果
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "result":
                res = obj
    if res is None:
        raise EngineError(f"Command Code 输出里没有结果行：{out[:300]}")
    if res.get("subtype") != "success":
        msg = str(res.get("error") or res.get("subtype") or "")
        if "max_turns" in (res.get("subtype") or "") or "turn" in msg.lower():
            msg += "（对话轮数到上限了，在 config.json 的 cmdc.extra_args 里加 --max-turns 500 再试）"
        elif "credit" in msg.lower() or "limit" in msg.lower():
            msg += "（额度用完了，等恢复后点“重试”，或在设置里换个引擎）"
        raise EngineError(f"Command Code 出错：{msg}")
    return res.get("finalText") or ""


def _communicate(proc, stdin_text: str, timeout: int, cancel) -> str:
    result = {}

    def talk():
        result["out"], result["err"] = proc.communicate(stdin_text)

    t = threading.Thread(target=talk, daemon=True)
    t.start()
    waited = 0.0
    while t.is_alive():
        t.join(0.5)
        waited += 0.5
        if cancel is not None and cancel.is_set():
            proc.kill()
            raise Cancelled()
        if waited > timeout:
            proc.kill()
            raise EngineError(f"超过 {timeout} 秒没有结果")
    if proc.returncode not in (0, None) and not result.get("out"):
        raise EngineError((result.get("err") or "")[-500:] or f"退出码 {proc.returncode}")
    return result.get("out", "")


# ---------- OpenAI 兼容接口 ----------
def run_openai(c: dict, prompt: str, images: list[Path], cancel=None) -> str:
    from . import openai_api  # 它要用本文件的 EngineError，放这里免得循环导入
    return openai_api.complete(c, prompt, images, cancel)


def parse_json(text: str):
    """从模型输出里取出 JSON（容忍 ```json 围栏和前后废话）。"""
    t = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()  # 推理模型（deepseek-r1、qwen3）先输出的思考过程
    # 先取最外层的 { … }：译文里可能本身带代码块（论文附录的 PyTorch 代码），按 ``` 围栏切会切到半截
    bodies = []
    for s in (t, *(m.group(1).strip() for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", t))):
        start = min([i for i in (s.find("{"), s.find("[")) if i >= 0], default=-1)
        if start >= 0:
            bodies.append(s[start:max(s.rfind("}"), s.rfind("]")) + 1])
    if not bodies:
        raise EngineError("模型输出里没有 JSON：" + text[:200])
    first = None
    for body in bodies:
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            first = first or e
    body = bodies[0]
    # 常见毛病：TeX 反斜杠没写成两个（\alpha、\sum）、字符串里有原样换行
    fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", body)
    try:
        return json.loads(fixed, strict=False)
    except json.JSONDecodeError:
        raise EngineError(f"模型输出的 JSON 格式有错（{first}），会自动重试")


def _version(exe: str) -> str:
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30,
                              creationflags=_NO_WINDOW).stdout.strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return ""


def test(cfg: dict) -> dict:
    """设置页“测试”按钮：真的让模型回一句，确认引擎能用。"""
    engine = cfg.get("engine")
    if engine in ("claude", "codex", "cmdc"):
        exe = {"claude": claude_path, "codex": codex_path, "cmdc": cmdc_path}[engine](cfg[engine])
        if not exe:
            return {"ok": False, "message": f"找不到 {engine} 命令，先安装并登录"}
    if engine == "none":
        return {"ok": True, "message": "未启用自动翻译"}
    try:
        out = run(cfg, '只回复 JSON，不要别的文字：{"ok": true}', Path(tempfile.gettempdir()), None, None)
        parse_json(out)
        return {"ok": True, "message": "可以用：" + out.strip()[:40]}
    except (EngineError, Cancelled) as e:
        return {"ok": False, "message": str(e)[:300]}
