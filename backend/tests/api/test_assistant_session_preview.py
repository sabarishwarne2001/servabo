"""Session previews are bounded and remain private to the conversation owner."""
import uuid

from app.models.assistant import ConversationMessage


def test_preview_contains_real_question_and_is_private(client, tenant, db_session):
    base = f"/api/v1/workspaces/{tenant.workspace.id}/assistant"
    created = client.post(f"{base}/conversations", json={}, headers=tenant.owner.headers)
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    db_session.add(ConversationMessage(
        conversation_id=uuid.UUID(conversation_id), role="user", content="Question " * 40, sources=[],
    ))
    db_session.commit()
    response = client.get(f"{base}/sessions", headers=tenant.owner.headers)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json() if row["id"] == conversation_id)
    assert row["last_message_preview"] == ("Question " * 40)[:180]
    assert row["message_count"] == 1
    other = client.get(f"{base}/sessions", headers=tenant.viewer.headers)
    assert other.status_code == 200
    assert conversation_id not in [row["id"] for row in other.json()]
