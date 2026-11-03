"""Handlers Python referenciados desde data/tweaks.json como 'tweaks.<modulo>:<funcion>'.

Contrato de un handler:
    def handler(ctx: core.context.HandlerContext) -> bool | DetectResult | None

- En apply/revert devuelve True si cambió algo y False si no había nada que hacer.
- Con ctx.dry_run=True NO modifica nada: solo describe con ctx.plan(...).
- Para lo que deba revertirse guarda el estado previo en ctx.state; al revertir lo lee de
  ctx.prior_state. Las escrituras de registro con ctx.set_registry(...) quedan registradas
  automáticamente y se revierten con la operación restore_snapshot.
- Los detectores devuelven DetectResult; las comprobaciones de requires.check devuelven bool.

Categorías puramente declarativas (bloatware, privacy, services, performance, security) no
necesitan módulo: todo su comportamiento está en el catálogo y en core/engine.py.
"""
