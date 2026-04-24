# kanbaroo-web

Static web UI for Kanbaroo, served by `kanbaroo-api` at `/ui` when you install the optional `kanbaroo-api[web]` extra. See [`docs/spec.md` section 9.2](https://github.com/areese801/kanbaroo/blob/main/docs/spec.md) for design intent.

This package ships a single function:

```python
from kanbaroo_web import web_assets_path

assets_dir = web_assets_path()  # absolute Path to the bundled dist/
```

`kanbaroo-api` uses it to mount a `/ui` catch-all with an SPA fallback.

## Building the bundle

The `dist/` directory under `src/kanbaroo_web/` is produced by a Vite + React build. The sources live in the sibling `frontend/` directory and are not shipped in the wheel; only the built output is.

Node 20+ is a build-time requirement. From the repo root:

```bash
make web-build   # installs npm deps and runs vite build
make web-dev     # runs the Vite dev server for iterative work
make web-test    # runs the frontend test suite (vitest, single-shot)
```

`make web-build` writes into `packages/kanbaroo-web/src/kanbaroo_web/dist/`, overwriting whatever was there. The committed `dist/` is what `pip install kanbaroo-web` delivers.

## Install

```bash
pip install 'kanbaroo-api[web]'
```

License: MIT.
