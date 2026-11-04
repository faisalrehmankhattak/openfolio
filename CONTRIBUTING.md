# Contributing to Openfolio

Thanks for helping build Openfolio, the open-source AI portfolio builder. Bug reports, fixes, features, tests, docs and translations are all welcome.

## Contribute and earn credits

When your pull request is merged, you earn extra **Openfolio Cloud credits**, on top of the free monthly credits founding members get. Credits pay for your AI's conversations on Openfolio Cloud and have no cash value.

- Every merged pull request counts: code, tests, documentation or translations.
- After the merge, the maintainer contacts you through GitHub to add the credits to your Cloud account.

## Good first issues

Look for issues labelled [`good first issue`](https://github.com/faisalrehmankhattak/openfolio/labels/good%20first%20issue). Some places where help is always useful:

- **Guard corpus.** Add real prompt-injection attempts and false alarms to `worker/tests/test_guard_eval.py`.
- **Browsers and devices.** Test voice calls on Safari for iOS, Android, Firefox and corporate networks, and report what breaks.
- **Accessibility.** Try the widget and the cloud pages with a screen reader and the keyboard only.
- **Avatars.** Document other rigs (ARKit or Oculus visemes) that work with `avatar.url`.
- **Providers.** Try other OpenAI-compatible models, speech-to-text or voices, and share settings that work.

Comment on an issue before starting something large, so nobody duplicates work.

## Set up

You need [uv](https://docs.astral.sh/uv/) and Node.js 22.12 or newer.

```sh
git clone https://github.com/faisalrehmankhattak/openfolio && cd openfolio
cp .env.example .env            # add an LLM key and a speech key, or point at local models
./scripts/dev.sh                # installs, builds the widget and serves http://127.0.0.1:7860
```

`cd worker && uv run openfolio-doctor` checks your provider settings without starting the server. To work on the hosted pages, also set `CLOUD_MODE=1` and the variables listed under "Openfolio Cloud" in the README.

## Checks

Run these before you open a pull request; CI runs the same ones.

```sh
cd worker
uv sync --group dev
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q

cd ../embed
npm ci
npm run check     # Biome lint, strict TypeScript, unit tests
npm run build
```

## Pull request rules

- **Small and focused.** One change per pull request. Split refactors from behaviour changes.
- **Tests for behaviour.** Any behaviour change or bug fix comes with a test.
- **Typed code.** Python passes `mypy --strict`; TypeScript stays strict with no `any`.
- **Safe HTML.** Cloud pages use Jinja2 templates with autoescaping, never HTML built from strings. The widget renders text with `textContent`.
- **No new third-party requests** from the browser, and no inline scripts on cloud pages (the Content Security Policy forbids both).
- **Short comments that explain why**, not what the code does.
- **Docs live in the README.** Update it when you change behaviour or configuration; please don't add separate docs files.
- **No secrets** in code, tests, logs or screenshots.
- Describe what changed and how you tested it in the pull request template.

By contributing, you agree that your work is licensed under the [Apache-2.0 license](LICENSE), and you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md). Found a vulnerability? Please follow [SECURITY.md](SECURITY.md) instead of opening an issue.
