# aurtool

A deliberately **un-easy** AUR helper. Tools like `yay` and `paru` collapse
*pull → build → install* into one motion, so a compromised `PKGBUILD` can slip
through unreviewed (as happened in the AUR recently). `aurtool` splits that
into discrete, human-gated steps and **refuses to build a package whose git
`HEAD` differs from the commit you explicitly approved** after reading the diff.

"I reviewed this PKGBUILD" becomes a persistent, auditable fact — a recorded
commit hash — not a fleeting y/N prompt.

- Python 3 standard library only. No dependencies.
- Operates on the **current working directory**, git-style. No hidden global state.
- Cloned AUR repos live under `./packages/<pkg>/`, kept separate from the tool's
  own files; state lives in `./aurtool.json`.

## Install

```sh
chmod +x aurtool
ln -s "$PWD/aurtool" ~/.local/bin/aurtool   # ensure ~/.local/bin is on PATH
```

Then work inside a directory of your choosing, e.g. `~/aur`:

```sh
mkdir -p ~/aur && cd ~/aur
```

## The trust model

```
add ──► clone (HEAD unreviewed) ──► diff (eyeball) ──► approve (records HEAD) ──► build ──► installed
                                                                                     │
   update (git pull moves HEAD; the approved commit does NOT) ◄───────────────────────┘
        │
        └─► HEAD ≠ approved  ──► diff ──► approve ──► build
```

`aurtool.json` stores only the approved commit per package:

```json
{
  "version": 1,
  "packages": { "some-pkg": { "approved_commit": "a1b2c3..." } }
}
```

Installed versions are read live from `pacman -Q`; available versions from each
clone's `.SRCINFO`. Nothing derived is cached, so nothing goes stale.

## Commands

| Command | What it does |
|---|---|
| `aurtool add <pkg>...` | Clone `https://aur.archlinux.org/<pkg>.git` into `./packages/<pkg>` and manage it. Starts **UNREVIEWED**. |
| `aurtool update [pkg...]` | `git pull --ff-only` each package, then print the status table. |
| `aurtool status [pkg...]` | Status table without pulling. |
| `aurtool diff [pkg...]` | `git log` + `git diff` from the approved commit to `HEAD` (full PKGBUILD if never approved). |
| `aurtool approve [pkg...]` | Record the current `HEAD` as approved (prompts per package; `-y` to skip prompt). |
| `aurtool build [pkg...]` | Build & install **approved** packages via `makepkg -si`. Refuses anything not at its approved commit. |
| `aurtool remove <pkg>...` | Stop managing a package (`--purge` also deletes its folder). |

Build flags: `--force` (rebuild even if up to date), `--dry-run` (show build
order and stop), `--noconfirm` (pass through to `makepkg`). Builds are ordered
so that managed AUR dependencies build before the packages that need them.

The status `REVIEW` column reads `UNREVIEWED` (never approved), `CHANGED`
(approved once, but `HEAD` has moved since — re-review), or `reviewed`.

## Worked example

```sh
cd ~/aur

aurtool add some-aur-pkg          # clones ./packages/some-aur-pkg, UNREVIEWED
aurtool status                    # AVAILABLE shown, INSTALLED -, REVIEW UNREVIEWED
aurtool diff some-aur-pkg         # read the full PKGBUILD / .install / sources
aurtool build some-aur-pkg        # REFUSED: not at approved commit
aurtool approve some-aur-pkg      # records HEAD after you confirm
aurtool build some-aur-pkg        # makepkg -si

# later, upstream pushes a new commit:
aurtool update                    # pulls; REVIEW flips to CHANGED
aurtool diff some-aur-pkg         # see exactly what changed since you approved
aurtool approve some-aur-pkg      # re-approve only if it looks safe
aurtool build some-aur-pkg        # rebuild & reinstall
```

## Tests

```sh
python3 -m unittest discover tests
```

The suite covers `.SRCINFO` parsing, the `vercmp` wrapper, build ordering, and
state round-tripping. None of it touches a live AUR, `pacman`, or `makepkg`.

## Out of scope (v1)

- Uninstalling system packages — use `pacman -R`.
- GPG verification of upstream sources — `makepkg` already does this where a
  PKGBUILD defines it.
- Resolving AUR dependencies that you haven't added yourself; only ordering
  among already-managed packages is handled. Unmanaged deps are left to
  `makepkg`/`pacman`.
