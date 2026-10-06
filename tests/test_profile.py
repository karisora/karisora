import importlib.util
from datetime import date, timedelta
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("profile", Path(__file__).resolve().parents[1] / "scripts/generate_profile.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def calendar_html(count=0):
    first = date(2025, 10, 5)
    cells = []
    for index in range(367):
        when = first + timedelta(days=index)
        amount = count if index == 366 else 0
        level = 4 if amount else 0
        label = f"{amount:,} contributions" if amount else "No contributions"
        cells.append(f'<td id="d{index}" data-date="{when}" data-level="{level}"></td>'
                     f'<tool-tip for="d{index}">{label} on October 6th.</tool-tip>')
    return "".join(cells)


class CalendarTests(unittest.TestCase):
    def parse(self, html):
        parser = profile.CalendarParser()
        parser.feed(html)
        return parser.days()

    def test_anonymous_counts_preserve_published_private_activity(self):
        days = self.parse(calendar_html(1234))
        self.assertEqual(days[-1]["count"], 1234)
        self.assertEqual(profile.contribution_stats(days)["total"], 1234)
        self.assertEqual(days[-1]["level"], 4)

    def test_missing_counts_fail_instead_of_becoming_zero(self):
        with self.assertRaises(ValueError):
            self.parse(calendar_html().replace("No contributions", "Unknown activity", 1))

    def test_rejects_truncated_calendar(self):
        with self.assertRaises(ValueError):
            self.parse('<td id="day" data-date="2026-10-06" data-level="0"></td>'
                       '<tool-tip for="day">No contributions on October 6th.</tool-tip>')

    def test_rejects_duplicate_dates(self):
        with self.assertRaises(ValueError):
            self.parse(calendar_html().replace('data-date="2025-10-06"', 'data-date="2025-10-05"'))

    def test_streak_and_30_day_boundaries(self):
        days = self.parse(calendar_html())
        for index in [-1, -2, -3, -30, -31]:
            days[index]["count"] = 2
        self.assertEqual(profile.contribution_stats(days),
                         {"total": 10, "active_days": 5, "longest_streak": 3, "last_30_days": 8})


class RepositoryTests(unittest.TestCase):
    def test_pagination_and_private_filter(self):
        public = {"private": False, "owner": {"login": "karisora"}, "name": "public"}
        private = {**public, "private": True, "name": "secret-project"}
        with patch.object(profile, "fetch", side_effect=[[public] * 99 + [private], [public]]) as fetch:
            repos = profile.public_repositories("karisora")
        self.assertEqual(len(repos), 100)
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(not repo["private"] for repo in repos))

    def test_languages_exclude_forks_and_profile_repo(self):
        repos = [{"name": "project", "fork": False}, {"name": "upstream", "fork": True},
                 {"name": "karisora", "fork": False}]
        with patch.object(profile, "fetch", return_value={"Python": 100, "C": 50}) as fetch:
            languages = profile.language_totals(repos, "karisora")
        self.assertEqual(languages, {"Python": 100, "C": 50})
        self.assertEqual(fetch.call_count, 1)


    def test_private_languages_paginate_filter_and_export_only_totals(self):
        owned = {"name": "secret-project", "private": True, "fork": False,
                 "owner": {"login": "karisora"}}
        foreign = {**owned, "owner": {"login": "another-owner"}}
        public = {**owned, "private": False}
        fork = {**owned, "fork": True}
        def response(url, **kwargs):
            self.assertEqual(kwargs["token"], "test-language-token")
            if "/user/repos?" in url:
                self.assertIn("visibility=private", url)
                self.assertIn("affiliation=owner", url)
                first_page = parse_qs(urlparse(url).query)["page"] == ["1"]
                return [owned] * 98 + [foreign, public] if first_page else [fork]
            return {"Python": 10}
        with patch.object(profile, "fetch", side_effect=response):
            totals = profile.private_language_totals("karisora", "test-language-token")
        self.assertEqual(totals, {"Python": 980})
        self.assertNotIn("secret-project", str(totals))

    def test_private_request_errors_hide_repository_name(self):
        private = {"name": "secret-project", "fork": False}
        error = HTTPError("https://api.github.com/repos/karisora/secret-project/languages", 403, "Forbidden", {}, None)
        with patch.object(profile, "fetch", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                profile.language_totals([private], "karisora", token="test-language-token")
        self.assertNotIn("secret-project", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def test_language_token_is_not_sent_to_calendar_or_public_api(self):
        environment = {"GITHUB_TOKEN": "public-token", "PROFILE_LANGUAGES_TOKEN": "private-token"}
        with patch.dict(os.environ, environment), patch.object(profile, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{}'
            profile.fetch("https://github.com/users/karisora/contributions")
            calendar_request = urlopen.call_args.args[0]
            self.assertIsNone(calendar_request.get_header("Authorization"))
            profile.fetch("https://api.github.com/users/karisora/repos", api=True)
            self.assertEqual(urlopen.call_args.args[0].get_header("Authorization"), "Bearer public-token")
            profile.fetch("https://api.github.com/user/repos", api=True, token="private-token")
            self.assertEqual(urlopen.call_args.args[0].get_header("Authorization"), "Bearer private-token")

    def test_collected_snapshot_contains_only_aggregate_private_data(self):
        public = {"name": "project", "private": False}
        with patch.dict(os.environ, {"PROFILE_LANGUAGES_TOKEN": "test-language-token"}), \
             patch.object(profile, "fetch", return_value=calendar_html()), \
             patch.object(profile, "public_repositories", return_value=[public]), \
             patch.object(profile, "language_totals", return_value={"C++": 100}), \
             patch.object(profile, "private_language_totals", return_value={"Python": 300}):
            data = profile.collect_data({"username": "karisora"})
        self.assertEqual(data["languages"], {"Python": 300, "C++": 100})
        self.assertEqual(data["repositories"], [public])
        self.assertTrue(data["languages_include_private"])
        self.assertNotIn("test-language-token", str(data))


class RenderTests(unittest.TestCase):
    def test_themes_xml_escaping_and_readme_links(self):
        parser = profile.CalendarParser()
        parser.feed(calendar_html(1234))
        config = {"username": "karisora", "featured_repositories": ["project"]}
        data = {"days": parser.days(), "updated": "2026.10.07", "languages": {"C++": 60, "Python": 40},
                "repositories": [{"name": "project", "description": '<script> & "test"',
                                  "private": False, "fork": False, "language": "C++",
                                  "stargazers_count": 2, "forks_count": 1}]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            readme = root / "README.md"
            readme.write_text("Before\n<!-- PROJECTS:START -->old<!-- PROJECTS:END -->\nAfter")
            profile.generate(config, data, root / "output", readme)
            for file in (root / "output").glob("*.svg"):
                parsed = ET.parse(file)
                self.assertEqual(parsed.getroot().tag, "{http://www.w3.org/2000/svg}svg")
                self.assertNotIn("<script>", file.read_text())
                self.assertNotIn("foreignObject", file.read_text())
            self.assertEqual(len(list((root / "output").glob("*.svg"))), 8)
            self.assertTrue(readme.read_text().startswith("Before\n"))
            self.assertTrue(readme.read_text().endswith("\nAfter"))
            self.assertIn("output/repository-project-dark.svg", readme.read_text())

    def test_japanese_description_wraps_within_card(self):
        lines = profile.wrap_text("組み込み用のコードの共有用ワークスペースです。" * 10)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(profile.text_width(line) <= 49 for line in lines))
        self.assertTrue(lines[-1].endswith("…"))

    def test_private_language_scope_is_labeled_without_repository_details(self):
        for theme in profile.THEMES:
            svg = profile.languages_svg({"Python": 300, "C++": 100}, theme, include_private=True)
            self.assertIn("Public + private originals", svg)
            self.assertIn("75.0%", svg)
            ET.fromstring(svg)


if __name__ == "__main__":
    unittest.main()
