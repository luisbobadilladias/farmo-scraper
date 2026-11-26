import argparse
import logging


def main() -> None:
    ap = argparse.ArgumentParser(prog="farmo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape", help="run the basket against the pharmacy sites (cached)")
    s.add_argument("--term", action="append", help="search term(s); default: whole basket")
    s.add_argument("--chain", action="append", help="chain(s); default: all")
    n = sub.add_parser("normalize", help="parse names + build equivalence groups")
    n.add_argument("--llm", action="store_true", help="send unparsed names to Claude (optional extra)")
    sub.add_parser("export", help="write the public static site to site/index.html")
    sub.add_parser("report", help="print coverage / match / spread stats used for FINDINGS.md")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.cmd == "scrape":
        from .scrape import run
        run(args.term, args.chain)
    elif args.cmd == "normalize":
        from .normalize import run
        run(["--llm"] if args.llm else [])
    elif args.cmd == "export":
        from .export import run
        run()
    elif args.cmd == "report":
        from .report import run
        run()
