import pytest

from ansible_base.resource_registry.models import ResourceType


@pytest.mark.django_db
def test_get_conflicting_resource(admin_api_client, team):
    team_type = ResourceType.objects.get(name="shared.team")
    org_id = str(team.organization.resource.ansible_id)
    dupe = team_type.get_conflicting_resource({"name": team.name, "organization": org_id})

    assert dupe.ansible_id == team.resource.ansible_id

    dupe = team_type.get_conflicting_resource({"name": "I don't exist", "organization": org_id})
    assert dupe is None
