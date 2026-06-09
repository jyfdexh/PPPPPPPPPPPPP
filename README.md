# OpenAI Pay Long Link

用于把 ChatGPT session / access token 转成 Stripe 中转地址或支付长链的本地服务。

## 本地运行

```powershell
cd D:\nanno\Gpt_Plus\转长链\opll
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8787
```

打开：

```text
http://127.0.0.1:8787
```

## Docker

```bash
docker compose up -d --build
```

停止：

```bash
docker compose down
```

## 服务器部署

一键安装：

```bash
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
```

手动更新：

```bash
sudo opll-update
sudo systemctl status opll
sudo journalctl -u opll -f
```

私有仓库更新时，GitHub 不支持账号密码拉取。服务器需要配置 PAT 或 SSH Deploy Key 后再执行 `sudo opll-update`。

## `/getPayPal_link` 接口

这个接口复用当前 PP 提取主流程，但默认只提取 `https://pm-redirects.stripe.com/authorize...` 中转地址，不再额外请求 PayPal BA 链。把这个中转地址粘贴到浏览器后，Stripe 会继续跳到 `https://www.paypal.com/agreements/approve?ba_token=...`。

### 默认行为

- 只传 `session` 即可；`session` 可以是完整 session 对象，也可以直接是 accessToken 字符串。
- 不传 `proxy`、`checkoutProxy`、`providerProxy`、`approveProxy` 时，默认全程不使用代理。
- 成功时返回 `pm_redirect_url`，同时为了兼容旧调用方，`paypal_link` 也会填同一个地址。
- 接口固定按 `fetchBaToken=false` 运行，也就是拿到 Stripe 中转地址就算成功。

### 请求

```http
POST /getPayPal_link
Content-Type: application/json

{
  "session": {
    "user": { "email": "demo@example.com" },
    "accessToken": "eyJ..."
  }
}
```

如果只复制了 accessToken，也可以直接这样传：

```json
{
  "session": "eyJ..."
}
```

curl 示例：

```bash
curl --location --request POST 'https://pay.2333330.xyz/getPayPal_link' \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "accessToken": "eyJ..."
  }'
```

也兼容旧字段：

```json
{
  "accessToken": "eyJ...",
  "sessionJson": "{\"access_token\":\"eyJ...\"}"
}
```

如需显式走代理，才传下面字段；只要任意代理字段不为空，就不会启用默认直连：

```json
{
  "session": "eyJ...",
  "proxy": "http://127.0.0.1:3010",
  "checkoutProxy": "http://127.0.0.1:3010",
  "providerProxy": "http://127.0.0.1:3010",
  "approveProxy": "http://127.0.0.1:3010",
  "approveProxyRegion": "JP",
  "maxRetries": 5,
  "approveRetries": 10
}
```

### 成功返回

```json
{
  "success": true,
  "code": "SUCCESS",
  "message": "ok",
  "paypal_link": "https://pm-redirects.stripe.com/authorize/...",
  "pm_redirect_url": "https://pm-redirects.stripe.com/authorize/...",
  "hosted_long_url": "",
  "fallback": false,
  "attempt_count": 1,
  "max_attempts": 5,
  "retries_used": 0,
  "cs_id": "cs_live_...",
  "billing_country": "US",
  "currency": "USD",
  "provider_error": "",
  "last_error": "",
  "provider_redirect_url": "",
  "stripe_redirect_url": "https://pm-redirects.stripe.com/authorize/...",
  "stripe_hosted_url": "https://checkout.stripe.com/c/pay/cs_live_...",
  "retry_history": []
}
```

### 失败返回

```json
{
  "success": false,
  "code": "PAYPAL_LINK_NOT_FOUND",
  "message": "redirect url resolution timeout: keys=[...]",
  "paypal_link": "",
  "pm_redirect_url": "",
  "hosted_long_url": "https://pay.openai.com/c/pay/cs_live_...",
  "fallback": true,
  "attempt_count": 5,
  "max_attempts": 5,
  "retries_used": 4,
  "last_error": "redirect url resolution timeout: keys=[...]",
  "retry_history": [
    { "attempt": 1, "ok": false, "error": "..." }
  ]
}
```

## `/api/long-link` 接口

主页面使用这个接口生成 hosted、PayPal、GoPay 等链接，字段更多，适合前端调试和完整流程。

```http
POST /api/long-link
Content-Type: application/json

{
  "accessToken": "eyJ...",
  "link_type": "paypal",
  "billing_country": "US",
  "payment_locale": "en",
  "fetchBaToken": false
}
```
