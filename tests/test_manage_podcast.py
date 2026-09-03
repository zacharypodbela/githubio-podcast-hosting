import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "manage_podcast.py"


class PodcastCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "feed.yml").write_text("{}\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, *args, env=None, check=True):
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.root,
            env=command_env,
            text=True,
            capture_output=True,
            check=check,
        )

    def create_feed(self):
        self.run_cli("create_feed", "test", "--title", "Test Podcast")

    def episode_directories(self):
        return list((self.root / "public" / "episodes").iterdir())

    def test_add_episode_stores_current_utc_publication_timestamp_by_default(self):
        self.create_feed()
        audio = self.root / "new-episode.mp3"
        audio.write_bytes(b"audio")
        os.utime(audio, (946684800, 946684800))

        before = datetime.now(timezone.utc)
        self.run_cli("add_episode", str(audio), "--feed", "test")
        after = datetime.now(timezone.utc)

        [episode_dir] = self.episode_directories()
        metadata = yaml.safe_load((episode_dir / "episode.yml").read_text(encoding="utf-8"))
        self.assertEqual(set(metadata), {"published_at"})
        published_at = datetime.fromisoformat(metadata["published_at"].replace("Z", "+00:00"))
        self.assertIsNotNone(published_at.tzinfo)
        self.assertEqual(published_at.utcoffset(), timezone.utc.utcoffset(published_at))
        self.assertLessEqual(before, published_at)
        self.assertLessEqual(published_at, after)

    def test_add_episode_accepts_offset_timestamp_and_rebuild_uses_it(self):
        self.create_feed()
        audio = self.root / "offset.mp3"
        audio.write_bytes(b"audio")

        self.run_cli(
            "add_episode",
            str(audio),
            "--feed",
            "test",
            "--published-at",
            "2024-03-02T05:30:00-08:00",
        )
        [episode_dir] = self.episode_directories()
        metadata = yaml.safe_load((episode_dir / "episode.yml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["published_at"], "2024-03-02T13:30:00Z")

        self.run_cli("rebuild", env={"PODCAST_BASE_URL": "https://example.test"})
        config = yaml.safe_load((self.root / "feed.yml").read_text(encoding="utf-8"))
        feed_id = config["test"]["feed_id"]
        rss = ET.parse(self.root / "public" / "feeds" / f"{feed_id}.xml")
        self.assertEqual(
            rss.findtext("./channel/item/pubDate"),
            "Sat, 02 Mar 2024 13:30:00 GMT",
        )

    def test_add_episode_accepts_z_timestamp(self):
        self.create_feed()
        audio = self.root / "utc.mp3"
        audio.write_bytes(b"audio")

        self.run_cli(
            "add_episode",
            str(audio),
            "--feed",
            "test",
            "--published-at",
            "2024-03-02T13:30:00Z",
        )

        [episode_dir] = self.episode_directories()
        metadata = yaml.safe_load((episode_dir / "episode.yml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["published_at"], "2024-03-02T13:30:00Z")

    def test_add_episode_rejects_naive_publication_timestamp(self):
        self.create_feed()
        audio = self.root / "naive.mp3"
        audio.write_bytes(b"audio")

        result = self.run_cli(
            "add_episode",
            str(audio),
            "--feed",
            "test",
            "--published-at",
            "2024-03-02T13:30:00",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timezone", result.stderr.lower())
        self.assertFalse((self.root / "public" / "episodes").exists())

    def test_rebuild_sorts_newest_first_and_falls_back_to_audio_mtime(self):
        episodes_root = self.root / "public" / "episodes"
        episodes_root.mkdir(parents=True)
        entries = []
        fixtures = [
            ("oldest", "2022-01-01T00:00:00Z", None),
            ("newest", "2024-01-01T00:00:00Z", None),
            ("legacy", None, datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()),
        ]
        for title, published_at, mtime in fixtures:
            episode_dir = episodes_root / title
            episode_dir.mkdir()
            audio = episode_dir / "audio.mp3"
            audio.write_bytes(title.encode())
            if mtime is not None:
                os.utime(audio, (mtime, mtime))
            metadata = {"title": title, "description": f"{title} description"}
            if published_at is not None:
                metadata["published_at"] = published_at
            (episode_dir / "episode.yml").write_text(
                yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
            )
            entries.append(episode_dir.relative_to(self.root).as_posix())

        (self.root / "feed.yml").write_text(
            yaml.safe_dump(
                {
                    "test": {
                        "feed_id": "feed-id",
                        "title": "Test Podcast",
                        "episodes": entries,
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        self.run_cli("rebuild", env={"PODCAST_BASE_URL": "https://example.test"})

        rss = ET.parse(self.root / "public" / "feeds" / "feed-id.xml")
        items = rss.findall("./channel/item")
        self.assertEqual([item.findtext("title") for item in items], ["newest", "legacy", "oldest"])
        date_texts = [item.findtext("pubDate") for item in items]
        self.assertNotIn(None, date_texts)
        dates = [parsedate_to_datetime(date_text) for date_text in date_texts if date_text]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(items[1].findtext("pubDate"), "Sun, 01 Jan 2023 00:00:00 GMT")


if __name__ == "__main__":
    unittest.main()
