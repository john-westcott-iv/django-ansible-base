# Bulk RBAC Operations

When creating or deleting many resources, or assigning permissions in bulk, the
per-call RBAC signal handlers can become a performance bottleneck. DAB provides
two separate APIs to batch this work. They handle different concerns and must
not be mixed.

## `defer_rbac_computations` — resource create/delete

Use this context manager when creating or deleting many RBAC-registered objects
(e.g. bulk inventory creation, organization cascade delete). It defers the RBAC
signal handlers that normally fire on every `save()` and `delete()`, then
flushes all recomputation in a single pass when the context manager exits.

**This is only for non-RBAC resource operations.** It does not handle permission
assignments — use `bulk_give_permissions` / `bulk_remove_permissions` for that.

```python
from ansible_base.rbac.triggers import defer_rbac_computations

with defer_rbac_computations():
    for i in range(100):
        Inventory.objects.create(name=f'inv-{i}', organization=org)
# One recomputation pass here instead of 100
```

### What errors while active

Once resources have been created or deleted inside the context manager (i.e.
deferred data is pending), the following calls will raise `RuntimeError`:

- **`give_permission` / `remove_permission`** — these run incremental
  recomputation that would produce incorrect results against stale state.
- **`has_obj_perm`** — evaluations are stale until the flush completes, so
  permission checks would return wrong answers.

These calls are allowed *before* any mutations occur inside the context manager.
This means a view can enter `defer_rbac_computations()`, pass its DRF permission
checks normally, and then perform bulk resource operations.

### Constraints

- Cannot be nested.
- Only defers signals for resource create/delete — not for permission
  assignment. Use `RoleDefinition.bulk_give_permissions` /
  `bulk_remove_permissions` outside this context manager for that.

### What it defers

- **Created resources:** defers `rbac_post_save_update_evaluations`, flushes
  parent ObjectRole lookups and `compute_object_role_permissions` once at exit.
- **Deleted resources:** defers `rbac_post_delete_remove_object_roles` and
  `team_pre_delete`, flushes bulk ObjectRole/RoleEvaluation cleanup at exit.
- **Team IDs:** collects all affected team IDs and calls
  `compute_team_member_roles` once.

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

- Must NOT be called inside `defer_rbac_computations`. Call it before or after.
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

## Combining both

The two APIs handle different phases and must be called separately. A typical
bulk-populate pattern:

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
    # This MUST be outside defer_rbac_computations
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
