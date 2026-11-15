"""Regression corpus: real threads from past audits that the ranking once got wrong. Run: python scanner/test_audit.py"""
import sys
from datetime import timedelta
from pathlib import Path

sys.argv = ["x"]
sys.path.insert(0, str(Path(__file__).parent))
import scan

iso = lambda d=0: (scan.NOW - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue(comments=(), labels=(), by="reporter", assoc="NONE", refs=(), days=5, url="https://github.com/o/r/issues/1", title="Some bug", body="x"):
    return {"assignees": {"totalCount": 0}, "createdAt": iso(days), "updatedAt": iso(1), "url": url, "title": title,
            "bodyText": body, "body": body, "authorAssociation": assoc, "author": {"login": by, "__typename": "User"},
            "labels": {"nodes": [{"name": l} for l in labels]},
            "labeled": {"nodes": [{"label": {"name": l}, "actor": {"__typename": "User", "login": "maint"}} for l in labels]},
            "timelineItems": {"nodes": [{"source": {"__typename": "Issue", "url": u, "author": {"login": a}}} for u, a in refs]},
            "comments": {"totalCount": len(comments), "nodes": [{"bodyText": t, "authorAssociation": ca, "author": {"login": cl}} for cl, ca, t in comments]}}


def cand(i):
    nodes = i["comments"]["nodes"]
    me = i["author"]["login"]
    c = {"labels": [l["name"] for l in i["labels"]["nodes"]], "title": i["title"], "body": i["bodyText"], "body_md": i["body"],
         "assoc": i["authorAssociation"], "human_labels": scan.human_labels(i),
         "self_labelled": False,
         "maint_replied": any(n["authorAssociation"] in scan.MAINT for n in nodes),
         "maint_text": " ".join(n["bodyText"] for n in nodes if n["authorAssociation"] in scan.MAINT),
         "thread_text": " ".join(n["bodyText"] for n in nodes),
         "own_comments": sum(n["author"]["login"] == me for n in nodes),
         "other_comments": sum(n["author"]["login"] != me and n["authorAssociation"] not in scan.MAINT for n in nodes)}
    return c


def verdict(i):
    if not scan.issue_open_for_grabs(i):
        return "dropped:claim/fixed/upstream"
    t, why = scan.actionability(cand(i))
    return "dropped:" + why if t is None else ("ready", "vetted", "raw")[t]


CASES = [  # name, issue, expected
    ("bevy: cannot reproduce on main", issue([("o", "CONTRIBUTOR", "I cannot reproduce this on current `main`. I think it was fixed in e79b0b3 (#26314).")]), "dropped:claim/fixed/upstream"),
    ("litellm: could I investigate", issue([("g", "NONE", "Could I investigate avoiding repeated Prisma imports during startup?")]), "dropped:claim/fixed/upstream"),
    ("lance: author prototype numbers", issue([("a", "CONTRIBUTOR", "A/B results for the prototype: inline vs pool")], by="a", assoc="CONTRIBUTOR"), "dropped:claim/fixed/upstream"),
    ("vllm: needs a ROCm machine", issue([("j", "CONTRIBUTOR", "someone with a ROCm machine would be best suited to take this on.")]), "dropped:needs hardware an outsider will not have"),
    ("vllm: reporter took it to flashinfer", issue([("p", "NONE", "I found the root cause.")], by="k", refs=[("https://github.com/other/flashinfer/issues/9", "p")]), "dropped:claim/fixed/upstream"),
    ("burn: contributor iterating on own thread", issue([("k", "CONTRIBUTOR", "Follow-up one"), ("k", "CONTRIBUTOR", "Follow-up two")], by="k", assoc="CONTRIBUTOR"), "dropped:author is working it through themselves"),
    ("llama.cpp: contributor's own profiling", issue([("g", "CONTRIBUTOR", "Raw profiling output")], by="g", assoc="CONTRIBUTOR"), "dropped:a contributor's own investigation"),
    ("langgraph: outsiders debating", issue([("a", "NONE", "x"), ("b", "NONE", "y"), ("c", "NONE", "z")], by="r"), "dropped:outsiders debating, no maintainer yet"),
    ("zed: good non-first, human label", issue(labels=[".contrib/good non-first issue"]), "ready"),
    ("plain new bug, nobody replied", issue(), "raw"),
    ("maintainer says working on it", issue([("m", "MEMBER", "We're working on Linux Vulkan support now, and it should be ready soon")]), "dropped:maintainer declined or asked for info"),
    ("maintainer: file it upstream", issue([("m", "MEMBER", "It sounds like an OpenBSD bug, please file a bug with OpenBSD")]), "dropped:maintainer declined or asked for info"),
    ("risingwave: interested in working on Phase 1", issue([("d", "NONE", "Hi, I'd be interested in working on the Phase 1 scope of this issue. My plan would be to reproduce first.")], labels=["good first issue"]), "dropped:claim/fixed/upstream"),
    ("risingwave: interested in exploring", issue([("x", "CONTRIBUTOR", "Hi, I am interested in exploring this. I traced the current implementation")], labels=["good first issue"]), "dropped:claim/fixed/upstream"),
    ("polars: hype title", issue(title="An enhanecment that boosts Polars's performance by 15-30%!!"), "dropped:discussion, not a task"),
    ("autogen: promo title", issue(title="Open-source MCP runtime behavior security tools - RFC 9334 aligned"), "dropped:outreach or promotion, not a task"),
    ("plain thanks comment is not a claim", issue([("o", "NONE", "Thanks for the report, I can reproduce this on 0.2.")]), "raw"),
    ("openhands: bot-labelled AI-written feedback", issue(title="Feedback: a zero-cost local-AI supply built with OpenHands", body="This feedback was written by an AI agent (OpenHands) on behalf of the user.", labels=["ready-for-dev"]), "dropped:written by an AI agent"),
    ("markitdown: joke title", issue(title="Autonomous Agents, Unite!", labels=["good first issue"]), "dropped:discussion, not a task"),
    ("agno: vendor cookbook", issue(title="[Feature Request] Add a Datacircle hosted MCP cookbook (no key)", labels=["ready"]), "dropped:discussion, not a task"),
    ("lmcache: maintainer says no longer maintained", issue([("d", "COLLABORATOR", "In-process CacheBlend is no longer maintained. We're developing CacheBlend support for MP mode.")], labels=["good second issue"]), "dropped:maintainer declined or asked for info"),
    ("qdrant: accepted bug", issue(title="Majority read consistency drops valid sparse search results", labels=["help wanted"]), "ready"),
]
bad = 0
for name, i, want in CASES:
    got = verdict(i)
    bad += got != want
    print(("ok  " if got == want else "FAIL"), name, "->", got, "" if got == want else f"(wanted {want})")
sys.exit(1 if bad else 0)
