package agenticos.tool_access

# Default deny.
default allow := false

# Allow if the principal has the workspace role and the tool is in the
# allow-list for the agent. Inputs:
#   input.principal.roles: list of role names in this workspace
#   input.tool: { id, name, scopes }
#   input.agent.allowed_tools: list of tool IDs
allow if {
    some role in input.principal.roles
    role in {"owner", "admin", "builder"}
    input.tool.id in input.agent.allowed_tools
}

# Members may invoke tools that are tagged "safe" without per-agent binding.
allow if {
    "member" in input.principal.roles
    "safe" in input.tool.scopes
}
