# Free and Open Source Podcast Hosing using Github Pages

Distribute your own small-scale podcast with minimal setup so you can:
- Host a public podcast for your niche community or blog
- Create and distribute a private weekly update podcast within your company
- Have your agent do deep dive research reports and automatically publish the findings to a podcast episode for you to consume on your phone. (This was my main reason for building this!)

Highlights:
- Built on top of Github Pages and Github Actions so hosting is free and takes only 4-minutes to setup
- (With a paid Github account) Supports unlisted/undiscoverable RSS feeds, so you can publish sensitive information for consumption by a restricted audience
- Comes with a lightweight CLI that makes it easy for both humans and agents to publish and manage episodes and feeds

## Limitations
- [Published GitHub Pages sites may not be larger than 1 GB.](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [GitHub Pages has a soft bandwidth limit of 100 GB per month.](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [GitHub blocks individual files larger than 100 MiB.](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
- [Github requires a paid account to enable Github Pages on a private repository.](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site?source=post_page---------------------------)
- There is no authentication-based access control. Random feed IDs and episode folders make URLs impossible to guess, but anyone with a URL can fetch the file.

The CLI rejects audio files larger than 100 MiB before adding them to `public/episodes/`.

For spoken-word podcasts, 64 kbps mono MP3 is usually fine. If you adhere to this bitrate, this means approximate limitations of:
- 3.5 hours of audio per episode
- 35 hours of total published audio
- 3,400 hours of audio downloaded per month

These numbers are estimates. Bitrate, MP3 encoder settings, artwork, feed XML, and metadata all count toward the actual storage and bandwidth used.

If you need real access control, high-fidelity audio, or scaled storage and downloads, check out [HarborFM](https://github.com/LoganRickert/HarborFM), which supports users, private feed tokens, and exporting podcast feeds and audio to S3-compatible storage such as Cloudflare R2.

## Setup

1. Fork this repo. If you want to host unlisted podcast feeds or be able to push up episodes before publishing them to your feed, make sure to set the visibility of the forked repo to **Private**.

2. Enable GitHub Pages for the repository and use the included GitHub Actions workflow:

```text
Repository page -> Settings -> Pages -> Build and deployment -> Source -> GitHub Actions
```

In the UI GitHub may shows suggested workflows such as “GitHub Pages Jekyll” or “Static HTML,” do not choose one. This repo already includes a Github Action workflow that will run the next time you push changes to the repo. The workflow detects your GitHub Pages URL automatically, rebuilds the RSS feeds, and publishes the generated `public/` directory.

3. Clone your fork locally and install the only Python dependency:

```bash
python3 -m pip install -r requirements.txt
```

4. Locally create your first feed and add your first podcast episode to it

```bash
python3 manage_podcast.py create_feed my-podcast --title "My Podcast" --description "A show about interesting things." --cover ~/Desktop/cover.jpg
python3 manage_podcast.py add_episode ~/Desktop/interview.mp3 --feed my-podcast --title "First Episode" --description "A short intro episode."
```

5. Push your local changes to Github

```bash
git add feed.yml public/episodes
git commit -m "Add first podcast feed and episode"
git push
```

GitHub Actions will rebuild the feed XML and publish it to GitHub Pages. Use the feed URL printed in step 4, replacing `YOUR_USERNAME` and `YOUR_REPO` with your GitHub username and repository name.

## CLI Usage

**Create a feed:**

```bash
python3 manage_podcast.py create_feed my-podcast --title "My Podcast" --description "A show about interesting things." --cover ~/Desktop/cover.jpg
```

**Add an episode to a feed:**

```bash
python3 manage_podcast.py add_episode ~/Desktop/interview.mp3 --feed my-podcast --title "First Episode" --description "A short intro episode."
```

If title and description are omitted they will be generated based on the audio file name. Episodes default to the current UTC publication time. For imports or backfills, set an explicit timezone-aware ISO 8601 timestamp with `--published-at`:

```bash
python3 manage_podcast.py add_episode ~/Desktop/interview.mp3 --feed my-podcast --published-at "2026-08-30T17:00:00-07:00"
```

**Cross-post an existing episode into an another feed:**

```bash
python3 manage_podcast.py cross_post --to-feed private-notes --episode-id 9c8b7a6f
```

## Project Structure & Publish Workflow

```text
.
├── .github/workflows/publish.yml
├── public/
│   ├── episodes/
│   │   ├── e5f1a8c9-3b2d-4f1a-9d6e-2f4a7b8c9d01/
│   │   │   ├── audio.mp3
│   │   │   └── episode.yml
│   │   └── 9c8b7a6f-5e4d-3c2b-8a1f-0e9d7c6b5a4f/
│   │       └── audio.mp3
│   └── covers/
│       └── 1b3f3b4a-3a40-4f7f-8df5-582c40f3f2fd.jpg
├── feed.yml
├── manage_podcast.py
└── requirements.txt
```

`feed.yml` is the source database. The CLI stores imported audio and optional episode metadata under random UUID folders in `public/episodes/`. Feed cover art is copied to `public/covers/<feed-id>.<ext>` when `create_feed` is run with `--cover`.

Feed files such as `public/feeds/1b3f3b4a-3a40-4f7f-8df5-582c40f3f2fd.xml` are generated inside GitHub Actions and uploaded to GitHub Pages. They are not committed back to the repository. The feed leverages the `feed_id` stored in `feed.yml` so that the url of the feed remains unchanged on subsequent publishes and regenerations and does not break connection of client podcast players that are subscribed to the feed.

### Public URL Formats

Feed URLs:

```text
https://YOUR_USERNAME.github.io/YOUR_REPO/feeds/<feed-id>.xml
```

Episode Audio URLs:

```text
https://YOUR_USERNAME.github.io/YOUR_REPO/episodes/<episode-id>/audio.mp3
```

Cover Art URLs:

```text
https://YOUR_USERNAME.github.io/YOUR_REPO/covers/<feed-id>.jpg
```

### Privacy Notes

Podcast apps need direct HTTP access to the feed XML and audio files. Anything in `public/` should be treated as public.

Feed XML filenames and episode folders both use random UUIDs. This makes feeds and episodes hard to discover unless someone has the URL, but it is not authentication. Do not publish anything to GitHub Pages that requires true access control.
