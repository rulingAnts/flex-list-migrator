# flex-list-migrator — Claude Code notes

## ⚠️ GitHub costs — ask before anything billable (firm policy, 2026-07-07)

**Claude: never trigger anything that can incur GitHub charges without Seth's explicit
approval AND a stated cost estimate first.**

- FREE, always: Actions on **public** repos with **standard** GitHub-hosted runners;
  self-hosted runners; GitHub Pages.
- METERED (free monthly quota, then paid): Actions in **private** repos (2,000 min/mo;
  **Windows counts 2×, macOS 10×**); Codespaces; Packages; Git LFS.
- **ALWAYS billable, even on public repos: larger / GPU runners** (anything beyond the
  standard `ubuntu-latest` / `windows-latest` / `macos-latest` tiers).
- Safety valve: with **no payment method on file, GitHub blocks usage at the quota and
  cannot bill** — keep it that way, or set stop-usage budgets.

So WITHOUT Seth's explicit OK (and cost), do **not**: add or change `.github/workflows/**`;
use a non-standard `runs-on:`; add a `schedule:` (cron) trigger; create Codespaces; use
Git LFS; publish private Packages; or change the plan / budgets. This billable-work rule
still stands — it is a policy, not a hook, so it applies even with no hook installed.

## Branch policy — EXEMPT from the dev-branch / main-push gate (Seth, 2026-09-25)

**This repo works DIRECTLY on `main`.** Seth has exempted `flex-list-migrator` from the
firm dev-branch rule and the `main`-push gate. Commit, build, and push to `main` freely —
no `dev` branch required, no `ALLOW_MAIN_PUSH=1` flag, and **no `.git/hooks/pre-push`
guard hook** (it has been removed; do not reinstall it). GitHub Pages serves the docs
site from `main`/`/docs`, so `main` is the working branch here.

The billable-work guardrail above is the only remaining gate and still applies.

> Note: `.github/workflows/build.yml` runs on `windows-latest` (standard tier) and only
> triggers on `workflow_dispatch` or a `v*.*.*` tag push — a normal `main` push does not
> trigger it. This repo is **public**, so that build is free.

## Docs site

`docs/` is a static GitHub Pages site (served from `main`, `/docs`, with `.nojekyll`).
It reuses the FLET design tokens (`styles.css` copied from `rulingAnts.github.io/docs`).
The download button points at `releases/latest/download/FLEx.List.Migrator.exe` — the
GitHub asset name (spaces become dots). Keep the `latest` release non-prerelease so that
URL resolves. The tool is also listed as a tile in the FLET catalog
(`rulingAnts.github.io`).
