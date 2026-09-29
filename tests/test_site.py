"""Acceptance (ATDD) tests for the Lab019 static landing-page slice.

Slice: "pagina inicial estatica do Lab019, hospedavel como site estatico na Vercel".

Run from the repository root (the parent directory of ``tests/``):

    python3 -m unittest discover -s tests -v

Python standard library only: unittest, html.parser, http.client, subprocess.
These tests are expected to FAIL (RED) until the page files exist.
"""

import http.client
import json
import re
import socket
import subprocess
import sys
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
VERCEL_JSON = REPO_ROOT / "vercel.json"

# Elements that never contain children in HTML5 (must not be pushed on the stack).
VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

# Attributes whose value is fetched from the network when the page loads.
RESOURCE_ATTRS = {
    "img": ("src", "srcset"),
    "script": ("src",),
    "source": ("src", "srcset"),
    "iframe": ("src",),
    "video": ("src", "poster"),
    "audio": ("src",),
    "embed": ("src",),
    "track": ("src",),
    "object": ("data",),
}

# Remote stylesheet / remote font-import signatures inside <style> or CSS.
REMOTE_IMPORT_RE = re.compile(r"@import\s+(?:url\(\s*)?[\"']?https?://", re.IGNORECASE)
REMOTE_URL_RE = re.compile(r"url\(\s*[\"']?(?:https?:)?//", re.IGNORECASE)


class _PageParser(HTMLParser):
    """Collects elements, ids, anchors and the text of <h1>/<p>/<a> tags."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # currently open elements
        self.elements = []  # every start tag, in document order
        self.ids = set()  # every non-empty id attribute value
        self.h1_texts = []
        self.p_texts = []
        self.anchors = []  # {"href": str, "text": str, "ancestors": tuple}
        self._recorders = []  # open <h1>/<p>/<a> text buffers

    def _ancestors(self):
        return tuple(
            (e["tag"], e["attrs"].get("id", ""), e["attrs"].get("class", ""))
            for e in self.stack
        )

    def _start(self, tag, attrs, is_self_closing):
        attr = {k.lower(): ("" if v is None else v) for k, v in attrs}
        element = {"tag": tag, "attrs": attr, "ancestors": self._ancestors()}
        self.elements.append(element)
        if attr.get("id"):
            self.ids.add(attr["id"])
        if tag in ("h1", "p", "a"):
            self._recorders.append(
                {"tag": tag, "depth": len(self.stack), "text": [], "element": element}
            )
        if not is_self_closing and tag not in VOID_ELEMENTS:
            self.stack.append(element)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def handle_data(self, data):
        for recorder in self._recorders:
            recorder["text"].append(data)

    def _flush_recorder(self, recorder):
        text = " ".join("".join(recorder["text"]).split())
        tag = recorder["tag"]
        if tag == "h1":
            self.h1_texts.append(text)
        elif tag == "p":
            self.p_texts.append(text)
        else:  # a
            self.anchors.append(
                {
                    "href": recorder["element"]["attrs"].get("href", ""),
                    "text": text,
                    "ancestors": recorder["element"]["ancestors"],
                }
            )

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()
        else:  # tolerate slightly malformed nesting
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index]["tag"] == tag:
                    del self.stack[index:]
                    break
        for recorder in list(self._recorders):
            if recorder["tag"] == tag and recorder["depth"] == len(self.stack):
                self._recorders.remove(recorder)
                self._flush_recorder(recorder)

    def close(self):
        super().close()
        for recorder in list(self._recorders):
            self._recorders.remove(recorder)
            self._flush_recorder(recorder)


def load_index_html():
    """Return index.html source text, failing the test if it is missing."""
    if not INDEX_HTML.is_file():
        raise AssertionError(
            "criterion 1: index.html must exist at the repository root (%s); "
            "found no file at %s" % (REPO_ROOT, INDEX_HTML)
        )
    return INDEX_HTML.read_text(encoding="utf-8")


def parse_index_html(html_text):
    parser = _PageParser()
    parser.feed(html_text)
    parser.close()
    return parser


def is_external_url(value):
    value = (value or "").strip()
    return value.startswith(("http://", "https://", "//"))


def internal_anchor_hrefs(parser):
    return [
        anchor
        for anchor in parser.anchors
        if anchor["href"].startswith("#") and len(anchor["href"]) > 1
    ]


def in_contact_container(anchor):
    for tag, element_id, class_attr in anchor["ancestors"]:
        if tag in ("section", "footer"):
            return True
        haystack = ("%s %s" % (element_id, class_attr)).lower()
        if "contato" in haystack or "contact" in haystack:
            return True
    return False


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class Lab019LandingPageFilesTest(unittest.TestCase):
    """Criteria 1-6: the static page files and their content."""

    def test_index_html_exists_at_repository_root(self):
        self.assertTrue(
            INDEX_HTML.is_file(),
            "criterion 1: index.html must exist at the repository root, not in a "
            "subdirectory; expected %s" % INDEX_HTML,
        )

    def test_html5_doctype_and_root_lang_is_pt_br(self):
        html_text = load_index_html()
        self.assertRegex(
            html_text[:200],
            r"(?is)^\s*<!doctype\s+html\s*>",
            "criterion 1: index.html must start with an HTML5 doctype "
            "(<!DOCTYPE html>)",
        )
        parser = parse_index_html(html_text)
        html_elements = [e for e in parser.elements if e["tag"] == "html"]
        self.assertEqual(
            len(html_elements),
            1,
            "criterion 1: expected exactly one <html> element, found %d"
            % len(html_elements),
        )
        lang = html_elements[0]["attrs"].get("lang", "")
        self.assertEqual(
            lang.lower(),
            "pt-br",
            'criterion 1: <html> must declare lang="pt-BR", found %r' % lang,
        )

    def test_viewport_meta_declares_device_width(self):
        parser = parse_index_html(load_index_html())
        viewports = [
            e
            for e in parser.elements
            if e["tag"] == "meta"
            and e["attrs"].get("name", "").strip().lower() == "viewport"
        ]
        self.assertTrue(
            viewports,
            'criterion 2: a <meta name="viewport" ...> tag is required for '
            "minimal responsiveness; none found",
        )
        content = viewports[0]["attrs"].get("content", "")
        self.assertIn(
            "width=device-width",
            content.replace(" ", "").lower(),
            'criterion 2: viewport content must include width=device-width, found %r'
            % content,
        )

    def test_exactly_one_h1_mentioning_lab019(self):
        parser = parse_index_html(load_index_html())
        self.assertEqual(
            len(parser.h1_texts),
            1,
            "criterion 2: expected exactly one <h1>, found %d (%r)"
            % (len(parser.h1_texts), parser.h1_texts),
        )
        self.assertIn(
            "lab019",
            parser.h1_texts[0].lower(),
            'criterion 2: the single <h1> must mention "Lab019", found %r'
            % parser.h1_texts[0],
        )

    def test_every_internal_anchor_href_resolves_to_an_existing_id(self):
        parser = parse_index_html(load_index_html())
        internal = internal_anchor_hrefs(parser)
        self.assertTrue(
            internal,
            'criterion 3: the navbar must link to on-page sections with at least '
            'one internal <a href="#...">; none found',
        )
        missing = sorted({a["href"][1:] for a in internal} - parser.ids)
        self.assertFalse(
            missing,
            "criterion 3: every internal href must resolve to an existing id on "
            "the page; unresolved ids: %s (ids present: %s)"
            % (missing, sorted(parser.ids)),
        )

    def test_navbar_links_to_on_page_sections(self):
        parser = parse_index_html(load_index_html())
        navs = [e for e in parser.elements if e["tag"] == "nav"]
        self.assertTrue(
            navs,
            "criterion 3: the page must contain a navbar (a <nav> element with "
            "anchor links); no <nav> element found",
        )
        nav_anchors = [
            a
            for a in internal_anchor_hrefs(parser)
            if any(ancestor[0] == "nav" for ancestor in a["ancestors"])
        ]
        self.assertTrue(
            nav_anchors,
            "criterion 3: the navbar must contain at least one internal anchor "
            'link (<a href="#secao">) to an on-page section; found none inside '
            "<nav>",
        )
        missing = sorted({a["href"][1:] for a in nav_anchors} - parser.ids)
        self.assertFalse(
            missing,
            "criterion 3: navbar anchors must resolve to ids that exist on the "
            "page; unresolved: %s" % missing,
        )

    def test_lead_paragraph_and_contact_mailto_link(self):
        parser = parse_index_html(load_index_html())
        leads = [text for text in parser.p_texts if "lab019" in text.lower()]
        self.assertTrue(
            leads,
            'criterion 4: a paragraph/lead presenting the Lab019 proposal is '
            'required (a <p> whose text mentions "Lab019"); paragraphs found: %r'
            % parser.p_texts,
        )
        mailtos = [
            a for a in parser.anchors if a["href"].strip().lower().startswith("mailto:")
        ]
        self.assertTrue(
            mailtos,
            "criterion 4: the contact section must contain at least one "
            '<a href="mailto:..."> link; none found',
        )
        addresses = [
            a["href"].strip()[len("mailto:") :].split("?")[0].strip().lower()
            for a in mailtos
        ]
        domains = [addr.rsplit("@", 1)[-1] for addr in addresses if "@" in addr]
        self.assertIn(
            "lab019.ai",
            domains,
            'criterion 4: the mailto link must use the lab019.ai domain '
            "(expected contato@lab019.ai); found: %s" % addresses,
        )
        contact_links = [a for a in mailtos if in_contact_container(a)]
        self.assertTrue(
            contact_links,
            "criterion 4: the mailto link must live in a contact section "
            "(<section>/<footer>, or an element whose id/class mentions "
            "contato/contact)",
        )

    def test_page_is_self_contained_with_no_external_resources(self):
        html_text = load_index_html()
        parser = parse_index_html(html_text)
        offenders = []
        for element in parser.elements:
            tag = element["tag"]
            for attr_name in RESOURCE_ATTRS.get(tag, ()):
                value = element["attrs"].get(attr_name, "")
                if not value:
                    continue
                urls = (
                    [part.strip().split(" ")[0] for part in value.split(",")]
                    if attr_name == "srcset"
                    else [value]
                )
                for url in urls:
                    if is_external_url(url):
                        offenders.append("<%s %s=%r>" % (tag, attr_name, url))
            if tag == "link" and "stylesheet" in element["attrs"].get("rel", "").lower():
                href = element["attrs"].get("href", "")
                if is_external_url(href):
                    offenders.append("<link rel=stylesheet href=%r>" % href)
        if REMOTE_IMPORT_RE.search(html_text):
            offenders.append("remote @import in CSS")
        if REMOTE_URL_RE.search(html_text):
            offenders.append("url(...) pointing at a remote resource in CSS")
        self.assertFalse(
            offenders,
            "criterion 5: the page must be self-contained (no external resource "
            "in src=/stylesheet href=/CSS imports; only <a href> navigation links "
            "may be external); offenders: %s" % offenders,
        )
        for element in parser.elements:
            if element["tag"] == "link" and "stylesheet" in element["attrs"].get(
                "rel", ""
            ).lower():
                href = element["attrs"].get("href", "").strip()
                if href and not is_external_url(href):
                    self.assertTrue(
                        (REPO_ROOT / href.lstrip("/")).is_file(),
                        "criterion 5: local stylesheet %r referenced by "
                        "<link rel=stylesheet> does not exist in the repository"
                        % href,
                    )

    def test_vercel_json_exists_and_is_a_valid_json_object(self):
        self.assertTrue(
            VERCEL_JSON.is_file(),
            "criterion 6: vercel.json must exist at the repository root (%s) so "
            "the static deploy is explicit" % VERCEL_JSON,
        )
        raw = VERCEL_JSON.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.fail("criterion 6: vercel.json is not valid JSON: %s" % exc)
        self.assertIsInstance(
            data,
            dict,
            "criterion 6: vercel.json must be a JSON object, found %s"
            % type(data).__name__,
        )
        bad_keys = [key for key in data if not isinstance(key, str)]
        self.assertFalse(
            bad_keys, "criterion 6: every top-level key must be a string: %r" % bad_keys
        )


class Lab019ServedOverHttpTest(unittest.TestCase):
    """Criterion 7: the repository root is served for real over HTTP."""

    def test_root_is_served_as_html_containing_lab019(self):
        self.assertTrue(
            INDEX_HTML.is_file(),
            "criterion 7: GET / must serve the page, so index.html must exist at "
            "the served root %s; otherwise the server returns a directory listing"
            % REPO_ROOT,
        )
        port = find_free_port()
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                "127.0.0.1",
                "--directory",
                str(REPO_ROOT),
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(stop_process, server)
        self.assertTrue(
            wait_for_port(port, timeout=15),
            "criterion 7: `python3 -m http.server` did not accept connections on "
            "127.0.0.1:%d within 15s" % port,
        )
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            status = response.status
            content_type = response.getheader("Content-Type") or ""
            body = response.read().decode("utf-8", "replace")
        finally:
            connection.close()
        self.assertEqual(
            status, 200, "criterion 7: GET / must return HTTP 200, got %s" % status
        )
        self.assertTrue(
            content_type.lower().startswith("text/html"),
            "criterion 7: GET / must return Content-Type text/html, got %r"
            % content_type,
        )
        self.assertIn(
            "Lab019",
            body,
            "criterion 7: the body served at GET / must contain \"Lab019\" "
            "(served %d bytes, first 200 chars: %r)" % (len(body), body[:200]),
        )


if __name__ == "__main__":
    unittest.main()
