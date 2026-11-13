"""Execution Workspace package (Phase 4).

Internal-only modules: path policy, safe directory-handle operations, the
Workdir provider contract and the durable Workspace manager. Nothing here is
exported through ``contracts/``; Workdir state lives in ``execution_workdirs``
and no client-supplied path ever enters these APIs (02 FR-5/FR-6, 03 §4.5).
"""
