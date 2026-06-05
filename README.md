# Franken-Stream

A terminal-based media streamer for movies and TV shows, inspired by [ani-cli](https://github.com/pystardust/ani-cli) but for general content.

## Features

- **Full-screen TUI dashboard**: Modern Textual-based UI with search, result display, and playback controls
- **Vantage Agent TV**: Integrated browsing and playback of Agent TV broadcasts from Vantage API
- **CLI streaming**: Search and stream movies/shows directly from your terminal

- **Multiple providers**: Configurable streaming providers via JSON with automatic updates
- **4-level fallback chain**: Configured providers → regex embed extraction → DuckDuckGo search → yt-dlp YouTube
- **Proxy support**: Optional HTTP proxy configuration for all requests
- **Interactive selection**: Pick from search results with an intuitive menu
- **Auto-download providers**: Fetches provider list from GitHub on first run
- **Termux/Android optimized**: Works on mobile with mpv hardware acceleration
- **Graceful error handling**: Clear error messages and automatic fallbacks

## Installation

### From source

```bash
git clone https://github.com/YOUR_USERNAME/franken-stream.git
cd franken-stream
pip install -e .
```

Or install with development dependencies:

```bash
pip install -e ".[dev]"
```

### Via pip (once published)

```bash
pip install franken-stream
```

## Quick Start

### Launch TUI Dashboard
```bash
# Start the full-screen TUI (default with no args)
franken-stream
```

### Web UI
```bash
# Start the browser-based Web UI locally
franken-stream web --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000` in your browser.

### CLI Commands
```bash
# Search and stream a movie
franken-stream watch "Inception"

# Use interactive mode (default)
franken-stream watch "Breaking Bad"

# With a proxy
franken-stream watch "The Matrix" --proxy http://proxy.example.com:8080

# Search TV shows
franken-stream tv "Breaking Bad" -s 5 -e 14

# Update providers from GitHub
franken-stream update

# Test provider health
franken-stream test-providers

# Show configuration
franken-stream config
```

## Requirements

- Python 3.8+
- `yt-dlp`: For fallback streaming via YouTube search
- `mpv` (optional): For direct video playback

### Dependencies

Installed automatically via pip:
- `typer[all]`: CLI framework
- `requests`: HTTP client
- `beautifulsoup4`: HTML parsing
- `yt-dlp`: YouTube/video downloader
- `rich`: Beautiful terminal output
- `textual`: Full-screen TUI framework

## Configuration

### Provider Configuration

Providers are stored at `~/.franken-stream/providers.json`:

```json
{
  "movie_search_bases": [
    "https://fmovies.to/search?keyword=",
    "https://myflixerz.to/search/",
    "https://solarmovie.pe/search/",
    "https://cineby.ru/search/",
    "https://123moviesfree.net/search/",
    "https://movies2watch.tv/search?q=",
    "https://yuppow.com/search/"
  ],
  "embed_fallbacks": [
    "vidcloud9.com",
    "vidplay.online",
    "upstream.to",
    "mycloud",
    "streamtape.com"
  ],
  "legal_fallbacks": [
    "https://www.youtube.com/results?search_query="
  ],
  "notes": "Sites change frequently—test manually first. Use VPN/proxy if needed. yt-dlp fallback handles 1000+ embeds."
}
```

**First run**: The app will attempt to download providers from GitHub. If that fails, it loads defaults from the config file above.

**To update**: Run `franken-stream update` (pulls fresh list from your GitHub providers repo)

You can also use `~/.franken-stream/providers.toml` instead of `providers.json` for richer provider definitions. Use `{query}` in `base_url` to interpolate the search term.

### Custom Providers

To add your own providers:

1. Edit `~/.franken-stream/providers.json`
2. Add search base URLs (with `{query}` placeholder or append query string)
3. List embed hosts in `embed_fallbacks`
4. Restart the app

Example:

```json
{
  "movie_search_bases": [
    "https://mysite.com/search?q=",
    "https://anothersite.com/?search="
  ],
  "embed_fallbacks": [
    "custom-embed-host",
    "mycloud"
  ]
}
```

## Commands

### Default (TUI Dashboard)

Launch the interactive full-screen dashboard.

```bash
franken-stream
```

**Features:**
- `Ctrl+F` to search
- `Ctrl+V` to browse Vantage Agent TV broadcasts
- `Ctrl+U` to update providers
- `Ctrl+Q` to quit

### `watch`

Search for and stream content.

```bash
franken-stream watch <query> [OPTIONS]

Options:
  --proxy TEXT              HTTP proxy URL
  -p, --interactive/--no-interactive
                           Enable/disable interactive selection (default: enabled)
  --legal-only             Search legal sources only
  -d, --download           Download instead of stream
  -o OUTPUT                Download output directory
  -v, --verbose            Show detailed debug info
```

### `tv`

Search for and stream TV shows with season/episode support.

```bash
franken-stream tv <query> [OPTIONS]

Options:
  -s, --season INT         Season number
  -e, --episode INT        Episode number
  -p, --proxy TEXT         HTTP proxy URL
```

### `update`

Refresh provider list from GitHub.

```bash
franken-stream update
```

### `test-providers`

Test streaming provider health and response times.

```bash
franken-stream test-providers [--fast]

Options:
  --fast                   Quick test (2s timeout instead of 10s)
```

### `config`

Display current configuration paths and statistics.

```bash
franken-stream config
```

### `validate`

Validate the providers configuration file.

```bash
franken-stream validate
```

## How It Works

### Search & Playback Pipeline

Franken-Stream uses a **4-level fallback chain**:

1. **Configured Providers** (BeautifulSoup parsing)
   - Queries multiple provider base URLs in parallel
   - Extracts titles and links from search results

2. **Regex Embed Extraction**
   - Automatically detects embedded video hosts
   - Supports vidcloud, vidplay, upstream, streamtape, etc.

3. **DuckDuckGo Search** (if no local results)
   - Searches the web for streaming links
   - Useful when providers are outdated

4. **yt-dlp YouTube Search** (final fallback)
   - Searches YouTube for full movies/shows
   - Handles 1000+ video embed hosts

### Playback

Once a URL is found:
- **Direct embeds**: Opens in mpv (with hardware acceleration on Android/Termux)
- **Detail pages**: Extracts embedded player links
- **Fallback**: Opens in browser if no player available

## Error Handling

- **Network errors**: Graceful timeouts and fallbacks
- **Parse errors**: Continues with other providers if one fails
- **Missing tools**: Clear error messages (e.g., if yt-dlp not installed)
- **User-Agent**: Includes realistic User-Agent to avoid blocking

## Example Workflow

```bash
$ franken-stream watch "Inception"

Searching for: Inception

Searching: https://fmovies.to/search?keyword=Inception...
✓ Found 8 results
✓ Found 5 results (from second provider)

Search Results
┌─┬────────────────────────┬──────────────────────┐
│#│Title                   │URL                   │
├─┼────────────────────────┼──────────────────────┤
│1│Inception (2010)        │https://...           │
│2│Inception Rewatch       │https://...           │
│3│Inception Explained     │https://...           │
└─┴────────────────────────┴──────────────────────┘

Select result [1-3]: 1

Selected: Inception (2010)
URL: https://fmovies.to/watch/inception-2010

→ Opening in browser...
```

## Troubleshooting

### "yt-dlp not found"
Install yt-dlp:
```bash
pip install yt-dlp
```

### "mpv not found"
Install mpv (optional, for direct video playback):
- **Linux**: `sudo apt install mpv`
- **macOS**: `brew install mpv`
- **Windows**: Download from [mpv.io](https://mpv.io)

### No results found
1. Check your internet connection
2. Verify providers with: `franken-stream config`
3. Try updating: `franken-stream update`
4. Fallback will automatically use yt-dlp

### Proxy issues
Ensure proxy URL format is correct:
```bash
franken-stream watch "Movie" --proxy http://user:pass@proxy.com:8080
```

## Adding Custom Providers

To set up your own provider repository:

1. Create a GitHub repo named `stream-providers`
2. Add `providers.json` with the structure above
3. Update the `github_url` in `franken_stream/providers.py`:
   ```python
   self.github_url = "https://raw.githubusercontent.com/YOUR_USERNAME/stream-providers/main/providers.json"
   ```
4. Rebuild and reinstall

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please:
1. Fork the repo
2. Create a feature branch
3. Add tests (in `tests/` directory)
4. Submit a PR

## Disclaimer

This tool is for educational and personal use only. Users are responsible for verifying that they have the right to stream content. Always respect copyright laws in your jurisdiction.

## Similar Projects

- [ani-cli](https://github.com/pystardust/ani-cli) - Anime streaming CLI
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Video downloader
- [mpv](https://mpv.io/) - Media player
