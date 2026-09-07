"""Environment configuration for the local read-only application."""

import os
from pathlib import Path

from pydantic import Field

from .models import Contract


class ApiSettings(Contract):
    published_dir: Path
    max_age_days: int = Field(default=60, ge=1, le=3650)

    @classmethod
    def from_env(cls) -> ApiSettings:
        # Editable/source installs have a known project root, independent of cwd.
        project = Path(__file__).resolve().parents[2]
        source_install = (project / "pyproject.toml").is_file() and (
            project / "src/food_deals_mvp"
        ).is_dir()
        configured = os.environ.get("FOOD_DEALS_PUBLISHED_DIR")
        if configured:
            directory = Path(configured).expanduser()
            if not directory.is_absolute():
                if not source_install:
                    raise ValueError("FOOD_DEALS_PUBLISHED_DIR must be absolute")
                directory = project / directory
        elif source_install:
            directory = project / "data/published"
        else:
            raise ValueError("Set FOOD_DEALS_PUBLISHED_DIR for an installed package")
        return cls(
            published_dir=directory.resolve(),
            max_age_days=int(os.environ.get("FOOD_DEALS_MAX_AGE_DAYS", "60")),
        )
