#!/usr/bin/env python3
"""Executable readiness gates for Kerdon MSP. Standard library only.

Usage:
    python scripts/verify_gates.py                          run all active gates
    python scripts/verify_gates.py --self-test              prove static gates fail on broken input
    python scripts/verify_gates.py --live <Url> --expected-sha <SHA>
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_LINES = 800
EM_DASH = chr(0x2014)

BANNED_IMPORT_TOPS = frozenset(
    {
        "anthropic",
        "bedrock_agentcore",
        "boto3",
        "botocore",
        "google",
        "httpx",
        "openai",
        "random",
        "requests",
        "socket",
        "strands",
        "time",
        "urllib",
    }
)

_CLEAN_ROOM_FRAGMENTS = (
    ("hed", "no"),
    ("euro", "sos"),
    ("reflect", "ive"),
    ("proter", "gia"),
    ("ded", "die"),
    ("compl", "iant"),
    ("conform", "ity"),
    ("cock", "roach"),
    ("back", "blaze"),
    ("qw", "en"),
    ("neb", "ius"),
    ("xpr", "ize"),
    ("kag", "gle"),
)
CLEAN_ROOM_TERMS = tuple(a + b for a, b in _CLEAN_ROOM_FRAGMENTS)
HYPE_WORDS = ("leverage", "robust", "seamless", "comprehensive", "in today's world")

_AGENT_FILE_FRAGMENTS = (
    ("AGE", "NTS.md"),
    ("STA", "TE.md"),
    ("LO", "G.md"),
    ("TRA", "PS.md"),
    ("CLA", "UDE.md"),
    ("GEM", "INI.md"),
)
FORBIDDEN_AGENT_FILES = frozenset(a + b for a, b in _AGENT_FILE_FRAGMENTS)


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    detail: str


def _python_files(root: Path, *subdirs: str) -> list[Path]:
    files: list[Path] = []
    for subdir in subdirs:
        base = root / subdir
        if base.is_dir():
            files.extend(sorted(base.rglob("*.py")))
    return files


def _doc_files(root: Path) -> list[Path]:
    docs: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        docs.append(readme)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        docs.extend(sorted(docs_dir.rglob("*.md")))
    return docs


def check_file_sizes(root: Path) -> GateResult:
    offenders: list[str] = []
    source_files = list(_python_files(root, "src", "scripts", "tests"))
    fe_src = root / "frontend" / "src"
    if fe_src.is_dir():
        for ext in ("*.ts", "*.tsx"):
            source_files.extend(sorted(fe_src.rglob(ext)))
    for path in source_files:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > MAX_SOURCE_LINES:
            offenders.append(f"{path.relative_to(root)} has {lines} lines")
    if offenders:
        return GateResult("A1", "FAIL", "; ".join(offenders))
    return GateResult("A1", "PASS", f"every Python/TypeScript source file is <= {MAX_SOURCE_LINES} lines")


def check_domain_imports(root: Path) -> GateResult:
    offenders: list[str] = []
    domain_files = _python_files(root, "src/kerdon")
    if not domain_files:
        return GateResult("A5", "FAIL", "src/kerdon has no Python modules")
    for path in domain_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in BANNED_IMPORT_TOPS:
                    offenders.append(
                        f"{path.relative_to(root)}:{node.lineno} imports {name}"
                    )
    if offenders:
        return GateResult("A5", "FAIL", "; ".join(offenders))
    return GateResult("A5", "PASS", "src/kerdon imports zero cloud, LLM, network, or clock SDKs")


def check_agent_file_isolation(root: Path, tracked_override: list[str] | None = None) -> GateResult:
    offenders: list[str] = []
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        gi_text = gitignore.read_text(encoding="utf-8")
        for af in FORBIDDEN_AGENT_FILES:
            if af in gi_text:
                offenders.append(f".gitignore advertises workspace file {af}")
    if tracked_override is not None:
        tracked = tracked_override
    elif (root / ".git").exists():
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        tracked = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    else:
        tracked = []

    for rel in tracked:
        name = Path(rel).name
        if name in FORBIDDEN_AGENT_FILES:
            offenders.append(f"workspace file tracked in git: {rel}")
    if offenders:
        return GateResult("B1/B2-isolation", "FAIL", "; ".join(offenders))
    return GateResult(
        "B1/B2-isolation",
        "PASS",
        "zero workspace coordination files tracked or advertised in .gitignore",
    )


def check_clean_room(root: Path) -> GateResult:
    offenders: list[str] = []
    scanned = _python_files(root, "src", "tests") + _doc_files(root)
    scanned += [
        path
        for path in _python_files(root, "scripts")
        if path.name != Path(__file__).name
    ]
    for path in scanned:
        text = path.read_text(encoding="utf-8").lower()
        for term in CLEAN_ROOM_TERMS:
            if term in text:
                offenders.append(f"{path.relative_to(root)} contains banned term {term!r}")
                break
    if offenders:
        return GateResult("B4/G4", "FAIL", "; ".join(offenders))
    return GateResult(
        "B4/G4",
        "PASS",
        "zero customer, compliance-claim, or other-competition terms in code/docs",
    )


def check_style(root: Path) -> GateResult:
    offenders: list[str] = []
    for path in _python_files(root, "src", "tests") + _doc_files(root):
        text = path.read_text(encoding="utf-8")
        if EM_DASH in text:
            offenders.append(f"{path.relative_to(root)} contains an em dash")
            continue
        lowered = text.lower()
        for word in HYPE_WORDS:
            if word in lowered:
                offenders.append(f"{path.relative_to(root)} contains hype word {word!r}")
                break
    if offenders:
        return GateResult("F5", "FAIL", "; ".join(offenders))
    return GateResult("F5", "PASS", "zero em dashes and zero hype words across code and docs")


def check_role_separation(root: Path) -> GateResult:
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    try:
        import kerdon as kd
    except Exception as exc:  # pragma: no cover
        return GateResult("A7", "FAIL", f"kerdon does not import: {exc}")
    problems: list[str] = []
    if hasattr(kd.Reader, "execute"):
        problems.append("Reader exposes execute")
    if hasattr(kd.Evaluator, "execute"):
        problems.append("Evaluator exposes execute")
    if not hasattr(kd.Writer, "execute"):
        problems.append("Writer has no execute")
    if problems:
        return GateResult("A7", "FAIL", "; ".join(problems))
    return GateResult("A7", "PASS", "only Writer exposes execute; Reader/Evaluator cannot mutate")


def check_determinism_and_benchmark(root: Path) -> GateResult:
    for subdir in ("src", "scripts"):
        if str(root / subdir) not in sys.path:
            sys.path.insert(0, str(root / subdir))
    try:
        import kerdon as kd
        import run_erp_benchmark
    except Exception as exc:  # pragma: no cover
        return GateResult("C-smoke", "FAIL", f"import error: {exc}")

    if len(kd.GapRuleId) != 24:
        return GateResult("C-smoke", "FAIL", f"Expected 24 GapRuleId members, got {len(kd.GapRuleId)}")

    summary = run_erp_benchmark.run_benchmark()
    if summary["total_cases"] != 90 or summary["passed_cases"] != 90:
        return GateResult(
            "C-smoke",
            "FAIL",
            f"Benchmark {summary['passed_cases']}/{summary['total_cases']} passed",
        )
    return GateResult(
        "C-smoke",
        "PASS",
        f"24 completeness rules active; 90/90 benchmark cases pass in {summary['elapsed_ms']}ms",
    )


def check_aws_adapter_presence(root: Path) -> GateResult:
    adapter_dir = root / "src" / "kerdon_aws"
    if not adapter_dir.is_dir():
        return GateResult("D5-static", "NOT_YET_DUE", "src/kerdon_aws not created until Phase 2")
    texts = [
        path.read_text(encoding="utf-8")
        for path in _python_files(root, "src/kerdon_aws")
    ]
    joined = "\n".join(texts)
    missing = [
        needle
        for needle in ("from strands import Agent", "BedrockModel", "import boto3")
        if needle not in joined
    ]
    if missing:
        return GateResult("D5-static", "FAIL", "missing adapter sites: " + ", ".join(missing))
    return GateResult(
        "D5-static",
        "PASS",
        "Strands Agents SDK, BedrockModel, and boto3 call sites verified in src/kerdon_aws",
    )


def check_infra_isolation(root: Path) -> GateResult:
    template = root / "infra" / "template.yaml"
    if not template.is_file():
        return GateResult("INFRA", "NOT_YET_DUE", "infra/template.yaml not created until Phase 2")
    text = template.read_text(encoding="utf-8")
    problems: list[str] = []
    if "Default: kerdon-paypal" not in text:
        problems.append("PayPal edition default stack prefix is missing")
    if 'AllowedPattern: "^kerdon-paypal(-[a-z0-9]+)?$"' not in text:
        problems.append("StackPrefix must accept only the PayPal edition namespace")
    if "bedrock:InvokeModelWithResponseStream" not in text:
        problems.append("missing bedrock:InvokeModelWithResponseStream permission")
    if "AWS::BedrockAgentCore::Memory" not in text:
        problems.append("missing provisioned AWS::BedrockAgentCore::Memory resource")
    for term in CLEAN_ROOM_TERMS:
        if term in text.lower():
            problems.append(f"template contains banned term {term!r}")
            break
    if problems:
        return GateResult("INFRA", "FAIL", "; ".join(problems))
    return GateResult(
        "INFRA",
        "PASS",
        "SAM template enforces kerdon-paypal-* isolation and ConverseStream IAM",
    )


def check_docs_completeness(root: Path) -> GateResult:
    import re

    readme = root / "README.md"
    hld = root / "docs" / "HLD.md"
    devpost = root / "docs" / "DEVPOST.md"
    if not readme.is_file() or not hld.is_file() or not devpost.is_file():
        return GateResult(
            "DOCS", "NOT_YET_DUE", "README.md, docs/HLD.md, and docs/DEVPOST.md built in Phase 3"
        )
    r_txt = readme.read_text(encoding="utf-8")
    h_txt = hld.read_text(encoding="utf-8")
    problems: list[str] = []
    if (root / "docs" / "ANTIGRAVITY_HANDOFF.md").exists():
        problems.append("stale internal handoff doc docs/ANTIGRAVITY_HANDOFF.md present (F7)")
    if "actions/workflows/ci.yml/badge.svg" not in r_txt:
        problems.append("README missing GitHub Actions CI status badge (F1)")
    if "Sofia Marinou" not in r_txt:
        problems.append("README missing named persona Sofia Marinou (J1)")
    if r_txt.count("```mermaid") < 2:
        problems.append("README needs at least 2 Mermaid diagrams (F2)")
    if h_txt.count("```mermaid") < 2:
        problems.append("docs/HLD.md needs at least 2 Mermaid diagrams")
    for article in ("Article 10", "Article 13", "Article 14", "Article 15", "Article 50"):
        if article not in r_txt and article not in h_txt:
            problems.append(f"missing EU AI Act {article} row (B2)")
    for doc_path in _doc_files(root):
        d_txt = doc_path.read_text(encoding="utf-8")
        for match in re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|yaml|json|md))`", d_txt):
            if "*" in match or "<" in match or match in (".eml", ".msg", ".pdf"):
                continue
            target = (
                (doc_path.parent / match).resolve()
                if match.startswith("../")
                else root / match
            )
            if not target.exists():
                problems.append(f"{doc_path.relative_to(root)} references missing `{match}`")
    if problems:
        return GateResult("DOCS", "FAIL", "; ".join(problems))
    return GateResult("DOCS", "PASS", "README.md and docs/*.md satisfy J1-J5, B1-B4, F1-F9, and path integrity")


def deferred_gates() -> list[GateResult]:
    return [
        GateResult("D-1/G2", "NOT_YET_DUE", "run with --live <ApiUrl> --expected-sha <HEAD> after deploy"),
        GateResult("D2", "NOT_YET_DUE", "deploy-smoke-teardown pipeline runs in GitHub Actions CI"),
        GateResult("E1-E4", "NOT_YET_DUE", "video starts at 9/10 evaluable or deadline minus 3 days"),
        GateResult("O1", "USER_GATED", "join paypalaihackathon.devpost.com"),
        GateResult("O2", "USER_GATED", "public MIT repository upgradedev/kerdon-paypal-erp"),
        GateResult("O3", "USER_GATED", "public demo video upload and Devpost form Submit"),
    ]


def run_gates(root: Path) -> list[GateResult]:
    return [
        check_file_sizes(root),
        check_domain_imports(root),
        check_agent_file_isolation(root),
        check_clean_room(root),
        check_style(root),
        check_role_separation(root),
        check_determinism_and_benchmark(root),
        check_aws_adapter_presence(root),
        check_infra_isolation(root),
        check_docs_completeness(root),
    ]


def run_self_test() -> int:
    """Prove every static gate fails on a deliberately broken fixture tree."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad_dir = root / "src" / "kerdon"
        bad_dir.mkdir(parents=True)
        banned_term = CLEAN_ROOM_TERMS[0]
        big_padding = "\n".join(f"x_{i} = {i}" for i in range(MAX_SOURCE_LINES + 5))
        (bad_dir / "bad.py").write_text(
            "import boto3\n"
            f"# {banned_term} note with an em dash {EM_DASH} here\n"
            f"{big_padding}\n",
            encoding="utf-8",
        )
        agent_file = next(iter(FORBIDDEN_AGENT_FILES))
        (root / ".gitignore").write_text(f"{agent_file}\n", encoding="utf-8")
        results = {
            "A1": check_file_sizes(root),
            "A5": check_domain_imports(root),
            "B1/B2-isolation": check_agent_file_isolation(root, tracked_override=[agent_file]),
            "B4/G4": check_clean_room(root),
            "F5": check_style(root),
        }
    failures = [gid for gid, res in results.items() if res.status != "FAIL"]
    for gid, res in results.items():
        print(f"self-test {gid}: {res.status} ({res.detail})")
    if failures:
        print(f"SELF-TEST FAIL: gates that did not fail on bad input: {failures}")
        return 1
    print("SELF-TEST PASS: all 5 static gates failed on the broken fixture")
    return 0


def check_live_url(base: str, expected_sha: str = "") -> GateResult:
    import json as _json
    import urllib.error
    import urllib.request

    url = base.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
            status = resp.status
    except Exception as exc:
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else "n/a"
        return GateResult("D-1/G2", "FAIL", f"{url} unreachable ({code}: {exc})")
    if status != 200 or data.get("status") != "ok":
        return GateResult("D-1/G2", "FAIL", f"{url} answered {status}: {data}")
    if expected_sha and data.get("deployed_sha") != expected_sha:
        return GateResult(
            "D-1/G2",
            "FAIL",
            f"deployed {data.get('deployed_sha')} != expected {expected_sha}",
        )
    return GateResult(
        "D-1/G2", "PASS", f"{url} HTTP 200 at sha {str(data.get('deployed_sha'))[:12]}"
    )


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return run_self_test()
    live_url = ""
    expected_sha = ""
    if "--live" in argv:
        idx = argv.index("--live")
        live_url = argv[idx + 1]
    if "--expected-sha" in argv:
        idx = argv.index("--expected-sha")
        expected_sha = argv[idx + 1]

    results = run_gates(REPO_ROOT)
    if live_url:
        results.append(check_live_url(live_url, expected_sha))
    active_pass = [r for r in results if r.status == "PASS"]
    active_fail = [r for r in results if r.status == "FAIL"]
    not_yet = [r for r in results if r.status == "NOT_YET_DUE"]

    for r in results:
        print(f"[{r.status}] {r.gate_id}: {r.detail}")
    print("--- deferred / owner-gated ---")
    for r in deferred_gates():
        if live_url and r.gate_id == "D-1/G2":
            continue
        print(f"[{r.status}] {r.gate_id}: {r.detail}")
    print(
        f"Summary: {len(active_pass)} PASS, {len(active_fail)} FAIL, {len(not_yet)} NOT_YET_DUE"
    )
    return 1 if active_fail else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
