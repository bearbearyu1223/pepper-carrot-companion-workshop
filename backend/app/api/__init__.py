"""HTTP API surface.

Route handlers depend on the Protocol-typed clients from `app.clients` so the
storage / model providers can be swapped via config without touching this
package. See docs/decisions/0002-model-provider-abstraction.md.
"""
