#!/usr/bin/env python3
import argparse
import mimetypes
import os
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


BASE_URL = os.environ.get("PODCAST_BASE_URL", "").rstrip("/")
PLACEHOLDER_PAGES_URL = "https://YOUR_USERNAME.github.io/YOUR_REPO"
FEEDS_FOLDER = Path("feeds")
PUBLIC_FOLDER = Path("public")
EPISODES_FOLDER = PUBLIC_FOLDER / "episodes"
COVERS_FOLDER = PUBLIC_FOLDER / "covers"
MASTER_CONFIG = Path("feed.yml")
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_GITHUB_FILE_SIZE_BYTES = 100 * 1024 * 1024

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)


def load_master_config():
    require_yaml()
    if not MASTER_CONFIG.exists():
        return {}

    with MASTER_CONFIG.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_master_config(config):
    require_yaml()
    with MASTER_CONFIG.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)


def require_yaml():
    if yaml is None:
        print(
            "Error: PyYAML is required. Install dependencies with "
            "'python3 -m pip install -r requirements.txt'.",
            file=sys.stderr,
        )
        sys.exit(1)


def sanitize_title(filename):
    name = Path(filename).stem
    return name.replace("_", " ").replace("-", " ").strip().title()


def parse_published_at(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise argparse.ArgumentTypeError(
                "published timestamp must be a valid ISO 8601 value"
            ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "published timestamp must include a timezone (for example, Z or +00:00)"
        )

    return parsed.astimezone(timezone.utc)


def format_published_at(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_valid_feed_key(feed_key):
    return bool(feed_key) and all(
        char.islower() or char.isdigit() or char == "-" for char in feed_key
    )


def find_audio_file(episode_dir):
    audio_files = sorted(
        path
        for path in episode_dir.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    return audio_files[0] if audio_files else None


def audio_mime_type(audio_path):
    guessed, _ = mimetypes.guess_type(audio_path.name)
    return guessed or "audio/mpeg"


def validate_publishable_file(file_path):
    file_size = file_path.stat().st_size
    if file_size > MAX_GITHUB_FILE_SIZE_BYTES:
        print(
            f"Error: '{file_path}' is {format_mib(file_size)}. GitHub blocks files "
            "larger than 100 MiB. Compress the file or use external object storage.",
            file=sys.stderr,
        )
        sys.exit(1)


def format_mib(size_bytes):
    return f"{size_bytes / (1024 * 1024):.1f} MiB"


def public_url_path(path):
    try:
        return path.relative_to(PUBLIC_FOLDER).as_posix()
    except ValueError:
        return path.as_posix()


def find_episode_by_id(episode_id):
    if not EPISODES_FOLDER.exists():
        return None

    matches = sorted(
        path
        for path in EPISODES_FOLDER.iterdir()
        if path.is_dir() and episode_id in path.name
    )

    if len(matches) > 1:
        print(
            f"Error: Episode ID '{episode_id}' matches multiple episode folders.",
            file=sys.stderr,
        )
        sys.exit(1)

    return matches[0] if matches else None


def create_base_feed(show_id, show_meta):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = show_meta.get("title", show_id)
    ET.SubElement(channel, "description").text = show_meta.get(
        "description", "No description provided."
    )
    ET.SubElement(channel, "link").text = BASE_URL
    ET.SubElement(channel, "language").text = show_meta.get("language", "en-us")

    cover_path = show_meta.get("cover")
    if cover_path:
        cover_url = f"{BASE_URL}/{public_url_path(Path(cover_path))}"
        image = ET.SubElement(channel, f"{{{ITUNES_NS}}}image")
        image.set("href", cover_url)

        rss_image = ET.SubElement(channel, "image")
        ET.SubElement(rss_image, "url").text = cover_url
        ET.SubElement(rss_image, "title").text = show_meta.get("title", show_id)
        ET.SubElement(rss_image, "link").text = BASE_URL

    return rss, channel


def episode_metadata(episode_dir, audio_path):
    title = sanitize_title(audio_path.name)
    description = "No description provided."
    published_at = None
    metadata_path = episode_dir / "episode.yml"

    if metadata_path.exists():
        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                metadata = yaml.safe_load(f) or {}
            title = metadata.get("title") or title
            description = metadata.get("description") or description
            published_at = metadata.get("published_at")
        except yaml.YAMLError as exc:
            print(f"Warning: Could not parse {metadata_path}: {exc}", file=sys.stderr)

    return title, description, published_at


def resolve_publication_datetime(published_at, audio_path, metadata_path):
    if published_at:
        try:
            return parse_published_at(published_at)
        except argparse.ArgumentTypeError:
            print(
                f"Warning: Invalid published_at in {metadata_path}; using audio mtime.",
                file=sys.stderr,
            )

    return datetime.fromtimestamp(audio_path.stat().st_mtime, tz=timezone.utc)


def build_all_feeds():
    if not BASE_URL:
        print(
            "Error: PODCAST_BASE_URL is required when rebuilding feeds.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = load_master_config()
    (PUBLIC_FOLDER / FEEDS_FOLDER).mkdir(parents=True, exist_ok=True)
    EPISODES_FOLDER.mkdir(parents=True, exist_ok=True)

    for show_key, show_meta in config.items():
        rss, channel = create_base_feed(show_key, show_meta or {})
        episode_paths = (show_meta or {}).get("episodes", [])
        feed_id = (show_meta or {}).get("feed_id")

        if not feed_id:
            print(f"Warning: Feed '{show_key}' is missing feed_id. Skipping.")
            continue

        episodes = []
        for episode_path in episode_paths:
            episode_dir = Path(episode_path)
            if not episode_dir.exists():
                print(f"Warning: Reference path {episode_dir} not found. Skipping.")
                continue

            audio_path = find_audio_file(episode_dir)
            if not audio_path:
                print(f"Warning: No audio file found in {episode_dir}. Skipping.")
                continue

            title, description, published_at = episode_metadata(episode_dir, audio_path)
            publication_datetime = resolve_publication_datetime(
                published_at, audio_path, episode_dir / "episode.yml"
            )
            episodes.append(
                (publication_datetime, audio_path, title, description)
            )

        for publication_datetime, audio_path, title, description in sorted(
            episodes, key=lambda episode: episode[0], reverse=True
        ):
            file_size = audio_path.stat().st_size
            pub_date = format_datetime(
                publication_datetime,
                usegmt=True,
            )
            file_url = f"{BASE_URL}/{public_url_path(audio_path)}"

            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = title
            ET.SubElement(item, "description").text = description
            ET.SubElement(item, "pubDate").text = pub_date

            enclosure = ET.SubElement(item, "enclosure")
            enclosure.set("url", file_url)
            enclosure.set("length", str(file_size))
            enclosure.set("type", audio_mime_type(audio_path))

            guid = ET.SubElement(item, "guid", isPermaLink="true")
            guid.text = file_url

        output_path = PUBLIC_FOLDER / FEEDS_FOLDER / f"{feed_id}.xml"
        tree = ET.ElementTree(rss)
        ET.indent(tree, space="  ", level=0)
        with output_path.open("wb") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            tree.write(f, encoding="utf-8", xml_declaration=False)

        print(f"Rebuilt feed: {output_path}")


def cmd_create_feed(args):
    config = load_master_config()
    show_key = args.feed

    if not is_valid_feed_key(show_key):
        print(
            "Error: Feed key must use only lowercase letters, numbers, and hyphens.",
            file=sys.stderr,
        )
        sys.exit(1)

    if show_key in config:
        print(f"Error: Feed '{show_key}' already exists.", file=sys.stderr)
        sys.exit(1)

    feed_id = str(uuid.uuid4())
    cover_path = None

    if args.cover:
        source_cover = Path(args.cover).expanduser()
        if not source_cover.exists():
            print(f"Error: Cover file '{source_cover}' not found.", file=sys.stderr)
            sys.exit(1)

        if source_cover.suffix.lower() not in COVER_EXTENSIONS:
            print(
                f"Error: '{source_cover}' is not a supported cover image.",
                file=sys.stderr,
            )
            sys.exit(1)

        validate_publishable_file(source_cover)
        COVERS_FOLDER.mkdir(parents=True, exist_ok=True)
        cover_path = COVERS_FOLDER / f"{feed_id}{source_cover.suffix.lower()}"
        shutil.copy2(source_cover, cover_path)

    config[show_key] = {
        "feed_id": feed_id,
        "title": args.title,
        "description": args.description or f"The {args.title} podcast feed.",
        "episodes": [],
    }
    if cover_path:
        config[show_key]["cover"] = cover_path.as_posix()

    save_master_config(config)
    print(
        "Success! Once you push these changes to GitHub, your new feed will be "
        f"available at:\n{PLACEHOLDER_PAGES_URL}/feeds/{feed_id}.xml"
    )


def cmd_add_episode(args):
    config = load_master_config()
    audio_path = Path(args.audio_path).expanduser()

    if args.feed not in config:
        print(f"Error: Target feed '{args.feed}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if not audio_path.exists():
        print(f"Error: Local audio file '{audio_path}' not found.", file=sys.stderr)
        sys.exit(1)

    if audio_path.suffix.lower() not in AUDIO_EXTENSIONS:
        print(f"Error: '{audio_path}' is not a supported audio file.", file=sys.stderr)
        sys.exit(1)

    validate_publishable_file(audio_path)

    episode_dir = EPISODES_FOLDER / str(uuid.uuid4())
    episode_dir.mkdir(parents=True, exist_ok=True)

    destination = episode_dir / f"audio{audio_path.suffix.lower()}"
    shutil.copy2(audio_path, destination)

    published_at = args.published_at or datetime.now(timezone.utc)
    episode = {"published_at": format_published_at(published_at)}
    if args.title or args.description:
        episode = {
            "title": args.title or sanitize_title(audio_path.name),
            "description": args.description or "No description provided.",
            **episode,
        }
    with (episode_dir / "episode.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(episode, f, default_flow_style=False, sort_keys=False)

    config[args.feed].setdefault("episodes", []).append(episode_dir.as_posix())
    save_master_config(config)
    print(f"Episode added to '{args.feed}' at {episode_dir}")


def cmd_cross_post(args):
    config = load_master_config()

    if args.to_feed not in config:
        print(f"Error: Target feed '{args.to_feed}' does not exist.", file=sys.stderr)
        sys.exit(1)

    episode_dir = find_episode_by_id(args.episode_id)

    if not episode_dir:
        print(
            f"Error: Could not find an episode folder matching '{args.episode_id}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    matched_path = episode_dir.as_posix()
    target_episodes = config[args.to_feed].setdefault("episodes", [])
    if matched_path in target_episodes:
        print(f"Episode already cross-posted to '{args.to_feed}'.")
        return

    target_episodes.append(matched_path)
    save_master_config(config)
    print(f"Cross-posted {matched_path} to '{args.to_feed}'.")


def main():
    parser = argparse.ArgumentParser(description="Podcast feed production CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_create = subparsers.add_parser("create_feed", help="Create a new show feed")
    p_create.add_argument("feed", type=str, help="Feed key used by other CLI commands")
    p_create.add_argument("--title", type=str, required=True, help="Human-readable podcast title")
    p_create.add_argument("--description", type=str, help="Overall podcast summary")
    p_create.add_argument("--cover", type=str, help="Path to feed cover art")

    p_add = subparsers.add_parser("add_episode", help="Import audio into a feed")
    p_add.add_argument("audio_path", type=str, help="Path to a local audio file")
    p_add.add_argument("--feed", type=str, required=True, help="Target feed key")
    p_add.add_argument("--title", type=str, help="Episode title")
    p_add.add_argument("--description", type=str, help="Episode description")
    p_add.add_argument(
        "--published-at",
        type=parse_published_at,
        help="Publication timestamp in ISO 8601 format with a timezone",
    )

    p_cross = subparsers.add_parser(
        "cross_post", help="Link an existing episode to another feed"
    )
    p_cross.add_argument("--to-feed", type=str, required=True, help="Destination feed key")
    p_cross.add_argument(
        "--episode-id", type=str, required=True, help="UUID or UUID fragment"
    )

    subparsers.add_parser(
        "rebuild", help="Regenerate public feed files for GitHub Actions"
    )

    args = parser.parse_args()

    if args.command == "create_feed":
        cmd_create_feed(args)
    elif args.command == "add_episode":
        cmd_add_episode(args)
    elif args.command == "cross_post":
        cmd_cross_post(args)
    elif args.command == "rebuild":
        build_all_feeds()


if __name__ == "__main__":
    main()
