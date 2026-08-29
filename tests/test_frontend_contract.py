import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]


class _IconLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "icon":
            self.icons.append(attributes)


class FrontendContractTests(unittest.TestCase):
    def test_html_has_semantic_monitor_regions_and_only_real_controls(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        for required in (
            "<header", "<main", "<section", "<footer", 'id="refresh-button"',
            'id="auto-refresh"', 'role="switch"', 'id="active-list"',
            'id="recent-list"', 'aria-live="polite"', "Agent Monitor",
            "Codex + Hermes", 'id="active-loading"', 'id="recent-loading"',
            'data-mobile-layout="cards"',
        ):
            self.assertIn(required, html)
        lowered = html.lower()
        for forbidden in (">stop<", ">kill<", ">resume<", "gradient", "indigo"):
            self.assertNotIn(forbidden, lowered)

    def test_html_references_a_self_contained_svg_favicon(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        parser = _IconLinkParser()
        parser.feed(html)

        self.assertNotIn("data:,", html)
        self.assertEqual(len(parser.icons), 1)
        icon = parser.icons[0]
        self.assertEqual(icon.get("type"), "image/svg+xml")
        href = icon.get("href", "")
        parsed_href = urlsplit(href)
        self.assertEqual(parsed_href.path, "/favicon.svg")
        self.assertTrue(parsed_href.query)

        favicon_path = ROOT / "frontend" / parsed_href.path.lstrip("/")
        self.assertTrue(favicon_path.is_file())
        root = ElementTree.parse(favicon_path).getroot()
        view_box = root.attrib.get("viewBox", "").split()
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(len(view_box), 4)
        self.assertEqual(view_box[2], view_box[3])

        svg = favicon_path.read_text(encoding="utf-8").lower()
        for forbidden in ("<script", "<text", "gradient", "data:", "base64", "href="):
            self.assertNotIn(forbidden, svg)

    def test_javascript_polls_safely_persists_preference_and_uses_safe_dom_apis(self):
        source = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        for required in (
            'fetch("/api/snapshot"', "AbortController", "localStorage.getItem",
            "localStorage.setItem", "30000", "POLL_INTERVAL_MS", "textContent", "aria-checked",
            "state.inFlight", "scheduleNext", "thread.provider", "provider-badge",
            'cell.dataset.label', 'row.dataset.provider', '"Source"', '"Project"',
            '"Task"', '"Branch"', '"Model"', '"Last update"',
        ):
            self.assertIn(required, source)
        self.assertNotIn(".innerHTML", source)
        self.assertNotIn("setInterval", source)

    def test_css_has_responsive_focus_mobile_targets_and_reduced_motion(self):
        css = (ROOT / "frontend/styles.css").read_text(encoding="utf-8")
        for required in (
            ":focus-visible", "@media (max-width:", "min-height: 44px",
            "prefers-reduced-motion", "--live:", "--warning:", "--danger:",
            'content: attr(data-label)', "overflow-wrap: anywhere",
            '.recent-table-wrap[data-mobile-layout="cards"]',
            "grid-template-columns: minmax(0, 1fr)",
        ):
            self.assertIn(required, css)
        self.assertNotIn("linear-gradient", css)
        self.assertNotIn("radial-gradient", css)

    def test_live_threads_use_responsive_activity_disclosure_and_compact_mobile_facts(self):
        source = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        for required in (
            'node("details", "timeline-panel")',
            'node("summary", "timeline-title")',
            'window.matchMedia("(max-width: 640px)").matches',
            "timeline.open = !isCompactViewport",
            '"Recent activity"',
        ):
            self.assertIn(required, source)

        css = (ROOT / "frontend/styles.css").read_text(encoding="utf-8")
        mobile = css.split("@media (max-width: 640px)", 1)[1].split(
            "@media (prefers-reduced-motion", 1
        )[0]
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", mobile)
        self.assertIn(".timeline-title", mobile)
        self.assertIn("min-height: 44px", mobile)
        self.assertIn("overflow-wrap: anywhere", mobile)


if __name__ == "__main__":
    unittest.main()
