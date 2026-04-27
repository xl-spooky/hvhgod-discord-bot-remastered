from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Enum as SAEnum, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base
from .enums import AuthorizationAccess

__all__ = ["GuildBotAuthorizationAccess", "GuildBotConfigureAuthorization"]


class GuildBotAuthorizationAccess(Base):
    """Per-guild toggle controlling authorized member access scopes."""

    __tablename__ = "guild_bot_authorization_access"
    __table_args__ = (UniqueConstraint("guild_id", "access"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    access: Mapped[AuthorizationAccess] = mapped_column(
        SAEnum(AuthorizationAccess, name="authorization_access")
    )
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class GuildBotConfigureAuthorization(Base):
    """Track users permitted to configure protected bot settings per guild."""

    __tablename__ = "guild_bot_configure_authorization"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
