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
names and code are not needed for the activity calendar. Repository cards
cover public repositories only. Language percentages can optionally include
private repositories using the setup below; forks are excluded from totals.

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

## Include private repository languages

The activity checkbox above does not expose private language statistics.
For languages, create a **fine-grained personal access token**:

1. Open https://github.com/settings/personal-access-tokens/new.
2. Set **Resource owner** to `karisora` and choose an expiration date.
3. Under **Repository access**, select the private repositories to include
   with **Only select repositories**, or choose **All repositories** to cover
   all repositories owned by `karisora`, including future ones.
4. Keep **Repository permissions → Metadata: Read-only**. No contents, write,
   workflow, or account permissions are required for the language API.
5. Generate the token and add it at
   https://github.com/karisora/karisora/settings/secrets/actions as a
   **New repository secret** named `PROFILE_LANGUAGES_TOKEN`.
6. Run **Actions → Update profile cards → Run workflow → main**.

The language card then combines byte counts from public repositories with
token-accessible private repositories **owned by karisora**. Organization and
other users' repositories are not included. The card says **Public + private
originals** when this mode is enabled. Repository access selected on the token
defines which private repositories can contribute to these percentages.

Only language totals and percentages reach the output or an optional saved
snapshot. Private repository names, descriptions, URLs, and per-repository
counts stay out of committed SVGs and snapshots. The generator requests
language byte counts, without downloading private source files. It keeps the
public repository cards and repository counts public-only.

Without the secret, the language card uses public repositories and labels
that scope. An expired token or a failed language request causes the update
to fail instead of quietly publishing incomplete totals. Renew the token and
replace the secret when necessary. No token should be added to source files.

- [Fine-grained token setup](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Required Metadata read permission](https://docs.github.com/en/rest/repos/repos#list-repository-languages)

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
cards. No additional secret is needed for activity or public languages.
The optional `PROFILE_LANGUAGES_TOKEN` is used only for private language reads;
commits continue to use the repository-scoped built-in token.

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
