"""Make and cache all pictures for a story, slowly, without rendering a video.

Usage:
    python -m harmis.prepare --story birbal_khichdi --style 3d_cartoon
    python -m harmis.prepare --story sher_khargosh --format long
    python -m harmis.prepare --story birbal_khichdi --list-file missing.json   # only list what is missing
    python -m harmis.prepare --story birbal_khichdi --only scene:palace_court  # make just one picture

Free image services limit how fast you may ask, so this asks for one picture at
a time with a pause in between (see delay_seconds in config.yaml). Pictures that
are already cached are skipped, so you can run it again later to fill in any
that failed. After that, `python -m harmis.main` with the same story and style
uses the cached pictures straight away.

--list-file and --only are used by the GitHub Actions workflow
(.github/workflows/prepare-pictures.yml), which makes each missing picture in
its own job, in parallel.
"""

import argparse
import json
import sys

from . import script
from .main import add_common_options, resolve_options, setup


def resolve_item(library, needed, name):
    """Turn 'scene:palace_court', 'character:akbar', 'palace_court' or 'Akbar' into an item."""
    if name in needed:
        return name
    for item in needed:
        if item.split(":", 1)[1] == name.lower():
            return item
    found = library.find(name)
    if found and f"character:{found['id']}" in needed:
        return f"character:{found['id']}"
    raise SystemExit(f"'{name}' is not a picture of this story. Pictures: {', '.join(needed)}")


def main():
    parser = argparse.ArgumentParser(description="Pre-generate and cache the pictures for a story.")
    add_common_options(parser)
    parser.add_argument("--list-file", help="do not make pictures; write the MISSING ones to this JSON file")
    parser.add_argument("--only", help="make only this picture, e.g. scene:palace_court or character:akbar")
    args = parser.parse_args()
    if not args.story:
        parser.error("--story is needed (for example --story birbal_khichdi)")
    args = resolve_options(parser, args)
    print(f"[prepare] story={args.story} style={args.style} format={args.format}")

    chain, library = setup(args)
    story = script.get_script(args.genre, args.lang, library, story=args.story, fmt=args.format)
    if args.list_file:  # the prepare-pictures workflow makes (and commits) the character pictures
        needed = library.needed_pictures(story, shots=False)
        missing = [item for item in needed if args.refresh_images or not library.is_ready(item)]
        with open(args.list_file, "w") as file:
            json.dump(missing, file)
        print(f"[prepare] {len(needed)} pictures needed, {len(missing)} missing: {', '.join(missing) or 'none'}")
        return

    needed = library.needed_pictures(story)
    items = [resolve_item(library, needed, args.only)] if args.only else needed
    for item in items:
        library.make_picture(item)

    # Summary: what is ready and what is still missing.
    print("\n[prepare] Pictures:")
    missing = 0
    for label, result in library.status.items():
        ready = result != "shapes"
        missing += not ready
        print(f"  {'OK  ' if ready else 'MISSING'}  {label:<32} {result if ready else 'no provider worked'}")
    if missing:
        print(f"\n[prepare] {missing} picture(s) are missing. Run the same command again later "
              "to retry them (ready pictures are skipped). Videos still work: missing ones are drawn as shapes.")
        sys.exit(1)
    if not args.only:
        print("\n[prepare] All pictures are ready. Now run:\n"
              f"  python -m harmis.main --story {args.story} --style {args.style}")


if __name__ == "__main__":
    main()
