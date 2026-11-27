"""Ingestion policy for Skill packages.

These are pure-function tests: no database, no S3, no network. The archive
policy is the security boundary for everything a package endpoint accepts, so
every rejection rule gets an explicit case rather than being covered indirectly
through the API.
"""

import io
import zipfile

import pytest

from agent_platform.business_capabilities.skill_library.importing import (
    MAX_ARCHIVE_BYTES,
    PackageRejected,
    _normalise_name,
    inspect_package,
)

SKILL_MD = b"""---
name: order-status-query
description: Look up an order and answer with its current status.
license: MIT
allowed-tools: order_lookup, order_notes
---

# Order status

Ask for the order id, then query it.
"""


def build(entries: dict[str, bytes], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def rejected(content: bytes) -> str:
    with pytest.raises(PackageRejected) as exc:
        inspect_package(content)
    return exc.value.code


def test_declarative_package_is_parsed():
    inspected = inspect_package(build({"SKILL.md": SKILL_MD, "references/faq.md": b"# FAQ"}))

    assert inspected.skill_name == "order-status-query"
    assert inspected.skill_description.startswith("Look up an order")
    assert inspected.has_scripts is False
    assert inspected.entrypoint is None
    assert inspected.file_count == 2
    assert inspected.digest.startswith("sha256:")
    assert len(inspected.digest) == len("sha256:") + 64
    assert inspected.frontmatter["license"] == "MIT"
    assert inspected.manifest()["skill"]["allowed_tools"] == ["order_lookup", "order_notes"]


def test_wrapping_directory_is_stripped():
    inspected = inspect_package(
        build({"my-skill/SKILL.md": SKILL_MD, "my-skill/references/faq.md": b"# FAQ"})
    )

    assert [item.path for item in inspected.files] == ["SKILL.md", "references/faq.md"]


def test_scripts_are_allowed_but_flagged():
    inspected = inspect_package(
        build({"SKILL.md": SKILL_MD, "scripts/main.py": b"print('hi')\n"})
    )

    assert inspected.has_scripts is True
    assert inspected.entrypoint == "scripts/main.py"
    assert any(item.executable for item in inspected.files)


def test_entrypoint_must_exist_in_the_package():
    document = b"---\nname: x\ndescription: y\nentrypoint: scripts/missing.py\n---\nbody\n"
    inspected = inspect_package(build({"SKILL.md": document, "scripts/other.py": b"pass\n"}))

    assert inspected.entrypoint is None
    assert inspected.has_scripts is True


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "nested/../../escape.txt",
        "/etc/passwd",
        "C:/windows/system32/drivers/etc/hosts",
    ],
)
def test_unsafe_paths_are_rejected(name):
    code = rejected(build({"SKILL.md": SKILL_MD, name: b"nope"}))
    assert code in {"skill_package_path_traversal", "skill_package_invalid_path"}


def test_backslash_path_is_rejected():
    # ``zipfile`` rewrites ``\`` to ``/`` on Windows both when writing and when
    # reading, so the rule cannot be exercised through a real archive on every
    # platform. It is still enforced, because a zip produced elsewhere can carry
    # the raw name, so the predicate is tested directly.
    with pytest.raises(PackageRejected) as exc:
        _normalise_name("references\\faq.md")
    assert exc.value.code == "skill_package_invalid_path"


def test_symlink_entry_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", SKILL_MD)
        link = zipfile.ZipInfo("references/link")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "SKILL.md")

    assert rejected(buffer.getvalue()) == "skill_package_symlink"


@pytest.mark.parametrize("name", ["tool.exe", "bin/lib.so", "run.bat", "setup.ps1", "mod.pyd"])
def test_executable_payloads_are_rejected(name):
    assert rejected(build({"SKILL.md": SKILL_MD, name: b"MZ"})) == (
        "skill_package_executable_payload"
    )


def test_nested_archive_is_rejected():
    assert rejected(build({"SKILL.md": SKILL_MD, "vendor/bundle.zip": b"PK\x03\x04"})) == (
        "skill_package_nested_archive"
    )


def test_missing_manifest_is_rejected():
    assert rejected(build({"README.md": b"# nothing here"})) == (
        "skill_package_missing_manifest"
    )


def test_empty_and_non_zip_payloads():
    assert rejected(b"") == "skill_package_empty"
    assert rejected(b"not a zip at all") == "skill_package_unsupported"


def test_oversized_archive_is_rejected_before_reading():
    assert rejected(b"\x00" * (MAX_ARCHIVE_BYTES + 1)) == "skill_package_too_large"


def test_too_many_entries_is_rejected():
    entries = {"SKILL.md": SKILL_MD}
    entries.update({f"references/{index}.md": b"x" for index in range(210)})
    assert rejected(build(entries)) == "skill_package_too_many_files"


def test_compression_ratio_bomb_is_rejected():
    # 2 MiB of zeros compresses to a few hundred bytes, comfortably past the
    # ratio guard while staying under the absolute size ceiling.
    payload = build({"SKILL.md": SKILL_MD, "assets/blob.bin": b"\x00" * (2 * 1024 * 1024)})
    assert rejected(payload) == "skill_package_compression_ratio"


def test_manifest_without_frontmatter_falls_back_to_body():
    inspected = inspect_package(build({"SKILL.md": b"# Refund helper\n\nHandle refunds.\n"}))

    assert inspected.skill_name == "Imported Skill"
    assert inspected.skill_description == "Refund helper"


def test_broken_frontmatter_is_rejected():
    document = b"---\nname: [unclosed\n---\nbody\n"
    assert rejected(build({"SKILL.md": document})) == "skill_package_manifest_invalid"
