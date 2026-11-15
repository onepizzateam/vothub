"""Generates the animated CRT panels used by README.md.  Run: python docs/make_panels.py"""
import math
import random
from pathlib import Path

OUT = Path(__file__).parent
BG, LINE, DIM, FG, HOT, AMBER, RED = "#040806", "#17402a", "#2f7a4f", "#72f5a2", "#c9ffd9", "#ffb84a", "#ff5d4d"

STYLE = f"""
text{{font-family:Consolas,'Cascadia Mono','DejaVu Sans Mono','Liberation Mono','Courier New',monospace}}
.g{{fill:{FG}}}.h{{fill:{HOT}}}.d{{fill:{DIM}}}.a{{fill:{AMBER}}}.r{{fill:{RED}}}.k{{fill:{BG}}}
.glow{{filter:url(#glow)}}
.blink{{animation:blink 1.2s steps(1) infinite}}
@keyframes blink{{50%{{opacity:.12}}}}
.band{{animation:band 6s linear infinite}}
@keyframes band{{from{{transform:translateY(-140px)}}to{{transform:translateY(VHpx)}}}}
.jit{{animation:jit 7s steps(1) infinite}}
@keyframes jit{{0%,91%,100%{{transform:translate(0,0)}}92%{{transform:translate(-5px,0)}}94%{{transform:translate(4px,1px)}}96%{{transform:translate(-2px,0)}}}}
"""


def frame(w, h, body, extra_css="", border=DIM):
    css = STYLE.replace("VH", str(h + 140)) + extra_css
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">
<defs>
<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect y="3" width="4" height="1" fill="#000" opacity=".38"/></pattern>
<radialGradient id="vig" cx="50%" cy="50%" r="72%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".62"/></radialGradient>
<linearGradient id="bandg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{FG}" stop-opacity="0"/><stop offset=".5" stop-color="{FG}" stop-opacity=".07"/><stop offset="1" stop-color="{FG}" stop-opacity="0"/></linearGradient>
<clipPath id="screen"><rect width="{w}" height="{h}" rx="12"/></clipPath>
</defs>
<style>{css}</style>
<g clip-path="url(#screen)">
<rect width="{w}" height="{h}" fill="{BG}"/>
{body}
<rect width="{w}" height="{h}" fill="url(#scan)"/>
<rect class="band" width="{w}" height="140" fill="url(#bandg)"/>
<rect width="{w}" height="{h}" fill="url(#vig)"/>
</g>
<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="12" fill="none" stroke="{border}" stroke-width="2"/>
</svg>
"""


def t(x, y, s, cls="g", size=16, anchor="start", extra=""):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}" text-anchor="{anchor}" {extra}>{s}</text>'


def wave_points(x0, y0, w, h, peaks, seed, n=150, noise=0.07):
    rnd = random.Random(seed)
    pts = []
    for i in range(n + 1):
        u = i / n
        y = rnd.random() * noise
        for pos, amp in peaks:
            d = (u - pos) * 55
            y += amp * 0.85 * math.exp(-d * d) * (0.85 + rnd.random() * 0.3)
        pts.append(f"{x0 + u * w:.1f},{y0 + h - 4 - min(1, y) * (h - 10):.1f}")
    return " ".join(pts)


def scope(x, y, w, h, peaks, color=FG, frames=4, width=2):
    grid = "".join(f'<line x1="{x + w * i / 8:.0f}" y1="{y}" x2="{x + w * i / 8:.0f}" y2="{y + h}" stroke="{LINE}"/>' for i in range(1, 8))
    grid += "".join(f'<line x1="{x}" y1="{y + h * i / 3:.0f}" x2="{x + w}" y2="{y + h * i / 3:.0f}" stroke="{LINE}"/>' for i in (1, 2))
    variants = [wave_points(x, y, w, h, peaks, s) for s in range(frames)]
    values = ";".join(variants + variants[:1])
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#020503" stroke="{LINE}"/>{grid}'
            f'<polyline class="glow" fill="none" stroke="{color}" stroke-width="{width}" points="{variants[0]}">'
            f'<animate attributeName="points" dur="{frames * 0.22:.2f}s" repeatCount="indefinite" calcMode="discrete" values="{values}"/></polyline>')


PEAKS = [(0.08, 0.62), (0.17, 0.98), (0.26, 0.5), (0.57, 0.97), (0.67, 0.9), (0.8, 0.14), (0.9, 0.7)]


def lamp(x, y, color=FG):
    return f'<circle class="blink glow" cx="{x}" cy="{y}" r="6" fill="{color}"/>'


def button(x, y, w, h, label, color=RED, filled=False, size=15):
    fill = color if filled else "none"
    cls_color = BG if filled else color
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{color}" stroke-width="1.5"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + size * 0.36:.0f}" fill="{cls_color}" font-size="{size}" text-anchor="middle" letter-spacing="2">{label}</text>')


# ------------------------------------------------------------------ header
def header():
    w, h = 1200, 400
    log = ["> 64 trending repos located. 18 rejected: closed to outsiders.",
           "> 1133 unclaimed signals received. 240 kept. docs sunk to the bottom.",
           "> strongest signal: vllm-project/vllm // score 96"]
    body = [scope(-20, 60, w + 40, 190, PEAKS, color=LINE, width=3).replace('class="glow" ', "")]
    body.append(f'<rect width="{w}" height="52" fill="#07100b"/><line x1="0" y1="52" x2="{w}" y2="52" stroke="{DIM}"/>')
    body.append(lamp(30, 27))
    body.append(t(48, 33, "STATION ONLINE", "d", 15, extra='letter-spacing="3"'))
    body.append(t(w - 28, 33, "SIGNAL LOCKED", "a", 15, "end", 'letter-spacing="3"'))
    body.append(f'<g class="jit">{t(w / 2 + 14, 178, "VOTHUB", "h glow", 124, "middle", "font-weight=\"700\" letter-spacing=\"28\"")}</g>')
    body.append(t(w / 2, 222, "DEEP REPO LISTENING POST", "g", 17, "middle", 'letter-spacing="9" word-spacing="16"'))
    body.append(f'<line x1="60" y1="252" x2="{w - 60}" y2="252" stroke="{LINE}"/>')
    cycle = 14
    for i, line in enumerate(log):
        y = 288 + i * 30
        t0, t1 = (0.6 + i * 2.6) / cycle, (0.6 + i * 2.6 + 2.0) / cycle
        body.append(f'<clipPath id="c{i}"><rect x="60" y="{y - 20}" height="28" width="0">'
                    f'<animate attributeName="width" dur="{cycle}s" repeatCount="indefinite" calcMode="linear" '
                    f'keyTimes="0;{t0:.3f};{t1:.3f};1" values="0;0;1080;1080"/></rect></clipPath>')
        body.append(f'<g clip-path="url(#c{i})">{t(60, y, line, "g glow", 19)}</g>')
    body.append(t(60, 288 + 3 * 30, ">", "g", 19))
    body.append(f'<rect class="blink" x="78" y="{288 + 3 * 30 - 15}" width="11" height="19" fill="{FG}"/>')
    return frame(w, h, "\n".join(body))


# ---------------------------------------------------------------- mini tab
def tab_body(w, h, halted=False):
    fg, hot, dim, line = (("#9a8a5a", "#d8c890", "#5c5236", "#3a3322") if halted else (FG, HOT, DIM, LINE))
    b = [f'<circle cx="30" cy="34" r="6" fill="{fg}"' + ('' if halted else ' class="blink glow"') + '/>']
    b.append(f'<text x="46" y="41" fill="{hot}" font-size="20" font-weight="700" letter-spacing="4">VOTHUB</text>')
    b.append(f'<text x="158" y="40" fill="{AMBER}" font-size="15" letter-spacing="2">{"HALTED" if halted else "LISTENING"}</text>')
    b.append(button(w - 132, 18, 108, 32, "RESUME", AMBER) if halted else button(w - 112, 18, 88, 32, "HALT"))
    if halted:
        pts = wave_points(24, 66, w - 48, 150, PEAKS, 9, noise=0)
        b.append(f'<rect x="24" y="66" width="{w - 48}" height="150" fill="#020503" stroke="{line}"/>'
                 f'<polyline fill="none" stroke="{fg}" stroke-width="2" points="{pts}"/>')
    else:
        b.append(scope(24, 66, w - 48, 150, PEAKS))
    cw = (w - 48) / 4
    for i, (v, k) in enumerate([("240", "SIGNALS"), ("12", "READY"), ("96", "TOP"), ("74", "REPOS")]):
        x = 24 + i * cw
        b.append(f'<rect x="{x:.0f}" y="228" width="{cw:.0f}" height="74" fill="#07100b" stroke="{line}"/>')
        b.append(f'<text x="{x + cw / 2:.0f}" y="266" fill="{hot}" font-size="32" font-weight="700" text-anchor="middle">{v}</text>')
        b.append(f'<text x="{x + cw / 2:.0f}" y="290" fill="{dim}" font-size="12" text-anchor="middle" letter-spacing="3">{k}</text>')
    return b, (fg, hot, dim)


def tab():
    w, h = 640, 400
    b, _ = tab_body(w, h)
    tick = ["> vllm-project/vllm: [RFC] Kernel-owned LoRA fusion for quant...",
            "> sgl-project/sglang: [RFC] Large-scale MoE inference with mul...",
            "> sgl-project/sglang: EAGLE tree verify without per-node stat..."]
    for i, line in enumerate(tick):
        b.append(f'<g class="tk" style="animation-delay:{i * 4}s">{t(24, 336, line, "h", 16)}</g>')
    b.append(t(24, 374, "NEXT SCAN 04:21:07", "d", 13, extra='letter-spacing="1"'))
    b.append(t(w - 24, 374, "SIGNAL LOCKED", "d", 13, "end", 'letter-spacing="1"'))
    css = ".tk{opacity:0;animation:tk 12s linear infinite}@keyframes tk{0%{opacity:0}3%,30%{opacity:1}33.4%,100%{opacity:0}}"
    return frame(w, h, "\n".join(b), css)


# ------------------------------------------------------------ halt sequence
def halt():
    w, h = 640, 400
    live, _ = tab_body(w, h)
    live.append(t(24, 336, "> one click on HALT ...", "h", 16))
    live.append(f'<rect class="blink" x="{w - 116}" y="14" width="96" height="40" fill="none" stroke="{RED}" stroke-width="2"/>')

    step1 = [f'<rect x="60" y="56" width="{w - 120}" height="288" fill="{BG}" stroke="{RED}" stroke-width="2"/>',
             f'<text x="86" y="100" fill="{RED}" font-size="20" letter-spacing="5">HALT ALL OPERATIONS</text>',
             t(86, 132, "For how long?", "g", 16)]
    opts = ["1 HOUR", "4 HOURS", "12 HOURS", "UNTIL 7 AM"]
    for i, o in enumerate(opts):
        x, y = 86 + (i % 2) * 238, 152 + (i // 2) * 50
        step1.append(button(x, y, 226, 38, o, RED, filled=(i == 1)))
    step1.append(button(86, 252, 464, 38, "UNTIL I RESUME IT", RED))
    step1.append(button(86, 300, 464, 34, "CANCEL", FG))

    step2 = [f'<rect x="60" y="96" width="{w - 120}" height="208" fill="{BG}" stroke="{RED}" stroke-width="2"/>',
             f'<text x="86" y="142" fill="{RED}" font-size="20" letter-spacing="5">ARE YOU SURE?</text>',
             t(86, 178, "Everything stops for 4 hours.", "g", 16),
             t(86, 204, "No syncing. No probing. No animation.", "d", 14),
             button(86, 232, 226, 44, "YES, HALT", RED, filled=True),
             button(324, 232, 226, 44, "NO, KEEP LISTENING", FG, size=13)]

    dead, (fg, hot, dim) = tab_body(w, h, halted=True)
    dead.append(f'<text x="24" y="336" fill="{hot}" font-size="16">&gt; station silent. one click resumes.</text>')
    dead.append(f'<text x="24" y="374" fill="{dim}" font-size="13" letter-spacing="1">HALTED 03:59:58</text>')
    dead.append(f'<text x="{w - 24}" y="374" fill="{dim}" font-size="13" text-anchor="end" letter-spacing="1">HALTED BY OPERATOR</text>')

    groups = [live, step1, step2, dead]
    body = "".join(f'<g class="s s{i}">{"".join(g)}</g>' for i, g in enumerate(groups))
    css = ".s{opacity:0;animation:16s linear infinite}"
    for i in range(4):
        a, z = i * 25, i * 25 + 25
        frames = f"0%,{a - 0.01:.2f}%{{opacity:0}}{a}%,{z - 0.5}%{{opacity:1}}{z}%,100%{{opacity:0}}" if i else f"0%,{z - 0.5}%{{opacity:1}}{z}%,100%{{opacity:0}}"
        css += f".s{i}{{animation-name:k{i}}}@keyframes k{i}{{{frames}}}"
    return frame(w, h, body, css)


# ---------------------------------------------------------------- pipeline
def pipeline():
    w, h = 1200, 430
    b = [t(40, 44, "SIGNAL PATH", "d", 15, extra='letter-spacing="5"'),
         t(w - 40, 44, "CLOUD -> LAPTOP", "d", 15, "end", 'letter-spacing="5"')]
    # cloud box
    b.append(f'<rect x="40" y="66" width="600" height="324" fill="#07100b" stroke="{DIM}"/>')
    b.append(t(60, 98, "GITHUB ACTIONS", "h", 18, extra='letter-spacing="3" font-weight="700"'))
    b.append(t(620, 98, "06:15 + 18:15 IST", "a", 15, "end"))
    stages = [("01", "DISCOVER", "star velocity across two lanes"),
              ("02", "GATE", "infra, and outsiders get merged?"),
              ("03", "FILTER", "unclaimed, not an RFC, not blocked"),
              ("04", "SCORE", "embedding model + verdict cache"),
              ("05", "RANK", "maintainer-ready first, docs last")]
    for i, (n, name, what) in enumerate(stages):
        y = 122 + i * 52
        b.append(f'<rect class="st" style="animation-delay:{i * 1.3:.1f}s" x="54" y="{y}" width="572" height="42" fill="{FG}"/>')
        b.append(f'<rect x="54" y="{y}" width="572" height="42" fill="none" stroke="{LINE}"/>')
        b.append(t(70, y + 27, n, "d", 15))
        b.append(t(108, y + 27, name, "h", 16, extra='letter-spacing="2" font-weight="700"'))
        b.append(t(250, y + 27, what, "g", 15))
    # link
    b.append(f'<line x1="640" y1="228" x2="820" y2="228" stroke="{DIM}" stroke-width="2" stroke-dasharray="6 6"/>')
    b.append(f'<path d="M820 228 l-14 -8 v16 z" fill="{DIM}"/>')
    b.append(t(730, 206, "feed.json.gz", "g", 14, "middle"))
    b.append(t(730, 256, "~20 KB", "d", 13, "middle"))
    for i in range(3):
        b.append(f'<rect class="glow" x="-6" y="-6" width="12" height="12" fill="{AMBER}">'
                 f'<animateMotion dur="2.4s" begin="{i * 0.8}s" repeatCount="indefinite" path="M646 228 L806 228"/></rect>')
    # laptop box
    b.append(f'<rect x="820" y="66" width="340" height="324" fill="#07100b" stroke="{DIM}"/>')
    b.append(t(840, 98, "YOUR LAPTOP", "h", 18, extra='letter-spacing="3" font-weight="700"'))
    b.append(t(1140, 98, "07:00 + 19:00", "a", 15, "end"))
    b.append(t(840, 140, "machine busy?", "d", 15))
    b.append(t(1140, 140, "stand down 1 hour", "r", 15, "end"))
    b.append(t(840, 168, "machine calm?", "d", 15))
    b.append(t(1140, 168, "pull the feed", "g", 15, "end"))
    b.append(scope(840, 190, 300, 96, PEAKS))
    b.append(t(840, 318, "mini tab: 1/16 of the screen", "g", 15))
    b.append(t(840, 346, "storage: 4 days, then gone", "g", 15))
    b.append(t(840, 374, "one click: HALT", "r", 15))
    css = ".st{opacity:0;animation:st 6.5s linear infinite}@keyframes st{0%{opacity:0}2%,16%{opacity:.16}20%,100%{opacity:0}}"
    return frame(w, h, "\n".join(b), css)


for name, svg in [("header", header()), ("tab", tab()), ("halt", halt()), ("pipeline", pipeline())]:
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
    print(f"{name}.svg  {len(svg) // 1024} KB")
