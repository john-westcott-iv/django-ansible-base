# Bulk RBAC Operations

When creating or deleting many resources, or assigning permissions in bulk, the
per-call RBAC signal handlers can become a performance bottleneck. DAB provides
two APIs to batch this work.

## `defer_rbac_computations` -- resource operations

Use this context manager when creating or deleting many RBAC-registered objects
(e.g. bulk inventory creation, organization cascade delete). It defers all
signal-driven RBAC recomputation until the context manager exits, then runs a
single flush pass.

```python
from ansible_base.rbac.triggers import defer_rbac_computations

with defer_rbac_computations():
    for i in range(100):
        Inventory.objects.create(name=f'inv-{i}', organization=org)
# One recomputation pass here instead of 100
```

**Constraint:** `give_permission` and `remove_permission` raise `RuntimeError`
inside `defer_rbac_computations`. Use `bulk_give_permissions` before or after the
context manager, not interleaved with resource operations.

The context manager handles:
- **Created resources:** defers `rbac_post_save_update_evaluations`, flushes
  parent ObjectRole lookups and `compute_object_role_permissions` once at exit.
- **Deleted resources:** defers `rbac_post_delete_remove_object_roles` and
  `team_pre_delete`, flushes bulk ObjectRole/RoleEvaluation cleanup at exit.
- **Team IDs:** collects all affected team IDs and calls
  `compute_team_member_roles` once.

Cannot be nested.

## `RoleDefinition.bulk_give_permissions` -- assignment operations

Use this classmethod when assigning permissions across multiple role definitions,
users, teams, and objects. It replaces wrapping N `give_permission` calls in a
loop.

```python
from ansible_base.rbac.models import RoleDefinition

# Assign multiple roles in one batch
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

**What it does:**
1. Validates once per unique `(role_definition, content_type)` pair
2. Bulk-creates ObjectRoles with `ignore_conflicts`
3. Bulk-creates `RoleUserAssignment` / `RoleTeamAssignment` with `ignore_conflicts`
4. Runs a single `compute_team_member_roles` + `compute_object_role_permissions` pass

## `RoleDefinition.bulk_remove_permissions`

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
recomputation pass.

## Combining both

A typical bulk-populate pattern:

```python
from ansible_base.activitystream import deferred_activity_stream
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.triggers import defer_rbac_computations

with deferred_activity_stream():
    # Phase 1: create resources (RBAC signals deferred)
    with defer_rbac_computations():
        teams = [Team.objects.create(name=f't-{i}', organization=org) for i in range(20)]
        inventories = [Inventory.objects.create(name=f'inv-{i}', organization=org) for i in range(10)]

    # Phase 2: assign permissions (one recomputation pass)
    user_perms = [(member_rd, user, team) for team in teams for user in team_users]
    team_perms = [(inv_admin_rd, teams[0], inv) for inv in inventories]
    RoleDefinition.bulk_give_permissions(user_permissions=user_perms, team_permissions=team_perms)
```

## Migration from `defer_rbac_cache`

`defer_rbac_cache` has been removed. It was designed for the assignment path but
read stale `provides_teams` state when deferring, producing incorrect results.

| Old pattern | New pattern |
|---|---|
| `with defer_rbac_cache():` around `give_permission` calls | `RoleDefinition.bulk_give_permissions(...)` |
| `with defer_rbac_cache():` around `obj.delete()` | `with defer_rbac_computations():` |
| `with defer_rbac_cache():` around resource creation | `with defer_rbac_computations():` |
