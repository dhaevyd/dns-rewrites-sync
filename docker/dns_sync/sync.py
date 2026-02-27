"""Sync orchestration with hub record caching"""

import logging
from typing import Optional

from .servers.base import DNSRecord
from . import db, notifications

logger = logging.getLogger(__name__)


def refresh_hub_cache(db_path: str, hub_cfg: dict, secrets) -> Optional[dict]:
    """
    Fetch records from hub and store in authoritative_records cache.
    Returns the records dict on success, None on failure (falls back to cached).
    """
    from .servers import create_server
    hub_name = hub_cfg["name"]
    hub_server = None
    try:
        hub_server = create_server(hub_cfg["type"], hub_name, hub_cfg, secrets)
        hub_server.connect()
        hub_records = hub_server.get_records()
        db.save_hub_records(db_path, hub_name, hub_records)
        logger.info("Hub cache refreshed for %s (%d record types)", hub_name, len(hub_records))
        return hub_records
    except Exception as e:
        err = str(e)
        logger.error("Hub cache refresh failed (%s): %s", hub_name, err)
        notifications.notify_hub_unreachable(hub_name, hub_cfg["type"], err)
        cached = db.get_cached_hub_records(db_path, hub_name)
        if cached:
            logger.warning("Using cached records for hub %s", hub_name)
        return cached
    finally:
        if hub_server:
            hub_server.disconnect()


def sync_all_enabled_spokes(db_path: str, hub_cfg: dict, spokes: list, secrets) -> dict:
    """
    Sync all enabled spokes against the authoritative cache.
    Returns {spoke_name: stats} for each spoke attempted.
    """
    hub_name = hub_cfg["name"]
    hub_records = db.get_cached_hub_records(db_path, hub_name)
    results = {}

    for spoke_cfg in spokes:
        if not spoke_cfg.get("enabled", True):
            logger.info("Skipping disabled spoke: %s", spoke_cfg["name"])
            continue

        spoke_name = spoke_cfg["name"]
        empty = {"added": 0, "removed": 0, "conflicts": 0, "a_records": 0, "cname_records": 0}

        if hub_records is None:
            msg = "No authoritative cache available — skipping spoke sync"
            db.record_sync(db_path, spoke_name, spoke_cfg["type"], "spoke", empty, error=msg)
            results[spoke_name] = empty
            continue

        spoke_server = None
        try:
            from .servers import create_server
            spoke_server = create_server(spoke_cfg["type"], spoke_name, spoke_cfg, secrets)
            spoke_server.connect()
            stats = _apply_diff(hub_records, spoke_server)
            db.save_spoke_records(db_path, spoke_name, hub_records)
            db.record_sync(db_path, spoke_name, spoke_cfg["type"], "spoke", stats)
            results[spoke_name] = stats
        except Exception as e:
            err = str(e)
            logger.error("Sync failed for %s: %s", spoke_name, err)
            db.record_sync(db_path, spoke_name, spoke_cfg["type"], "spoke", empty, error=err)
            notifications.notify_sync_failed(spoke_name, spoke_cfg["type"], err)
            results[spoke_name] = empty
        finally:
            if spoke_server:
                spoke_server.disconnect()

    return results


def perform_sync(db_path: str, hub_cfg: dict, spoke_cfg: dict, secrets) -> dict:
    """
    Sync a single spoke: always refreshes hub cache first, then diffs against spoke.
    """
    hub_name = hub_cfg["name"]
    spoke_name = spoke_cfg["name"]
    empty = {"added": 0, "removed": 0, "conflicts": 0, "a_records": 0, "cname_records": 0}

    if not spoke_cfg.get("enabled", True):
        logger.info("Skipping disabled spoke: %s", spoke_name)
        return empty

    # Always refresh hub so we diff against the latest records
    hub_records = refresh_hub_cache(db_path, hub_cfg, secrets)
    if hub_records is None:
        msg = "Hub unreachable and no cached records"
        db.record_sync(db_path, spoke_name, spoke_cfg["type"], "spoke", empty, error=msg)
        return empty

    spoke_server = None
    try:
        from .servers import create_server
        spoke_server = create_server(spoke_cfg["type"], spoke_name, spoke_cfg, secrets)
        spoke_server.connect()
        stats = _apply_diff(hub_records, spoke_server)
        db.save_spoke_records(db_path, spoke_name, hub_records)
        db.record_sync(db_path, spoke_name, spoke_cfg["type"], "spoke", stats)
        return stats
    except Exception as e:
        err = str(e)
        logger.error("Sync failed for %s: %s", spoke_name, err)
        db.record_sync(db_path, spoke_name, spoke_cfg["type"], "spoke", empty, error=err)
        notifications.notify_sync_failed(spoke_name, spoke_cfg["type"], err)
        return empty
    finally:
        if spoke_server:
            spoke_server.disconnect()


def _apply_diff(source_records: dict, target_server) -> dict:
    """
    Diff source_records (hub cache) against target_server's live records.
    Adds records missing from target, removes records not in source.
    """
    stats = {"added": 0, "removed": 0, "conflicts": 0, "a_records": 0, "cname_records": 0}
    target_records = target_server.get_records()

    for record_type in ["A", "CNAME"]:
        source_set = source_records.get(record_type, set())
        target_set = target_records.get(record_type, set())
        to_add = source_set - target_set
        to_remove = target_set - source_set

        logger.debug(
            "[%s] %s — source=%d target=%d to_add=%d to_remove=%d",
            target_server.name,
            record_type,
            len(source_set),
            len(target_set),
            len(to_add),
            len(to_remove),
        )

        for record_str in to_add:
            record = (
                DNSRecord.from_a_string(record_str)
                if record_type == "A"
                else DNSRecord.from_cname_string(record_str)
            )
            try:
                result = target_server.add_record(record)
                if result:
                    stats["added"] += 1
                else:
                    logger.warning(
                        "[%s] add_record returned False for %s %s — server rejected without exception",
                        target_server.name,
                        record_type,
                        record_str,
                    )
                    stats["conflicts"] += 1
            except Exception as e:
                logger.error("Failed to add %s %s: %s", record_type, record_str, e)
                stats["conflicts"] += 1

        for record_str in to_remove:
            record = (
                DNSRecord.from_a_string(record_str)
                if record_type == "A"
                else DNSRecord.from_cname_string(record_str)
            )
            try:
                if target_server.delete_record(record):
                    stats["removed"] += 1
                else:
                    logger.warning(
                        "[%s] delete_record returned False for %s %s",
                        target_server.name,
                        record_type,
                        record_str,
                    )
            except Exception as e:
                logger.error("Failed to remove %s %s: %s", record_type, record_str, e)
                stats["conflicts"] += 1

    # Post-sync counts: spoke should now match source (hub)
    stats["a_records"] = len(source_records.get("A", set()))
    stats["cname_records"] = len(source_records.get("CNAME", set()))
    return stats
