import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Restore sale.report_saleorder_document to Odoo's real 19.0 file
    content before this module reloads its own inheriting view.

    ZACCARIA - local patch on top of the OCA sale-workflow submodule, added
    for the 17.0 -> 19.0 migration. See UPGRADE_19_BRAND_ID_REMOVAL.md's
    sibling notes in the zaccaria repo root for the wider migration context
    (this file is a separate, unrelated fix within the same effort).

    Why this lives HERE and not in one of Zaccaria's own custom modules'
    migrations: it must run before Odoo (re)validates THIS module's own
    inheriting view against sale.report_saleorder_document, which is
    exactly where the odoo.sh 17 -> 19 migration failed:

        odoo.tools.convert.ParseError: ... report_saleorder_document
        L'elemento '<xpath expr="//table/tbody[hasclass('sale_tbody')]
        //td[@name='td_product_quantity']">' non puo' essere localizzato
        nella vista genitore

    A pre-migrate script in a different (Zaccaria-owned) module cannot
    guarantee it runs before sale_order_line_date's own reload - nothing
    forces that ordering between sibling modules with no dependency
    relationship. A pre-migrate script inside THIS module's own
    migrations/ folder always runs before this module's own data/views are
    reloaded, by definition of the hook - no ordering assumption needed.

    ACTUAL root cause (confirmed via direct SQL on zaccaria-staging-38206729,
    2026-09-17, after a first attempt at this fix - see revision history of
    this file for what was tried and ruled out first):

    The BASE view itself (sale.report_saleorder_document, "1146" on both
    production and staging) has `arch_updated = True`. Its stored `arch_db`
    length (10915 chars) exactly matches the Odoo Studio backup view
    `web_studio_backup__report_saleorder_document` - i.e. Odoo Studio's
    "full report editor" mode overwrote the BASE view's own arch_db
    in-place (not just an inheriting override) back when this customization
    was first made, and flagged it `arch_updated=True`. Per
    `ir_ui_view._compute_arch`, a view with `arch_updated=True` NEVER reads
    its architecture from the module's XML file again - it is permanently
    pinned to whatever is in `arch_db`, regardless of any future 'sale'
    module upgrade (this is Odoo's intentional protection against a module
    update silently wiping out a Studio customization). Since 'sale' itself
    isn't part of THIS custom/OCA-modules update batch (it went through the
    separate official base 17->19 migration earlier), nothing else in this
    run would otherwise ever touch it - it stays frozen at its old,
    pre-td_product_quantity/tr_product structure forever.

    First attempt, INSUFFICIENT (kept below, still useful): deactivating
    the Studio "full override" INHERITING view
    (web_studio.report_editor_customization_full.view._sale.report_saleorder_document,
    priority 9999999) - this did NOT fix the crash. Turns out
    `ir_ui_view._filter_loaded_views()` already excludes any view
    attributed to the pseudo-module 'studio_customization' from view
    combination during an upgrade regardless of active state (see its
    docstring: "Custom views defined directly in the database are loaded
    only after the module initialization phase is completely finished").
    So that override was never actually the thing breaking validation -
    the corrupted BASE view was. Kept here anyway (harmless) so that once
    stably on 19.0, the full override doesn't silently keep overriding the
    now-correct base view with its own stale content.

    Not matched by xmlid: Studio generates a random UUID suffix per
    customization (e.g. web_studio_report_ed_<uuid>), not stable across
    databases (confirmed different between databases). Matched instead by
    the view's own deterministic `name` (Studio encodes the target
    template in it) plus its real inherit_id relationship to
    sale.report_saleorder_document, both stable across environments.
    """
    cr.execute("""
        SELECT base.id
        FROM ir_ui_view base
        JOIN ir_model_data imd
          ON imd.model = 'ir.ui.view' AND imd.res_id = base.id
        WHERE imd.module = 'sale' AND imd.name = 'report_saleorder_document'
    """)
    row = cr.fetchone()
    if not row:
        # base view xmlid not found (shouldn't happen on a real sale
        # install) - nothing to anchor the match to, skip rather than guess
        return
    base_view_id = row[0]

    # 1) The real fix: restore the base view to Odoo's actual 19.0 file
    # content if Studio has pinned it to a stale arch_db override.
    env = api.Environment(cr, SUPERUSER_ID, {})
    base_view = env['ir.ui.view'].browse(base_view_id)
    if base_view.arch_updated and base_view.arch_fs:
        _logger.warning(
            "sale.report_saleorder_document (ir.ui.view id %s) has "
            "arch_updated=True (Odoo Studio overwrote it directly) - "
            "resetting to the real 19.0 file content (%s) before the "
            "17.0 -> 19.0 migration. See the migrate() docstring in this "
            "file for why. The Studio 'full' override (if still active) "
            "will keep replacing this with its own stale content at "
            "runtime until it is reset/redone via Studio on 19.0.",
            base_view_id, base_view.arch_fs,
        )
        base_view.reset_arch('hard')

    # 2) Kept from the first attempt: deactivate the Studio "full override"
    # inheriting view too, so it stops silently shadowing the now-correct
    # base view once the site is back to normal (non-upgrade) operation.
    cr.execute("""
        UPDATE ir_ui_view
        SET active = false
        WHERE active = true
          AND inherit_id = %s
          AND name = 'web_studio.report_editor_customization_full.view._sale.report_saleorder_document'
        RETURNING id
    """, (base_view_id,))
    deactivated = cr.fetchall()
    if deactivated:
        _logger.warning(
            "Deactivated stale Odoo Studio 'full' report customization on "
            "sale.report_saleorder_document (ir.ui.view id(s): %s). "
            "Re-apply the customization via Studio once stably on 19.0, "
            "if still needed.",
            [r[0] for r in deactivated],
        )
