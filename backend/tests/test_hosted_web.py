"""Hosted web page: a public chat link with anonymous visitors.

A Hosted Web page is the third browser delivery mode next to the iframe widget
and the server-issued chat token. It must work with no host page, no identity
provider and no API key in the browser — while still being gated by an explicit
switch, revocable by rotating the link, and confined to the chat surface.
"""

from uuid import uuid4

import pytest
from test_open_platform import PUBLIC, ROOT, application
from test_platform_postgres import create_agent, execute_next, platform  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

HOSTED = "/api/v1/hosted"


def bearer(token):
    return {"Authorization": "Bearer " + token}


async def test_hosted_link_session_isolation_and_revocation(platform):
    client, _services, _settings = platform
    agent, _ = await create_agent(client)
    app, _key = await application(client, agent["id"])
    endpoint = ROOT + "/" + app["id"] + "/embed"

    # Nothing is public until the page is switched on.
    assert (await client.get(HOSTED + "/" + uuid4().hex)).status_code == 404
    assert (
        await client.post(HOSTED + "/" + uuid4().hex + "/sessions", json={})
    ).status_code == 404

    cfg = {
        "enabled": True,
        "origins": ["https://oa.example"],
        "provider_ids": [],
        "hosted": True,
        "welcome": "你好，我能帮你查订单。",
        "title": "在线助手",
        "color": "#123456",
    }
    saved = await client.put(endpoint, json=cfg)
    assert saved.status_code == 200, saved.text
    config = saved.json()
    link = config["hosted_key"]
    assert link and config["hosted"] is True

    page = await client.get(HOSTED + "/" + link)
    assert page.status_code == 200, page.text
    assert page.json() == {
        "title": "在线助手",
        "color": "#123456",
        "welcome": "你好，我能帮你查订单。",
        "application": app["name"],
    }

    # A visitor gets a credential with no identity provider involved.
    minted = await client.post(HOSTED + f"/{link}/sessions", json={"visitor_id": "visitor-a"})
    assert minted.status_code == 201, minted.text
    session = minted.json()
    assert session["access_token"].startswith("chat_")
    assert session["external_user_id"].startswith("enterprise:")
    headers = bearer(session["access_token"])
    assert (await client.get(PUBLIC + "/targets", headers=headers)).status_code == 200

    # The visitor keeps one customer namespace across reloads, and two visitors
    # never share one.
    again = await client.post(HOSTED + f"/{link}/sessions", json={"visitor_id": "visitor-a"})
    assert again.json()["user"]["id"] == session["user"]["id"]
    other = await client.post(HOSTED + f"/{link}/sessions", json={"visitor_id": "visitor-b"})
    assert other.json()["user"]["id"] != session["user"]["id"]
    # A page without a stored visitor id still gets a usable identity.
    anonymous = await client.post(HOSTED + f"/{link}/sessions")
    assert anonymous.status_code == 201
    assert anonymous.json()["visitor_id"]

    # A hosted credential reaches the chat surface only: it is not a workbench
    # login and it is not an application key.
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401
    assert (await client.get(PUBLIC + "/knowledge-bases", headers=headers)).status_code == 403

    # A public visitor can hold a real conversation through the same entry the
    # widget uses.
    created = await client.post(
        PUBLIC + "/conversations",
        headers=headers,
        json={"agent_id": agent["id"], "external_session_id": "page-1"},
    )
    assert created.status_code == 201, created.text
    answer = await client.post(
        PUBLIC + f"/conversations/{created.json()['conversation_id']}/messages",
        headers={**headers, "Idempotency-Key": "hosted-1"},
        json={"message": "你好", "wait_seconds": 0},
    )
    assert answer.status_code == 202, answer.text
    await execute_next(_services, _settings)
    assert (await client.get(PUBLIC + "/runs/" + answer.json()["id"], headers=headers)).json()[
        "status"
    ] == "completed"

    # Rotating the link is the revocation lever: the address disappears and the
    # credentials minted from it stop working.
    rotated = await client.post(endpoint + "/hosted-key")
    assert rotated.status_code == 200, rotated.text
    new_link = rotated.json()["hosted_key"]
    assert new_link != link
    assert (await client.get(HOSTED + "/" + link)).status_code == 404
    assert (await client.get(PUBLIC + "/targets", headers=headers)).status_code == 401
    assert (await client.get(HOSTED + "/" + new_link)).status_code == 200
    renewed = await client.post(HOSTED + f"/{new_link}/sessions", json={})
    assert (await client.get(PUBLIC + "/targets", headers=bearer(renewed.json()["access_token"]))).status_code == 200

    # Switching the page off closes it without touching the iframe configuration.
    final = await client.put(
        endpoint,
        json={**cfg, "hosted": False, "revision": rotated.json()["revision"]},
    )
    assert final.status_code == 200, final.text
    assert final.json()["hosted"] is False
    assert (await client.get(HOSTED + "/" + new_link)).status_code == 404
    assert (
        await client.get(
            PUBLIC + "/targets", headers=bearer(renewed.json()["access_token"])
        )
    ).status_code == 401
    # The link survives a disable/enable cycle so shared URLs keep working.
    assert final.json()["hosted_key"] == new_link


async def test_hosted_page_matches_the_public_quota(platform):
    """Public traffic spends the application's own per-minute request budget."""

    client, _services, _settings = platform
    agent, _ = await create_agent(client)
    app, _key = await application(client, agent["id"], rpm=2)
    saved = await client.put(
        ROOT + "/" + app["id"] + "/embed",
        json={"enabled": True, "origins": ["https://oa.example"], "hosted": True},
    )
    assert saved.status_code == 200, saved.text
    token = (
        await client.post(HOSTED + f"/{saved.json()['hosted_key']}/sessions", json={})
    ).json()["access_token"]
    # rpm=2: the two probes fit, the third is throttled exactly like an API key.
    assert (await client.get(PUBLIC + "/targets", headers=bearer(token))).status_code == 200
    assert (await client.get(PUBLIC + "/targets", headers=bearer(token))).status_code == 200
    limited = await client.get(PUBLIC + "/targets", headers=bearer(token))
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "application_rate_limit"
