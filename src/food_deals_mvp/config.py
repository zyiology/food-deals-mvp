"""Source paths are relative to the source configuration file."""

from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Sources
from .storage import read_json


def load_sources(path: Path) -> Sources:
    config = Sources.model_validate(read_json(path))
    ids = [source.channel_id for source in config.sources]
    if len(ids) != len(set(ids)):
        raise ValueError("source configuration contains duplicate channel IDs")
    roots = [(path.parent / source.export_root).resolve() for source in config.sources]
    if len(roots) != len(set(roots)):
        raise ValueError("source configuration contains duplicate export roots")
    for source in config.sources:
        ZoneInfo(source.export_timezone)
    return config
