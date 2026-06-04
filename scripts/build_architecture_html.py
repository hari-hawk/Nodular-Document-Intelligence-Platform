"""Render ARCHITECTURE_OVERVIEW.md to a self-contained HTML file.

Run:    python scripts/build_architecture_html.py
Output: ARCHITECTURE_OVERVIEW.html (single file, opens in any browser)

The HTML uses Mermaid via CDN — diagrams render on first internet-connected
open. On offline machines, the diagram blocks fall back to readable source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ARCHITECTURE_OVERVIEW.md"
DST = ROOT / "ARCHITECTURE_OVERVIEW.html"


def render(md_text: str) -> str:
    """Convert Markdown → HTML body, preserving ```mermaid blocks for client-side render."""
    md = markdown.Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "toc",
            "attr_list",
            "pymdownx.superfences",
            "pymdownx.smartsymbols",
        ],
        extension_configs={
            "pymdownx.superfences": {
                # Tell SuperFences to leave ```mermaid blocks intact so Mermaid.js
                # can pick them up in the browser.
                "custom_fences": [
                    {
                        "name": "mermaid",
                        "class": "mermaid",
                        "format": lambda src, lang, cls, opts, md_, **k: (
                            f'<pre class="mermaid">{src}</pre>'
                        ),
                    },
                ],
            },
        },
        output_format="html5",
    )
    return md.convert(md_text)


CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.6; color: #1F2937; background: #FAFAFA;
    margin: 0; padding: 0;
}
.container { max-width: 1100px; margin: 0 auto; padding: 48px 32px 96px; }
header {
    background: linear-gradient(135deg, #6366F1 0%, #EC4899 100%);
    color: white; padding: 56px 32px;
}
header .inner { max-width: 1100px; margin: 0 auto; }
header h1 {
    font-size: 2.3rem; font-weight: 700; margin: 0 0 12px;
    letter-spacing: -0.02em;
}
header .sub { font-size: 1.05rem; opacity: 0.92; max-width: 720px; }
h1, h2, h3, h4 { color: #111827; line-height: 1.25; }
h1 { font-size: 2rem; margin-top: 56px; padding-bottom: 12px;
     border-bottom: 1px solid #E5E7EB; }
h2 { font-size: 1.5rem; margin-top: 44px; padding-bottom: 8px;
     border-bottom: 1px solid #F3F4F6; }
h3 { font-size: 1.18rem; margin-top: 32px; color: #374151; }
h4 { font-size: 1rem; margin-top: 24px; color: #4B5563; }
p { margin: 14px 0; }
hr { border: none; border-top: 1px solid #E5E7EB; margin: 40px 0; }
strong { color: #111827; }
em { color: #4B5563; }
blockquote {
    border-left: 4px solid #6366F1; background: #EEF2FF;
    margin: 18px 0; padding: 14px 20px; color: #312E81; border-radius: 0 6px 6px 0;
}
code {
    font-family: 'SF Mono', Monaco, Menlo, Consolas, monospace;
    font-size: 0.88em; background: #F3F4F6; color: #BE123C;
    padding: 2px 6px; border-radius: 4px;
}
pre {
    background: #1F2937; color: #E5E7EB; padding: 16px 20px;
    border-radius: 8px; overflow-x: auto; font-size: 0.85em;
    line-height: 1.5;
}
pre code { background: transparent; color: inherit; padding: 0; }
table {
    border-collapse: collapse; width: 100%; margin: 18px 0;
    font-size: 0.92em; background: white;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); border-radius: 6px;
    overflow: hidden;
}
th, td { padding: 10px 14px; text-align: left; vertical-align: top;
         border-bottom: 1px solid #F3F4F6; }
th { background: #1F2937; color: white; font-weight: 600;
     font-size: 0.86em; letter-spacing: 0.02em; text-transform: uppercase; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #FAFAFA; }
a { color: #6366F1; text-decoration: none; }
a:hover { text-decoration: underline; }
ul, ol { padding-left: 24px; }
li { margin: 4px 0; }
.mermaid {
    background: white; border: 1px solid #E5E7EB; border-radius: 8px;
    padding: 24px; margin: 24px 0; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
footer {
    text-align: center; padding: 32px; color: #9CA3AF;
    font-size: 0.85em; border-top: 1px solid #E5E7EB; margin-top: 48px;
}
.toc-wrap {
    background: white; border: 1px solid #E5E7EB; border-radius: 8px;
    padding: 16px 24px; margin: 24px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.toc-wrap > p { font-weight: 600; color: #111827; margin: 0 0 8px; }
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MDI · Architecture Overview</title>
  <style>{css}</style>
</head>
<body>
  <header><div class="inner">
    <h1>MDI · Modular Data Intelligence</h1>
    <div class="sub">Architecture overview for tech review · {date}</div>
  </div></header>
  <div class="container">
    {body}
  </div>
  <footer>Generated from <code>ARCHITECTURE_OVERVIEW.md</code> · MDI Platform Team</footer>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>
    mermaid.initialize({{
      startOnLoad: true,
      theme: 'base',
      themeVariables: {{
        primaryColor: '#1F2A44',
        primaryTextColor: '#E5E7EB',
        primaryBorderColor: '#6366F1',
        lineColor: '#9CA3AF',
        secondaryColor: '#312E81',
        tertiaryColor: '#374151',
        background: '#FFFFFF',
        mainBkg: '#1F2A44',
        nodeBorder: '#6366F1',
        clusterBkg: '#FAFAFA',
        clusterBorder: '#D1D5DB',
        edgeLabelBackground: '#FFFFFF',
        fontFamily: '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif'
      }}
    }});
  </script>
</body>
</html>
"""


def main() -> int:
    if not SRC.exists():
        print(f"missing source: {SRC}", file=sys.stderr)
        return 1
    md_text = SRC.read_text(encoding="utf-8")
    body = render(md_text)
    from datetime import date
    html = TEMPLATE.format(css=CSS, body=body, date=date.today().isoformat())
    DST.write_text(html, encoding="utf-8")
    print(f"wrote {DST.relative_to(ROOT)} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
