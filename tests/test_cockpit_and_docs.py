"""Accessibility (H1-H3, Volcan/Aletheia) and cross-surface consistency (G1) tests."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import kerdon as kd  # noqa: E402
import kerdon_aws as kaws  # noqa: E402

J5_SENTENCE = (
    "Kerdon turns PayPal checkouts, subscriptions, disputes, and bills into a balanced "
    "double-entry ledger, seller commissions, and Four-Eyes governed payouts."
)


class _A11yParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_lang: str = ""
        self.has_main: bool = False
        self.has_header: bool = False
        self.labels_for: set[str] = set()
        self.form_control_ids: list[str] = []
        self.disabled_buttons: list[dict[str, str]] = []
        self.element_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        if "id" in attr_map and attr_map["id"]:
            self.element_ids.add(attr_map["id"])
        if tag == "html":
            self.html_lang = attr_map.get("lang", "")
        elif tag == "main":
            self.has_main = True
        elif tag == "header":
            self.has_header = True
        elif tag == "label" and attr_map.get("for"):
            self.labels_for.add(attr_map["for"])
        elif tag in ("input", "select", "textarea"):
            self.form_control_ids.append(attr_map.get("id", ""))
        elif tag == "button" and any(k == "disabled" for k, _ in attrs):
            self.disabled_buttons.append(attr_map)


class TestCockpitAccessibilityAndDocsConsistency(unittest.TestCase):
    def test_cockpit_a11y_labels_disabled_reasons_and_braille_receipt(self) -> None:
        ws = kd.build_default_msp_workspace()
        html_doc = kaws.render_workspace(ws)
        self.assertTrue(html_doc.lower().startswith("<!doctype html>"))
        self.assertIn(J5_SENTENCE, html_doc)
        self.assertIn("ASCII Braille Merkle verification token", html_doc)
        self.assertIn("Aletheia Merkle receipt sealed", html_doc)

        parser = _A11yParser()
        parser.feed(html_doc)
        self.assertEqual(parser.html_lang, "en")
        self.assertTrue(parser.has_main)
        self.assertTrue(parser.has_header)
        self.assertGreaterEqual(len(parser.form_control_ids), 4)
        for ctrl_id in parser.form_control_ids:
            self.assertTrue(ctrl_id, "Every form control must have an id")
            self.assertIn(
                ctrl_id,
                parser.labels_for,
                f"Form control #{ctrl_id} is missing an explicit <label for='{ctrl_id}'>",
            )

        # H2/H3: Every disabled button has an aria-describedby pointing to an existing reason element
        self.assertGreaterEqual(len(parser.disabled_buttons), 1)
        for btn in parser.disabled_buttons:
            desc_id = btn.get("aria-describedby", "")
            self.assertTrue(desc_id, "Disabled button must carry aria-describedby")
            self.assertIn(desc_id, parser.element_ids)

    def test_j5_sentence_and_file_references_across_docs_g1(self) -> None:
        words = J5_SENTENCE.split()
        self.assertLessEqual(len(words), 25)
        self.assertNotIn(chr(0x2014), J5_SENTENCE)

        for rel_doc in (
            "README.md",
            "docs/HLD.md",
            "docs/DEVPOST.md",
            "docs/GTM_PLAYBOOK.md",
            "docs/ERP_WORKSPACE.md",
        ):
            doc_path = REPO_ROOT / rel_doc
            self.assertTrue(doc_path.is_file(), f"Missing {rel_doc}")
            text = doc_path.read_text(encoding="utf-8")
            self.assertIn(J5_SENTENCE, text, f"J5 sentence missing in {rel_doc}")
            self.assertIn("Sofia Marinou", text, f"Persona J1 missing in {rel_doc}")

            # Verify every backticked repo path resolves on disk (Persona 08 K3 Half C)
            for match in re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|yaml|json|md))`", text):
                if "*" in match or "<" in match or match in (".eml", ".msg", ".pdf"):
                    continue
                target = (
                    (doc_path.parent / match).resolve()
                    if match.startswith("../")
                    else REPO_ROOT / match
                )
                self.assertTrue(
                    target.exists(),
                    f"{rel_doc} references non-existent path `{match}`",
                )

    def test_all_10_readiness_gates_and_self_test_pass(self) -> None:
        if str(REPO_ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import verify_gates

        results = verify_gates.run_gates(REPO_ROOT)
        failures = [r for r in results if r.status != "PASS"]
        self.assertEqual(failures, [], f"Non-PASS gates: {failures}")
        self.assertEqual(len(results), 10)
        self.assertEqual(verify_gates.run_self_test(), 0)


if __name__ == "__main__":
    unittest.main()
