# Franken-Stream Quick Start Guide

## 1. Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/franken-stream.git
cd franken-stream

# Install (development mode with editable install)
pip install -e .

# Or just install dependencies
pip install -r requirements.txt
```

## 2. First Run

```bash
# Check configuration
franken-stream config

# Create default providers.json
franken-stream update
```

## 3. Basic Usage

```bash
# Search for a movie
franken-stream watch "Inception"

# Launch TUI Dashboard with Vantage Agent TV
franken-stream
# Inside TUI: Ctrl+F to search, Ctrl+V for Vantage Agent TV broadcasts

# Use with proxy
franken-stream watch "The Matrix" --proxy http://proxy:8080

# Non-interactive mode (just show results)
franken-stream watch "Breaking Bad" --no-interactive
```

## 4. What Happens

1. **Search**: App searches multiple provider URLs for your query
2. **Parse**: Extracts titles and links from HTML
3. **Display**: Shows results in a nice table
4. **Select**: You pick which result to watch
5. **Stream**: Opens link or falls back to yt-dlp

## 5. Troubleshooting

### No results?
- Check internet connection
- Verify providers: `franken-stream config`
- Update providers: `franken-stream update`

### yt-dlp errors?
```bash
pip install --upgrade yt-dlp
```

### Need mpv for direct playback?
```bash
# Linux
sudo apt install mpv

# macOS
brew install mpv

# Or download from https://mpv.io
```

## 6. Adding Custom Providers

Edit `~/.franken-stream/providers.json`:

```json
{
  "movie_search_bases": [
    "https://mysite.com/search?q=",
    "https://other.com/?search="
  ],
  "embed_fallbacks": [
    "mycloud",
    "upstream"
  ]
}
```

Then restart the app.

## 7. Environment Variables (Optional)

```bash
# Set proxy globally
export HTTP_PROXY=http://proxy:8080
export HTTPS_PROXY=http://proxy:8080

# Then use normally
franken-stream watch "Movie Title"
```

## 8. File Structure

```
franken-stream/
├── franken_stream/
│   ├── __init__.py       # Package metadata
│   ├── main.py           # CLI commands
│   ├── providers.py      # Provider management
│   └── scraper.py        # Web scraping logic
├── pyproject.toml        # Package config
├── requirements.txt      # Dependencies
├── README.md            # Full documentation
└── QUICKSTART.md        # This file
```

## 9. Testing

```bash
# Run test suite
python test_demo.py

# Or use the CLI directly
franken-stream watch "test query" --no-interactive
```

## 10. Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Format code
black franken_stream/

# Lint
flake8 franken_stream/
```

## Next Steps

- Read [README.md](README.md) for detailed documentation
- Set up your own [providers repo](https://github.com/new)
- Contribute improvements on GitHub
- Report issues and suggest features

---

**Need help?** Check the README or open an issue!
