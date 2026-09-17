import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Deactivate the stale Odoo Studio "full" report customization on
    sale.report_saleorder_document before this module reloads its own view.

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

    Root cause (confirmed via direct SQL on zaccaria-main-7295035
    production, 2026-09-17): the Studio view's frozen HTML snapshot has
    <tbody class="sale_tbody"> but NOT td[@name='td_product_quantity'] or
    tr[name='tr_product'] - it predates those name attributes being added
    to the base sale.report_saleorder_document template. Being a "full"
    override (xpath on the whole <t t-name=...>, priority 9999999 i.e.
    applied last/authoritative), its frozen content becomes what any other
    inheriting view - including this module's own update - gets validated
    against, and the xpath can no longer be located there.

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
            "sale.report_saleorder_document (ir.ui.view id(s): %s) before "
            "the 17.0 -> 19.0 migration - see the migrate() docstring in "
            "this file for why. Re-apply the customization via Studio "
            "once stably on 19.0, if still needed.",
            [r[0] for r in deactivated],
        )
