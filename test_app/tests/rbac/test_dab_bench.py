"""
Profile org deletion in DAB test_app: baseline vs defer_rbac_computations.

Run with:
    source ~/venvs/dab/bin/activate
    cd /home/arominge/repos/django-ansible-base
    pytest test_app/tests/rbac/test_dab_bench.py -xvs --no-header -p no:warnings
"""
import time

import pytest

from ansible_base.rbac.models import (
    DABContentType,
    ObjectRole,
    RoleDefinition,
    RoleTeamAssignment,
    RoleUserAssignment,
)
from test_app.models import Inventory, Organization, Team

_bench_counter = 0


def _create_scaled_org(n_teams=150, n_users=50, n_inventories=10):
    """Create an org mirroring the AWX benchmark data shape."""
    global _bench_counter
    _bench_counter += 1
    prefix = f'b{_bench_counter}'

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    User = get_user_model()

    org = Organization.objects.create(name=f'bench-org-{prefix}')
    teams = [Team.objects.create(name=f'{prefix}-team-{i}', organization=org) for i in range(n_teams)]
    inventories = [Inventory.objects.create(name=f'{prefix}-inv-{i}', organization=org) for i in range(n_inventories)]

    now = timezone.now()
    User.objects.bulk_create(
        [User(username=f'{prefix}-user-{i}', date_joined=now) for i in range(n_users)],
        ignore_conflicts=True,
    )
    users = list(User.objects.filter(username__startswith=f'{prefix}-user-').order_by('pk'))

    member_rd = RoleDefinition.objects.managed.team_member
    team_ct = DABContentType.objects.get_for_model(teams[0])

    ObjectRole.objects.bulk_create(
        [ObjectRole(role_definition=member_rd, content_type=team_ct, object_id=str(t.pk)) for t in teams],
        ignore_conflicts=True,
    )
    team_or_map = {
        or_.object_id: or_
        for or_ in ObjectRole.objects.filter(
            role_definition=member_rd, content_type=team_ct, object_id__in=[str(t.pk) for t in teams]
        )
    }

    user_assignments = []
    for team in teams:
        obj_role = team_or_map.get(str(team.pk))
        if not obj_role:
            continue
        for user in users:
            user_assignments.append(
                RoleUserAssignment(
                    user=user,
                    object_role=obj_role,
                    role_definition_id=obj_role.role_definition_id,
                    content_type_id=obj_role.content_type_id,
                    object_id=obj_role.object_id,
                )
            )
    for i in range(0, len(user_assignments), 2000):
        RoleUserAssignment.objects.bulk_create(user_assignments[i : i + 2000], ignore_conflicts=True)

    inv_ct = DABContentType.objects.get_for_model(inventories[0])
    inv_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['change_inventory', 'view_inventory'],
        name=f'{prefix}-inv-admin',
        content_type=inv_ct,
    )

    ObjectRole.objects.bulk_create(
        [ObjectRole(role_definition=inv_rd, content_type=inv_ct, object_id=str(inv.pk)) for inv in inventories],
        ignore_conflicts=True,
    )
    inv_or_map = {
        or_.object_id: or_
        for or_ in ObjectRole.objects.filter(
            role_definition=inv_rd, content_type=inv_ct, object_id__in=[str(inv.pk) for inv in inventories]
        )
    }

    team_assignments = []
    for inv in inventories:
        obj_role = inv_or_map.get(str(inv.pk))
        if not obj_role:
            continue
        for team in teams:
            team_assignments.append(
                RoleTeamAssignment(
                    team=team,
                    object_role=obj_role,
                    role_definition_id=obj_role.role_definition_id,
                    content_type_id=obj_role.content_type_id,
                    object_id=obj_role.object_id,
                )
            )
    RoleTeamAssignment.objects.bulk_create(team_assignments, ignore_conflicts=True)

    from ansible_base.rbac.caching import compute_object_role_permissions, compute_team_member_roles

    compute_team_member_roles()
    compute_object_role_permissions()

    n_rua = RoleUserAssignment.objects.count()
    n_rta = RoleTeamAssignment.objects.count()
    print(f'\n  Created: {n_teams} teams, {n_inventories} inventories, {len(users)} users')
    print(f'  {n_rua} user assignments, {n_rta} team assignments')
    return org


@pytest.mark.django_db
class TestOrgDeleteBenchmark:

    def test_baseline_delete(self):
        """Baseline: org.delete() with no context managers."""
        org = _create_scaled_org()
        pk = org.pk

        t0 = time.time()
        org.delete()
        elapsed = time.time() - t0

        print(f'\n  BASELINE: {elapsed:.2f}s')
        assert Organization.objects.filter(pk=pk).count() == 0

    def test_cached_system_user_only(self):
        """cached_system_user() alone."""
        from ansible_base.lib.utils.models import cached_system_user

        org = _create_scaled_org()
        pk = org.pk

        t0 = time.time()
        with cached_system_user():
            org.delete()
        elapsed = time.time() - t0

        print(f'\n  cached_system_user ONLY: {elapsed:.2f}s')
        assert Organization.objects.filter(pk=pk).count() == 0

    def test_defer_rbac_only(self):
        """defer_rbac_computations() alone."""
        from ansible_base.rbac.triggers import defer_rbac_computations

        org = _create_scaled_org()
        pk = org.pk

        t0 = time.time()
        with defer_rbac_computations():
            org.delete()
        elapsed = time.time() - t0

        print(f'\n  defer_rbac ONLY: {elapsed:.2f}s')
        assert Organization.objects.filter(pk=pk).count() == 0

    def test_deferred_activity_stream_only(self):
        """deferred_activity_stream() alone."""
        from ansible_base.activitystream.signals import deferred_activity_stream

        org = _create_scaled_org()
        pk = org.pk

        t0 = time.time()
        with deferred_activity_stream():
            org.delete()
        elapsed = time.time() - t0

        print(f'\n  deferred_activity_stream ONLY: {elapsed:.2f}s')
        assert Organization.objects.filter(pk=pk).count() == 0

    def test_all_cms_delete(self):
        """With all four CMs (matches the AWX view patch)."""
        from ansible_base.activitystream.signals import deferred_activity_stream
        from ansible_base.lib.utils.models import cached_system_user
        from ansible_base.rbac.triggers import defer_rbac_computations
        from ansible_base.resource_registry.signals.handlers import defer_resource_cleanup

        org = _create_scaled_org()
        pk = org.pk

        t0 = time.time()
        with cached_system_user(), defer_rbac_computations(), deferred_activity_stream(), defer_resource_cleanup():
            org.delete()
        elapsed = time.time() - t0

        print(f'\n  ALL CMs: {elapsed:.2f}s')
        assert Organization.objects.filter(pk=pk).count() == 0
