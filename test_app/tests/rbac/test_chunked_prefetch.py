"""Tests for EvaluationsPrefetch and the batched recompute path."""

import pytest
from django.test.utils import CaptureQueriesContext

from ansible_base.rbac import permission_registry
from ansible_base.rbac.caching import compute_object_role_permissions
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID
from ansible_base.rbac.prefetch import EvaluationsPrefetch, TypesPrefetch
from ansible_base.rbac.triggers import defer_rbac_cache
from test_app.models import Inventory, Organization


@pytest.fixture
def org_inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_inventory', 'change_inventory'],
        name='test-org-inv-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


class TestEvaluationsPrefetch:
    @pytest.mark.django_db
    def test_partials_loaded(self, org_inv_rd, rando):
        """EvaluationsPrefetch loads existing evaluation data by role PK."""
        org = Organization.objects.create(name='ep_test_org')
        org_inv_rd.give_permission(rando, org)

        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))
        assert len(roles) > 0
        ep = EvaluationsPrefetch.from_roles(roles)

        for role in roles:
            partials = ep.get_partials(role.pk)
            expected = {}
            for eval_id, codename, ct_id, obj_id in role.permission_partials.values_list('id', 'codename', 'content_type_id', 'object_id'):
                expected[(codename, ct_id, obj_id)] = eval_id
            assert partials == expected

    @pytest.mark.django_db
    def test_empty_partials_for_unknown_role(self):
        """get_partials returns empty dict for a role PK not in the batch."""
        ep = EvaluationsPrefetch()
        assert ep.get_partials(99999) == {}
        assert ep.get_partials_uuid(99999) == {}
        assert ep.get_team_roles(99999) == []

    @pytest.mark.django_db
    def test_no_per_role_queries_with_prefetch(self, org_inv_rd, rando):
        """Using EvaluationsPrefetch avoids per-role evaluation queries."""
        org = Organization.objects.create(name='no_query_org')
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)
        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))
        ep = EvaluationsPrefetch.from_roles(roles)

        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            for role in roles:
                role.needed_cache_updates(types_prefetch=types_prefetch, evaluations_prefetch=ep)

        partials_queries = [q for q in ctx.captured_queries if 'dab_rbac_roleevaluation' in q['sql'] and 'SELECT' in q['sql']]
        assert len(partials_queries) == 0, "With EvaluationsPrefetch, no per-role RoleEvaluation queries should occur"

    @pytest.mark.django_db
    def test_values_list_fallback_without_prefetch(self, org_inv_rd, rando):
        """Without EvaluationsPrefetch, needed_cache_updates falls back to per-role queries."""
        org = Organization.objects.create(name='fallback_org')
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)
        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))

        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            for role in roles:
                role.needed_cache_updates(types_prefetch=types_prefetch)

        partials_queries = [q for q in ctx.captured_queries if 'dab_rbac_roleevaluation' in q['sql'] and 'SELECT' in q['sql']]
        assert len(partials_queries) > 0, "Without prefetch, should fall back to per-role queries"

    @pytest.mark.django_db
    def test_prefetch_and_fallback_produce_same_result(self, org_inv_rd, rando):
        """EvaluationsPrefetch and fallback paths return identical results."""
        org = Organization.objects.create(name='consistency_org')
        for i in range(3):
            Inventory.objects.create(name=f'consistency_inv_{i}', organization=org)
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_database(RoleDefinition)

        role = ObjectRole.objects.filter(object_id=str(org.pk)).first()
        to_delete_fallback, to_add_fallback = role.needed_cache_updates(types_prefetch=types_prefetch)

        ep = EvaluationsPrefetch.from_roles([role])
        to_delete_ep, to_add_ep = role.needed_cache_updates(types_prefetch=types_prefetch, evaluations_prefetch=ep)

        assert to_delete_fallback == to_delete_ep
        assert set((e.codename, e.content_type_id, e.object_id) for e in to_add_fallback) == set(
            (e.codename, e.content_type_id, e.object_id) for e in to_add_ep
        )


class TestComputeObjectRolePermissionsQueryReduction:
    @pytest.mark.django_db
    def test_full_recompute_uses_fewer_queries_than_iterator(self, org_inv_rd, rando):
        """The batched EvaluationsPrefetch default path should use fewer queries
        than the old .iterator() approach for a non-trivial number of ObjectRoles."""
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
        assert len(new_ctx) < len(old_ctx), f"Batched prefetch ({len(new_ctx)} queries) should use fewer queries " f"than iterator ({len(old_ctx)} queries)"
