"""SQLAlchemy モデル定義。"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AutoReactionConfig(Base):
    """指定チャンネルへの新規メッセージに自動でリアクションを付与する設定。

    同一 (guild_id, channel_id) に対して複数レコードを持てる。
    例えば "おはよう" には ☀️、"おやすみ" には 🌙 のように
    pattern を変えて複数の自動リアクションを 1 チャンネルに併設できる。
    emojis は JSON 配列文字列で複数の絵文字を保持する。
    Unicode 絵文字とカスタム絵文字 (例: ``<:name:123>`` / ``<a:name:123>``) の
    両方をそのまま要素として扱える。
    """

    __tablename__ = "auto_reaction_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False)
    emojis: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 正規表現フィルタ。NULL or 空文字なら全メッセージにマッチ (= フィルタなし)。
    # Python の re.search を使うので部分マッチ。フラグはインライン記法で
    # 指定可能 (例: ``(?i)hello`` で大文字小文字無視)。
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<AutoReactionConfig(id={self.id}, guild_id={self.guild_id}, "
            f"channel_id={self.channel_id}, enabled={self.enabled})>"
        )


class MessageMilestoneConfig(Base):
    """指定チャンネルで投稿習慣を達成したユーザーへ通知する設定。"""

    __tablename__ = "message_milestone_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    condition_type: Mapped[str] = mapped_column(
        String, default="daily_streak", nullable=False
    )
    daily_required_count: Mapped[int] = mapped_column(Integer, nullable=False)
    required_days: Mapped[int] = mapped_column(Integer, nullable=False)
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_type: Mapped[str] = mapped_column(String, default="plain", nullable=False)
    message_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    embed_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    embed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embed_color: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delete_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backfill_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    consecutive_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    consecutive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_reward_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<MessageMilestoneConfig(id={self.id}, guild_id={self.guild_id}, "
            f"channel_id={self.channel_id}, enabled={self.enabled})>"
        )


class MessageMilestoneProgress(Base):
    """MessageMilestoneConfig ごとのユーザー別達成状況。"""

    __tablename__ = "message_milestone_progress"
    __table_args__ = (
        UniqueConstraint(
            "config_id", "user_id", name="uq_message_milestone_config_user"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("message_milestone_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    last_counted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reward_pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reward_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<MessageMilestoneProgress(config_id={self.config_id}, "
            f"user_id={self.user_id}, streak_days={self.streak_days})>"
        )


class MessageMilestoneProcessedMessage(Base):
    """MessageMilestoneConfig ごとに処理済みメッセージIDを記録する。"""

    __tablename__ = "message_milestone_processed_messages"
    __table_args__ = (
        UniqueConstraint(
            "config_id", "message_id", name="uq_message_milestone_config_message"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("message_milestone_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<MessageMilestoneProcessedMessage(config_id={self.config_id}, "
            f"message_id={self.message_id})>"
        )


class DiscordGuild(Base):
    """Discord ギルド情報のキャッシュテーブル。

    Bot が参加しているサーバーの情報を保存し、
    Web 管理画面でギルド名を表示できるようにする。
    Bot 起動時、サーバー参加時、サーバー情報変更時に同期される。
    """

    __tablename__ = "discord_guilds"

    guild_id: Mapped[str] = mapped_column(String, primary_key=True)
    guild_name: Mapped[str] = mapped_column(String, nullable=False)
    icon_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<DiscordGuild(guild_id={self.guild_id}, name={self.guild_name})>"


class DiscordEmoji(Base):
    """Discord カスタム絵文字キャッシュ。

    Bot が見える guild の custom emoji を保存し、Web 管理画面の絵文字
    ピッカーで選択肢として提供する。Unicode 絵文字はキャッシュ不要。
    """

    __tablename__ = "discord_emojis"
    __table_args__ = (UniqueConstraint("guild_id", "emoji_id", name="uq_guild_emoji"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    emoji_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    animated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DiscordEmoji(guild_id={self.guild_id}, emoji_id={self.emoji_id}, "
            f"name={self.name}, animated={self.animated})>"
        )


class DiscordChannel(Base):
    """Discord チャンネル情報のキャッシュテーブル。

    Bot が参加しているサーバーのチャンネル情報を保存し、
    Web 管理画面でチャンネル名表示・選択肢を提供する。
    """

    __tablename__ = "discord_channels"
    __table_args__ = (
        UniqueConstraint("guild_id", "channel_id", name="uq_guild_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel_name: Mapped[str] = mapped_column(String, nullable=False)
    # 0=text, 2=voice, 4=category, 5=news, 15=forum
    channel_type: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DiscordChannel(guild_id={self.guild_id}, channel_id={self.channel_id}, "
            f"name={self.channel_name}, type={self.channel_type})>"
        )
