# Profile cards

The first image in the profile README is a rounded contribution calendar.
All cards have matching light and dark SVGs selected with GitHub's supported
`picture` / `prefers-color-scheme` markup. They use native SVG text and shapes,
without JavaScript, external fonts, or `foreignObject`.

## Include private contributions

1. Sign in as `karisora` and open https://github.com/karisora.
2. Above GitHub's own contribution calendar, open **Contribution settings**.
3. Enable **Private contributions**.
4. Open this repository's **Actions → Update profile cards → Run workflow**,
   or wait for the next daily run at 03:10 JST.

GitHub exposes anonymous daily contribution counts to profile visitors when
this option is enabled. The custom calendar reads that anonymously accessible
calendar, so those counts become green blocks here too. Private repository
names and code are never fetched. Language percentages and repository cards
cover public repositories only; forks are excluded from language totals.

GitHub's contribution eligibility rules still apply. Commits must use an email
associated with the account and be on the default or `gh-pages` branch of a
non-fork repository. Local edits and unpushed commits are not contributions.
GitHub may take time to update its graph.

If **Private contributions** is later disabled, run the workflow again to
refresh the generated images. Committed SVGs are snapshots; historical
versions in Git retain previously published daily counts.

References:

- [Private contribution visibility](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/manage-visibility-settings-for-private-contributions-and-achievements)
- [Contribution criteria](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference)

## Update and customize

Change `featured_repositories` in `profile.json` to choose repository cards.
They must be public repositories owned by `karisora`. Descriptions and language
labels come from GitHub; project descriptions are not invented.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/generate_profile.py
```

The generator uses Python's standard library. It fetches public repository
metadata and language byte counts through GitHub REST, with pagination. In
Actions the built-in `GITHUB_TOKEN` raises the API rate limit and commits the
cards. A personal access token or additional repository secret is unnecessary.

The contribution calendar HTML endpoint is a GitHub page, not a versioned API.
If GitHub changes its markup, parsing fails instead of publishing a misleading
empty calendar. Retrieval or validation failures leave the committed cards
unchanged, and the workflow fails visibly in Actions.

To render the same live snapshot repeatedly for visual checks:

```sh
python3 scripts/generate_profile.py --save-data /tmp/profile-data.json
python3 scripts/generate_profile.py --data /tmp/profile-data.json
```

The old `output/metrics.svg` is retained as a historical artifact; the README
and workflow no longer use it.
