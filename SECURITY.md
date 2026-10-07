# Security boundaries

Hardline is experimental software running with the controller user's privileges. Use a dedicated environment and narrowly scoped agent charters. A separate Codex home separates local state; it does not guarantee separation of account connections, plugins, or desktop credentials.

Matrix coordination currently requires unencrypted rooms. Do not transmit credentials, MFA codes, financial documents, or other sensitive payloads through these rooms. Use separate account tokens and private per-agent room grants. The routing listener necessarily sees monitored rooms.

Keep `.runtime/`, `agents.json`, environment files, credential imports, service configuration, and historical operational evidence private. These are excluded from Git. Never store live credentials in example files, issues, screenshots, or logs. File permissions restrict local access but are not encryption at rest.

Workers receive a Codex workspace permission profile that denies the controller's runtime state, the default desktop Codex home, SSH directory, and Matrix MCP credential directory. Extra filesystem grants are trusted operator configuration. Verify actual enforcement and plugin behavior in your Codex version; the profile is not an independent OS container.

Messaging and approved manager lifecycle tools are preapproved only within explicit controller grants. All other actions retain platform approval behavior. The listener does not answer approval requests. Authorized Matrix identities can submit tasks; messages, web pages, emails, and attached documents do not independently expand task authority.

SSH provisioning can execute privileged code on the Matrix host. Protect the key, restrict who can invoke management tools, and keep admin APIs private. Supply account credentials manually if this level of infrastructure access is unsuitable.

For a suspected vulnerability, contact the repository owner privately through GitHub. Do not publish exploit details or credentials in a public issue before coordination.
