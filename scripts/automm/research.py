"""文献池轮次、元数据核验和关键假设引用门禁。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import ROOT, config_section, hash_json, read_json, read_yaml, utc_now, write_json, write_yaml
from .problems import problem_dir, question_manifest


def _pool_path(problem_id: str, question_id: str) -> Path:
    question_manifest(problem_id, question_id)
    return problem_dir(problem_id) / question_id / "shared" / "literature_pool.yaml"


def load_pool(problem_id: str, question_id: str) -> dict[str, Any]:
    return read_yaml(
        _pool_path(problem_id, question_id), {"question_id": question_id, "dry": False, "items": [], "rounds": []}
    )


def _elapsed_minutes(started_at: str) -> float:
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds() / 60


def start_round(problem_id: str, question_id: str, query: str) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("检索 query 不能为空")
    pool = load_pool(problem_id, question_id)
    if any(item.get("status") == "active" for item in pool.get("rounds", [])):
        raise RuntimeError("已有活动文献检索轮次")
    round_id = f"rnd-{hash_json({'question': question_id, 'query': query, 'at': utc_now()})[:12]}"
    round_item = {"round_id": round_id, "query": query, "status": "active", "started_at": utc_now(), "added_ids": []}
    pool.setdefault("rounds", []).append(round_item)
    pool["dry"] = False
    pool["dry_reason"] = None
    write_yaml(_pool_path(problem_id, question_id), pool)
    return round_item


def _active_round(pool: dict[str, Any]) -> dict[str, Any]:
    active = [item for item in pool.get("rounds", []) if item.get("status") == "active"]
    if len(active) != 1:
        raise RuntimeError("需要且只能有一个活动文献检索轮次")
    return active[0]


def add_candidate(problem_id: str, question_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    pool = load_pool(problem_id, question_id)
    round_item = _active_round(pool)
    config = config_section("research", problem_id, question_id)
    if len(pool.get("items", [])) >= int(config.get("max_items_per_question", 25)):
        raise RuntimeError("文献池已达到数量上限，请结束轮次")
    if _elapsed_minutes(round_item["started_at"]) >= float(config.get("max_search_minutes_per_round", 30)):
        raise RuntimeError("本轮文献检索已达到时间上限，请结束轮次")
    for field in ("id", "title", "source"):
        if not str(candidate.get(field, "")).strip():
            raise ValueError(f"文献候选缺少 {field}")
    fingerprint = str(candidate.get("doi") or candidate.get("url") or candidate["title"]).strip().lower()
    if any(str(item.get("fingerprint", "")).lower() == fingerprint for item in pool.get("items", [])):
        raise RuntimeError("文献候选重复")
    item = {
        **candidate,
        "fingerprint": fingerprint,
        "status": "pending",
        "verified": False,
        "verification_provider": None,
        "verification_error": None,
        "added_at": utc_now(),
        "round_id": round_item["round_id"],
    }
    pool.setdefault("items", []).append(item)
    round_item.setdefault("added_ids", []).append(item["id"])
    write_yaml(_pool_path(problem_id, question_id), pool)
    return item


def _fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "AutoMM/1.0 (metadata verification)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def verify_reference(problem_id: str, question_id: str, reference_id: str) -> dict[str, Any]:
    pool = load_pool(problem_id, question_id)
    item = next((entry for entry in pool.get("items", []) if entry.get("id") == reference_id), None)
    if item is None:
        raise KeyError(f"文献不存在：{reference_id}")
    config = config_section("research", problem_id, question_id)
    metadata = config.get("metadata_verification", {})
    doi = str(item.get("doi", "")).strip().removeprefix("https://doi.org/")
    if not metadata.get("enabled", True) or not doi:
        item["verification_error"] = "元数据核验未启用或没有 DOI"
        write_yaml(_pool_path(problem_id, question_id), pool)
        return item
    cache_dir = ROOT / metadata.get("cache_directory", "runtime/research_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hash_json({'doi': doi})[:20]}.json"
    try:
        if cache_path.exists():
            payload = read_json(cache_path)
            provider = payload["provider"]
        else:
            timeout = int(metadata.get("request_timeout_seconds", 20))
            providers = metadata.get("providers", ["crossref", "openalex"])
            last_error = "没有可用 provider"
            payload = {}
            provider = None
            for name in providers:
                try:
                    if name == "crossref":
                        data = _fetch_json(
                            f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}", timeout
                        )
                        payload = {"provider": name, "record": data.get("message", {})}
                    elif name == "openalex":
                        data = _fetch_json(
                            f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}",
                            timeout,
                        )
                        payload = {"provider": name, "record": data}
                    else:
                        continue
                    provider = name
                    write_json(cache_path, payload)
                    break
                except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    last_error = f"{name}: {exc}"
            if provider is None:
                raise RuntimeError(last_error)
        record = payload.get("record", {})
        item.update(
            {
                "verified": True,
                "verification_provider": provider,
                "verification_error": None,
                "verified_at": utc_now(),
                "verified_title": record.get("title"),
            }
        )
    except Exception as exc:
        item.update({"verified": False, "verification_error": str(exc), "verified_at": utc_now()})
    write_yaml(_pool_path(problem_id, question_id), pool)
    return item


def decide_reference(problem_id: str, question_id: str, reference_id: str, status: str, reason: str) -> dict[str, Any]:
    if status not in {"used", "rejected", "pending"}:
        raise ValueError("文献状态只能是 used、rejected 或 pending")
    if status in {"used", "rejected"} and not reason.strip():
        raise ValueError("文献决策必须说明理由")
    pool = load_pool(problem_id, question_id)
    item = next((entry for entry in pool.get("items", []) if entry.get("id") == reference_id), None)
    if item is None:
        raise KeyError(f"文献不存在：{reference_id}")
    item.update({"status": status, "decision_reason": reason, "decided_at": utc_now()})
    write_yaml(_pool_path(problem_id, question_id), pool)
    citations_path = problem_dir(problem_id) / "citations.yaml"
    citations = read_yaml(citations_path, {"references": []})
    references = citations.setdefault("references", [])
    references[:] = [entry for entry in references if entry.get("id") != reference_id]
    if status == "used":
        references.append({key: value for key, value in item.items() if key not in {"fingerprint", "round_id"}})
    write_yaml(citations_path, citations)
    return item


def finish_round(problem_id: str, question_id: str, dry_reason: str | None = None) -> dict[str, Any]:
    pool = load_pool(problem_id, question_id)
    round_item = _active_round(pool)
    config = config_section("research", problem_id, question_id)
    item_limit = len(pool.get("items", [])) >= int(config.get("max_items_per_question", 25))
    time_limit = _elapsed_minutes(round_item["started_at"]) >= float(config.get("max_search_minutes_per_round", 30))
    allowed = {"item_limit_reached", "time_limit_reached", "all_candidates_decided", "no_new_assumption_family"}
    if dry_reason and dry_reason not in allowed:
        raise ValueError(f"未知 dry 原因：{dry_reason}")
    if dry_reason == "item_limit_reached" and not item_limit:
        raise ValueError("尚未达到文献数量上限")
    if dry_reason == "time_limit_reached" and not time_limit:
        raise ValueError("尚未达到检索时间上限")
    if dry_reason == "all_candidates_decided" and any(
        item.get("status") == "pending" for item in pool.get("items", [])
    ):
        raise ValueError("仍有 pending 文献")
    round_item.update({"status": "completed", "finished_at": utc_now(), "dry_reason": dry_reason})
    pool["dry"] = bool(dry_reason)
    pool["dry_reason"] = dry_reason
    write_yaml(_pool_path(problem_id, question_id), pool)
    return round_item


def check_key_assumptions(problem_id: str, question_id: str) -> dict[str, Any]:
    _, manifest = question_manifest(problem_id, question_id)
    number = int(manifest.get("active_assumption_version", 0))
    if number < 1:
        return {"passed": False, "errors": ["没有活动假设版本"]}
    version = read_yaml(
        problem_dir(problem_id) / question_id / "versions" / f"assumption_v{number:03d}" / "version.yaml"
    )
    pool = load_pool(problem_id, question_id)
    references = {item.get("id"): item for item in pool.get("items", [])}
    errors = []
    minimum = int(config_section("research", problem_id, question_id).get("minimum_items_per_question", 1))
    used_verified = [item for item in pool.get("items", []) if item.get("status") == "used" and item.get("verified")]
    if len(used_verified) < minimum:
        errors.append(f"verified 且 used 的文献只有 {len(used_verified)} 篇，至少需要 {minimum} 篇")
    for assumption in version.get("assumptions", []):
        if not assumption.get("key", False):
            continue
        ids = assumption.get("reference_ids", [])
        valid = [references.get(item) for item in ids]
        if not any(ref and ref.get("verified") and ref.get("status") == "used" for ref in valid):
            errors.append(f"关键假设 {assumption.get('id', '?')} 没有 verified 且 used 的文献")
    return {"passed": not errors, "errors": errors, "assumption_version": version.get("version")}
