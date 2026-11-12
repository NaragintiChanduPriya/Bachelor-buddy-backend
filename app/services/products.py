"""Products: search, detail with verdict and best offer, price history, price alerts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.calc.offers import Application, best_offer_for
from app.calc.products import (
    PlatformToday,
    available,
    build_verdict,
    daily_lowest,
    discount_percent,
    history_summary,
    price_stats,
)
from app.core.clock import local_datetime
from app.core.constants import HISTORY_DAYS_API, PRODUCT_CATEGORY_LABELS, SHOPPING_PLATFORMS
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.ids import format_id
from app.core.money import format_inr
from app.db.models import PriceAlert, PriceHistory, Product
from app.schemas.product import (
    DeleteAlertResponse,
    PlatformPrice,
    PriceAlertOut,
    PriceHistoryOut,
    PricePoint,
    ProductDetail,
    ProductSummary,
)
from app.services import offers as offer_service
from app.services.context import Ctx

#: Delivery dates are quoted for 8 PM IST on the day the order would arrive.
DELIVERY_HOUR = 20


def to_summary(product: Product) -> ProductSummary:
    return ProductSummary(
        id=product.id,
        name=product.name,
        brand=product.brand,
        category=product.category,  # type: ignore[arg-type]
        category_label=PRODUCT_CATEGORY_LABELS[product.category],
        lowest_price=product.lowest_price,
        highest_price=product.highest_price,
        mrp=product.mrp,
        discount_percent=product.discount_percent,
        rating=product.rating,
        review_count=product.review_count,
        cheapest_platform=product.cheapest_platform,
        fastest_delivery_days=product.fastest_delivery_days,
        thumbnail_seed=product.thumbnail_seed,
        sponsored=product.sponsored_platform is not None,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_query(
    q: str | None, category: str | None, max_price: int | None, sort: str
) -> Select[Product]:
    query = select(Product)
    for token in (q or "").lower().split():
        pattern = f"%{_escape_like(token)}%"
        condition = or_(
            Product.name.ilike(pattern, escape="\\"), Product.brand.ilike(pattern, escape="\\")
        )
        categories = [c for c, label in PRODUCT_CATEGORY_LABELS.items() if token in label.lower()]
        if categories:
            condition = or_(condition, Product.category.in_(categories))
        query = query.where(condition)
    if category:
        query = query.where(Product.category == category)
    if max_price is not None:
        query = query.where(Product.lowest_price <= max_price)
    # Honest sorts only; sponsored products keep whatever position these give them.
    if sort == "rating":
        return query.order_by(Product.rating.desc(), Product.lowest_price, Product.id)
    if sort == "discount":
        return query.order_by(Product.discount_percent.desc(), Product.lowest_price, Product.id)
    return query.order_by(Product.lowest_price, Product.rating.desc(), Product.id)


async def search(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    max_price: int | None = None,
    sort: str = "price",
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[list[ProductSummary], int]:
    """Summaries and the total match count. Unpaginated when page is None (for the agents)."""
    query = _search_query(q, category, max_price, sort)
    if page is None or page_size is None:
        rows = (await session.scalars(query)).all()
        return [to_summary(p) for p in rows], len(rows)
    total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = (await session.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
    return [to_summary(p) for p in rows], int(total or 0)


async def _product_with_prices(ctx: Ctx, product_id: str) -> Product:
    product = (
        (
            await ctx.session.execute(
                select(Product).options(joinedload(Product.prices)).where(Product.id == product_id)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if product is None:
        raise NotFoundError.resource("Product")
    return product


async def _series(ctx: Ctx, product: Product, days: int) -> tuple[list[date], dict[str, list[int]]]:
    """Days (oldest first, ending today) and each platform's price on them. Only days every
    platform has a price for are kept, so the series always line up."""
    today = ctx.clock.today()
    start = today - timedelta(days=days - 1)
    rows = await ctx.session.execute(
        select(PriceHistory.platform, PriceHistory.day, PriceHistory.price)
        .where(
            PriceHistory.product_id == product.id,
            PriceHistory.day >= start,
            PriceHistory.day <= today,
        )
        .order_by(PriceHistory.day)
    )
    by_platform: dict[str, dict[date, int]] = defaultdict(dict)
    for platform, day, price in rows:
        by_platform[platform][day] = price
    platforms = [p.platform for p in product.prices]
    common = sorted(
        set.intersection(*(set(by_platform[p]) for p in platforms)) if platforms else set()
    )
    return common, {p: [by_platform[p][d] for d in common] for p in platforms}


def _today_rows(product: Product) -> list[PlatformToday]:
    return [PlatformToday(p.platform, p.price, p.in_stock, p.delivery_days) for p in product.prices]


async def detail(ctx: Ctx, product_id: str) -> ProductDetail:
    product = await _product_with_prices(ctx, product_id)
    summary = to_summary(product)
    selling = {p.platform for p in available(_today_rows(product))}
    today = ctx.clock.today()

    platforms = sorted(
        (
            PlatformPrice(
                platform=p.platform,
                price=p.price,
                mrp=product.mrp,
                discount_percent=discount_percent(p.price, product.mrp),
                in_stock=p.in_stock,
                delivery_days=p.delivery_days,
                delivery_by=local_datetime(
                    today + timedelta(days=p.delivery_days), DELIVERY_HOUR, 0, ctx.clock.zone
                ),
                sponsored=p.sponsored,
                is_cheapest=p.in_stock and p.platform == summary.cheapest_platform,
            )
            for p in product.prices
        ),
        key=lambda row: (not row.in_stock, row.price, row.platform),
    )

    _, series_by_platform = await _series(ctx, product, HISTORY_DAYS_API)
    series = daily_lowest([s for p, s in series_by_platform.items() if p in selling])
    stats = price_stats(series)
    verdict = build_verdict(series)

    # The platform where the best usable offer leaves the lowest final price; on a tie, the
    # lower price before the offer wins.
    usable = {
        row.id: (offer_service.terms_of(row), out)
        for row, out in await offer_service.live_offer_pairs(ctx)
        if out.eligible
    }
    terms = [t for t, _ in usable.values()]
    best: tuple[int, int, str, Application | None] | None = None
    for row in sorted(product.prices, key=lambda r: r.platform):
        if row.platform not in selling:
            continue
        application = best_offer_for(row.price, row.platform, terms)
        final = application.final_price if application else row.price
        if best is None or final < best[0] or (final == best[0] and row.price < best[1]):
            best = (final, row.price, row.platform, application)
    assert best is not None  # noqa: S101 - every product is listed on at least one platform
    final_price, best_base, best_platform, best_application = best
    best_offer = usable[best_application.offer_id][1] if best_application else None
    alert = await ctx.session.scalar(
        select(PriceAlert).where(
            PriceAlert.user_id == ctx.user.id, PriceAlert.product_id == product.id
        )
    )
    return ProductDetail(
        **summary.model_dump(),
        description=product.description,
        highlights=list(product.highlights),
        platforms=platforms,
        verdict=verdict.verdict,  # type: ignore[arg-type]
        verdict_reason=verdict.reason,
        lowest_90_day=stats.lowest,
        highest_90_day=stats.highest,
        average_90_day=stats.average,
        above_lowest_90_day=stats.current - stats.lowest,
        best_offer=best_offer,
        best_deal_platform=best_platform,
        best_deal_base_price=best_base,
        final_price=final_price,
        offer_saving=best_application.discount if best_application else 0,
        total_saving_vs_mrp=max(0, product.mrp - final_price),
        has_alert=alert is not None,
        alert_target_price=alert.target_price if alert else None,
    )


async def price_history(ctx: Ctx, product_id: str, days: int) -> PriceHistoryOut:
    product = await _product_with_prices(ctx, product_id)
    selling = {p.platform for p in available(_today_rows(product))}
    dates, series_by_platform = await _series(ctx, product, days)
    # Fixed platform order, so each platform keeps its chart colour in the UI.
    platforms = [p for p in SHOPPING_PLATFORMS if p in series_by_platform]
    points = [
        PricePoint(
            date=day.isoformat(),
            prices={p: series_by_platform[p][i] for p in platforms},
        )
        for i, day in enumerate(dates)
    ]
    stats = price_stats(daily_lowest([series_by_platform[p] for p in platforms if p in selling]))
    return PriceHistoryOut(
        product_id=product.id,
        days=days,
        platforms=platforms,
        points=points,
        lowest=stats.lowest,
        highest=stats.highest,
        average=stats.average,
        current_lowest=stats.current,
        summary=history_summary(days, stats, product.cheapest_platform),
    )


def _alert_out(alert: PriceAlert, product: Product) -> PriceAlertOut:
    current = product.lowest_price
    return PriceAlertOut(
        id=format_id("alert", alert.id),
        product_id=product.id,
        product_name=f"{product.brand} {product.name}",
        target_price=alert.target_price,
        current_price=current,
        gap_to_target=max(0, current - alert.target_price),
        triggered=current <= alert.target_price,
        created_at=alert.created_at,
    )


async def alerts(ctx: Ctx) -> list[PriceAlertOut]:
    rows = await ctx.session.execute(
        select(PriceAlert, Product)
        .join(Product, Product.id == PriceAlert.product_id)
        .where(PriceAlert.user_id == ctx.user.id)
        .order_by(PriceAlert.created_at.desc(), PriceAlert.id.desc())
    )
    return [_alert_out(alert, product) for alert, product in rows]


async def set_alert(ctx: Ctx, product_id: str, target: int) -> PriceAlertOut:
    """One alert per product: setting it again moves the target."""
    product = await ctx.session.get(Product, product_id)
    if product is None:
        raise NotFoundError.resource("Product")
    current = product.lowest_price
    if target >= current:
        raise ValidationFailedError(
            f"Set a target below today's lowest price of {format_inr(current)} — at that price "
            "you could buy it now.",
            {"currentPrice": current},
        )
    values = insert(PriceAlert).values(
        user_id=ctx.user.id,
        product_id=product_id,
        target_price=target,
        created_at=ctx.clock.now(),
    )
    statement = values.on_conflict_do_update(
        constraint="uq_price_alerts_user_product",
        set_={
            "target_price_paise": values.excluded.target_price_paise,
            "last_notified_price_paise": None,
        },
    ).returning(PriceAlert.id)
    alert_id = (await ctx.session.execute(statement)).scalar_one()
    await ctx.session.commit()
    alert = await ctx.session.get(PriceAlert, alert_id, populate_existing=True)
    assert alert is not None  # noqa: S101 - just written
    return _alert_out(alert, product)


async def delete_alert(ctx: Ctx, product_id: str) -> DeleteAlertResponse:
    if await ctx.session.get(Product, product_id) is None:
        raise NotFoundError.resource("Product")
    alert = await ctx.session.scalar(
        select(PriceAlert).where(
            PriceAlert.user_id == ctx.user.id, PriceAlert.product_id == product_id
        )
    )
    if alert is None:
        raise NotFoundError.resource("Price alert")
    await ctx.session.delete(alert)
    await ctx.session.commit()
    return DeleteAlertResponse(product_id=product_id)
