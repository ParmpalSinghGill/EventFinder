# Shared

Used by both [gold](../gold/README.md) and [stocks](../stock/README.md).

| File | What it does |
|---|---|
| `find_labels.py` | Pivot highs and lows. A level drops once a later candle trades through it. |
| `web_control_dashboard.py` | Page at http://localhost:5050 |
| `run_dashboard.bat` | Starts that page |
| `background_event_manager.py` | Repeating loop: gold watch, and the stock list at its scheduled times |
| `start_event_finders_background.vbs` | Starts the page and the loop with no console window |
| `install_startup_shortcut.bat` | Puts dashboard + gold/stock loop in Windows Startup and starts them now |
| `.env` | Telegram and Discord secrets. Not committed. |
| `logs/` | Dashboard and loop logs |

From the EventFinder folder:

```powershell
python utils\web_control_dashboard.py
```
