package agenticos.model_access

default allow := false

# Default policy: any workspace member may use any model marked enabled.
# More restrictive policies (e.g., gating large models) can be added by ops.
allow if {
    input.model.enabled == true
    count(input.principal.workspace_ids) > 0
}
