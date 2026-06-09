import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from spider.config.compat import model_dump
from spider.config.loader import load_app_config
from spider.core.engine import SpiderEngine
from spider.core.scheduler import SpiderScheduler
from spider.utils.logging import log_event, setup_logging


LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(description="Config-driven tender spider")
    parser.add_argument(
        "--root",
        default=None,
        help="Project root containing settings.yaml and sites/ (auto-detected when omitted)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=LOG_LEVEL_CHOICES,
        help="Log level override. If omitted, use settings runtime.log_level (default INFO)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logs (same as --log-level DEBUG)",
    )

    sub = parser.add_subparsers(dest="command")
    sub.required = True

    run_all = sub.add_parser("run-all", help="Run all enabled sites once")
    run_all.add_argument("--local-test", action="store_true", help="Write results to local file instead of Redis queues")
    run_all.add_argument(
        "--local-test-output",
        nargs="?",
        const=None,
        default=None,
        help="Optional JSONL output file for local test mode; if omitted, use default path",
    )

    run_site = sub.add_parser("run-site", help="Run one site once")
    run_site.add_argument("site_id")
    run_site.add_argument("--local-test", action="store_true", help="Write results to local file instead of Redis queues")
    run_site.add_argument(
        "--local-test-output",
        nargs="?",
        const=None,
        default=None,
        help="Optional JSONL output file for local test mode; if omitted, use default path",
    )

    run_once = sub.add_parser("run-once", help="Run one URL once using a site config")
    run_once.add_argument("--site-id", required=True)
    run_once.add_argument("--url", required=True)
    run_once.add_argument("--local-test", action="store_true", help="Write results to local file instead of Redis queues")
    run_once.add_argument(
        "--local-test-output",
        nargs="?",
        const=None,
        default=None,
        help="Optional JSONL output file for local test mode; if omitted, use default path",
    )

    dry = sub.add_parser("dry-run-config", help="Validate and print one site config")
    dry.add_argument("site_id")

    sub.add_parser("schedule", help="Start scheduler")
    return parser


def _run_async(coro):
    # type: (object) -> None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _walk_up(path_obj):
    # type: (Path) -> list
    current = path_obj.resolve()
    output = []
    while True:
        output.append(current)
        if current.parent == current:
            break
        current = current.parent
    return output


def _looks_like_project_root(path_obj):
    # type: (Path) -> bool
    return (path_obj / "settings.yaml").exists() and (path_obj / "sites").is_dir()


def _resolve_project_root(root_arg):
    # type: (Optional[str]) -> str
    if root_arg:
        explicit = Path(root_arg).resolve()
        if not _looks_like_project_root(explicit):
            raise ValueError("Invalid --root: %s (settings.yaml or sites/ not found)" % explicit)
        return str(explicit)

    start_points = [Path.cwd(), Path(__file__).resolve().parent.parent]
    seen = set()
    for start in start_points:
        for candidate in _walk_up(start):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if _looks_like_project_root(candidate):
                return str(candidate)

    return str(Path.cwd().resolve())


def _resolve_log_level(root, args):
    # type: (str, argparse.Namespace) -> str
    if args.verbose:
        return "DEBUG"
    if args.log_level:
        return args.log_level

    try:
        cfg = load_app_config(root)
        return str(cfg.runtime.log_level or "INFO").upper()
    except Exception:
        return "INFO"


def _build_engine(root, local_test=False, local_test_output=None):
    # type: (str, bool, Optional[str]) -> SpiderEngine
    cfg = load_app_config(root)
    return SpiderEngine(cfg, local_test=local_test, local_test_output_file=local_test_output)


async def _cmd_run_all(root, local_test=False, local_test_output=None):
    # type: (str, bool, Optional[str]) -> None
    engine = _build_engine(root, local_test=local_test, local_test_output=local_test_output)
    try:
        await engine.run_all()
    finally:
        await engine.aclose()


async def _cmd_run_site(root, site_id, local_test=False, local_test_output=None):
    # type: (str, str, bool, Optional[str]) -> None
    engine = _build_engine(root, local_test=local_test, local_test_output=local_test_output)
    try:
        await engine.run_site(site_id)
    finally:
        await engine.aclose()


async def _cmd_run_once(root, site_id, url, local_test=False, local_test_output=None):
    # type: (str, str, str, bool, Optional[str]) -> None
    engine = _build_engine(root, local_test=local_test, local_test_output=local_test_output)
    try:
        await engine.run_site(site_id, override_entry_urls=[url])
    finally:
        await engine.aclose()


def _cmd_dry_run_config(root, site_id):
    # type: (str, str) -> None
    cfg = load_app_config(root)
    site_map = cfg.site_map()
    if site_id not in site_map:
        raise KeyError("Site not found: %s" % site_id)
    print(json.dumps(model_dump(site_map[site_id]), ensure_ascii=False, indent=2))


async def _cmd_schedule(root):
    # type: (str) -> None
    cfg = load_app_config(root)
    engine = SpiderEngine(cfg)
    scheduler = SpiderScheduler(cfg, engine)
    try:
        await scheduler.run_forever()
    finally:
        await engine.aclose()


def main():
    # type: () -> None
    parser = build_parser()
    args = parser.parse_args()

    try:
        root = _resolve_project_root(args.root)
    except ValueError as exc:
        parser.error(str(exc))

    setup_logging(_resolve_log_level(root, args), log_dir=str(Path(root) / "log"))
    logger = logging.getLogger("default_spider.cli")

    start_ts = time.time()
    log_event(
        logger,
        logging.INFO,
        "cli.command.start",
        command=args.command,
        root=root,
        local_test=bool(getattr(args, "local_test", False)),
    )

    try:
        if args.command == "run-all":
            _run_async(_cmd_run_all(root, args.local_test, args.local_test_output))
            return
        if args.command == "run-site":
            _run_async(_cmd_run_site(root, args.site_id, args.local_test, args.local_test_output))
            return
        if args.command == "run-once":
            _run_async(_cmd_run_once(root, args.site_id, args.url, args.local_test, args.local_test_output))
            return
        if args.command == "dry-run-config":
            _cmd_dry_run_config(root, args.site_id)
            return
        if args.command == "schedule":
            _run_async(_cmd_schedule(root))
            return

        parser.print_help()
    finally:
        cost = round(time.time() - start_ts, 3)
        log_event(logger, logging.INFO, "cli.command.end", command=args.command, duration_seconds=cost)


if __name__ == "__main__":
    main()

