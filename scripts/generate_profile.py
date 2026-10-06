#!/usr/bin/env python3
"""Render profile SVGs from public GitHub data, including published private counts."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
THEMES = {
    "light": {
        "surface": "#ffffff", "tint": "#f3faf6", "border": "#dce8e1",
        "ink": "#18352b", "muted": "#597368", "accent": "#168454",
        "heat": ["#eaf1ed", "#a8dfbb", "#60c88b", "#2aa865", "#157747"],
    },
    "dark": {
        "surface": "#101b17", "tint": "#152a21", "border": "#294035",
        "ink": "#e1f2e9", "muted": "#9ab5a7", "accent": "#72dfa0",
        "heat": ["#1d3026", "#235b3b", "#2d8c54", "#49bb76", "#85e7ac"],
    },
}
LANGUAGE_COLORS = {
    "Python": "#6ea8dc", "C++": "#e891af", "C": "#a1acba",
    "C#": "#95c76d", "TypeScript": "#69a7e7", "JavaScript": "#dfc862",
    "Shell": "#8bc993", "HTML": "#e39779", "CSS": "#a99bdd",
    "CMake": "#90b6a8", "Rust": "#d9a384", "Jupyter Notebook": "#dbab73",
}


def fetch(url, *, api=False):
    # Calendar requests are anonymous. Credentials go only to GitHub REST.
    headers = {"User-Agent": "karisora-profile-generator", "Accept-Language": "en-US"}
    if api:
        if not url.startswith("https://api.github.com/"):
            raise ValueError("API requests must target api.github.com")
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                body = response.read().decode("utf-8")
            return json.loads(body) if api else body
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


class CalendarParser(HTMLParser):
    """Read dated cells and associated daily-count tooltips, without guessing."""

    def __init__(self):
        super().__init__()
        self.cells = {}
        self.tooltips = {}
        self.tooltip_target = None
        self.tooltip_text = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "data-date" in attrs and "data-level" in attrs:
            self.cells[attrs["id"]] = {"date": attrs["data-date"], "level": int(attrs["data-level"])}
        if tag == "tool-tip":
            self.tooltip_target = attrs.get("for")
            self.tooltip_text = []

    def handle_data(self, text):
        if self.tooltip_target:
            self.tooltip_text.append(text)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.tooltip_target:
            self.tooltips[self.tooltip_target] = "".join(self.tooltip_text).strip()
            self.tooltip_target = None

    def days(self):
        days = []
        for cell_id, cell in self.cells.items():
            match = re.match(r"(No|[\d,]+) contributions? on\b", self.tooltips.get(cell_id, ""))
            if not match:
                raise ValueError(f"Missing or unrecognized contribution count for {cell['date']}")
            count = 0 if match[1] == "No" else int(match[1].replace(",", ""))
            if cell["level"] not in range(5) or (count == 0) != (cell["level"] == 0):
                raise ValueError(f"Invalid contribution level for {cell['date']}")
            date.fromisoformat(cell["date"])
            days.append({**cell, "count": count})
        days.sort(key=lambda day: day["date"])
        if not 365 <= len(days) <= 371:
            raise ValueError(f"Expected a full contribution year, received {len(days)} days")
        for before, after in zip(days, days[1:]):
            if date.fromisoformat(after["date"]) - date.fromisoformat(before["date"]) != timedelta(days=1):
                raise ValueError("Contribution dates must be unique and consecutive")
        return days


def contribution_stats(days):
    latest = date.fromisoformat(days[-1]["date"])
    run = longest = 0
    for day in days:
        run = run + 1 if day["count"] else 0
        longest = max(longest, run)
    return {
        "total": sum(day["count"] for day in days),
        "active_days": sum(day["count"] > 0 for day in days),
        "longest_streak": longest,
        "last_30_days": sum(day["count"] for day in days
                            if date.fromisoformat(day["date"]) > latest - timedelta(days=30)),
    }


def public_repositories(username):
    repos = []
    page = 1
    while True:
        query = urlencode({"per_page": 100, "sort": "pushed", "page": page})
        batch = fetch(f"https://api.github.com/users/{username}/repos?{query}", api=True)
        if not isinstance(batch, list):
            raise ValueError("Expected a repository list")
        repos.extend(repo for repo in batch if repo.get("private") is False
                     and repo["owner"]["login"].lower() == username.lower())
        if len(batch) < 100:
            break
        page += 1
    return repos


def language_totals(repositories, username):
    originals = [repo for repo in repositories if not repo["fork"] and repo["name"] != username]
    def read_languages(repo):
        return fetch(f"https://api.github.com/repos/{username}/{repo['name']}/languages", api=True)
    total = Counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for languages in pool.map(read_languages, originals):
            total.update(languages)
    return dict(total.most_common())


def attributes(values):
    return " ".join(f'{key.replace("_", "-")}="{escape(str(value), quote=True)}"'
                    for key, value in values.items())


class SVG:
    def __init__(self, width, height, theme, title, description):
        self.theme = THEMES[theme]
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
            f'<title id="title">{escape(title)}</title>',
            f'<desc id="description">{escape(description)}</desc>',
            '<defs><linearGradient id="surface" x2="1" y2="1">'
            f'<stop stop-color="{self.theme["surface"]}"/>'
            f'<stop offset="1" stop-color="{self.theme["tint"]}"/>'
            '</linearGradient></defs>',
            '<g font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, '
            'Hiragino Sans, Noto Sans CJK JP, sans-serif">',
        ]
        self.rect(0.5, 0.5, width - 1, height - 1, "url(#surface)", rx=20, stroke=self.theme["border"])

    def rect(self, x, y, width, height, fill, **attrs):
        self.parts.append(f'<rect {attributes(dict(x=x, y=y, width=width, height=height, fill=fill, **attrs))}/>')

    def text(self, x, y, value, size=14, color=None, **attrs):
        values = dict(x=x, y=y, fill=color or self.theme["ink"], font_size=size, **attrs)
        self.parts.append(f'<text {attributes(values)}>{escape(str(value))}</text>')

    def line(self, x1, y, x2):
        self.parts.append(f'<path d="M{x1} {y}H{x2}" stroke="{self.theme["border"]}"/>')

    def label(self, value, x=28, y=35):
        self.text(x, y, value, size=11, color=self.theme["muted"], font_weight=600, letter_spacing=2)

    def finish(self):
        return "\n".join([*self.parts, "</g></svg>"]) + "\n"


def activity_svg(days, theme, updated):
    stats = contribution_stats(days)
    svg = SVG(896, 344, theme, "A year of building",
              f"{stats['total']} contributions from {days[0]['date']} to {days[-1]['date']}. "
              "Includes anonymized private counts made visible by GitHub profile settings.")
    colors = svg.theme
    svg.label("A YEAR OF BUILDING")
    svg.text(28, 85, f"{stats['total']:,}", size=40, font_weight=700, letter_spacing=-1.5)
    total_width = len(f"{stats['total']:,}") * 24
    svg.text(40 + total_width, 82, "contributions, one day at a time", size=16, color=colors["muted"])
    svg.text(868, 35, "@karisora", size=13, color=colors["muted"], text_anchor="end")
    svg.line(28, 106, 868)
    first = date.fromisoformat(days[0]["date"])
    origin = first - timedelta(days=(first.weekday() + 1) % 7)
    weeks = (date.fromisoformat(days[-1]["date"]) - origin).days // 7 + 1
    pitch = min(15, 798 / weeks)
    previous_month = None
    for day in days:
        when = date.fromisoformat(day["date"])
        week, weekday = divmod((when - origin).days, 7)
        x, y = 61 + week * pitch, 143 + weekday * 15
        if when.month != previous_month:
            if week < weeks - 2:
                svg.text(x, 131, when.strftime("%b"), size=10, color=colors["muted"])
            previous_month = when.month
        svg.parts.append(f'<g><title>{day["date"]}: {day["count"]} contributions</title>')
        svg.rect(round(x, 2), y, round(pitch - 3, 2), 12, colors["heat"][day["level"]], rx=3)
        svg.parts.append('</g>')
    for weekday, label in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        svg.text(28, 153 + weekday * 15, label, size=10, color=colors["muted"])
    svg.text(61, 265, f"{first.strftime('%d %b %Y')} — {days[-1]['date']}", size=10, color=colors["muted"])
    svg.text(733, 265, "Less", size=10, color=colors["muted"])
    for index, color in enumerate(colors["heat"]):
        svg.rect(764 + index * 15, 255, 11, 11, color, rx=3)
    svg.text(844, 265, "More", size=10, color=colors["muted"])
    svg.line(28, 281, 868)
    for x, value, label in [(28, stats["active_days"], "active days"),
                            (242, stats["longest_streak"], "day best streak"),
                            (465, stats["last_30_days"], "in the last 30 days")]:
        svg.text(x, 315, value, size=22, font_weight=650)
        svg.text(x + len(str(value)) * 14 + 10, 314, label, size=12, color=colors["muted"])
    svg.text(868, 315, f"Updated {updated} · JST", size=10, color=colors["muted"], text_anchor="end")
    return svg.finish()


def languages_svg(languages, theme):
    svg = SVG(440, 300, theme, "Language mix", "Language percentages by code bytes in public, non-fork repositories.")
    colors = svg.theme
    svg.label("THE CODE BEHIND THE WORK")
    svg.text(28, 71, "Language mix", size=26, font_weight=650, letter_spacing=-0.7)
    svg.text(28, 94, "Public originals · share of code bytes", size=12, color=colors["muted"])
    entries = list(languages.items())
    top = entries[:5]
    if len(entries) > 5:
        top.append(("Other", sum(value for _, value in entries[5:])))
    total = sum(languages.values())
    if not total:
        svg.text(28, 158, "No language data yet", color=colors["muted"])
        return svg.finish()
    svg.parts.append('<defs><clipPath id="bar"><rect x="28" y="119" width="384" height="10" rx="5"/></clipPath></defs>')
    svg.parts.append('<g clip-path="url(#bar)">')
    offset = 28
    for language, count in top:
        width = 384 * count / total
        svg.rect(round(offset, 3), 119, round(width, 3), 10, LANGUAGE_COLORS.get(language, "#8daf9e"))
        offset += width
    svg.parts.append('</g>')
    for index, (language, count) in enumerate(top):
        x, y = 28 + (index % 2) * 200, 160 + (index // 2) * 40
        svg.rect(x, y - 9, 8, 8, LANGUAGE_COLORS.get(language, "#8daf9e"), rx=3)
        svg.text(x + 16, y, language, size=12)
        svg.text(x + 16, y + 17, f"{count / total * 100:.1f}%", size=11, color=colors["muted"])
    svg.line(28, 267, 412)
    svg.text(28, 285, "Small experiments. Different languages.", size=11, color=colors["muted"])
    return svg.finish()


def overview_svg(repositories, theme):
    svg = SVG(440, 300, theme, "GitHub at a glance", "Public repository statistics for karisora.")
    colors = svg.theme
    svg.label("OPEN SOURCE FOOTPRINT")
    svg.text(28, 71, "GitHub at a glance", size=26, font_weight=650, letter_spacing=-0.7)
    svg.text(28, 94, "Ideas, experiments, and shared code", size=12, color=colors["muted"])
    values = [(len(repositories), "public repositories"),
              (sum(not repo["fork"] for repo in repositories), "original repositories"),
              (sum(repo["stargazers_count"] for repo in repositories), "stars received"),
              (sum(repo["forks_count"] for repo in repositories), "forks received")]
    for index, (value, label) in enumerate(values):
        x, y = 28 + (index % 2) * 200, 148 + (index // 2) * 77
        svg.text(x, y, f"{value:,}", size=30, font_weight=650, color=colors["accent"])
        svg.text(x, y + 21, label, size=12, color=colors["muted"])
    svg.line(28, 267, 412)
    svg.text(28, 285, "Explore the repositories below ↗", size=11, color=colors["muted"])
    return svg.finish()


def text_width(value):
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in value)


def wrap_text(value, limit=49, max_lines=2):
    remaining = " ".join(value.split())
    lines = []
    while remaining and len(lines) < max_lines:
        if text_width(remaining) <= limit:
            lines.append(remaining)
            break
        end = 0
        while end < len(remaining) and text_width(remaining[:end + 1]) <= limit - 1:
            end += 1
        if len(lines) == max_lines - 1:
            lines.append(remaining[:end].rstrip() + "…")
            break
        space = remaining.rfind(" ", 0, end + 1)
        if space > end // 2:
            end = space
        lines.append(remaining[:end].rstrip())
        remaining = remaining[end:].lstrip()
    return lines


def repository_svg(repo, theme):
    svg = SVG(440, 178, theme, repo["name"], repo["description"] or f"Explore {repo['name']} on GitHub.")
    colors = svg.theme
    svg.label("SELECTED REPOSITORY", y=31)
    svg.text(412, 32, "↗", size=20, color=colors["accent"], text_anchor="end")
    name = repo["name"]
    if text_width(name) > 32:
        name = wrap_text(name, limit=32, max_lines=1)[0]
    svg.text(28, 65, name, size=21, font_weight=650, letter_spacing=-0.4)
    description = repo["description"] or "Explore the source code on GitHub."
    for index, line in enumerate(wrap_text(description)):
        svg.text(28, 90 + index * 18, line, size=12, color=colors["muted"])
    svg.line(28, 127, 412)
    language = repo["language"] or "Repository"
    svg.rect(28, 147, 8, 8, LANGUAGE_COLORS.get(language, colors["accent"]), rx=4)
    svg.text(43, 155, language, size=11, color=colors["muted"])
    svg.text(412, 155, f"★ {repo['stargazers_count']}   ·   ⑂ {repo['forks_count']}",
             size=11, color=colors["muted"], text_anchor="end")
    return svg.finish()


def project_markup(username, featured):
    rows = []
    for start in range(0, len(featured), 2):
        row = ['<p align="center">']
        for name in featured[start:start + 2]:
            safe = escape(name, quote=True)
            row += [f'  <a href="https://github.com/{username}/{safe}">',
                    '    <picture>',
                    f'      <source media="(prefers-color-scheme: dark)" srcset="output/repository-{safe}-dark.svg" />',
                    f'      <img src="output/repository-{safe}-light.svg" width="400" alt="{safe} repository" />',
                    '    </picture>', '  </a>']
        rows.append("\n".join([*row, '</p>']))
    return "\n\n".join(rows)


def collect_data(config):
    username = config["username"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        calendar_task = pool.submit(fetch, f"https://github.com/users/{username}/contributions")
        repositories_task = pool.submit(public_repositories, username)
        parser = CalendarParser()
        parser.feed(calendar_task.result())
        days = parser.days()
        repositories = repositories_task.result()
    return {"days": days, "repositories": repositories,
            "languages": language_totals(repositories, username),
            "updated": datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y.%m.%d")}


def generate(config, data, output_dir, readme):
    by_name = {repo["name"]: repo for repo in data["repositories"] if repo.get("private") is False}
    featured = config["featured_repositories"]
    missing = set(featured) - set(by_name)
    if missing:
        raise ValueError(f"Featured repositories must be public: {', '.join(sorted(missing))}")
    images = {}
    for theme in THEMES:
        images[f"activity-{theme}.svg"] = activity_svg(data["days"], theme, data["updated"])
        images[f"languages-{theme}.svg"] = languages_svg(data["languages"], theme)
        images[f"overview-{theme}.svg"] = overview_svg(data["repositories"], theme)
        for name in featured:
            images[f"repository-{name}-{theme}.svg"] = repository_svg(by_name[name], theme)
    original = readme.read_text()
    pattern = r"<!-- PROJECTS:START -->.*?<!-- PROJECTS:END -->"
    block = "<!-- PROJECTS:START -->\n" + project_markup(config["username"], featured) + "\n<!-- PROJECTS:END -->"
    updated, count = re.subn(pattern, lambda _: block, original, flags=re.DOTALL)
    if count != 1:
        raise ValueError("README must contain exactly one selected-projects marker pair")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in images.items():
        (output_dir / name).write_text(content)
    readme.write_text(updated)
    print(f"Generated {len(images)} cards; {contribution_stats(data['days'])['total']} contributions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, help="Render a previously fetched public-data snapshot")
    parser.add_argument("--save-data", type=Path, help="Save public data for offline validation")
    args = parser.parse_args()
    config = json.loads((ROOT / "profile.json").read_text())
    data = json.loads(args.data.read_text()) if args.data else collect_data(config)
    if args.save_data:
        args.save_data.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    generate(config, data, ROOT / "output", ROOT / "README.md")


if __name__ == "__main__":
    main()
