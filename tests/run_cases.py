#!/usr/bin/env python3
"""Rejoue une suite de cas (smoke ou malicious) contre une image TeX Live, dans le sandbox Kaxolax.

Chaque cas est un dossier contenant case.json et les fichiers du projet. Le conteneur est lancé
avec exactement les règles du sandbox de l'agent de compilation (voir SANDBOX_FLAGS).

    python3 tests/run_cases.py --image kaxolax-texlive:2026-medium tests/smoke tests/malicious
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path

MIB = 1024 * 1024
PDF_CAP_BYTES = 100 * MIB
LOG_CAP_BYTES = 10 * MIB
# Un fichier qui atteint cette taille est tronqué par le noyau (RLIMIT_FSIZE) : il dépasse donc
# forcément le plafond du PDF, ce qui permet de le détecter.
FSIZE_LIMIT_BYTES = PDF_CAP_BYTES + MIB

COMPILER_FLAGS = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}


def sandbox_flags(runtime: str) -> list[str]:
    """Règles non négociables du sandbox (identiques à celles de l'agent)."""
    return [
        "--runtime", runtime,
        "--network", "none",
        "--user", "1000:1000",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=512m",
        # Seul emplacement exécutable hors image : biber (PAR) y recopie son cache.
        "--tmpfs", "/tmp/biber:rw,exec,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=0700",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", "2g",
        "--memory-swap", "2g",
        "--cpus", "1",
        "--pids-limit", "256",
        "--ulimit", f"fsize={FSIZE_LIMIT_BYTES}",
        "--env", "HOME=/tmp",
    ]


@dataclass
class RunResult:
    status: str  # success | failure | timeout | error
    exit_code: int | None
    duration_ms: int
    output: str


@dataclass
class CaseResult:
    name: str
    failures: list[str] = field(default_factory=list)
    detail: str = ""


def run_in_sandbox(image: str, runtime: str, workdir: Path, command: list[str], timeout_s: float) -> RunResult:
    """Lance un conteneur neuf, attend sa fin ou le tue au bout du timeout, puis le supprime."""
    name = f"kaxolax-test-{uuid.uuid4().hex[:12]}"
    args = [
        "docker", "run", "--detach", "--name", name,
        *sandbox_flags(runtime),
        "--mount", f"type=bind,source={workdir},target=/compile",
        "--workdir", "/compile",
        image, *command,
    ]
    started = time.monotonic()
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
    timed_out = False
    exit_code: int | None = None
    try:
        waited = subprocess.run(["docker", "wait", name], check=True, capture_output=True, text=True, timeout=timeout_s)
        exit_code = int(waited.stdout.strip())
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(["docker", "kill", name], check=False, capture_output=True)
    duration_ms = int((time.monotonic() - started) * 1000)
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.OOMKilled}}", name], capture_output=True, text=True, check=False
    )
    logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, errors="replace", check=False)
    subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)

    if timed_out:
        status = "timeout"
    elif inspect.stdout.strip() == "true":
        status = "error"
    else:
        status = "success" if exit_code == 0 else "failure"
    return RunResult(status, exit_code, duration_ms, logs.stdout + logs.stderr)


def compile_status(run: RunResult, workdir: Path) -> str:
    """Statut final, avec les plafonds de sortie : au-delà, la compilation passe en erreur."""
    if run.status in ("timeout", "error"):
        return run.status
    pdf, log = workdir / "output.pdf", workdir / "output.log"
    if pdf.exists() and pdf.stat().st_size > PDF_CAP_BYTES:
        return "error"
    if log.exists() and log.stat().st_size > LOG_CAP_BYTES:
        return "error"
    if any(path.is_file() and path.stat().st_size >= FSIZE_LIMIT_BYTES for path in workdir.rglob("*")):
        return "error"
    if run.status == "success" and not pdf.exists():
        return "failure"
    return run.status


def readable_contents(path: Path) -> bytes:
    """Contenu d'un fichier, avec les flux PDF décompressés et les .gz décompressés."""
    data = path.read_bytes()
    if path.suffix == ".gz":
        try:
            return gzip.decompress(data)
        except OSError:
            return data
    if path.suffix == ".pdf":
        chunks = [data]
        for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
            try:
                chunks.append(zlib.decompress(match.group(1)))
            except zlib.error:
                pass
        return b"\n".join(chunks)
    return data


def leaks(root: Path, markers: list[str], extra: str) -> list[str]:
    found = []
    for marker in markers:
        needle = marker.encode()
        if marker in extra:
            found.append(f"'{marker}' found in container output")
        for path in root.rglob("*"):
            if path.is_file() and needle in readable_contents(path):
                found.append(f"'{marker}' found in {path.relative_to(root)}")
    return found


def run_case(case_dir: Path, image: str, runtime: str) -> CaseResult:
    spec = json.loads((case_dir / "case.json").read_text())
    result = CaseResult(case_dir.name)
    expect = spec.get("expect", {})
    timeout_s = spec.get("timeoutSeconds", 60)

    with tempfile.TemporaryDirectory(prefix=f"kaxolax-{case_dir.name}-") as tmp:
        parent = Path(tmp)
        parent.chmod(0o755)
        workdir = parent / "work"
        shutil.copytree(case_dir, workdir, ignore=shutil.ignore_patterns("case.json"))
        # Fichier témoin sur l'hôte, hors du répertoire de travail : un cas peut tenter de le lire
        # par son chemin absolu (@@HOST_CANARY@@) ; son contenu ne doit jamais apparaître.
        canary = parent / "host-canary.txt"
        canary_content = f"KX-HOST-CANARY-{uuid.uuid4().hex}"
        canary.write_text(canary_content + "\n")
        for path in workdir.rglob("*.tex"):
            path.write_text(path.read_text().replace("@@HOST_CANARY@@", str(canary)))
        for path in [workdir, *workdir.rglob("*")]:
            path.chmod(0o777 if path.is_dir() else 0o666)
        no_leak = [marker.replace("@@HOST_CANARY_CONTENT@@", canary_content) for marker in expect.get("noLeak", [])]

        if "command" in spec:
            run = run_in_sandbox(image, runtime, workdir, spec["command"], timeout_s)
            status = run.status
        else:
            compiler = spec["compiler"]
            main = spec.get("main", "main.tex")
            # -norc : latexmk n'exécute jamais un latexmkrc (du Perl) fourni par le projet.
            command = [
                "latexmk", "-norc", "-cd", "-f", "-jobname=output", "-synctex=1",
                "-interaction=batchmode", "-file-line-error", COMPILER_FLAGS[compiler], main,
            ]
            run = run_in_sandbox(image, runtime, workdir, command, timeout_s)
            status = compile_status(run, workdir)
        result.detail = f"status={status} exit={run.exit_code} {run.duration_ms} ms"

        allowed = expect.get("status", ["success"])
        if status not in allowed:
            result.failures.append(f"status {status} not in {allowed}")
        if "exitCode" in expect and run.exit_code != expect["exitCode"]:
            result.failures.append(f"exit code {run.exit_code} != {expect['exitCode']}")
        for text in expect.get("outputContains", []):
            if text not in run.output:
                result.failures.append(f"container output lacks {text!r}")
        log_path = workdir / "output.log"
        log = log_path.read_text(errors="replace") if log_path.exists() else ""
        for text in expect.get("logContains", []):
            if text not in log:
                result.failures.append(f"output.log lacks {text!r}")
        for text in expect.get("logLacks", []):
            if text in log:
                result.failures.append(f"output.log contains {text!r}")
        for relative in expect.get("files", []):
            if not (workdir / relative).is_file():
                result.failures.append(f"missing file {relative}")
        for relative in expect.get("absentFiles", []):
            if (workdir / relative).exists():
                result.failures.append(f"unexpected file {relative}")
        # Rien ne doit apparaître hors du répertoire de travail.
        escaped = [p.name for p in parent.iterdir() if p.name not in ("work", canary.name)]
        if escaped:
            result.failures.append(f"files written outside the workdir: {escaped}")
        result.failures.extend(leaks(workdir, no_leak, run.output))

        for check in spec.get("synctex", []):
            synctex = run_in_sandbox(image, runtime, workdir, ["synctex", *check["args"]], 30)
            for text in check["outputContains"]:
                if text not in synctex.output:
                    result.failures.append(f"synctex {' '.join(check['args'])}: output lacks {text!r}")

        if result.failures:
            result.failures.append("container output tail:\n" + "\n".join(run.output.splitlines()[-15:]))
            if log:
                result.failures.append("output.log tail:\n" + "\n".join(log.splitlines()[-15:]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True)
    parser.add_argument("--runtime", default="runc", help="runc en local, runsc (gVisor) sur les workers")
    parser.add_argument("--only", help="ne lance que les cas dont le nom contient cette chaîne")
    parser.add_argument("suites", nargs="+", type=Path)
    args = parser.parse_args()

    cases = sorted(d for suite in args.suites for d in suite.iterdir() if (d / "case.json").exists())
    if args.only:
        cases = [case for case in cases if args.only in case.name]
    failed = 0
    for case in cases:
        result = run_case(case, args.image, args.runtime)
        label = f"{case.parent.name}/{result.name}"
        if result.failures:
            failed += 1
            print(f"not ok  {label}  ({result.detail})")
            for failure in result.failures:
                print("        " + failure.replace("\n", "\n        "))
        else:
            print(f"ok      {label}  ({result.detail})")
    print(f"\n{len(cases) - failed}/{len(cases)} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
