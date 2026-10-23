#!/usr/bin/env python3
"""Split a book into one text file per chapter: split_book.py <book.epub|book.txt> <out_dir>

An epub is read in OPF spine order with its XHTML stripped to text; a txt is decoded as UTF-8 or GB18030.
Chapters start at headings: a Roman numeral line followed by an all-capitals title, or a "Chapter N" /
"第N章" line. Writes <out_dir>/chapters/NNN.txt and <out_dir>/chapters.json, and prints the chapters found so
their count and order can be checked. Standard library only; run it with `python3 -I`.
"""
import json
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from posixpath import dirname, join, normpath

NUMERAL = re.compile(r"^[IVXLC]+\.?$")
TITLED = re.compile(r"^(CHAPTER|Chapter) [0-9IVXLC]+\b.*$|^第[一二三四五六七八九十百千零〇0-9]+[章回节卷].*$")


class Text(HTMLParser):
    BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "br", "li", "tr"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def spine_text(book):
    z = zipfile.ZipFile(book)
    opf = re.search(r'full-path="([^"]+)"', z.read("META-INF/container.xml").decode()).group(1)
    o = z.read(opf).decode("utf-8", "replace")
    items = {m.group(1): m.group(2) for m in re.finditer(r'<item\b[^>]*id="([^"]+)"[^>]*href="([^"]+)"', o)}
    items.update({m.group(2): m.group(1) for m in re.finditer(r'<item\b[^>]*href="([^"]+)"[^>]*id="([^"]+)"', o)})
    for idref in re.findall(r'<itemref[^>]*idref="([^"]+)"', o):
        href = items.get(idref)
        if href and href.endswith(("html", "htm")):
            p = Text()
            p.feed(z.read(normpath(join(dirname(opf), href))).decode("utf-8", "replace"))
            yield "".join(p.parts)


def txt_text(book):
    raw = open(book, "rb").read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            yield raw.decode(enc)
            return
        except UnicodeDecodeError:
            pass
    yield raw.decode("utf-8", "replace")


def main():
    book, out = sys.argv[1], Path(sys.argv[2])
    texts = spine_text(book) if book.lower().endswith(".epub") else txt_text(book)
    lines = [re.sub(r"[ \t\xa0\u3000]+", " ", l).strip() for t in texts for l in t.splitlines()]
    def next_text(i):
        return next((l for l in lines[i + 1:] if l), "")

    # A numeral line is a heading only when an all-capitals title follows; on its own it is layout debris.
    chapters, title, buf = [], None, []
    for i, line in enumerate(lines):
        if TITLED.match(line):
            if title is not None:
                chapters.append((title, buf))
            title, buf = line, []
            continue
        if NUMERAL.match(line):
            nxt = next_text(i)
            if nxt.isupper() and len(nxt) > 3 and not NUMERAL.match(nxt):
                if title is not None:
                    chapters.append((title, buf))
                title, buf = f"{line} {nxt}", []
                lines[lines.index(nxt, i + 1)] = ""
            continue
        if title is not None:
            buf.append(line)
    chapters.append((title, buf))
    out.joinpath("chapters").mkdir(parents=True, exist_ok=True)
    index = []
    for n, (title, body) in enumerate(chapters, 1):
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip()
        for marker in ("*** END OF THE PROJECT GUTENBERG", "THE FULL PROJECT GUTENBERG"):
            text = text.split(marker)[0].strip()
        f = out / "chapters" / f"{n:03d}.txt"
        f.write_text(f"{title}\n\n{text}\n")
        index.append({"n": n, "title": title, "chars": len(text), "words": len(text.split()), "file": str(f.name)})
    json.dump(index, open(out / "chapters.json", "w"), ensure_ascii=False, indent=1)
    for c in index:
        print(f"{c['n']:3d} {c['words']:6d} words  {c['title'][:70]}")
    print(len(index), "chapters,", sum(c["words"] for c in index), "words")


if __name__ == "__main__":
    main()
