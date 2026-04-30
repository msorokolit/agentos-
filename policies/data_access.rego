package agenticos.data_access

default allow := false

# Members of the same workspace can read its documents/collections.
allow if {
    input.action == "read"
    input.resource.workspace_id in input.principal.workspace_ids
}

# Builders+ can write.
allow if {
    input.action in {"create", "update", "delete"}
    input.resource.workspace_id in input.principal.workspace_ids
    some role in input.principal.roles
    role in {"owner", "admin", "builder"}
}
