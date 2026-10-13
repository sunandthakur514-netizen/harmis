"""Make and cache all pictures for a story, slowly, without rendering a video.

Usage:
    python -m harmis.prepare --story birbal_khichdi --style 3d_cartoon
    python -m harmis.prepare --story sher_khargosh --format long

Free image services limit how fast you may ask, so this asks for one picture at
a time with a pause in between (see delay_seconds in config.yaml). Pictures that
are already cached are skipped, so you can run it again later to fill in any
that failed. After that, `python -m harmis.main` with the same story and style
uses the cached pictures straight away.
"""

import argparse
import sys

from . import script
from .main import add_common_options, resolve_options, setup


def main():
    parser = argparse.ArgumentParser(description="Pre-generate and cache the pictures for a story.")
    add_common_options(parser)
    args = parser.parse_args()
    if not args.story:
        parser.error("--story is needed (for example --story birbal_khichdi)")
    args = resolve_options(parser, args)
    print(f"[prepare] story={args.story} style={args.style} format={args.format}")

    chain, library = setup(args)
    story = script.get_script(args.genre, args.lang, library, story=args.story, fmt=args.format)
    library.load_visuals(story)

    # Summary: what is ready and what is still missing.
    print("\n[prepare] Pictures for this story:")
    missing = 0
    for label, result in library.status.items():
        ready = result != "shapes"
        missing += not ready
        print(f"  {'OK  ' if ready else 'MISSING'}  {label:<32} {result if ready else 'no provider worked'}")
    if missing:
        print(f"\n[prepare] {missing} picture(s) are missing. Run the same command again later "
              "to retry them (ready pictures are skipped). Videos still work: missing ones are drawn as shapes.")
        sys.exit(1)
    print("\n[prepare] All pictures are ready. Now run:\n"
          f"  python -m harmis.main --story {args.story} --style {args.style}")


if __name__ == "__main__":
    main()
