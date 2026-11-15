#!/usr/bin/env python3
"""VOTHUB scanner - runs in GitHub Actions twice a day.

discover fast-rising repos -> drop repos closed to outsiders -> collect open,
unclaimed, PR-less issues -> score + tag them with an ML model (cached by
issue updated_at) -> write one compact gzipped feed for the desktop tab.
"""
import argparse
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
NOW = datetime.now(timezone.utc)
KEEP_DAYS = 4            # nothing older than this survives in feed or cache
ISSUE_WINDOW_DAYS = 45   # "recent" issues
MAX_FEED = 200
MAX_PER_REPO = 5
MAX_RAW = 40          # unvetted issues are admitted only as a small tail
TIERS = ["ready", "vetted", "raw"]
KINDS = ["feature", "perf", "bug", "research", "infra", "refactor", "test", "question", "docs"]
EFFORTS = ["S", "M", "L"]
LANES = ["ai-infra", "systems"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- github api
def gh(url, payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "vothub-scanner",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                wait = int(e.headers.get("Retry-After") or 25 * (attempt + 1))
                log(f"  rate limited, sleeping {min(wait, 90)}s")
                time.sleep(min(wait, 90))
            elif e.code >= 500:
                time.sleep(6)
            else:
                raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(6)
    raise RuntimeError("github api gave up: " + url)


REPO_QUERY = """
query($owner:String!,$name:String!,$since:DateTime!){
  repository(owner:$owner,name:$name){
    nameWithOwner description isArchived isFork isDisabled hasIssuesEnabled
    stargazerCount createdAt pushedAt
    primaryLanguage{name}
    repositoryTopics(first:10){nodes{topic{name}}}
    contributing: object(expression:"HEAD:CONTRIBUTING.md"){... on Blob{text}}
    pullRequests(states:MERGED, first:30, orderBy:{field:UPDATED_AT,direction:DESC}){
      nodes{authorAssociation mergedAt}
    }
    issues(states:OPEN, first:40, orderBy:{field:CREATED_AT,direction:DESC}, filterBy:{since:$since}){
      nodes{
        number title createdAt updatedAt bodyText body authorAssociation
        author{__typename}
        assignees(first:1){totalCount}
        labels(first:10){nodes{name}}
        comments(last:8){totalCount nodes{bodyText authorAssociation}}
        reactions{totalCount}
        timelineItems(itemTypes:[CROSS_REFERENCED_EVENT,CONNECTED_EVENT], first:15){
          nodes{
            __typename
            ... on CrossReferencedEvent{source{__typename ... on PullRequest{state}}}
            ... on ConnectedEvent{subject{__typename ... on PullRequest{state}}}
          }
        }
      }
    }
  }
}"""


def fetch_repo(full_name):
    owner, name = full_name.split("/", 1)
    since = (NOW - timedelta(days=ISSUE_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = gh("https://api.github.com/graphql",
             {"query": REPO_QUERY, "variables": {"owner": owner, "name": name, "since": since}})
    if out.get("errors") and not (out.get("data") or {}).get("repository"):
        raise RuntimeError(out["errors"][0].get("message", "graphql error"))
    return (out.get("data") or {}).get("repository")


# ------------------------------------------------------------------ discovery
NOISE = re.compile(r"awesome|curated|roadmap|interview|tutorial|course|cheat.?sheet|"
                   r"\bbooks?\b|papers? list|leetcode|prompts? collection|free.?api", re.I)

SEARCHES = [  # (lane, query fragment)
    (0, "topic:llm stars:>400"), (0, "topic:ai-agents stars:>300"), (0, "topic:agents stars:>400"),
    (0, "topic:llm-inference stars:>150"), (0, "topic:inference stars:>300"), (0, "topic:rag stars:>400"),
    (0, "topic:mlops stars:>300"), (0, "topic:model-serving stars:>100"), (0, "topic:mcp stars:>400"),
    (0, "topic:machine-learning stars:>800"), (0, "topic:gpu stars:>300"),
    (1, "language:Rust stars:>400"), (1, "language:C++ stars:>500"), (1, "language:Zig stars:>250"),
    (1, "topic:database language:Rust stars:>150"), (1, "topic:compiler stars:>250"),
    (1, "topic:webassembly stars:>250"), (1, "topic:distributed-systems stars:>250"),
    (1, "topic:research language:Rust stars:>80"), (1, "topic:runtime stars:>300"),
]


def discover(per_lane, limit_queries=None):
    created = (NOW - timedelta(days=420)).strftime("%Y-%m-%d")
    pushed = (NOW - timedelta(days=10)).strftime("%Y-%m-%d")
    found = {}
    pause = 2.3 if TOKEN else 7.0  # search api: 30/min with token, 10/min without
    for lane, frag in SEARCHES[:limit_queries]:
        q = f"{frag} created:>{created} pushed:>{pushed} archived:false fork:false"
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "stars", "order": "desc", "per_page": 30})
        try:
            items = gh(url).get("items", [])
        except Exception as e:  # one bad query must not sink the run
            log("  search failed:", frag, e)
            items = []
        for it in items:
            blob = f"{it['full_name']} {it.get('description') or ''} {' '.join(it.get('topics') or [])}"
            if NOISE.search(blob) or not it.get("has_issues"):
                continue
            age = max(14, (NOW - _dt(it["created_at"])).days)
            vel = it["stargazers_count"] / age
            cur = found.get(it["full_name"])
            if not cur or cur["vel"] < vel:
                found[it["full_name"]] = {"lane": lane, "vel": vel}
        time.sleep(pause)
    picked = {}
    for lane in (0, 1):
        ranked = sorted((kv for kv in found.items() if kv[1]["lane"] == lane),
                        key=lambda kv: -kv[1]["vel"])[:per_lane]
        picked.update(dict(ranked))
    return picked


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ------------------------------------------------------------ repo + issue gates
CLOSED_DOOR = re.compile(
    r"(not|n't|no longer) (currently )?(accept|accepting|taking|open to|able to accept)\w* "
    r"(any |external |outside |community |public )*(contribution|pull request|pr)s?|"
    r"contributions? (are|is) (not|currently not) (accepted|welcome)|"
    r"closed to (external |outside )?contribution", re.I)
OUTSIDER = {"CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"}
CLAIM = re.compile(
    r"\b(i('| a)?m (already |currently )?working on|"
    r"i('ll| will| can| would like to|'d like to| want to|'d love to) "
    r"(take|work on|pick|tackle|fix|implement|give (this|it) a|submit|open|send)|"
    r"working on (this|it|a fix|a pr|a patch)|assign (this |it )?to me|"
    r"(can|may|could) i (take|work on|pick|tackle|be assigned)|"
    r"i (have|opened|submitted|created|pushed) (a |an )?(pr|pull request|fix|patch|draft))\b|/assign", re.I)
SKIP_LABELS = re.compile(r"wontfix|won't fix|invalid|duplicate|stale|blocked|needs.?repro|"
                         r"waiting|on.?hold|spam|not planned", re.I)


def outside_merges(r):
    """How many of the last 30 merged PRs (within 90 days) came from non-members."""
    cutoff = NOW - timedelta(days=90)
    return sum(1 for p in r["pullRequests"]["nodes"]
               if p["authorAssociation"] in OUTSIDER and p["mergedAt"] and _dt(p["mergedAt"]) > cutoff)


INFRA_WORDS = re.compile(
    r"inference|serving|\bengine\b|runtime|framework|\bsdk\b|library|database|query|\bsql\b|compiler|tensor|"
    r"deep learning|distributed|gateway|\bproxy\b|lakehouse|package manager|kernel|\bgpu\b|cuda|protocol|"
    r"orchestrat|scheduler|storage|vector|embedding|training|quantiz|wasm|webassembly|allocator|sandbox|"
    r"foundation model|toolkit|compute|headless|code intelligence|memory system|data ?frame|"
    r"file format|parser|interpreter|virtual machine|\brpc\b|consensus|key-value|cache|operator", re.I)
APP_WORDS = re.compile(
    r"\bapps?\b|tracker|dashboard|video editor|photo editor|word processor|marketing|\bskills?\b|"
    r"account (manager|switch)|switcher|one-click|tutor|viral|menu bar|diagram|design vocabulary|alternative to|"
    r"(for|control|manage) (\w+ code|codex|cursor)\b|coding agents? (with|from)|\bnews\b|\bgym\b|at work|"
    r"wallpaper|template|boilerplate|awesome|prompts?\b|personal assistant|browser extension|\bui kit\b|"
    r"api key|free model|subscription|launcher|\bclient\b|chatbot|companion|plugin for|emulator|nintendo|"
    r"playstation|\bps[45]\b|\bgames?\b|trading|\bpersonal\b|codex|copilot|windsurf|enhanced tool|"
    r"reader and editor|\bpdf\b|logitech|\bmouse\b|wallet|crypto|social|e-?commerce|\bcms\b|blog", re.I)
CORE_LANGS = {"Rust", "C++", "C", "Zig", "Go", "Python", "Cuda", "Assembly", "Mojo"}


def domain_fit(desc, topics, lang):
    """0..1: infrastructure / systems software (the two lanes) rather than an end-user app."""
    text = f"{desc} {' '.join(topics)}"
    fit = 0.5 + 0.16 * len(set(m.lower() for m in INFRA_WORDS.findall(text))) \
        - 0.24 * len(set(m if isinstance(m, str) else m[0] for m in APP_WORDS.findall(text)))
    fit += 0.1 if lang in CORE_LANGS else -0.12
    return max(0.0, min(1.0, fit))


def repo_credibility(stars, age_days, vel, outside, seeded, fit=1.0):
    """0..1: is an outsider's merged PR here both likely and worth putting on a resume?

    Led by evidence that outsiders really get merged; star count and age guard against
    star-farmed or days-old hype, velocity keeps a little 'early traction', and domain
    fit scales the whole thing down for end-user apps.
    """
    cred = (0.45 * min(1.0, outside / 20)
            + 0.25 * min(1.0, math.log10(max(stars, 10)) / 5)
            + 0.20 * min(1.0, max(0, age_days - 30) / 335)
            + 0.10 * min(1.0, math.log10(1 + vel) / 2))
    cred *= 0.35 + 0.65 * fit
    return max(cred, 0.75) if seeded else cred


def repo_verdict(r, seeded=False):
    """Return None if outsiders can contribute, else the reason it is dropped."""
    if r is None:
        return "not found"
    if r["isArchived"] or r["isDisabled"]:
        return "archived"
    if not r["hasIssuesEnabled"]:
        return "issues disabled"
    outside = outside_merges(r)
    contributing = ((r.get("contributing") or {}).get("text") or "")[:20000]
    # Merged outside PRs are stronger evidence than wording: the text only decides
    # when few outsiders actually get merged (it often restricts one kind of PR).
    if outside < 5 and CLOSED_DOOR.search(contributing):
        return "CONTRIBUTING says no outside PRs"
    if outside < (2 if seeded else 4):
        return f"only {outside} outside PRs merged in 90d"
    return None


def issue_open_for_grabs(i):
    if i["assignees"]["totalCount"]:
        return False
    if (NOW - _dt(i["createdAt"])).days > ISSUE_WINDOW_DAYS:
        return False
    if any(SKIP_LABELS.search(l["name"]) for l in i["labels"]["nodes"]):
        return False
    for ev in i["timelineItems"]["nodes"]:
        src = ev.get("source") or ev.get("subject") or {}
        if src.get("__typename") == "PullRequest" and src.get("state") in ("OPEN", "MERGED"):
            return False
    return not any(CLAIM.search(c["bodyText"] or "") or DONE.search(c["bodyText"] or "")
                   for c in i["comments"]["nodes"])


# --------------------------------------------------------------- actionability
# Who filed an issue and whether a maintainer endorsed it predict "an outsider can
# land this" far better than the issue text (cf. GitHub's good-first-issues ranking,
# RecGFI, and the Kubernetes / Rust triage label conventions).
MAINT = {"MEMBER", "OWNER", "COLLABORATOR"}
DONE = re.compile(r"(fixed|addressed|resolved|implemented|landed) (in|by|on|via) (main|master|#\d+)|"
                  r"already (fixed|implemented|addressed|supported)|duplicate of|dup of #|"
                  r"working on (this|it) internally|on our (internal )?roadmap|will be (fixed|addressed|included) in", re.I)
READY_LABEL = re.compile(
    r"help.?wanted|good.?(first|second)|contributions?.?welcome|up.?for.?grabs|prs?.?welcome|"
    r"^e-(easy|medium|help-wanted|mentor)$|community.?backlog|ready.?for.?(implementation|work|dev)|"
    r"triage/ready|^ready$|hacktoberfest|bounty", re.I)
VETTED_LABEL = re.compile(
    r"^(triaged|accepted|confirmed|reproduced|approved|verified)$|triage/accepted|^backlog$|priority|severity|"
    r"^p[0-3]$|s-has-(mcve|bisection)|regression", re.I)
BLOCKED_LABEL = re.compile(
    r"needs?[-: _/]*(triage|info|more|repro|design|investigation|decision|discussion|feedback|clarification|author|sig)|"
    r"triage[-/: _]*need|untriaged|unconfirmed|awaiting|waiting|wait-|pending|blocked|stale|obsolete|duplicate|"
    r"invalid|wontfix|won't fix|not planned|in.?progress|\bwip\b|on.?hold|spam|cannot reproduce|not.?reproducible", re.I)
NOT_TASK_LABEL = re.compile(
    r"^(question|support|discussion|rfc|proposal|tracking|meta|epic|roadmap|announcement|showcase|usage)$|"
    r"kind/support|c-discussion|c-tracking|tracking.?issue", re.I)
NOT_TASK_TITLE = re.compile(
    r"^\W*(rfc|proposal|discussion|tracking|meta|epic|roadmap|question|announcement|showcase|survey|feedback)\b|"
    r"\[[^\]]*(rfc|benchmark|discussion|question|proposal|tracking|roadmap)[^\]]*\]|"
    r"tracking issue|field report|sharing results|design doc|^how (do|to|can|should)\b|is it possible|any plans?\b", re.I)
OWNED = re.compile(  # the author says they are doing it themselves
    r"\bi('ll| will| plan to| am going to|'m going to| intend to| would like to|'d like to|'d be happy to|'m happy to|"
    r" am happy to| can| could) (submit|open|send|raise|contribute|work on|put up|take (this|it)|tackle|pick (this|it))|"
    r"\bwe('ll| will| plan to| are going to| intend to) (submit|open|send|upstream|contribute|work on|implement)|"
    r"(happy|willing|glad|keen|able) to (submit|open|send|contribute|work on|implement|put up|help implement|"
    r"take (this|it)|upstream)|"
    r"\b(i|we) (have|'ve)( already)? (a |an )?(working |draft |initial |local |rough )?"
    r"(prototype|implementation|branch|patch|fix|poc|proof of concept|draft)\b|"
    r"(proposed|implemented|opened|submitted|available|addressed) in #\d+|/pull/\d+|"
    r"\b(my|our) (pr|pull request|branch|fork|prototype|patch)\b|pr (is )?(incoming|coming|to follow)|"
    r"will follow up with (a )?(pr|patch)", re.I)
MAINT_INVITE = re.compile(
    r"prs? (are |is |would be |very |more than )*(welcome|appreciated)|"
    r"happy to (review|accept|merge|take|look at) (a |the |any )?(pr|pull request|patch|contribution)|"
    r"contributions? (are |is |would be |very )*(welcome|appreciated)|"
    r"feel free to (open|submit|send|work on|take|pick|contribute|put up|give it)|"
    r"would (accept|welcome|merge|review|take) (a |the |any )?(pr|pull request|patch|contribution)|"
    r"(want|like|care|interested) to (open|submit|send|contribute|put up) (a |the )?(pr|pull request|patch)|"
    r"help (is |would be )?(wanted|welcome|appreciated)|open to (a |the )?(pr|pull request|contribution)", re.I)
MAINT_DECLINE = re.compile(
    r"no plans?\b|not planned|won'?t (fix|implement|support|be |add)|out of scope|not a priority|not something we|"
    r"can(no|')t reproduce|unable to reproduce|could ?n[o']t reproduce|need more (info|information|details)|"
    r"please (provide|share|attach|post)|(can|could) you (share|provide|post|attach|try)|closing (this|as)|"
    r"works as (intended|designed|expected)|by design|not a bug|expected behaviou?r|already (tracked|covered) in", re.I)
REPORT_TITLE = re.compile(r"performance report|\bvs\.? .*comparison|comparison$|^call for\b|meet-?up|"
                          r"\bsurvey\b|release notes|changelog|\bamas?\b", re.I)
COMMIT_STYLE = re.compile(r"^(fix|feat|chore|ci|refactor|perf|test|build|docs|style)(\([^)]*\))?!?:", re.I)
WILLING_BOX = re.compile(
    r"\[x\][^\n]{0,90}(willing|submit a (pr|pull request)|i can (help|contribute)|i would like to work|i'd like to work)", re.I)


def issue_refs(full, number, body):
    """Issue/PR numbers of this repo that the issue text mentions (GitHub only links PR -> issue, not this way)."""
    found = re.findall(r"(?<![\w/])#(\d{2,7})\b", body)
    found += re.findall(r"github\.com/" + re.escape(full) + r"/(?:pull|issues)/(\d{2,7})", body, re.I)
    return [n for n in dict.fromkeys(int(x) for x in found) if n != number][:6]


def open_prs_among(full, numbers):
    """Which of these numbers are open pull requests: one batched GraphQL query per 40."""
    owner, name = full.split("/", 1)
    numbers, is_open = sorted(set(numbers)), set()
    for k in range(0, len(numbers), 40):
        chunk = numbers[k:k + 40]
        fields = " ".join(f"n{n}: issueOrPullRequest(number:{n}){{__typename ... on PullRequest{{state}}}}" for n in chunk)
        out = gh("https://api.github.com/graphql",
                 {"query": f"query($owner:String!,$name:String!){{repository(owner:$owner,name:$name){{{fields}}}}}",
                  "variables": {"owner": owner, "name": name}})
        repo = (out.get("data") or {}).get("repository") or {}
        for n in chunk:
            node = repo.get(f"n{n}") or {}
            if node.get("__typename") == "PullRequest" and node.get("state") == "OPEN":
                is_open.add(n)
    return is_open


def actionability(c):
    """(tier, reason): tier 0 ready, 1 vetted, 2 raw; tier None means not pick-up-able."""
    labels, title, body = c["labels"], c["title"], c.get("body_md") or c["body"]
    if c.get("is_bot"):
        return None, "filed by a bot"
    blocked = next((l for l in labels if BLOCKED_LABEL.search(l)), None)
    if blocked:
        return None, "blocked label: " + blocked.lower()
    if OWNED.search(body) or WILLING_BOX.search(body):
        return None, "author is doing it"
    if sum(ord(ch) > 0x2E7F for ch in title) > 0.3 * max(1, len(title)):
        return None, "not in english"
    said = c.get("maint_text") or ""
    if said and MAINT_DECLINE.search(said):
        return None, "maintainer declined or asked for info"
    ready = next((l for l in labels if READY_LABEL.search(l)), None)
    if ready:
        return 0, ready.lower()
    not_task = next((l for l in labels if NOT_TASK_LABEL.search(l)), None)
    if not_task or NOT_TASK_TITLE.search(title) or REPORT_TITLE.search(title):
        return None, "discussion, not a task"
    if said and MAINT_INVITE.search(said):
        return 0, "maintainer invited a pr"
    vetted = next((l for l in labels if VETTED_LABEL.search(l)), None)
    if vetted:
        return 1, vetted.lower()
    if c.get("assoc") in MAINT:
        # Core authors mostly close their own issues: without an invitation label this is their to-do list.
        if COMMIT_STYLE.search(title):
            return None, "author is doing it"
        return 2, "maintainer's own item"
    if c.get("maint_replied"):
        return 1, "maintainer replied"
    return 2, "unvetted"


# -------------------------------------------------------------------- scoring
KIND_ANCHORS = {
    "feature": ["add support for a new feature", "implement new functionality or API", "feature request: allow users to"],
    "perf": ["performance regression, this is slow", "optimize throughput, latency or memory usage", "reduce allocations and speed up the hot path"],
    "bug": ["bug: crashes with an error or panic", "incorrect result, unexpected behavior", "fails with exception, stack trace attached"],
    "research": ["implement the algorithm from this paper", "new model architecture or numerical method", "prototype a novel technique and benchmark it"],
    "infra": ["build system, CI pipeline, packaging or release tooling", "docker image, wheels, cross compilation"],
    "refactor": ["refactor internal code structure", "clean up technical debt, simplify module"],
    "test": ["add missing unit tests", "flaky test in the test suite"],
    "question": ["how do I use this, question about usage", "need help with my configuration"],
    "docs": ["fix typo in the documentation", "update README, add an example to the docs", "docstring is unclear or outdated"],
}
SECTOR_ANCHORS = {
    "inference-serving": "LLM inference server, batching, token throughput, model serving",
    "agents": "AI agents, tool calling, multi-agent orchestration, workflows",
    "training": "model training, fine-tuning, optimizers, distributed training",
    "gpu-kernels": "CUDA, GPU kernels, tensor ops, quantization, accelerators",
    "rag-data": "retrieval, embeddings, vector search, data pipelines",
    "evals": "benchmarks, evaluation harness, observability, tracing",
    "compilers": "compiler, parser, type checker, code generation, language tooling",
    "databases": "database engine, storage, query planner, indexing, transactions",
    "distributed": "distributed systems, consensus, scheduling, cluster, networking, RPC",
    "runtime": "async runtime, memory allocator, concurrency, operating system, kernel",
    "wasm-web": "WebAssembly, browser engine, rendering, UI framework",
    "crypto-sec": "cryptography, zero knowledge proofs, security, sandboxing",
    "devtools": "CLI tool, package manager, build tool, editor, developer experience",
}
SUBSTANTIAL = ["design and implement a substantial new subsystem",
               "non-trivial engineering change touching core architecture",
               "implement an algorithm with careful performance and correctness work"]
TRIVIAL = ["fix a small typo", "minor wording change", "bump a dependency version",
           "simple question about how to use it"]


JUNK = re.compile(r"airdrop|micro-?payments?|boost your|giveaway|backlinks?|\bseo\b|sponsor(ed|ship)|"
                  r"promo(tion| code)|earn (money|crypto|rewards)|listed your (tool|project)", re.I)
SCORE_V = 4  # bump when scoring rules change so cached verdicts are recomputed


def issue_text(c):
    return f"{c['title']}. {c['body'][:900]}"


class EmbedScorer:
    """Zero-shot scoring with a small ONNX embedding model (no API key)."""
    name = "embed:bge-small-en-v1.5"

    def __init__(self):
        import numpy as np
        from fastembed import TextEmbedding
        self.np = np
        self.model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=os.environ.get("VOTHUB_MODEL_DIR"))
        self.kind = {k: self.embed(v) for k, v in KIND_ANCHORS.items()}
        self.sectors = list(SECTOR_ANCHORS)
        self.sector = self.embed(list(SECTOR_ANCHORS.values()))
        self.big, self.small = self.embed(SUBSTANTIAL), self.embed(TRIVIAL)

    def embed(self, texts):
        v = self.np.array(list(self.model.embed(texts)))
        return v / self.np.linalg.norm(v, axis=1, keepdims=True)

    def score(self, cands):
        vecs = self.embed([issue_text(c) for c in cands])
        out = []
        for c, v in zip(cands, vecs):
            kind = max(self.kind, key=lambda k: float((self.kind[k] @ v).max()))
            sector = self.sectors[int((self.sector @ v).argmax())]
            spread = float((self.big @ v).max() - (self.small @ v).max())
            out.append(_finish(c, kind, sector, 50 + spread * 260))
        return out


class HeuristicScorer:
    """Last-resort fallback when no model can be loaded; flagged in the feed."""
    name = "heuristic"
    RULES = [("docs", r"typo|readme|\bdocs?\b|documentation|docstring"), ("perf", r"perf|slow|latency|throughput|memory"),
             ("bug", r"bug|crash|panic|error|fail|regression"), ("question", r"^how |question|\?$"),
             ("test", r"\btests?\b|flaky"), ("research", r"paper|arxiv|algorithm"), ("infra", r"\bci\b|build|docker|release")]

    def score(self, cands):
        out = []
        for c in cands:
            head = (c["title"] + " " + " ".join(c["labels"])).lower()
            kind = next((k for k, rx in self.RULES if re.search(rx, head)), "feature")
            out.append(_finish(c, kind, LANES[c["lane"]], 45))
        return out


def _finish(c, kind, sector, base):
    """Blend the model signal with structural evidence of how big the change is."""
    labels = " ".join(c["labels"]).lower()
    title = c["title"].lower()
    # an explicit title prefix beats the model's guess at the kind
    if re.search(r"\[\s*bug\s*\]|^bug\s*[:(]", title):
        kind = "bug"
    elif kind not in ("perf", "research") and re.search(
            r"\[\s*(feature|feat|enhancement)( request)?\s*\]|^(feature request|feat\b|proposal)", title):
        kind = "feature"
    if kind in ("docs", "question") and not re.search(
            r"\bdocs?\b|documentation|readme|typo|docstring|\bguide\b|tutorial|how (do|to|can)|\?\s*$|question|usage",
            title + " " + labels):
        kind = "bug" if re.search(r"bug|crash|fail|error|panic|regression|broken|wrong", title + " " + labels) else "feature"
    s = base + min(9, len(c["body"]) / 320) + min(8, c["reactions"] * 2) + min(6, c["comments"])
    if re.search(r"enhancement|feature|perf|epic", labels):
        s += 5
    if re.search(r"```|traceback|stack trace|steps to reproduce|minimal repro|panicked at|bisect", c.get("body_md") or c["body"], re.I):
        s += 5  # concrete evidence: code, a trace, a repro
    if len(re.findall(r"\w+", title)) < 3:
        s -= 30  # one- or two-word titles are almost never real work items
    if JUNK.search(title + " " + c["body"][:400]):
        s -= 45
    effort = "L" if s >= 70 else "M" if s >= 48 else "S"
    bits = [kind, f"{len(c['body']) // 100 * 100}+ chars" if len(c["body"]) > 300 else "short report"]
    if c["reactions"]:
        bits.append(f"{c['reactions']} reactions")
    return {"s": int(max(3, min(97, s))), "k": kind, "sec": sector, "e": effort, "why": " / ".join(bits)}


def pick_scorer():
    try:
        return EmbedScorer()
    except Exception as e:
        log("embedding model unavailable, falling back to heuristics:", e)
        return HeuristicScorer()


def priority(c, sc):
    """Blend: is it ready (tier), is the repo worth it (cred), is it real work (substance)."""
    labels = " ".join(c["labels"]).lower()
    if re.search(r"\bdocs?\b|documentation|typo", labels):
        sc["k"] = "docs"  # maintainers' own label wins: docs always sink
    fresh = max(0.0, 1 - c["age_days"] / ISSUE_WINDOW_DAYS)
    p = 0.42 * sc["s"] + 26 * c["cred"] + 8 * fresh + (24, 12, -10)[c["tier"]]
    if sc["s"] < 45:
        p -= 8          # ready but tiny: fine to do, not much to show for it
    if c["tier"] == 2:
        p = min(p, 58)  # nobody from the project has looked at it yet
    if sc["k"] == "docs":
        p *= 0.2
    elif sc["k"] == "question":
        p *= 0.45
    return int(max(1, min(99, p)))


def rank(cands):
    """Docs last, then priority; cap per repo, and admit unvetted issues only as a tail."""
    cands.sort(key=lambda c: (c["sc"]["k"] == "docs", -c["pri"]))
    per_repo, raw, ranked = {}, 0, []
    for c in cands:
        if per_repo.get(c["repo"], 0) >= MAX_PER_REPO or len(ranked) >= MAX_FEED:
            continue
        if c["tier"] == 2:
            if raw >= MAX_RAW:
                continue
            raw += 1
        per_repo[c["repo"]] = per_repo.get(c["repo"], 0) + 1
        ranked.append(c)
    return ranked


# ----------------------------------------------------------------------- feed
def load_gz(path, default):
    try:
        return json.loads(gzip.decompress(Path(path).read_bytes()))
    except Exception:
        return default


def save_gz(path, obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    Path(path).write_bytes(gzip.compress(raw, 9, mtime=0))
    return len(raw)


def fixture():
    """Synthetic repos/issues so scoring and feed building can be tested offline."""
    def issue(n, title, body, labels=(), react=0, days=3, assoc="NONE"):
        t = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"number": n, "title": title, "bodyText": body, "body": body, "createdAt": t, "updatedAt": t,
                "authorAssociation": assoc, "author": {"__typename": "User"},
                "assignees": {"totalCount": 0}, "labels": {"nodes": [{"name": l} for l in labels]},
                "comments": {"totalCount": 2, "nodes": []}, "reactions": {"totalCount": react},
                "timelineItems": {"nodes": []}}
    merged = (NOW - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prs = {"nodes": [{"authorAssociation": "CONTRIBUTOR", "mergedAt": merged}] * 5}
    base = {"isArchived": False, "isFork": False, "isDisabled": False, "hasIssuesEnabled": True,
            "contributing": None, "pullRequests": prs, "repositoryTopics": {"nodes": []},
            "createdAt": (NOW - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    long = "We need to redesign the scheduler so that requests are batched across replicas. " * 12
    return {
        "demo/fastserve": dict(base, nameWithOwner="demo/fastserve", description="High-throughput LLM inference server",
                               stargazerCount=9400, primaryLanguage={"name": "Python"}, issues={"nodes": [
            issue(101, "Continuous batching stalls under mixed prompt lengths", long, ["performance"], 14, 2),
            issue(102, "Typo in README quickstart", "s/recieve/receive", ["documentation"], 0, 1),
            issue(103, "Support speculative decoding with draft models", long, ["enhancement", "help wanted"], 22, 6),
            issue(104, "How do I set the port?", "Which flag sets the port?", ["question"], 0, 1),
            issue(105, "[RFC] Multi-GPU partial expert offload", long + " An initial implementation has been proposed in #317.", [], 30, 2),
            issue(106, "Scheduler deadlocks when a replica restarts mid-batch", long, ["bug", "needs triage"], 5, 2),
            issue(107, "Add per-tenant rate limiting to the batch queue", long, ["enhancement", "priority: medium"], 4, 5, "MEMBER"),
            issue(108, "Streaming responses drop the final token", long + " I'd be happy to submit a PR.", ["bug"], 6, 2)]}),
        "demo/oxidb": dict(base, nameWithOwner="demo/oxidb", description="Embedded columnar database in Rust",
                           stargazerCount=3100, primaryLanguage={"name": "Rust"}, issues={"nodes": [
            issue(7, "Implement vectorized hash join from the paper", long, ["enhancement"], 9, 4),
            issue(8, "Panic in WAL replay after partial write", "thread main panicked at wal.rs " * 20, ["bug"], 3, 9),
            issue(9, "Docs: explain compaction settings", "The docs page is missing compaction.", ["docs"], 1, 3)]}),
        "demo/closed": dict(base, nameWithOwner="demo/closed", description="Vendor SDK", stargazerCount=5000,
                            primaryLanguage={"name": "C++"}, pullRequests={"nodes": []}, issues={"nodes": [
            issue(1, "Add feature", long)]}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--per-lane", type=int, default=32)
    ap.add_argument("--max-queries", type=int, default=None)
    ap.add_argument("--fixture", action="store_true", help="offline run on synthetic data")
    ap.add_argument("--discover-only", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    now_s = int(NOW.timestamp())
    cutoff = now_s - KEEP_DAYS * 86400

    cache = load_gz(out / "cache.json.gz", {})
    cache = {"repos": cache.get("repos", {}), "issues": cache.get("issues", {})}
    prev_feed = load_gz(out / "feed.json.gz", {})

    # 1. which repos
    if args.fixture:
        fake = fixture()
        targets = {n: {"lane": 1 if "oxidb" in n else 0, "vel": r["stargazerCount"] / 120} for n, r in fake.items()}
    else:
        seeds = json.loads((HERE / "seeds.json").read_text())
        targets = discover(args.per_lane, args.max_queries)
        log(f"discovered {len(targets)} trending repos")
        if args.discover_only:
            for n, t in sorted(targets.items(), key=lambda kv: -kv[1]["vel"]):
                print(f"{LANES[t['lane']]:9} {t['vel']:7.1f}/day  {n}")
            return
        for lane_name, names in seeds.items():
            for n in names:
                targets.setdefault(n, {"lane": LANES.index(lane_name), "vel": None})

    # 2. repo gate + issue gate
    repos, cands, dropped, rejected = {}, [], 0, {}
    for full, t in targets.items():
        memo = cache["repos"].get(full)
        if memo and memo.get("v") == SCORE_V and memo["t"] > now_s - 3 * 86400:  # known closed-door repo: skip the API call
            dropped += 1
            continue
        try:
            r = fake[full] if args.fixture else fetch_repo(full)
        except Exception as e:
            log(f"  {full}: fetch failed ({e})")
            continue
        seeded = t["vel"] is None
        fit = domain_fit(r.get("description") or "", [n["topic"]["name"] for n in r["repositoryTopics"]["nodes"]],
                         (r.get("primaryLanguage") or {}).get("name"))
        why_not = repo_verdict(r, seeded)
        if not why_not and not seeded and fit < 0.5:
            why_not = f"end-user app, not infra/systems (fit {fit:.2f})"
        if why_not:
            log(f"  drop {full}: {why_not}")
            cache["repos"][full] = {"t": now_s, "why": why_not, "v": SCORE_V}
            dropped += 1
            continue
        age = max(14, (NOW - _dt(r["createdAt"])).days)
        vel = r["stargazerCount"] / age if seeded else t["vel"]
        cred = repo_credibility(r["stargazerCount"], age, vel, outside_merges(r), seeded, fit)
        repos[full] = {"stars": r["stargazerCount"], "vel": vel, "lane": t["lane"], "cred": cred,
                       "lang": (r.get("primaryLanguage") or {}).get("name") or "?",
                       "desc": (r.get("description") or "")[:110]}
        mine = []
        for i in r["issues"]["nodes"]:
            if issue_open_for_grabs(i):
                c = {
                    "repo": full, "num": i["number"], "title": i["title"][:140], "body": i["bodyText"] or "",
                    "body_md": i.get("body") or "", "assoc": i.get("authorAssociation"), "cred": cred,
                    "is_bot": (i.get("author") or {}).get("__typename") == "Bot",
                    "maint_replied": any(cm.get("authorAssociation") in MAINT for cm in i["comments"]["nodes"]),
                    "maint_text": " ".join((cm.get("bodyText") or "")[:1500] for cm in i["comments"]["nodes"]
                                           if cm.get("authorAssociation") in MAINT),
                    "labels": [l["name"] for l in i["labels"]["nodes"]], "updated": i["updatedAt"],
                    "created_h": int(_dt(i["createdAt"]).timestamp() // 3600),
                    "age_days": (NOW - _dt(i["createdAt"])).days, "comments": i["comments"]["totalCount"],
                    "reactions": i["reactions"]["totalCount"], "vel": vel, "lane": t["lane"],
                    "desc": repos[full]["desc"]}
                c["tier"], c["reason"] = actionability(c)
                if c["tier"] is None:
                    rejected[c["reason"].split(":")[0]] = rejected.get(c["reason"].split(":")[0], 0) + 1
                else:
                    c["refs"] = issue_refs(full, c["num"], c["body_md"])
                    mine.append(c)
        if not args.fixture and any(c["refs"] for c in mine):
            try:  # someone already has a PR open for it, even though GitHub shows no link on the issue
                taken = open_prs_among(full, [n for c in mine for n in c["refs"]])
                for c in [c for c in mine if taken.intersection(c["refs"])]:
                    mine.remove(c)
                    rejected["open pr referenced"] = rejected.get("open pr referenced", 0) + 1
            except Exception as e:
                log(f"  {full}: reference check failed ({e})")
        cands.extend(mine)
    log(f"{len(repos)} repos open to outsiders, {dropped} dropped, {len(cands)} actionable issues")
    log("  not pick-up-able:", ", ".join(f"{k} {v}" for k, v in sorted(rejected.items(), key=lambda kv: -kv[1])) or "none")
    log("  tiers:", ", ".join(f"{TIERS[n]} {sum(c['tier'] == n for c in cands)}" for n in range(3)))

    # 3. score, reusing cached verdicts for issues that have not changed
    def stale(c):
        entry = cache["issues"].get(f"{c['repo']}#{c['num']}", {})
        return entry.get("u") != c["updated"] or entry.get("v") != SCORE_V

    fresh = [c for c in cands if stale(c)]
    scorer_name = prev_feed.get("scorer", "cache")
    if fresh:
        scorer = pick_scorer()
        scorer_name = scorer.name
        log(f"scoring {len(fresh)} new/changed issues with {scorer.name} ({len(cands) - len(fresh)} cached)")
        for c, sc in zip(fresh, scorer.score(fresh)):
            key = f"{c['repo']}#{c['num']}"
            first = cache["issues"].get(key, {}).get("first", now_s)
            cache["issues"][key] = {"u": c["updated"], "sc": sc, "first": first, "v": SCORE_V}
    for c in cands:
        entry = cache["issues"][f"{c['repo']}#{c['num']}"]
        entry["seen"] = now_s
        c["sc"], c["first"] = entry["sc"], entry["first"]
        c["pri"] = priority(c, c["sc"])

    # 4. rank: docs last, then by priority; cap per repo, unvetted only as a tail
    ranked = rank(cands)

    # 5. compact feed: string tables + positional rows, gzipped
    names = sorted({c["repo"] for c in ranked})
    tags = []

    def tag(t):
        t = t.lower()[:24]
        if t not in tags:
            tags.append(t)
        return tags.index(t)

    last_run = (prev_feed.get("runs") or [[0]])[-1][0] * 3600
    rows = []
    for c in ranked:
        sc = c["sc"]
        extra = [tag(l) for l in c["labels"] if re.search(r"help.?wanted|good.?first|rfc|perf|epic", l, re.I)][:3]
        rows.append([names.index(c["repo"]), c["num"], c["title"], c["pri"], sc["s"],
                     KINDS.index(sc["k"]) if sc["k"] in KINDS else 0, EFFORTS.index(sc["e"]) if sc["e"] in EFFORTS else 1,
                     tag(sc["sec"]), extra, c["created_h"], c["comments"], c["reactions"],
                     f"{c['reason']} / {sc['why']}"[:90], 1 if c["first"] > last_run else 0, c["tier"]])
    runs = [r for r in prev_feed.get("runs", []) if r[0] * 3600 > cutoff]
    runs.append([now_s // 3600, len(targets), len(repos), len(ranked), sum(r[13] for r in rows),
                 rows[0][3] if rows else 0])
    feed = {"v": 1, "gen": now_s, "scorer": scorer_name, "kinds": KINDS, "efforts": EFFORTS, "lanes": LANES, "tiers": TIERS,
            "tags": tags,
            "repos": [[n, repos[n]["stars"], int(repos[n]["vel"] * 10), repos[n]["lang"], repos[n]["lane"],
                       repos[n]["desc"]] for n in names],
            "issues": rows, "runs": runs[-2 * KEEP_DAYS:]}

    # 6. prune cache to the retention window and write both files
    cache["issues"] = {k: v for k, v in cache["issues"].items() if v.get("seen", 0) > cutoff}
    cache["repos"] = {k: v for k, v in cache["repos"].items() if v["t"] > cutoff}
    raw = save_gz(out / "feed.json.gz", feed)
    save_gz(out / "cache.json.gz", cache)
    log(f"feed: {len(rows)} issues / {len(names)} repos, {raw} bytes raw, "
        f"{(out / 'feed.json.gz').stat().st_size} bytes gzipped")


if __name__ == "__main__":
    main()
