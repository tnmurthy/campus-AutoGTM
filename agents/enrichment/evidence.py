"""Turns fetched pages into the evidence the scoring questions actually need.

The score levels ask about a training and placement cell, event history and
relevant departments. A roster row carries none of that, which is why real
colleges scored ~32/100 against a 70 threshold: the model was being asked to
judge evidence it had never been shown.

Excerpts are selected in code rather than handing the model whole pages. Code
is good at finding candidate spans and bad at judging them; the model is the
other way round. It also keeps the request bounded -- a homepage can be tens of
thousands of tokens, and almost none of it is about placements.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Pages worth looking at beyond the homepage, matched against link text and href.
CANDIDATE_LINK_HINTS = (
    "placement", "training", "tnp", "t&p", "career",
    "department", "academics", "programme", "program", "course",
    "event", "hackathon", "symposium", "fest", "workshop",
)

TOPICS: dict[str, tuple[str, ...]] = {
    "placement": ("placement", "training and placement", "t&p cell", "tnp", "recruiter", "placed"),
    "events": ("hackathon", "symposium", "techfest", "tech fest", "workshop", "bootcamp", "ideathon"),
    "departments": ("computer science", "cse", "information technology", "artificial intelligence",
                    "data science", "electronics", "ece", "mechanical", "civil", "mba", "bca", "mca"),
    "scale": ("students", "intake", "admissions", "naac", "nba", "nirf", "autonomous", "accredited"),
}

MAX_EXCERPTS_PER_TOPIC = 4
MAX_EXCERPT_CHARS = 240
MAX_PAGES = 4
# A real sentence is not 600 characters long. Anything past this is a menu or a
# footer that survived chrome-stripping, and it is noise in every topic.
MAX_SENTENCE_CHARS = 400


@dataclass
class Evidence:
    excerpts: dict[str, list[str]] = field(default_factory=dict)
    departments: list[str] = field(default_factory=list)
    pages_read: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.excerpts and not self.departments


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    # nav/header/footer are the same link soup on every page. Left in, that
    # one giant punctuation-free blob matched every topic keyword and won the
    # top excerpt slot for placement, departments and scale simultaneously.
    for tag in soup(["script", "style", "noscript", "svg", "form",
                     "nav", "header", "footer", "aside"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def candidate_links(html: str, base_url: str, limit: int = MAX_PAGES) -> list[str]:
    """Same-host links whose text or href suggests placement, course or event pages."""
    soup = BeautifulSoup(html, "lxml")
    host = urlparse(base_url).netloc
    found: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        haystack = f"{anchor.get_text(' ', strip=True)} {anchor['href']}".lower()
        if not any(hint in haystack for hint in CANDIDATE_LINK_HINTS):
            continue
        url = urljoin(base_url, anchor["href"]).split("#")[0]
        if urlparse(url).netloc != host or url in seen or url.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= limit:
            break
    return found


def excerpts_from(text: str) -> dict[str, list[str]]:
    """Sentences mentioning each topic, deduplicated and length-capped."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out: dict[str, list[str]] = {}

    for topic, keywords in TOPICS.items():
        hits: list[str] = []
        seen: set[str] = set()
        for sentence in sentences:
            if len(sentence) > MAX_SENTENCE_CHARS:
                continue
            lowered = sentence.lower()
            if not any(k in lowered for k in keywords):
                continue
            snippet = sentence[:MAX_EXCERPT_CHARS].strip()
            fingerprint = snippet.lower()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            hits.append(snippet)
            if len(hits) >= MAX_EXCERPTS_PER_TOPIC:
                break
        if hits:
            out[topic] = hits
    return out


def departments_from(text: str) -> list[str]:
    """Named programmes present in the text, in a stable order."""
    lowered = text.lower()
    aliases = {
        "CSE": ("computer science", "cse"),
        "IT": ("information technology",),
        "AI/DS": ("artificial intelligence", "data science"),
        "ECE": ("electronics and communication", "ece"),
        "EEE": ("electrical and electronics", "eee"),
        "MECH": ("mechanical engineering",),
        "CIVIL": ("civil engineering",),
        "MBA": ("mba", "business administration"),
        "BCA/MCA": ("bca", "mca", "computer applications"),
    }
    return [name for name, keys in aliases.items() if any(k in lowered for k in keys)]


def merge(into: Evidence, text: str, url: str) -> Evidence:
    for topic, hits in excerpts_from(text).items():
        existing = into.excerpts.setdefault(topic, [])
        for hit in hits:
            if len(existing) >= MAX_EXCERPTS_PER_TOPIC:
                break
            if hit not in existing:
                existing.append(hit)
    for dept in departments_from(text):
        if dept not in into.departments:
            into.departments.append(dept)
    into.pages_read.append(url)
    return into
