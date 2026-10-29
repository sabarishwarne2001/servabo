"""Who sees TRINETRA's write forms matches who the server lets write (Final 2T, Phase 1.6).

The page shows the forms when the active workspace's effective role is ADMIN (`useActiveWorkspace().role`, which is the
server's `effective_role`). The server writes for exactly that role. An organization owner and a workspace administrator
see and may use the forms; a member with a contributor or viewer role sees and may do neither. This pins the pair so
neither side can drift; the browser assertion is in spec 141."""

from tests.trinetra.test_api import world  # noqa: F401


def effective_role(client, tenant, persona):
    context = client.get("/api/v1/me/context", headers=persona.headers).json()
    for organization in context["organizations"]:
        for workspace in organization["workspaces"]:
            if workspace["id"] == str(tenant.workspace.id):
                return workspace["effective_role"]
    return None


def test_write_is_allowed_exactly_when_the_effective_role_is_admin(client, tenant, world):
    url = world[0]
    expected = {"owner": True, "org_admin": True, "ws_admin": True, "contributor": False, "viewer": False}
    for name, may_write in expected.items():
        persona = getattr(tenant, name)
        status = client.post(url + "/profiles", headers=persona.headers, json={"name": "X", "pan": "ABCDE1234F"}).status_code
        assert (status == 200) is may_write, (name, status)
        assert (effective_role(client, tenant, persona) == "ADMIN") is may_write, name
        assert client.get(url + "/credits", headers=persona.headers).status_code == 200  # every role reads
