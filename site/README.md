# AIOpsPilot Docs Site

Astro Starlight source for the [AIOpsPilot](../README.md) documentation site.
Deployed to GitHub Pages at
[dotnetpower.github.io/aiopspilot](https://dotnetpower.github.io/aiopspilot/).

Docs sources live in [docs/roadmap](../docs/roadmap/) as the canonical Markdown; this
folder is a **read-only presentation layer** that mounts those files and adds
navigation, search, i18n, and theming. Editing a page here means editing the sibling
Markdown in `docs/roadmap/` — the site rebuilds automatically on push to `main`.

## Design source

The visual language mirrors [`examples/option-b-tailwind.html`](../examples/option-b-tailwind.html)
(Azure palette `#0078D4` / `#50E6FF`, Segoe UI Variable, Fluent depth-4/8/16 shadows).
Those tokens are ported into Starlight CSS variables in `src/styles/` — see the
follow-up commits.

## Local development

```bash
cd site
npm install
npm run dev       # http://localhost:4321/aiopspilot/
npm run build     # dist/
npm run preview
```

## Deployment

`main` → `.github/workflows/pages.yml` → `actions/deploy-pages@v4`. Fork owners can
override the target URL without editing config:

```bash
SITE_URL="https://acme.github.io" BASE_PATH="/aiopspilot" npm run build
```

## Scope

- **In**: [README.md](../README.md), [docs/**/*.md](../docs/) (both English and
  Korean pairs via i18n).
- **Out**: [.github/**](../.github/) — developer-facing guidelines, English-only,
  intentionally not on the user-facing site.
- Language and translation-pair rules match
  [.github/instructions/language.instructions.md](../.github/instructions/language.instructions.md);
  the `check-translations.sh` CI gate is authoritative — the site consumes what the
  gate accepts.
