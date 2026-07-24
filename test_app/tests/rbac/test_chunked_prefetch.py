"""Tests for the chunked prefetch iterator and its integration with
compute_object_role_permissions.
"""

import pytest
from django.test.utils import CaptureQueriesContext

from ansible_base.rbac import permission_registry
from ansible_base.rbac.caching import chunked_queryset, compute_object_role_permissions
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID
from ansible_base.rbac.prefetch import TypesPrefetch
from ansible_base.rbac.triggers import defer_rbac_cache
from test_app.models import Inventory, Organization


@pytest.fixture
def org_inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_inventory', 'change_inventory'],
        name='test-org-inv-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


class TestChunkedQueryset:
    @pytest.mark.django_db
    def test_empty_queryset(self):
        results = list(chunked_queryset(Organization.objects.none()))
        assert results == []

    @pytest.mark.django_db
    def test_single_chunk(self):
        orgs = [Organization.objects.create(name=f'chunk_org_{i}') for i in range(3)]
        results = list(chunked_queryset(Organization.objects.filter(name__startswith='chunk_org_'), chunk_size=1000))
        assert set(o.pk for o in results) == set(o.pk for o in orgs)

    @pytest.mark.django_db
    def test_multiple_chunks(self):
        orgs = [Organization.objects.create(name=f'multi_chunk_{i}') for i in range(5)]
        results = list(chunked_queryset(Organization.objects.filter(name__startswith='multi_chunk_'), chunk_size=2))
        assert len(results) == 5
        assert set(o.pk for o in results) == set(o.pk for o in orgs)

    @pytest.mark.django_db
    def test_exact_chunk_boundary(self):
        """Chunk size exactly matches queryset size — no off-by-one."""
        for i in range(4):
            Organization.objects.create(name=f'exact_{i}')
        results = list(chunked_queryset(Organization.objects.filter(name__startswith='exact_'), chunk_size=4))
        assert len(results) == 4

    @pytest.mark.django_db
    def test_prefetch_related_works(self, org_inv_rd, rando):
        """prefetch_related on the queryset is respected by chunked iteration."""
        org = Organization.objects.create(name='prefetch_test_org')
        org_inv_rd.give_permission(rando, org)

        qs = ObjectRole.objects.filter(
            object_id=str(org.pk), content_type=permission_registry.content_type_model.objects.get_for_model(Organization)
        ).prefetch_related('provides_teams')

        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            roles = list(chunked_queryset(qs, chunk_size=100))
            for role in roles:
                list(role.provides_teams.all())

        provides_teams_queries = [q for q in ctx.captured_queries if 'provides_teams' in q['sql']]
        per_object_queries = [q for q in provides_teams_queries if 'IN (' not in q['sql'] and 'objectrole_id' in q['sql']]
        assert len(per_object_queries) == 0, "provides_teams.all() should use prefetch cache, not individual queries"

    @pytest.mark.django_db
    def test_ordering_is_replaced(self):
        """chunked_queryset replaces any existing ordering with pk ordering."""
        for i in range(3):
            Organization.objects.create(name=f'order_{2 - i}')
        qs = Organization.objects.filter(name__startswith='order_').order_by('-name')
        results = list(chunked_queryset(qs, chunk_size=2))
        pks = [o.pk for o in results]
        assert pks == sorted(pks), "Results should be in pk order regardless of original ordering"


class TestNeededCacheUpdatesWithPrefetch:
    @pytest.mark.django_db
    def test_prefetch_cache_used_when_present(self, org_inv_rd, rando):
        """When permission_partials is prefetched, needed_cache_updates should
        use the prefetch cache instead of issuing per-object queries."""
        org = Organization.objects.create(name='cache_test_org')
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)
        roles = list(
            ObjectRole.objects.filter(object_id=str(org.pk)).prefetch_related('permission_partials', 'permission_partials_uuid', 'provides_teams__has_roles')
        )
        assert len(roles) > 0

        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            for role in roles:
                role.needed_cache_updates(types_prefetch=types_prefetch)

        partials_queries = [q for q in ctx.captured_queries if 'dab_rbac_roleevaluation' in q['sql'] and 'SELECT' in q['sql']]
        assert len(partials_queries) == 0, "With prefetched permission_partials, no per-object RoleEvaluation queries should occur"

    @pytest.mark.django_db
    def test_values_list_fallback_without_prefetch(self, org_inv_rd, rando):
        """Without prefetch, needed_cache_updates falls back to values_list queries."""
        org = Organization.objects.create(name='no_cache_test_org')
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)
        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))

        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            for role in roles:
                role.needed_cache_updates(types_prefetch=types_prefetch)

        partials_queries = [q for q in ctx.captured_queries if 'dab_rbac_roleevaluation' in q['sql'] and 'SELECT' in q['sql']]
        assert len(partials_queries) > 0, "Without prefetch, should fall back to values_list queries"

    @pytest.mark.django_db
    def test_both_paths_produce_same_result(self, org_inv_rd, rando):
        """Prefetched and non-prefetched paths should return identical results."""
        org = Organization.objects.create(name='consistency_org')
        for i in range(3):
            Inventory.objects.create(name=f'consistency_inv_{i}', organization=org)
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)

        role_no_prefetch = ObjectRole.objects.filter(object_id=str(org.pk)).first()
        to_delete_no_pf, to_add_no_pf = role_no_prefetch.needed_cache_updates(types_prefetch=types_prefetch)

        role_with_prefetch = list(
            ObjectRole.objects.filter(pk=role_no_prefetch.pk).prefetch_related('permission_partials', 'permission_partials_uuid', 'provides_teams__has_roles')
        )[0]
        to_delete_pf, to_add_pf = role_with_prefetch.needed_cache_updates(types_prefetch=types_prefetch)

        assert to_delete_no_pf == to_delete_pf
        assert set((e.codename, e.content_type_id, e.object_id) for e in to_add_no_pf) == set((e.codename, e.content_type_id, e.object_id) for e in to_add_pf)


class TestComputeObjectRolePermissionsQueryReduction:
    @pytest.mark.django_db
    def test_full_recompute_uses_fewer_queries_than_iterator(self, org_inv_rd, rando):
        """The chunked-prefetch default path should use fewer queries than the
        old .iterator() approach for a non-trivial number of ObjectRoles."""
        orgs = [Organization.objects.create(name=f'qr_org_{i}') for i in range(5)]
        for org in orgs:
            for j in range(3):
                Inventory.objects.create(name=f'qr_inv_{org.name}_{j}', organization=org)

        with defer_rbac_cache():
            for org in orgs:
                org_inv_rd.give_permission(rando, org)

        n_roles = ObjectRole.objects.count()
        assert n_roles >= 5

        from django.db import connection

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)
        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()
        with CaptureQueriesContext(connection) as old_ctx:
            compute_object_role_permissions(object_roles=ObjectRole.objects.iterator(), types_prefetch=types_prefetch)
        old_evals = RoleEvaluation.objects.count()

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)
        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()
        with CaptureQueriesContext(connection) as new_ctx:
            compute_object_role_permissions(object_roles=None, types_prefetch=types_prefetch)
        new_evals = RoleEvaluation.objects.count()

        assert old_evals == new_evals, "Both approaches must produce the same evaluations"
        assert len(new_ctx) < len(old_ctx), f"Chunked prefetch ({len(new_ctx)} queries) should use fewer queries " f"than iterator ({len(old_ctx)} queries)"
