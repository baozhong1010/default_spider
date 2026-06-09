from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from pydantic import ValidationError

from .compat import model_validate
from .models import AppConfig, DefaultsConfig, RedisConfig, RuntimeConfig, SiteConfig, apply_defaults


def _read_yaml(path):
    # type: (Path) -> Dict[str, Any]
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_site_file(path):
    # type: (Path) -> List[Dict[str, Any]]
    data = _read_yaml(path)
    if not data:
        return []
    if isinstance(data, list):
        return data
    return [data]


def load_app_config(root_dir="."):
    # type: (Union[str, Path]) -> AppConfig
    root = Path(root_dir).resolve()
    settings_path = root / "settings.yaml"
    sites_dir = root / "sites"

    settings = _read_yaml(settings_path)

    redis = model_validate(RedisConfig, settings.get("redis", {}))
    runtime = model_validate(RuntimeConfig, settings.get("runtime", {}))
    defaults = model_validate(DefaultsConfig, settings.get("defaults", {}))

    site_dicts = []  # type: List[Dict[str, Any]]
    if sites_dir.exists():
        for path in sorted(sites_dir.glob("*.y*ml")):
            site_dicts.extend(_load_site_file(path))

    if not site_dicts:
        raise ValueError("No site configuration found in: %s" % sites_dir)

    sites = []  # type: List[SiteConfig]
    errors = []  # type: List[str]
    for raw in site_dicts:
        try:
            site = model_validate(SiteConfig, raw)
            site = apply_defaults(site, defaults)
            sites.append(site)
        except ValidationError as exc:
            errors.append(str(exc))

    if errors:
        raise ValueError("Invalid site configuration:\n" + "\n\n".join(errors))

    return AppConfig(root_dir=root, redis=redis, runtime=runtime, defaults=defaults, sites=sites)
