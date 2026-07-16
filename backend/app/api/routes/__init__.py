"""SmartForge REST route modules; each module owns one resource or surface.

Every route declares its own auth dependency (internal, superuser, or owner)
so no endpoint is exposed without an explicit access rule.
"""
