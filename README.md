# Itsuka Bot

Discord で任意のチャンネルへの新規投稿に、設定した N 個のリアクションを
自動で付ける Bot。設定はすべて Web 管理画面 (Next.js) から行う。
構成は `../discord-util-bot` を踏襲し、機能を AutoReaction だけに絞っている。

## アーキテクチャ

```
itsuka-bot/
├── src/                       # Python (Bot + FastAPI)
│   ├── main.py                # bot エントリー
│   ├── bot.py                 # discord.py の commands.Bot
│   ├── config.py / constants.py
│   ├── database/{engine,models}.py
│   ├── services/
│   │   ├── auto_reaction_service.py
│   │   └── discord_cache_service.py
│   ├── cogs/
│   │   ├── auto_reaction.py   # on_message ホットパス + キャッシュループ
│   │   └── discord_cache.py   # ギルド/チャンネル情報を DB に同期
│   └── web/                   # FastAPI (JSON API のみ)
│       ├── app.py             # thin facade
│       ├── jwt_auth.py / security.py / db_helpers.py
│       └── routes/
│           ├── api_auth.py
│           └── api_auto_reaction.py
└── frontend/                  # Next.js (App Router, Tailwind v4, shadcn/ui)
    └── src/
        ├── proxy.ts           # 認証ガード
        ├── lib/{api,client-api,constants,types,utils}.ts
        ├── components/        # shadcn/ui + 共有コンポーネント
        └── app/
            ├── layout.tsx
            ├── login/page.tsx
            └── dashboard/
                ├── layout.tsx
                └── auto-reaction/page.tsx
```

Bot プロセスと Web API プロセスは独立。両者は同じ DB を共有し、

- **Bot 側**は Discord イベントで `discord_guilds` / `discord_channels` を更新
  し、`auto_reaction_configs` を 1 分ごとに読み込んで on_message でリアクションを付与
- **Web API 側**は管理画面に CRUD を提供し、変更は次のキャッシュ更新で
  Bot に反映 (最大 60 秒)

## 必要な環境

- Python 3.11+ (3.12 推奨)
- Node.js 24+ (フロント開発時)
- Docker / Docker Compose (任意)

## セットアップ (Docker Compose)

```bash
cp .env.example .env
# DISCORD_TOKEN, ADMIN_PASSWORD, SESSION_SECRET_KEY を編集
docker compose up --build
```

- Postgres: `localhost:5432`
- API: `http://localhost:8000`
- Web (Next.js): `http://localhost:3000`

`http://localhost:3000/login` にアクセスして `ADMIN_USER` / `ADMIN_PASSWORD`
でログインする。

## セットアップ (ローカル開発)

ローカルでも Postgres を使う。docker-compose の `db` サービスだけ立てて
bot / api / frontend は venv / npm で動かす運用を推奨。

### 1. Postgres を起動

```bash
docker compose up -d db   # localhost:5432 に Postgres
```

### 2. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env  # DISCORD_TOKEN / ADMIN_PASSWORD を埋める

# Bot プロセス
python -m src.main

# Web API プロセス (別ターミナル)
uvicorn src.web.app:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

## デプロイ (Railway)

Railway 上では **3 サービス + Postgres アドオン** を立てる。bot と api を
別サービスにしているのは、片方が落ちてももう片方を維持しつつ自動再起動
させるため。3 サービスとも同一リポジトリから生やす。

### 1. Postgres アドオンを追加

プロジェクトに `Add Service → Database → PostgreSQL` を追加すると
`DATABASE_URL=postgresql://...` が自動で全サービスに注入される (asyncpg
形式への変換は `src/config.py` の `_normalize_database_url` で行う)。

### 2. サービスを 3 つ作る

| サービス | Root Directory | Custom Start Command | 公開ポート |
| --- | --- | --- | --- |
| `itsuka-bot` (Worker) | 空欄 (=`/`) | (空欄、`/railway.toml` + Dockerfile CMD で OK) | なし |
| `itsuka-api` (FastAPI) | 空欄 (=`/`) | `sh -c 'uvicorn src.web.app:app --host :: --port ${PORT}'` | あり (Generate Domain) |
| `itsuka-frontend` (Next.js) | `/frontend` | (空欄、`frontend/railway.toml` で OK) | あり (Generate Domain) |

> Railway は `railway.toml` (default name) しか自動で拾わないため、複数サービスで
> 別々の `startCommand` を持たせるには、**toml に書かず UI の Custom Start Command
> で個別指定する** のが確実。`/railway.toml` から `startCommand` を抜いてある
> のはこのため (UI 側で編集できなくなるのを避ける)。
>
> Railway の private network (`*.railway.internal`) は IPv6-only なので、api は
> `--host ::` で bind すること (IPv4 dual-stack も同時に受ける)。`0.0.0.0` だと
> private 経由のアクセスが ECONNREFUSED で死ぬ。

### 3. 環境変数

各サービスに以下を設定する。

**`itsuka-bot`** だけ:

| Key | Value |
| --- | --- |
| `DISCORD_TOKEN` | Discord Bot トークン |

**`itsuka-api`** だけ:

| Key | Value |
| --- | --- |
| `ADMIN_USER` | Web 管理画面のユーザー名 (例: `admin`) |
| `ADMIN_PASSWORD` | Web 管理画面のパスワード |
| `SESSION_SECRET_KEY` | JWT 署名鍵 (Railway の `Generate` で乱数を生成) |
| `SECURE_COOKIE` | `true` (HTTPS 配信のため) |
| `CORS_ORIGINS` | `https://${{itsuka-frontend.RAILWAY_PUBLIC_DOMAIN}}` |

**共通** (3 サービス全部):

| Key | Value |
| --- | --- |
| `LOG_LEVEL` | `INFO` |
| `DATABASE_URL` | Postgres アドオンが自動注入 (bot と api のみ) |

**`itsuka-frontend`** のみ:

| Key | Value |
| --- | --- |
| `API_URL` | `http://${{itsuka-api.RAILWAY_PRIVATE_DOMAIN}}:${{itsuka-api.PORT}}` (private、推奨) または `https://${{itsuka-api.RAILWAY_PUBLIC_DOMAIN}}` (public) |

`${{service-name.RAILWAY_PUBLIC_DOMAIN}}` は Railway のサービス参照変数で、
他サービスのドメインに展開される。

### 4. デプロイ後

`https://<itsuka-frontend のドメイン>/login` にアクセスして
`ADMIN_USER` / `ADMIN_PASSWORD` でログイン。Bot を Discord サーバーに
招待した後、`/dashboard/auto-reaction` で設定を追加する。

### Railway のはまりどころ

- 各サービスの **Settings → Deploy → Start Command** を空欄にしておくこと
  (`railway.*.toml` の `startCommand` が使われる)。Railway UI で手動で
  Start Command を入れると toml 側の値より優先される。
- 環境変数展開 (`${PORT}` など) は Railway が直接 exec するので、
  `sh -c '...'` で包んでいる。`bash` ビルトイン (`cd` 等) を直接使うと
  `executable not found` になるので、シェル経由にすること。
- `frontend` サービスは Root Directory を `/frontend` に設定しないと、
  リポジトリルートの Python Dockerfile を拾ってビルドが通ったように見えて
  起動時に死ぬので注意。

## Discord Developer Portal

- **Privileged Gateway Intents**:
  - **Message Content Intent**: **ON** (正規表現フィルタで本文を読むため必須)
  - その他は OFF のまま
- **Bot Permissions** (招待時): `View Channels`, `Send Messages`,
  `Add Reactions`, `Use External Emojis`, `Read Message History`

## 環境変数

| 変数 | 用途 |
| --- | --- |
| `DISCORD_TOKEN` | Bot トークン |
| `DATABASE_URL` | SQLAlchemy の接続 URL |
| `ADMIN_USER` / `ADMIN_PASSWORD` | Web 管理画面の単一管理者 |
| `SESSION_SECRET_KEY` | JWT 署名鍵 (未設定だと再起動でセッション失効) |
| `SECURE_COOKIE` | HTTPS 配信時に `true` |
| `CORS_ORIGINS` | Next.js のオリジン (カンマ区切り) |
| `WEB_HOST` / `WEB_PORT` | uvicorn のバインド先 |
| `LOG_LEVEL` | DEBUG / INFO / WARNING / ERROR |

## API

すべて `/api/v1` プレフィックス。`session` クッキー (JWT) で認証。

| Method | Path | 概要 |
| --- | --- | --- |
| POST | `/auth/login` | `{ user, password }` で JWT クッキー発行 |
| POST | `/auth/logout` | クッキー削除 |
| GET | `/auth/me` | 認証中のユーザー名 |
| GET | `/auto-reaction` | 設定一覧 + ギルド/チャンネルマップ |
| POST | `/auto-reaction` | `{ guild_id, channel_id, emojis[] }` で新規作成 |
| PATCH | `/auto-reaction/{id}/toggle` | 有効/無効切替 |
| DELETE | `/auto-reaction/{id}` | 削除 |

## 制約

- 1 メッセージあたり最大 20 リアクション (Discord 制約)
- カスタム絵文字は Bot が見える共有絵文字のみ反応可
- Web 管理画面の変更は最大 60 秒後に Bot へ反映 (キャッシュ更新ループ間隔)
