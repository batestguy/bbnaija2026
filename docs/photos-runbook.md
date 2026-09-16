# Housemate photos — runbook (deferred task, ~30–45 min)

**Status: DONE (2026-09-16).** All 24 photos sourced, processed, and committed.
QA: 24/24 `<img>` loaded (naturalWidth > 0), zero console errors, zero 404s.

**Provenance (all $0, downloaded, no hotlinking):** official Africa Magic/DStv
housemate headshots — `https://cdn-africamagic.dstv.com/images/003/504/{id}/original/{NAME}.png`
(exact per-housemate URLs recorded in `raw_photos/manifest.json`, local-only).
Source page: the DStv housemates grid (`.../big-brother-naija/season/11/housemates`).
Backup source with 23/24 headshots: Vanguard's roster article (2026/07 uploads).

**Processing notes:** originals were 960×1440 (2:3 portrait, face in the upper
third) — so the crop is **top-anchored**, not center (a center square crop would
have decapitated everyone). 256×256 JPEG q82; largest file 14.6 KB (budget 40 KB).
Rerun: `python /tmp/process_photos.py`-style pass over `raw_photos/*.png` — script
preserved in this doc's git history; raw PNGs are gitignored, re-downloadable via
the manifest URLs.

Original runbook text follows for reference.

## Where photos appear
- **Roster cards** (`docs/assets/script.js` → `avatarHTML`): `<img src="{photo}">`
  in a 34px circle; `onerror` swaps to the initials fallback automatically.
- **Chart end-labels** (canvas): each series draws an 8px-radius circular avatar at
  the line end — images are preloaded (`photos` map) and drawn on `load`; missing
  files draw initials instead. No JS changes needed when files land.

## Filename contract (config is source of truth — never rename in JS)
24 files, kebab-case `.jpg`, under **`docs/assets/photos/`** (Pages-served) and the
same names under `data/assets/photos/` if the runner ever needs them locally:

```
tram.jpg  abi.jpg  aikou.jpg  araga.jpg  barry.jpg  bells.jpg  bluethopia.jpg
cassi.jpg  chimsom-chuka.jpg  flora.jpg  gerard.jpg  goddessa.jpg  keivo.jpg
kamsy.jpg  mercedes.jpg  martins.jpg  neche.jpg  nomy.jpg  oyin.jpg  ricky.jpg
sheba.jpg  sultex.jpg  temi-nkem.jpg  yusuf.jpg
```
Verify any drift with:
```bash
python -c "import json;[print(h['photo']) for h in json.load(open('config/housemates.json',encoding='utf-8'))['housemates']]"
```

## Steps (as originally planned)
1. **Source** images — Africa Magic/DStv housemate pages or Wikipedia cast portraits.
   Respect the $0 ceiling: no paid image APIs; hotlinking is not allowed (dashboard
   must be fully static), so download files into the repo.
2. **Process** to squares, ~256×256, ≤40 KB each (they render at 34px/16px — retina
   headroom only):
   ```bash
   python - <<'EOF'
   from PIL import Image; from pathlib import Path
   for p in Path('raw_photos').glob('*.jpg'):
       im = Image.open(p).convert('RGB')
       s = min(im.size); im = im.crop(((im.width-s)//2,(im.height-s)//2,
                                       (im.width+s)//2,(im.height+s)//2)).resize((256,256))
       im.save(Path('docs/assets/photos')/p.name, quality=82, optimize=True)
   EOF
   ```
   (pillow is in `bap3`; if not: `pip install pillow` into the env, never globally.)
3. **Faces centered in the top 60%** of the square — end-label avatars crop nothing
   (CSS `object-fit: cover`; canvas draws the full square), but roster circles are
   small, so tight head crops read best.
4. **QA:** serve `docs/`, reload, confirm **zero 404s** in console, initials gone on
   both roster + chart, evicted cards keep the dim treatment, Gambit "G" chip still
   overlays where flagged. Quick check:
   ```bash
   cd docs && python -m http.server 8765 &
   # browser: http://localhost:8765/index.html — DevTools console should be clean
   ```
5. **Commit** the jpgs (`docs/assets/photos/*.jpg`) — one commit, message like
   "P7: housemate photos (24) for roster + chart end labels".

## Gotchas
- `chimsom-chuka.jpg` and `temi-nkem.jpg` are the easy ones to misname (two-word
  names) — the contract above is exact.
- Keep the `.gitkeep` in `docs/assets/photos/` (harmless once real files exist).
- If a housemate enters mid-season later (spec allows), add their file AND update
  `config/housemates.json` `photo` in the same commit — config is the contract.
- If an image can't be sourced for someone, leave the file absent: initials fallback
  is an accepted final state, not a bug (per Readme.txt constraint notes).
