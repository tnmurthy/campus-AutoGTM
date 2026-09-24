import time
from pathlib import Path

import pytest

from agents.enrichment import evidence as ev
from agents.enrichment.enricher import enrich_lead
from agents.enrichment.fetcher import Fetcher, Page

HOMEPAGE = """
<html><head><title>Probe Institute</title><style>.x{color:red}</style></head>
<body>
  <nav><a href="/tnp/placements.html">Training &amp; Placement</a>
       <a href="/departments/cse.html">Departments</a>
       <a href="https://elsewhere.example/ads">Sponsored</a>
       <a href="/contact">Contact</a></nav>
  <p>Probe Institute is an autonomous engineering college accredited by NAAC.</p>
  <script>var tracking = 1;</script>
</body></html>
"""

PLACEMENTS = """
<html><body>
<p>The Training and Placement cell runs year-round with 40 recruiters on campus.</p>
<p>Our students placed in 2025 numbered 820 across Computer Science and Information Technology.</p>
<p>We hosted a national hackathon and an annual techfest last year.</p>
</body></html>
"""


class StubFetcher:
    """Serves canned pages. No network, no robots lookup, no sleeping."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str) -> Page | None:
        self.requested.append(url)
        html = self.pages.get(url)
        return Page(url=url, html=html) if html else None


class TestEvidenceExtraction:
    def test_strips_scripts_and_styles(self):
        text = ev.page_text(HOMEPAGE)
        assert "tracking" not in text
        assert "color:red" not in text
        assert "autonomous engineering college" in text

    def test_finds_only_same_host_relevant_links(self):
        links = ev.candidate_links(HOMEPAGE, "https://probe.example/")
        assert "https://probe.example/tnp/placements.html" in links
        assert "https://probe.example/departments/cse.html" in links
        # Off-host advert and an irrelevant contact page are both excluded.
        assert not any("elsewhere.example" in l for l in links)
        assert not any(l.endswith("/contact") for l in links)

    def test_groups_excerpts_by_topic(self):
        found = ev.excerpts_from(ev.page_text(PLACEMENTS))
        assert any("Training and Placement" in e for e in found["placement"])
        assert any("hackathon" in e.lower() for e in found["events"])

    def test_identifies_departments(self):
        assert set(ev.departments_from(ev.page_text(PLACEMENTS))) >= {"CSE", "IT"}

    def test_excerpts_are_length_capped(self):
        long_text = "Placement " + ("x" * 900) + "."
        for hits in ev.excerpts_from(long_text).values():
            assert all(len(h) <= ev.MAX_EXCERPT_CHARS for h in hits)


class TestEnrichLead:
    def test_attaches_evidence_and_departments(self):
        fetcher = StubFetcher({
            "https://probe.example": HOMEPAGE,
            "https://probe.example/tnp/placements.html": PLACEMENTS,
            "https://probe.example/departments/cse.html": PLACEMENTS,
        })
        lead = {"college_name": "Probe Institute", "website": "https://probe.example"}

        out = enrich_lead(lead, fetcher)

        assert "placement" in out["evidence"]
        assert "events" in out["evidence"]
        assert "CSE" in out["departments"]
        assert out["pages_read"]

    def test_does_not_mutate_the_input_lead(self):
        fetcher = StubFetcher({"https://probe.example": HOMEPAGE})
        lead = {"college_name": "Probe", "website": "https://probe.example"}

        enrich_lead(lead, fetcher)

        assert "evidence" not in lead

    def test_adds_a_scheme_when_the_roster_omits_it(self):
        fetcher = StubFetcher({"https://probe.example": HOMEPAGE})
        enrich_lead({"college_name": "P", "website": "probe.example"}, fetcher)
        assert fetcher.requested[0].startswith("https://")

    def test_a_lead_with_no_website_is_returned_untouched(self):
        fetcher = StubFetcher({})
        lead = {"college_name": "No Site College"}
        assert enrich_lead(lead, fetcher) == lead
        assert fetcher.requested == []

    def test_an_unreachable_site_degrades_rather_than_raising(self):
        fetcher = StubFetcher({})
        lead = {"college_name": "Down College", "website": "https://down.example"}
        assert enrich_lead(lead, fetcher) == lead

    def test_existing_roster_departments_are_not_overwritten(self):
        fetcher = StubFetcher({
            "https://probe.example": HOMEPAGE,
            "https://probe.example/tnp/placements.html": PLACEMENTS,
        })
        lead = {"college_name": "P", "website": "https://probe.example",
                "departments": ["Aerospace"]}
        assert enrich_lead(lead, fetcher)["departments"] == ["Aerospace"]


class TestFetcherPoliteness:
    def test_serves_from_cache_without_refetching(self, tmp_path, monkeypatch):
        f = Fetcher(tmp_path)
        url = "https://cached.example/page"
        f._cache_path(url).write_text("<html>cached</html>", encoding="utf-8")

        def explode(*_a, **_k):
            raise AssertionError("cache miss: went to the network")

        monkeypatch.setattr("agents.enrichment.fetcher.requests.get", explode)
        assert f.get(url).html == "<html>cached</html>"

    def test_expired_cache_is_ignored(self, tmp_path):
        f = Fetcher(tmp_path)
        url = "https://stale.example/page"
        path = f._cache_path(url)
        path.write_text("<html>old</html>", encoding="utf-8")
        import os
        old = time.time() - (8 * 24 * 3600)
        os.utime(path, (old, old))
        assert f._cached(url) is None

    def test_respects_a_disallow_rule(self, tmp_path, monkeypatch):
        f = Fetcher(tmp_path)

        class R:
            status_code = 200
            text = "User-agent: *\nDisallow: /private/\nCrawl-delay: 7\n"

        monkeypatch.setattr("agents.enrichment.fetcher.requests.get", lambda *a, **k: R())
        assert f.allowed("https://polite.example/public/x") is True
        assert f.allowed("https://polite.example/private/x") is False

    def test_adopts_the_published_crawl_delay(self, tmp_path, monkeypatch):
        f = Fetcher(tmp_path)

        class R:
            status_code = 200
            text = "User-agent: *\nCrawl-delay: 9\n"

        monkeypatch.setattr("agents.enrichment.fetcher.requests.get", lambda *a, **k: R())
        _, delay = f._robots_for("https://slow.example/")
        assert delay == 9.0

    def test_missing_robots_does_not_block_fetching(self, tmp_path, monkeypatch):
        f = Fetcher(tmp_path)

        class R:
            status_code = 404
            text = ""

        monkeypatch.setattr("agents.enrichment.fetcher.requests.get", lambda *a, **k: R())
        assert f.allowed("https://norobots.example/anything") is True


class TestEvidenceVolumeGate:
    """Thin evidence is as unreliable as none, and must not auto-qualify."""

    def test_counts_characters_across_all_topics(self):
        from agents.scoring_agent import _evidence_volume

        assert _evidence_volume({"placement": ["abcde"], "events": ["fg"]}) == 7
        assert _evidence_volume(None) == 0
        assert _evidence_volume({}) == 0

    def test_threshold_sits_above_the_observed_unstable_band(self):
        from agents.scoring_agent import MIN_EVIDENCE_CHARS

        # Observed: 50 chars -> 98.8, 72 chars -> 49.5; >=1179 chars was stable.
        assert 72 < MIN_EVIDENCE_CHARS <= 1179
