# kanberoo-web

Static web UI for Kanberoo, served by `kanberoo-api` at `/ui` when you install the optional `kanberoo-api[web]` extra. See [`docs/spec.md` section 9.2](https://github.com/areese801/kanberoo/blob/main/docs/spec.md) for design intent.

This package ships a single function:

```python
from kanberoo_web import web_assets_path

assets_dir = web_assets_path()  # absolute Path to the bundled dist/
```

`kanberoo-api` uses it to mount a `/ui` catch-all with an SPA fallback.

## Building the bundle

The `dist/` directory under `src/kanberoo_web/` is produced by a Vite + React build. The sources live in the sibling `frontend/` directory and are not shipped in the wheel; only the built output is.

Node 20+ is a build-time requirement. From the repo root:

```bash
make web-build   # installs npm deps and runs vite build
make web-dev     # runs the Vite dev server for iterative work
make web-test    # runs the frontend test suite (vitest, single-shot)
```

`make web-build` writes into `packages/kanberoo-web/src/kanberoo_web/dist/`, overwriting whatever was there. The committed `dist/` is what `pip install kanberoo-web` delivers.

## Install

```bash
pip install 'kanberoo-api[web]'
```

License: MIT.
