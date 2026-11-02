#!/usr/bin/env python3
"""Shared compare-and-swap GitHub pointer updates for cache bundle publishers."""
from __future__ import annotations

import base64
import json
import subprocess
import time
from typing import Any, Callable


def _api(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    repository: str,
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command = ["gh", "api", f"repos/{repository}/{endpoint}"]
    kwargs: dict[str, Any] = {"check": True, "capture_output": True, "text": True}
    if method != "GET":
        command.extend(["--method", method])
        if payload is not None:
            kwargs["input"] = json.dumps(payload)
            command.extend(["--input", "-"])
    result = runner(command, **kwargs)
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


def _read_branch(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    repository: str,
    branch: str,
) -> str | None:
    try:
        result = _api(runner, repository, f"git/ref/heads/{branch}")
    except subprocess.CalledProcessError as exc:
        if "404" in (exc.stderr or "") or "Not Found" in (exc.stderr or ""):
            return None
        raise
    return result["object"]["sha"]


def _ensure_branch(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    repository: str,
    branch: str,
) -> str:
    current = _read_branch(runner, repository, branch)
    if current:
        return current
    main = _api(runner, repository, "git/ref/heads/main")["object"]["sha"]
    try:
        _api(
            runner,
            repository,
            "git/refs",
            method="POST",
            payload={"ref": f"refs/heads/{branch}", "sha": main},
        )
    except subprocess.CalledProcessError as exc:
        # Another publisher may have created the branch concurrently.
        if "422" not in (exc.stderr or "") and "already exists" not in (exc.stderr or "").lower():
            raise
    current = _read_branch(runner, repository, branch)
    if not current:
        raise RuntimeError(f"Could not create or read cache pointer branch {branch}")
    return current


def _pointer_from_tree(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    repository: str,
    commit_sha: str,
    path: str,
) -> dict[str, Any] | None:
    commit = _api(runner, repository, f"git/commits/{commit_sha}")
    tree_sha = commit["tree"]["sha"]
    tree = _api(runner, repository, f"git/trees/{tree_sha}?recursive=1")
    entry = next(
        (item for item in tree.get("tree", []) if item.get("path") == path),
        None,
    )
    if entry is None:
        return None
    blob = _api(runner, repository, f"git/blobs/{entry['sha']}")
    raw = blob["content"]
    if blob.get("encoding") == "base64":
        decoded = base64.b64decode(raw).decode("utf-8")
    else:
        decoded = raw
    value = json.loads(decoded)
    if not isinstance(value, dict):
        raise ValueError(f"Existing cache pointer {path} is not a JSON object")
    return value


def advance_pointer(
    repository: str,
    path: str,
    value: dict[str, Any],
    is_same_or_stale: Callable[[dict[str, Any], dict[str, Any]], bool],
    *,
    label: str,
    branch: str = "cache-manifests",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    max_attempts: int = 8,
) -> str:
    """Atomically advance one JSON pointer, preserving other files on its branch.

    The callback returns True when the incoming value is already current; it may
    raise when the incoming generation is stale or conflicts with the current one.
    """
    if not repository or not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("Invalid repository or cache pointer path")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    for attempt in range(max_attempts):
        head = _ensure_branch(runner, repository, branch)
        current = _pointer_from_tree(runner, repository, head, path)
        if current is not None and is_same_or_stale(value, current):
            return head

        blob = _api(
            runner,
            repository,
            "git/blobs",
            method="POST",
            payload={"content": json.dumps(value, sort_keys=True, separators=(",", ":")), "encoding": "utf-8"},
        )["sha"]

        commit = _api(runner, repository, f"git/commits/{head}")
        base_tree = commit["tree"]["sha"]
        tree = _api(runner, repository, f"git/trees/{base_tree}?recursive=1")
        entries = [
            {
                "path": item["path"],
                "mode": item.get("mode", "100644"),
                "type": item.get("type", "blob"),
                "sha": item["sha"],
            }
            for item in tree.get("tree", [])
            if item.get("path") != path
        ]
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob})
        new_tree = _api(
            runner,
            repository,
            "git/trees",
            method="POST",
            payload={"base_tree": base_tree, "tree": entries},
        )["sha"]
        new_commit = _api(
            runner,
            repository,
            "git/commits",
            method="POST",
            payload={
                "message": f"Advance {label} cache bundle pointer",
                "tree": new_tree,
                "parents": [head],
            },
        )["sha"]
        try:
            _api(
                runner,
                repository,
                f"git/refs/heads/{branch}",
                method="PATCH",
                payload={"sha": new_commit, "force": False},
            )
            return new_commit
        except subprocess.CalledProcessError as exc:
            # A concurrent publisher moved the branch. Re-read and rebuild on
            # its latest tree so the other cache-domain pointer is preserved.
            if "422" not in (exc.stderr or "") and "Reference update failed" not in (exc.stderr or ""):
                raise
            if attempt + 1 == max_attempts:
                raise RuntimeError(
                    f"Could not advance {label} cache pointer after {max_attempts} concurrent updates"
                ) from exc
            time.sleep(min(0.05 * (attempt + 1), 0.25))

    raise RuntimeError(f"Could not advance {label} cache pointer")
