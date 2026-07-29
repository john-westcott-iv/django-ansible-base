from collections import defaultdict

from .models.content_type import DABContentType


class TypesPrefetch:
    "Custom class to manage prefetching the models we know to be acceptable in memory"

    def __init__(self):
        self._content_types = {}
        self._role_definitions = {}
        self._permissions = {}
        self._rd_permissions = {}

    @classmethod
    def from_database(cls, RoleDefinition):
        inst = cls()
        for rd in RoleDefinition.objects.prefetch_related('permissions__content_type'):
            inst._role_definitions[rd.id] = rd
            perm_list = []
            for perm in rd.permissions.all():
                if perm.id not in inst._permissions:
                    inst._permissions[perm.id] = perm
                perm_list.append(perm.id)
                if perm.content_type_id not in inst._content_types:
                    inst._content_types[perm.content_type_id] = perm.content_type
            inst._rd_permissions[rd.id] = perm_list
        return inst

    def get_content_type(self, ct_id):
        if ct_id not in self._content_types:
            self._content_types[ct_id] = DABContentType.objects.get_for_id(ct_id)
        return self._content_types[ct_id]

    def permissions_for_object_role(self, role):
        if role.role_definition_id not in self._rd_permissions:
            perm_id_list = []
            for perm in role.role_definition.permissions.all():
                self._permissions[perm.id] = perm
                perm_id_list.append(perm.id)
            self._rd_permissions[role.role_definition_id] = perm_id_list
        for permission_id in self._rd_permissions[role.role_definition_id]:
            yield self._permissions[permission_id]


class EvaluationsPrefetch:
    """Batch-loads RoleEvaluation data for a chunk of ObjectRoles using values_list.

    This avoids both N+1 queries (one per role) and full model materialization
    (which prefetch_related would do). Only the columns needed by
    needed_cache_updates are fetched, grouped by role PK.

    Also batch-loads the provides_teams -> has_roles chain so that
    team role traversal doesn't trigger per-role queries.
    """

    def __init__(self):
        self._partials: dict[int, dict[tuple, int]] = {}
        self._partials_uuid: dict[int, dict[tuple, int]] = {}
        self._team_roles: dict[int, list] = {}

    @classmethod
    def from_roles(cls, roles, role_evaluation_cls, role_evaluation_uuid_cls, role_team_assignment_cls) -> 'EvaluationsPrefetch':
        inst = cls()
        role_pks = [r.pk for r in roles]

        inst._load_evaluations(role_pks, role_evaluation_cls, role_evaluation_uuid_cls)

        object_role_cls = type(roles[0]) if roles else None
        inst._load_team_roles(role_pks, object_role_cls, role_team_assignment_cls)

        return inst

    def _load_evaluations(self, role_pks, role_evaluation_cls, role_evaluation_uuid_cls):
        """Batch-load existing evaluation values, keyed by role PK."""
        for model, target in ((role_evaluation_cls, self._partials), (role_evaluation_uuid_cls, self._partials_uuid)):
            by_role: dict[int, dict[tuple, int]] = defaultdict(dict)
            for role_id, eval_id, codename, ct_id, obj_id in model.objects.filter(role_id__in=role_pks).values_list(
                'role_id', 'id', 'codename', 'content_type_id', 'object_id'
            ):
                by_role[role_id][(codename, ct_id, obj_id)] = eval_id
            for pk in role_pks:
                target[pk] = by_role.get(pk, {})

    def _load_team_roles(self, role_pks, object_role_cls, role_team_assignment_cls):
        """Batch-load provides_teams -> has_roles chain for team role traversal."""
        # Step 1: which roles provide which teams
        role_to_teams: dict[int, list[int]] = defaultdict(list)
        if object_role_cls is not None:
            for role_id, team_id in object_role_cls.provides_teams.through.objects.filter(objectrole_id__in=role_pks).values_list('objectrole_id', 'team_id'):
                role_to_teams[role_id].append(team_id)

        # Step 2: which teams have which roles (via has_roles = RoleTeamAssignment)
        all_team_ids = set()
        for team_ids in role_to_teams.values():
            all_team_ids.update(team_ids)

        team_role_pks: set[int] = set()
        team_to_role_pks: dict[int, list[int]] = defaultdict(list)
        if all_team_ids:
            for team_id, obj_role_id in role_team_assignment_cls.objects.filter(team_id__in=all_team_ids).values_list('team_id', 'object_role_id'):
                team_to_role_pks[team_id].append(obj_role_id)
                team_role_pks.add(obj_role_id)

        # Step 3: load the actual ObjectRole instances for team roles
        team_roles_by_pk = {}
        if team_role_pks and object_role_cls is not None:
            team_roles_by_pk = {r.pk: r for r in object_role_cls.objects.filter(pk__in=team_role_pks)}

        # Step 4: assemble per-role list of team ObjectRole instances
        for pk in role_pks:
            team_roles = []
            for team_id in role_to_teams.get(pk, []):
                for role_pk in team_to_role_pks.get(team_id, []):
                    if role_pk in team_roles_by_pk:
                        team_roles.append(team_roles_by_pk[role_pk])
            self._team_roles[pk] = team_roles

    def get_partials(self, role_pk: int) -> dict[tuple, int]:
        """Returns {(codename, ct_id, obj_id): eval_id} from RoleEvaluation."""
        return self._partials.get(role_pk, {})

    def get_partials_uuid(self, role_pk: int) -> dict[tuple, int]:
        """Returns {(codename, ct_id, obj_id): eval_id} from RoleEvaluationUUID."""
        return self._partials_uuid.get(role_pk, {})

    def get_team_roles(self, role_pk: int) -> list:
        """Returns ObjectRole instances reachable via provides_teams -> has_roles."""
        return self._team_roles.get(role_pk, [])
