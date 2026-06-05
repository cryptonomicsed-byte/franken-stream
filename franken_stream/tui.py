"""Enhanced Textual TUI for franken-stream."""

import asyncio
from typing import List, Tuple

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static
from textual.containers import Vertical
from textual.binding import Binding

from franken_stream.providers import ProviderManager
from franken_stream.scraper import ContentScraper
from .tui_agent_tv import AgentTVScreen


class FrankenStreamTUI(App):
    """Full-screen TUI with search, result display, and playback."""

    CSS = """
    Screen { layout: vertical; background: $surface; color: $text; }
    #search-bar { height: 3; dock: top; border-bottom: solid $primary; padding: 0 1; }
    #results-panel { height: 1fr; overflow-y: auto; padding: 1; }
    #select-bar { height: 3; dock: bottom; border-top: solid $accent; padding: 0 1; }
    #status-bar { height: 1; dock: bottom; background: $surface; padding: 0 1; content-align: left middle; }
    .hidden { display: none; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+f", "focus_search", "Search"),
        Binding("ctrl+v", "show_vantage", "Vantage"),
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+u", "update_providers", "Update"),
    ]

    def __init__(self):
        super().__init__()
        self._results: List[Tuple[str, str]] = []
        self._pm: ProviderManager = None
        self._scraper: ContentScraper = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="search-bar"):
            yield Input(placeholder="Search movies & TV shows… (Enter to search)", id="search-input")
        yield Static("", id="results-panel")
        with Vertical(id="select-bar", classes="hidden"):
            yield Input(placeholder="Enter result # to play  (0 = cancel)", id="select-input")
        yield Static(
            " Franken-Stream  │  Ctrl+F search  │  Ctrl+V Vantage  │  Ctrl+U update  │  Ctrl+Q quit",
            id="status-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._pm = ProviderManager()
        self._scraper = ContentScraper(provider_manager=self._pm)
        self.query_one("#search-input", Input).focus()
        self._set_status("Ready — type a title and press Enter")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            query = event.value.strip()
            if query:
                self._set_status(f"Searching '{query}'…")
                asyncio.create_task(self._do_search(query))
        elif event.input.id == "select-input":
            await self._handle_selection(event.value.strip())
            event.input.value = ""

    async def _do_search(self, query: str) -> None:
        try:
            bases = self._pm.get_ranked_search_bases()
            results: List[Tuple[str, str]] = await asyncio.to_thread(
                self._scraper.search, query, bases, False
            )
            self._results = results
            self._render_results(query, results)

            if results:
                self.query_one("#select-bar").remove_class("hidden")
                self.query_one("#select-input", Input).focus()
                self._set_status(
                    f"Found {len(results)} result(s) for '{query}' — enter number to play, 0 to cancel"
                )
            else:
                self._set_status(f"No results for '{query}' — try different keywords")
        except Exception as e:
            self._set_status(f"Search error: {e}")

    def _render_results(self, query: str, results: List[Tuple[str, str]]) -> None:
        from rich.table import Table
        from urllib.parse import urlparse

        panel = self.query_one("#results-panel", Static)

        if not results:
            panel.update("[yellow]No results found[/yellow]")
            return

        table = Table(
            title=f"Results for: {query}",
            expand=True,
            header_style="bold cyan",
            border_style="dim",
        )
        table.add_column("#", style="magenta", width=4, no_wrap=True)
        table.add_column("Title", style="cyan")
        table.add_column("Source", style="dim", width=28)

        for i, (title, url) in enumerate(results[:20], 1):
            domain = urlparse(url).netloc or url[:28]
            table.add_row(str(i), title[:65], domain[:28])

        panel.update(table)

    async def _handle_selection(self, value: str) -> None:
        try:
            num = int(value)
        except ValueError:
            self._set_status(f"Invalid number: '{value}' — enter a result number")
            return

        if num == 0:
            self.query_one("#select-bar").add_class("hidden")
            self.query_one("#search-input", Input).focus()
            self._set_status("Cancelled — type a new search")
            return

        if not self._results or num < 1 or num > len(self._results):
            self._set_status(f"#{num} out of range (1–{len(self._results)})")
            return

        title, url = self._results[num - 1]
        self.query_one("#select-bar").add_class("hidden")
        self._set_status(f"Fetching player for: {title}…")
        asyncio.create_task(self._do_play(title, url))

    async def _do_play(self, title: str, url: str) -> None:
        try:
            embed_url = await asyncio.to_thread(self._scraper.fetch_embed_from_page, url)
            play_url = embed_url or url
            is_embed = bool(embed_url)
            self._set_status(f"Playing: {title}")
            await asyncio.to_thread(self._scraper.play_url, play_url, is_embed, title)
            self._set_status(f"Finished: {title}  │  Ctrl+F to search again")
        except Exception as e:
            self._set_status(f"Playback error: {e}")

    def action_focus_search(self) -> None:
        self.query_one("#select-bar").add_class("hidden")
        self.query_one("#search-input", Input).focus()

    def action_show_vantage(self) -> None:
        self.push_screen(AgentTVScreen())

    def action_cancel(self) -> None:
        self.query_one("#select-bar").add_class("hidden")
        self.query_one("#search-input", Input).focus()
        self._set_status("Cancelled")

    def action_update_providers(self) -> None:
        self._set_status("Updating providers…")
        asyncio.create_task(self._update_providers())

    async def _update_providers(self) -> None:
        ok = await asyncio.to_thread(self._pm.update_providers)
        self._set_status("Providers updated ✓" if ok else "Provider update failed")

    def _set_status(self, message: str) -> None:
        self.query_one("#status-bar", Static).update(f" {message}")


def run_tui() -> None:
    """Entry point for TUI."""
    try:
        FrankenStreamTUI().run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        from rich.console import Console
        Console().print(f"[red]TUI error: {e}[/red]")
        raise
