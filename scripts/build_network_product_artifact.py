"""Build a portable, dependency-free stakeholder review from its Markdown source."""
import base64
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/artifacts/network-product-review-for-mark.md'
TARGET = SOURCE.with_suffix('.html')

def inline(text):
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text

def blocks(text):
    out = []
    for block in text.strip().split('\n\n'):
        lines = block.splitlines()
        if block.startswith('## '):
            title = block[3:]
            ident = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
            out.append(f'<h2 id="{ident}">{inline(title)}</h2>')
        elif block.startswith('# '):
            out.append('<h1>'+inline(block[2:])+'</h1>')
        elif block.startswith('|'):
            rows = [[inline(c.strip()) for c in line.strip('|').split('|')] for line in lines]
            out.append('<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+c+'</th>' for c in rows[0])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+c+'</td>' for c in row)+'</tr>' for row in rows[2:])+'</tbody></table></div>')
        elif all(re.match(r'^(?:- |\d+\. )', line) for line in lines):
            tag = 'ul' if lines[0].startswith('- ') else 'ol'
            out.append('<'+tag+'>'+''.join('<li>'+inline(re.sub(r'^(?:- |\d+\. )','',line))+'</li>' for line in lines)+'</'+tag+'>')
        else:
            out.append('<p>'+inline(block)+'</p>')
    return '\n'.join(out)

md = SOURCE.read_text(encoding='utf-8')
intro, rest = md.split('## Numbered feature catalogue', 1)
features_text, ending = rest.split('## What has actually been demonstrated', 1)
features = re.findall(r'### (\d+)\. ([^\n]+)\n\n(.*?)(?=\n### |\Z)', features_text, re.DOTALL)
nav = ''; cards = ''
for number, title, body in features:
    fields = dict(re.findall(r'\*\*([^*]+):\*\*\s*(.*?)(?=\s*\*\*[^*]+:\*\*|\Z)', body, re.DOTALL))
    nav += f'<a href="#feature-{number}"><span>{number}</span>{html.escape(title)}</a>'
    cards += f'<article class="feature" id="feature-{number}"><div class="feature-head"><span class="number">{number}</span><h3>{html.escape(title)}</h3></div>'
    for label in ('Origin','Status','Value hypothesis','Research','Choice/reason','Boundary'):
        title_label={'Choice/reason':'Architecture & rationale','Boundary':'Current boundary','Value hypothesis':'Expected value'}.get(label,label)
        cards += f'<section class="field"><h4>{title_label}</h4><p>{inline(fields[label])}</p></section>'
    cards += '<details><summary>Implementation trace</summary><p>'+inline(fields['Evidence'])+'</p></details></article>'
shot = ROOT/'docs/artifacts/network-scopes-demo.png'
visual = ''
if shot.exists():
    encoded = base64.b64encode(shot.read_bytes()).decode()
    visual = f'<figure><img src="data:image/png;base64,{encoded}" alt="The light network explorer with four relationship scopes and evidence inspector"><figcaption>Current synthetic demo. The scope controls explain why a person appears; the inspector retains sources and unknowns.</figcaption></figure>'
css = '''
:root{--ink:#282333;--muted:#6e6877;--purple:#725680;--line:#e7e1e9;--paper:#fff;--wash:#f7f5f8}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:28px}body{margin:0;color:var(--ink);background:var(--wash);font:16px/1.7 system-ui,-apple-system,"Segoe UI",sans-serif}a{color:var(--purple);text-underline-offset:3px}header{padding:38px 5vw 26px;background:#eee9f1;border-bottom:1px solid var(--line)}.eyebrow{text-transform:uppercase;font-size:12px;letter-spacing:2px;font-weight:700;color:var(--purple)}header .title{font:500 clamp(30px,4vw,50px)/1.12 Georgia,serif;max-width:850px;margin:14px 0}.meta{color:var(--muted);font-size:13px}button{background:var(--purple);color:white;border:0;border-radius:6px;padding:10px 16px;font:inherit;cursor:pointer}.shell{display:grid;grid-template-columns:265px minmax(0,920px);gap:50px;max-width:1310px;margin:auto;padding:36px 30px}nav{position:sticky;top:20px;align-self:start;max-height:92vh;overflow:auto;padding-right:15px;font-size:12px;line-height:1.35}nav strong{display:block;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;color:var(--muted)}nav a{display:flex;gap:10px;padding:8px 4px;text-decoration:none;border-bottom:1px solid var(--line)}nav a:hover{background:#ece5f0}nav span{color:#9b87a5;min-width:20px}main{min-width:0}main>h1{display:none}h2{font:500 30px/1.2 Georgia,serif;margin:52px 0 20px;padding-top:10px}p{margin:0 0 17px}li{margin:10px 0}strong{font-weight:650}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;margin:12px 0 22px}th{text-align:left;color:var(--purple);background:#eee9f1}th,td{padding:14px;border:1px solid var(--line);vertical-align:top}.feature{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:26px 30px;margin:20px 0 30px;box-shadow:0 4px 16px #30203505;scroll-margin-top:20px}.feature-head{display:flex;gap:20px;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:20px}.number{font:32px/1 Georgia,serif;color:#9c84ad}h3{font-size:22px;line-height:1.3;margin:0;letter-spacing:-.3px}.field{display:grid;grid-template-columns:135px 1fr;gap:18px;margin:15px 0}.field h4{font-size:11px;color:var(--purple);text-transform:uppercase;letter-spacing:.7px;margin:4px 0}.field p{font-size:14px;margin:0}details{border-top:1px solid var(--line);padding-top:12px;font-size:12px;color:var(--muted)}summary{cursor:pointer}details p{padding-top:10px;overflow-wrap:anywhere}figure{margin:30px 0}img{width:100%;border:1px solid var(--line);border-radius:8px}figcaption{font-size:12px;color:var(--muted);margin-top:8px}code{font-size:.88em;overflow-wrap:anywhere}footer{padding:30px;text-align:center;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.flow div{background:#eee8f2;padding:16px;font-size:13px;border-radius:8px}.flow b{display:block;margin-bottom:4px}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #af90c3;outline-offset:3px}@media(max-width:900px){.shell{display:block;padding:20px}nav{position:static;max-height:230px;margin-bottom:30px;border-bottom:1px solid var(--line)}.field{display:block}.field h4{margin-bottom:5px}.feature{padding:22px 18px}.flow{grid-template-columns:1fr 1fr}h2{font-size:27px}}@media print{body{background:white;font-size:10pt}header{padding:10mm 0;background:white}header button,nav{display:none}.shell{display:block;padding:0}h2{break-after:avoid;margin-top:20px}.feature{box-shadow:none;border-radius:0;padding:16px;break-inside:auto}.feature-head,.field{break-inside:avoid}.field{grid-template-columns:110px 1fr}.field p{font-size:10pt}a{color:inherit}details{display:none}figure{break-inside:avoid}footer{display:none}}
'''
flow='<div class="flow" aria-label="Architecture"><div><b>01 / Evidence</b>Stable identities, sources, dates, review state</div><div><b>02 / Projection</b>Scopes, tags, entity views, shared graph</div><div><b>03 / Retrieval</b>Entities, complete paths, excerpts, coverage</div><div><b>04 / Assistance</b>Grounded synthesis, candidate map, review</div></div>'
page='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Network product review | Eva for Mark</title><style>'+css+'</style></head><body><header><div class="eyebrow">Comms / Product review</div><div class="title">From conversations to useful network decisions.</div><p class="meta">Eva for Mark &nbsp; / &nbsp; 28 September 2026 &nbsp; / &nbsp; Synthetic demo</p><button onclick="window.print()">Print / save PDF</button></header><div class="shell"><nav aria-label="Feature catalogue"><strong>19 features / design decisions</strong><a href="#the-product-direction">Product thinking</a><a href="#the-four-relationship-scopes">The four scopes</a>'+nav+'<a href="#what-has-actually-been-demonstrated">Evidence & limitations</a><a href="#research-and-design-references">Research references</a></nav><main>'+blocks(intro)+flow+visual+'<h2 id="catalogue">Numbered feature catalogue</h2><p>Each feature records its origin, research, architecture, expected value and current boundary. Implemented means available in this synthetic demonstrator.</p>'+cards+blocks('## What has actually been demonstrated'+ending)+'</main></div><footer>Prepared for product discussion. No production data or credentials are included. This file is self-contained and works offline.</footer></body></html>'
TARGET.write_text(page,encoding='utf-8')
print(TARGET, len(page),'characters;',len(features),'feature cards')
