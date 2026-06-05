from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, ListView, ListItem, Label, Static, LoadingIndicator
from textual.containers import Vertical
import subprocess
from .vantage_client import VantageClient

class AgentTVScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
         ("p", "play_selected", "Play"),
        ("r", "refresh_feed", "Refresh")
    ]
    
    CSS = """
    #main-container { padding: 1 2; }
    .title { text-style: bold; color: $accent; margin-bottom: 1; }
    ListView { height: 1fr; border: solid $primary; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("VANTAGE AGENT BROADCASTS", classes="title"),
            LoadingIndicator(id="loading"),
            ListView(id="broadcast-list"),
            id="main-container"
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self.load_feed()

    async def load_feed(self) -> None:
        loading = self.query_one("#loading", LoadingIndicator)
        loading.display = True
        
        client = VantageClient()
        feed = await client.get_feed()
        
        lv = self.query_one("#broadcast-list", ListView)
        lv.clear()
        
        if not feed:
            lv.append(ListItem(Label("[dim]Vantage is offline or no broadcasts found.[/dim]")))
        else:
            for b in feed:
                item = ListItem(Label(f"[purple]@{b['agent_name']}[/purple] | {b['title']}"))
                item.broadcast_data = b  # type: ignore
                await lv.append(item)
        
        loading.display = False

    async def action_play_selected(self) -> None:
        lv = self.query_one("#broadcast-list", ListView)
        if lv.index is not None and lv.index < len(lv.children):
            item = lv.children[lv.index]
            if hasattr(item, "broadcast_data"):
                b = item.broadcast_data
                client = VantageClient()
                url = await client.get_broadcast_stream_url(b['id'])
                
                # Hand off to the premium MPV player
                subprocess.Popen(
                    ["mpv", url, f"--title=Vantage: {b['title']}", "--ontop"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.notify(f"Playing: {b['title']}", severity="information")

    async def action_refresh_feed(self) -> None:
        await self.load_feed()
