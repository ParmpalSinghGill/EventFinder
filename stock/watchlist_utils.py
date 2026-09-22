import os
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_export_dir() -> str:
    """
    Returns the configured export_dir from config.yml, resolving user directories.
    Defaults to the absolute path of the 'Results' directory inside the project folder.
    """
    default_dir = os.path.join(BASE, "stock", "Results")
    cfg_path = os.path.join(BASE, "stock", "config.yml")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                export_dir = cfg.get("output", {}).get("export_dir", default_dir)
                return os.path.abspath(os.path.expanduser(export_dir))
        except Exception as e:
            print(f"Error reading config.yml in get_export_dir: {e}")
    return os.path.abspath(default_dir)

def sync_and_clean_watchlist(filename: str = None, content: str = None) -> None:
    """
    Saves `content` to `filename` inside `~/Downloads/Watchlist`.
    Then cleans up the directory so only the allowed 4 files remain.
    Allowed files:
      - latest_fyers.txt
      - latest_fyers_new.txt
      - latest_MC_fyers.txt
      - latest_MC_missing.txt
    """
    watchlist_dir = os.path.abspath(os.path.expanduser("~/Downloads/Watchlist"))
    os.makedirs(watchlist_dir, exist_ok=True)

    allowed = {
        "latest_fyers.txt",
        "latest_fyers_new.txt",
        "latest_MC_fyers.txt",
        "latest_MC_missing.txt"
    }

    # 1. If we have a file to write, write it
    if filename and content is not None:
        if filename in allowed:
            target_path = os.path.join(watchlist_dir, filename)
            encoding = "ascii" if "fyers" in filename else "utf-8"
            try:
                with open(target_path, "w", encoding=encoding, newline="") as f:
                    f.write(content)
            except Exception as e:
                print(f"Failed to write watchlist file {target_path}: {e}")

    # 2. Clean up other files in ~/Downloads/Watchlist
    if os.path.exists(watchlist_dir):
        for name in os.listdir(watchlist_dir):
            file_path = os.path.join(watchlist_dir, name)
            if os.path.isfile(file_path):
                if name not in allowed:
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        print(f"Failed to remove {file_path}: {e}")
