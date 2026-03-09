"""Stripe Connect integration routes.

Flow:
  1. Business owner hits /api/stripe/onboard/<slug>
     → creates a Stripe Connect (Express) account
     → returns an onboarding URL the owner visits
  2. Stripe redirects back to /api/stripe/onboard/<slug>/callback
     → marks tenant as onboarded
  3. Customer hits /api/stripe/checkout
     → creates a Checkout Session with an application_fee
     → redirects customer to Stripe-hosted payment page
  4. Stripe sends events to /api/stripe/webhook
     → records successful payments in the tenant's schema
"""

import stripe
from flask import request, jsonify, current_app, redirect, url_for

from core.stripe import stripe_bp
from core.extensions import db
from core.models import Tenant
from core.auth.routes import auth_required


def _init_stripe():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]


# ── 1. Connect Onboarding ──────────────────────────────────────────────

@stripe_bp.route("/api/stripe/onboard/<slug>", methods=["POST"])
@auth_required
def onboard_start(slug):
    """Create a Stripe Express account for a tenant and return the onboarding URL."""
    _init_stripe()
    user = request.current_user

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    if tenant.owner_id != user.id and user.role != "platform_admin":
        return jsonify({"error": "Only the business owner can onboard Stripe"}), 403

    # Create or reuse existing Connect account
    if not tenant.stripe_account_id:
        account = stripe.Account.create(
            type="express",
            email=user.email,
            metadata={"tenant_slug": slug, "platform": "saas"},
        )
        tenant.stripe_account_id = account.id
        db.session.commit()

    # Generate onboarding link
    base_url = request.host_url.rstrip("/")
    account_link = stripe.AccountLink.create(
        account=tenant.stripe_account_id,
        refresh_url=f"{base_url}/api/stripe/onboard/{slug}/refresh",
        return_url=f"{base_url}/api/stripe/onboard/{slug}/callback",
        type="account_onboarding",
    )

    return jsonify({
        "url": account_link.url,
        "stripe_account_id": tenant.stripe_account_id,
    })


@stripe_bp.route("/api/stripe/onboard/<slug>/callback", methods=["GET"])
def onboard_callback(slug):
    """Called by Stripe after the owner completes onboarding."""
    _init_stripe()

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant or not tenant.stripe_account_id:
        return jsonify({"error": "Tenant not found"}), 404

    # Verify charges are enabled
    account = stripe.Account.retrieve(tenant.stripe_account_id)
    if account.charges_enabled:
        tenant.stripe_onboarded = True
        db.session.commit()

    # Redirect to the owner dashboard
    return redirect("/dashboard")


@stripe_bp.route("/api/stripe/onboard/<slug>/refresh", methods=["GET"])
def onboard_refresh(slug):
    """If the onboarding link expired, generate a new one."""
    _init_stripe()

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant or not tenant.stripe_account_id:
        return jsonify({"error": "Tenant not found"}), 404

    base_url = request.host_url.rstrip("/")
    account_link = stripe.AccountLink.create(
        account=tenant.stripe_account_id,
        refresh_url=f"{base_url}/api/stripe/onboard/{slug}/refresh",
        return_url=f"{base_url}/api/stripe/onboard/{slug}/callback",
        type="account_onboarding",
    )
    return redirect(account_link.url)


# ── 2. Account Status ──────────────────────────────────────────────────

@stripe_bp.route("/api/stripe/status/<slug>", methods=["GET"])
@auth_required
def account_status(slug):
    """Check the Stripe Connect status for a tenant."""
    _init_stripe()
    user = request.current_user

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    if tenant.owner_id != user.id and user.role != "platform_admin":
        return jsonify({"error": "Forbidden"}), 403

    if not tenant.stripe_account_id:
        return jsonify({
            "connected": False,
            "onboarded": False,
            "charges_enabled": False,
        })

    account = stripe.Account.retrieve(tenant.stripe_account_id)

    # Update our record if status changed
    if account.charges_enabled and not tenant.stripe_onboarded:
        tenant.stripe_onboarded = True
        db.session.commit()

    return jsonify({
        "connected": True,
        "onboarded": tenant.stripe_onboarded,
        "charges_enabled": account.charges_enabled,
        "payouts_enabled": account.payouts_enabled,
        "stripe_account_id": tenant.stripe_account_id,
    })


# ── 3. Checkout (payment) ──────────────────────────────────────────────

@stripe_bp.route("/api/stripe/checkout", methods=["POST"])
def create_checkout():
    """Create a Stripe Checkout Session for a purchase.

    Expected JSON body:
      {
        "tenant_slug": "halalio",
        "item_name": "Halal Burger Box",
        "amount": 2500,          // in cents
        "quantity": 1,
        "success_url": "https://...",
        "cancel_url": "https://..."
      }
    """
    _init_stripe()
    data = request.get_json() or {}

    tenant_slug = data.get("tenant_slug")
    item_name = data.get("item_name", "Purchase")
    amount = data.get("amount")  # cents
    quantity = data.get("quantity", 1)
    success_url = data.get("success_url", request.host_url)
    cancel_url = data.get("cancel_url", request.host_url)

    if not tenant_slug or not amount:
        return jsonify({"error": "tenant_slug and amount are required"}), 400

    tenant = Tenant.query.filter_by(slug=tenant_slug, status="active").first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404

    if not tenant.stripe_account_id or not tenant.stripe_onboarded:
        return jsonify({"error": "This business has not set up payments yet"}), 400

    # Calculate platform fee
    fee_percent = current_app.config["STRIPE_PLATFORM_FEE_PERCENT"]
    application_fee = int(amount * quantity * fee_percent / 100)

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": int(amount),
                "product_data": {"name": item_name},
            },
            "quantity": quantity,
        }],
        payment_intent_data={
            "application_fee_amount": application_fee,
            "transfer_data": {
                "destination": tenant.stripe_account_id,
            },
            "metadata": {
                "tenant_slug": tenant_slug,
            },
        },
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        metadata={
            "tenant_slug": tenant_slug,
        },
    )

    return jsonify({
        "checkout_url": session.url,
        "session_id": session.id,
    })


# ── 4. Create Payment Link (simpler alternative) ───────────────────────

@stripe_bp.route("/api/stripe/payment-link", methods=["POST"])
@auth_required
def create_payment_link():
    """Create a reusable Stripe Payment Link for a product/service.

    Used by business owners to generate shareable links.
    """
    _init_stripe()
    user = request.current_user
    data = request.get_json() or {}

    tenant_slug = data.get("tenant_slug")
    item_name = data.get("item_name", "Item")
    amount = data.get("amount")  # cents

    if not tenant_slug or not amount:
        return jsonify({"error": "tenant_slug and amount are required"}), 400

    tenant = Tenant.query.filter_by(slug=tenant_slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    if tenant.owner_id != user.id and user.role != "platform_admin":
        return jsonify({"error": "Forbidden"}), 403
    if not tenant.stripe_account_id or not tenant.stripe_onboarded:
        return jsonify({"error": "Complete Stripe onboarding first"}), 400

    fee_percent = current_app.config["STRIPE_PLATFORM_FEE_PERCENT"]
    application_fee = int(int(amount) * fee_percent / 100)

    # Create a product + price on the connected account
    product = stripe.Product.create(
        name=item_name,
        stripe_account=tenant.stripe_account_id,
    )
    price = stripe.Price.create(
        product=product.id,
        unit_amount=int(amount),
        currency="usd",
        stripe_account=tenant.stripe_account_id,
    )
    link = stripe.PaymentLink.create(
        line_items=[{"price": price.id, "quantity": 1}],
        application_fee_percent=fee_percent,
        stripe_account=tenant.stripe_account_id,
    )

    return jsonify({
        "payment_link": link.url,
        "product_id": product.id,
    })


# ── 5. Webhook ──────────────────────────────────────────────────────────

@stripe_bp.route("/api/stripe/webhook", methods=["POST"])
def webhook():
    """Handle Stripe webhook events.

    Key events:
      - checkout.session.completed  → record payment
      - account.updated             → update onboarding status
    """
    _init_stripe()
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = current_app.config["STRIPE_WEBHOOK_SECRET"]

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        tenant_slug = session.get("metadata", {}).get("tenant_slug")
        if tenant_slug:
            _record_payment(
                tenant_slug=tenant_slug,
                stripe_session_id=session["id"],
                stripe_payment_intent=session.get("payment_intent"),
                amount_total=session.get("amount_total", 0),
                currency=session.get("currency", "usd"),
                customer_email=session.get("customer_details", {}).get("email", ""),
            )

    elif event["type"] == "account.updated":
        account = event["data"]["object"]
        tenant = Tenant.query.filter_by(stripe_account_id=account["id"]).first()
        if tenant:
            was_onboarded = tenant.stripe_onboarded
            tenant.stripe_onboarded = account.get("charges_enabled", False)
            if tenant.stripe_onboarded != was_onboarded:
                db.session.commit()

    return jsonify({"status": "ok"})


def _record_payment(tenant_slug, stripe_session_id, stripe_payment_intent,
                    amount_total, currency, customer_email):
    """Record a successful payment in the tenant's schema."""
    try:
        from core.tenants.db_manager import get_tenant_connection
        conn = get_tenant_connection(tenant_slug)

        # Ensure payments table exists
        conn.execute('''CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            stripe_session_id TEXT UNIQUE,
            stripe_payment_intent TEXT,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'usd',
            customer_email TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT NOW()
        )''')

        conn.execute(
            "INSERT INTO payments (stripe_session_id, stripe_payment_intent, amount, currency, customer_email) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (stripe_session_id) DO NOTHING",
            (stripe_session_id, stripe_payment_intent, amount_total, currency, customer_email),
        )
        conn.commit()
    except Exception as e:
        current_app.logger.error(f"Failed to record payment for {tenant_slug}: {e}")


# ── 6. Dashboard data ──────────────────────────────────────────────────

@stripe_bp.route("/api/stripe/balance/<slug>", methods=["GET"])
@auth_required
def get_balance(slug):
    """Get Stripe balance for a tenant's connected account."""
    _init_stripe()
    user = request.current_user

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    if tenant.owner_id != user.id and user.role != "platform_admin":
        return jsonify({"error": "Forbidden"}), 403
    if not tenant.stripe_account_id:
        return jsonify({"error": "Stripe not connected"}), 400

    balance = stripe.Balance.retrieve(stripe_account=tenant.stripe_account_id)

    return jsonify({
        "available": [
            {"amount": b["amount"], "currency": b["currency"]}
            for b in balance.get("available", [])
        ],
        "pending": [
            {"amount": b["amount"], "currency": b["currency"]}
            for b in balance.get("pending", [])
        ],
    })


@stripe_bp.route("/api/stripe/payments/<slug>", methods=["GET"])
@auth_required
def list_payments(slug):
    """List recorded payments for a tenant from their schema."""
    user = request.current_user

    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    if tenant.owner_id != user.id and user.role != "platform_admin":
        return jsonify({"error": "Forbidden"}), 403

    try:
        from core.tenants.db_manager import get_tenant_connection
        conn = get_tenant_connection(slug)

        # Ensure table exists (first time)
        conn.execute('''CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            stripe_session_id TEXT UNIQUE,
            stripe_payment_intent TEXT,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'usd',
            customer_email TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT NOW()
        )''')
        conn.commit()

        rows = conn.execute(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
