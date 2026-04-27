"""SQLAlchemy models describing premium catalog and entitlements."""

from __future__ import annotations

from datetime import UTC, datetime

from spooky.premium.enums import PremiumProduct
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base

__all__ = ["PremiumEntitlement", "PremiumSKU", "PremiumSavedMedia"]


class PremiumSKU(Base):
    """Map a Discord SKU to a catalog product entry."""

    __tablename__ = "premium_skus"

    sku_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    product: Mapped[PremiumProduct] = mapped_column(SAEnum(PremiumProduct, name="premium_product"))
    name: Mapped[str] = mapped_column(String(128))
    sku_type: Mapped[str] = mapped_column(String(32))
    application_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class PremiumEntitlement(Base):
    """Persist premium entitlement grants for offline reconciliation."""

    __tablename__ = "premium_entitlements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    sku_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("premium_skus.sku_id", ondelete="CASCADE"), nullable=False
    )
    product: Mapped[PremiumProduct] = mapped_column(SAEnum(PremiumProduct, name="premium_product"))
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class PremiumSavedMedia(Base):
    """Persist premium video assets saved by end users."""

    __tablename__ = "premium_saved_media"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "platform",
            "code",
            name="uq_premium_saved_media_user_platform_code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
