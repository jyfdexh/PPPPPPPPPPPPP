# OpenAI Pay Long Link

### 以后服务器同步 GitHub 更新：sudo opll-update
Standalone tool for generating a hosted payment long link from a ChatGPT access token.
部署
curl -fsSL "https://github.com/jyfdexh/PPPPPPPPPPPPP/raw/refs/heads/main/deploy/install.sh" | sudo env \
  DOMAIN=pay.2333330.xyz \
  BIND_DOMAIN=yes \
  USE_CLOUDFLARE=yes \
  REPO_URL=https://github.com/jyfdexh/PPPPPPPPPPPPP.git \
  BRANCH=main \
  APP_DIR=/opt/opll \
  APP_HOST=127.0.0.1 \
  APP_PORT=8787 \
  NONINTERACTIVE=yes \
  bash
## Run

```powershell
cd openai_pay_long_link
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

## Docker

```bash
cd openai_pay_long_link
docker compose up -d --build
```

Open:

```text
http://127.0.0.1:8787
```

Stop:

```bash
docker compose down
```

The server uses a built-in default outbound proxy when the page does not submit
one. Override it at deploy time with `OPENAI_PAY_DEFAULT_PROXY`; set it to an
empty value to use direct outbound network.

For PP provider extraction, the server switches the post-checkout
Stripe/Provider stage to a US proxy. By default it derives this from the
built-in proxy by changing `region-JP` to `region-US`; override with
`OPENAI_PAY_PROVIDER_PROXY`. GoPay switches the post-checkout provider stage
to the built-in Indonesia proxy; override with `OPENAI_PAY_GOPAY_PROVIDER_PROXY`.

## API

```http
POST /api/long-link
Content-Type: application/json

{
  "accessToken": "eyJ...",
  "proxy": "",
  "billing_country": "US",
  "payment_locale": "en",
  "stripe_publishable_key": ""
}
```

The server creates a ChatGPT checkout, calls:

```text
https://api.stripe.com/v1/payment_pages/{cs_id}/init
```

Then it reads `stripe_hosted_url` and changes:

```text
https://checkout.stripe.com -> https://pay.openai.com
```

## Link Types

- `hosted`: normal payment long link, defaults to `US/USD`; country remains selectable.
- `paypal`: PP redirect extraction, checkout locked to `US/USD`, uses a Japan billing address.
- `gopay`: GoPay redirect extraction, checkout locked to `ID/IDR`, uses an Indonesia billing address. Accounts with active USD checkout/subscription state may be blocked by Stripe from creating an IDR checkout.

For `paypal` and `gopay`, if Stripe provider redirect extraction fails but the
hosted checkout URL exists, the API falls back to the hosted long link and
returns `fallback: true` plus `provider_error`.

## 服务器一键部署

脚本风格参考 `mail 2`：首次安装后会创建 systemd 服务，并安装 `opll-update` 命令。后续你手动执行更新命令时，服务器会从 GitHub 拉取最新代码、更新依赖并重启服务。

交互式安装：

```bash
curl -fsSL https://raw.githubusercontent.com/jyfdexh/PPPPPPPPPPPPP/main/deploy/install.sh | sudo bash
```

非交互式安装示例：

```bash
curl -fsSL https://raw.githubusercontent.com/jyfdexh/PPPPPPPPPPPPP/main/deploy/install.sh | sudo env \
  DOMAIN=pay.2333330.xyz \
  BIND_DOMAIN=yes \
  USE_CLOUDFLARE=yes \
  REPO_URL=https://github.com/jyfdexh/PPPPPPPPPPPPP.git \
  BRANCH=main \
  APP_DIR=/opt/opll \
  APP_HOST=127.0.0.1 \
  APP_PORT=8787 \
  NONINTERACTIVE=yes \
  bash
```

常用命令：

```bash
sudo opll-update
sudo systemctl status opll
sudo journalctl -u opll -f
```

代理说明：

- 安装时 `OPENAI_PAY_DEFAULT_PROXY` 留空表示后端默认直连。
- 如果服务器本机运行了 `127.0.0.1:3010` 代理，systemd 直跑模式可以直接填这个地址。
- 不启用自动更新。需要同步 GitHub 时，手动执行 `sudo opll-update`。

域名说明：

- 默认域名是 `pay.2333330.xyz`。
- 使用 Cloudflare 代理时，DNS 添加 A 记录：`pay.2333330.xyz` 指向服务器 IP，并开启橙色云。
- Cloudflare SSL/TLS 模式选择 `Full`。脚本会生成自签源站证书；如果要用 `Full strict`，需要替换为 Cloudflare Origin Certificate。
