# Bulk RBAC Permission Assignment

When assigning or removing permissions across many role definitions, users,
teams, and objects, looping over individual `give_permission` /
`remove_permission` calls is a performance bottleneck. DAB provides bulk
classmethods that batch the work into a single recomputation pass.

## `RoleDefinition.bulk_give_permissions` — permission assignment

Use this classmethod when assigning permissions across multiple role definitions,
users, teams, and objects. It replaces looping over `give_permission` calls.

```python
from ansible_base.rbac.models import RoleDefinition

RoleDefinition.bulk_give_permissions(
    user_permissions=[
        (member_rd, user1, team_a),
        (member_rd, user2, team_a),
        (org_admin_rd, user1, org),
        (inv_admin_rd, user3, inv1),
    ],
    team_permissions=[
        (inv_admin_rd, team_a, inv1),
        (inv_admin_rd, team_a, inv2),
    ],
)
```

Each entry is a `(role_definition, actor, content_object)` triple. User and team
permissions are separated because team assignments trigger additional
recomputation (ancestor roles, `provides_teams`, descendent roles).

### What it does

1. Validates once per unique `(role_definition, content_type)` pair
2. Bulk-creates ObjectRoles with `ignore_conflicts`
3. Bulk-creates `RoleUserAssignment` / `RoleTeamAssignment` with `ignore_conflicts`
4. Runs a single `compute_team_member_roles` + `compute_object_role_permissions` pass

### Constraints

- Idempotent — calling with the same triples twice will not duplicate assignments.

## `RoleDefinition.bulk_remove_permissions` — permission removal

Same API shape as `bulk_give_permissions`, but for removal:

```python
RoleDefinition.bulk_remove_permissions(
    user_permissions=[
        (member_rd, user1, team_a),
        (inv_admin_rd, user3, inv1),
    ],
)
```

Bulk-deletes assignments, cleans up orphaned ObjectRoles, and runs a single
recomputation pass. Same constraints as `bulk_give_permissions`.

## Migration from `defer_rbac_cache`

`defer_rbac_cache` has been removed. For bulk permission assignments, use the
new classmethods instead:

| Old pattern | New pattern |
|---|---|
| `with defer_rbac_cache():` around `give_permission` calls | `RoleDefinition.bulk_give_permissions(...)` |
