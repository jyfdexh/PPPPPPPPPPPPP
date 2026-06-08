# OpenAI Pay Long Link

Standalone tool for generating a hosted payment long link from a ChatGPT access token.

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
