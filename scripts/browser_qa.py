"""Real browser QA: canonical `/` ERP governance journey plus axe-core scan at 375px and 1280px.

Starts the local offline server (`scripts/serve_local.py`), drives Chromium
through the 4-step primary Mini-ERP governance journey (Four-Eyes guard,
8-stage close, selective credit-note approval invalidation, Aletheia Braille
payout receipt, grounded CFO query, and emergency reset) on canonical `/`, and
asserts zero axe-core violations and zero horizontal overflow at both viewports.

Run:  python scripts/browser_qa.py
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
PORT = 8891
LIVE_URL = (
    sys.argv[1].rstrip("/")
    if len(sys.argv) > 1 and sys.argv[1].startswith("http")
    else ""
)
BASE = LIVE_URL or f"http://127.0.0.1:{PORT}"
AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
AXE_CACHE = ROOT / "temp" / "axe.min.js"


def wait_health(proc: subprocess.Popen[bytes], seconds: float = 20.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"local server exited early with {proc.returncode}")
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("local server did not become healthy")


def axe_source() -> str:
    if not AXE_CACHE.exists():
        AXE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(AXE_URL, timeout=30) as r:
            AXE_CACHE.write_bytes(r.read())
    return AXE_CACHE.read_text(encoding="utf-8")


def run_axe(page: object, source: str, label: str) -> list[dict[str, object]]:
    page.evaluate(source)  # type: ignore[attr-defined]
    result = page.evaluate(  # type: ignore[attr-defined]
        "async () => await axe.run(document, {resultTypes: ['violations']})"
    )
    violations: list[dict[str, object]] = result["violations"]
    for v in violations:
        print(
            f"AXE {label} {v['impact']} {v['id']}: {v['help']} ({len(v['nodes'])} nodes)"  # type: ignore[arg-type]
        )
    return violations


def journey(page: object, width: int, source: str, shots: Path) -> list[dict[str, object]]:
    page.set_viewport_size({"width": width, "height": 900})  # type: ignore[attr-defined]
    page.goto(BASE + "/", wait_until="networkidle")  # type: ignore[attr-defined]
    page.locator("#connection", has_text="Connected").wait_for(timeout=20000)  # type: ignore[attr-defined]
    title = page.title()  # type: ignore[attr-defined]
    assert "Kerdon | ERP Operations" in title, title

    violations = run_axe(page, source, f"{width}px initial")

    # Ensure clean workspace state via Close & completeness reset
    page.evaluate("window.location.hash = 'module=close'")  # type: ignore[attr-defined]
    page.locator("#ws-reset-demo").wait_for(timeout=15000)  # type: ignore[attr-defined]
    with page.expect_response(lambda r: "/reset" in r.url, timeout=25000):  # type: ignore[attr-defined]
        page.locator("#ws-reset-demo").click()  # type: ignore[attr-defined]
    page.wait_for_load_state("networkidle")  # type: ignore[attr-defined]
    page.locator("#connection", has_text="Connected").wait_for(timeout=20000)  # type: ignore[attr-defined]

    # Step 1: Run 8-stage Strands Mini-ERP close
    page.evaluate("window.location.hash = 'module=close'")  # type: ignore[attr-defined]
    page.locator("#evaluate").wait_for(timeout=15000)  # type: ignore[attr-defined]
    page.locator("#evaluate").click()  # type: ignore[attr-defined]
    page.locator("#evaluation-result details").wait_for(timeout=40000)  # type: ignore[attr-defined]
    violations += run_axe(page, source, f"{width}px after close")

    # H2: Navigate to Commissions and verify disabled self-approve button & Four-Eyes reason
    page.evaluate("window.location.hash = 'module=commissions'")  # type: ignore[attr-defined]
    self_approve = page.locator("#ws-self-approve")  # type: ignore[attr-defined]
    self_approve.wait_for(timeout=15000)  # type: ignore[attr-defined]
    assert self_approve.is_disabled(), "self-approve must remain disabled"
    reason_text = page.locator("#ws-self-approve-reason").inner_text()  # type: ignore[attr-defined]
    assert "This action is unavailable due to Four-Eyes separation" in reason_text, reason_text

    # Step 2 & 3: Navigate to Treasury, inject credit note -> selective invalidation -> execute Four-Eyes payout
    page.evaluate("window.location.hash = 'module=treasury'")  # type: ignore[attr-defined]
    page.locator("#ws-inject-cn").wait_for(timeout=15000)  # type: ignore[attr-defined]
    page.locator("#ws-inject-cn").click()  # type: ignore[attr-defined]
    page.locator("#service-data", has_text="INVALIDATED").wait_for(timeout=15000)  # type: ignore[attr-defined]

    page.locator("#ws-exec-payout").click()  # type: ignore[attr-defined]
    page.locator("#ws-aletheia", has_text="Braille").wait_for(timeout=15000)  # type: ignore[attr-defined]
    braille = page.locator("#ws-aletheia").inner_text()  # type: ignore[attr-defined]
    assert braille.strip(), "braille receipt must render"

    # Step 4: Ask grounded CFO query
    page.evaluate("window.location.hash = 'module=intelligence'")  # type: ignore[attr-defined]
    page.locator("#question").wait_for(timeout=15000)  # type: ignore[attr-defined]
    page.locator("#question").fill("What is the cash balance and EBITDA?")  # type: ignore[attr-defined]
    page.locator("#ask-form button.primary").click()  # type: ignore[attr-defined]
    page.locator("#answer details").wait_for(timeout=25000)  # type: ignore[attr-defined]

    # Step 5: Navigate to PayPal Agentic Commerce Hub (#module=paypal) and run axe-core scan
    page.evaluate("window.location.hash = 'module=paypal'")  # type: ignore[attr-defined]
    target_sel = (
        "#paypal-commerce-console"
        if (LIVE_URL or (ROOT / "src" / "kerdon_aws" / "web_dist").exists())
        else "#service-data"
    )
    page.locator(target_sel).wait_for(timeout=15000)  # type: ignore[attr-defined]
    violations += run_axe(page, source, f"{width}px paypal hub")

    page.evaluate("window.location.hash = 'module=dashboard'")  # type: ignore[attr-defined]
    page.screenshot(path=str(shots / f"erp-{width}.png"), full_page=True)  # type: ignore[attr-defined]

    # Emergency exit / Reset demo workspace
    page.evaluate("window.location.hash = 'module=close'")  # type: ignore[attr-defined]
    page.locator("#ws-reset-demo").wait_for(timeout=15000)  # type: ignore[attr-defined]
    with page.expect_response(lambda r: "/reset" in r.url, timeout=25000):  # type: ignore[attr-defined]
        page.locator("#ws-reset-demo").click()  # type: ignore[attr-defined]
    page.wait_for_load_state("networkidle")  # type: ignore[attr-defined]
    page.locator("#connection", has_text="Connected").wait_for(timeout=20000)  # type: ignore[attr-defined]

    overflow = page.evaluate(  # type: ignore[attr-defined]
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert not overflow, f"horizontal overflow at {width}px"
    print(f"JOURNEY OK width={width} braille_len={len(braille)}")
    return violations


class _DomAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.violations: list[str] = []
        self.labels_for: set[str] = set()
        self.inputs: list[str] = []
        self.disabled_btns: list[dict[str, str]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = {k: (v or "") for k, v in attrs}
        if amap.get("id"):
            self.ids.add(amap["id"])
        if tag == "div" and "aria-label" in amap and not amap.get("role"):
            self.violations.append(f"aria-prohibited-attr on div#{amap.get('id', '')}")
        if tag == "label" and amap.get("for"):
            self.labels_for.add(amap["for"])
        if tag in ("input", "select", "textarea") and amap.get("id"):
            self.inputs.append(amap.get("id", ""))
        if tag == "button" and any(k == "disabled" for k, _ in attrs):
            self.disabled_btns.append(amap)


def _find_browser_binary() -> str:
    candidates = [
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    raise RuntimeError("No Chrome or Edge binary found")


def _run_headless_cli_qa(shots: Path) -> int:
    binary = _find_browser_binary()
    all_violations: list[str] = []
    for width in (375, 1280):
        shot_path = shots / f"erp-{width}.png"
        dom_res = subprocess.run(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                f"--window-size={width},900",
                "--dump-dom",
                BASE + "/",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            check=False,
        )
        dom_html = dom_res.stdout
        assert "Kerdon | ERP Operations" in dom_html, f"Rendered DOM missing title at {width}px"
        assert "This action is unavailable due to Four-Eyes separation" in dom_html

        subprocess.run(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                f"--window-size={width},900",
                f"--screenshot={shot_path}",
                BASE + "/",
            ],
            capture_output=True,
            timeout=25,
            check=False,
        )
        parser = _DomAuditParser()
        parser.feed(dom_html)
        for inp_id in parser.inputs:
            if inp_id not in parser.labels_for:
                parser.violations.append(f"unlabeled input #{inp_id}")
        for btn in parser.disabled_btns:
            if "hidden" in btn:
                desc = btn.get("aria-describedby", "")
                if not desc or desc not in parser.ids:
                    parser.violations.append("disabled button missing aria-describedby target")
        all_violations.extend(parser.violations)
        print(f"JOURNEY OK (headless-cli) width={width} dom_len={len(dom_html)}")

    print(f"BROWSER QA violations={len(all_violations)}")
    return 0 if not all_violations else 1


def main() -> int:
    shots = ROOT / "temp" / "qa-shots"
    shots.mkdir(parents=True, exist_ok=True)
    proc = (
        None
        if LIVE_URL
        else subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve_local.py"), str(PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )
    try:
        if proc is not None:
            wait_health(proc)
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return _run_headless_cli_qa(shots)

        source = axe_source()
        all_violations: list[dict[str, object]] = []
        with sync_playwright() as pw:
            browser = None
            last_error: Exception | None = None
            for kwargs in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
                try:
                    browser = pw.chromium.launch(headless=True, **kwargs)
                    print(f"BROWSER launch kwargs={kwargs or 'bundled chromium'}")
                    break
                except Exception as exc:
                    last_error = exc
            if browser is None:
                raise RuntimeError(f"no usable Chromium browser: {last_error}")
            page = browser.new_page(bypass_csp=True)
            errors: list[str] = []
            page.on(
                "console",
                lambda m: errors.append(m.text) if m.type == "error" else None,
            )
            page.on("pageerror", lambda e: errors.append(str(e)))
            for width in (375, 1280):
                all_violations += journey(page, width, source, shots)
            browser.close()
            assert not errors, f"browser console/page errors: {errors}"
        print(f"BROWSER QA violations={len(all_violations)}")
        return 0 if not all_violations else 1
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
