const Stripe = require('stripe');
const config = require('../config');
const { HttpError } = require('../middleware/errors');
const walletService = require('./walletService');

const stripe = config.stripe.mockMode ? null : new Stripe(config.stripe.secretKey);

const TOP_UP_PURPOSE = 'wallet_topup';

function requireStripe() {
  if (!stripe) throw new HttpError(503, 'Stripe is not configured on this server', 'STRIPE_DISABLED');
  return stripe;
}

async function createTopUpSession({ user, wallet, amount }) {
  return requireStripe().checkout.sessions.create({
    mode: 'payment',
    line_items: [
      {
        quantity: 1,
        price_data: {
          currency: config.currency,
          unit_amount: Math.round(amount * 100),
          product_data: { name: `Wolt for Pros wallet top-up (₪${amount})` },
        },
      },
    ],
    client_reference_id: user.id,
    metadata: { purpose: TOP_UP_PURPOSE, walletId: wallet.id, userId: user.id },
    success_url: `${config.frontendUrl}/pro?topup=success&session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${config.frontendUrl}/pro?topup=cancelled`,
  });
}

// Credits the wallet for a paid top-up session. The amount comes from
// Stripe's amount_total, never from anything the browser sent.
async function fulfilTopUp(session) {
  if (!session || session.metadata?.purpose !== TOP_UP_PURPOSE) return { credited: false, reason: 'not_a_topup' };
  if (session.payment_status !== 'paid') return { credited: false, reason: 'not_paid' };
  if (session.currency !== config.currency) {
    console.error(`[stripe] session ${session.id} paid in ${session.currency}, expected ${config.currency}`);
    return { credited: false, reason: 'wrong_currency' };
  }
  return walletService.creditStripeDeposit({
    walletId: session.metadata.walletId,
    cents: session.amount_total,
    sessionId: session.id,
  });
}

function constructWebhookEvent(rawBody, signature) {
  if (!config.stripe.webhookSecret) {
    throw new HttpError(503, 'STRIPE_WEBHOOK_SECRET is not configured', 'STRIPE_DISABLED');
  }
  try {
    return requireStripe().webhooks.constructEvent(rawBody, signature, config.stripe.webhookSecret);
  } catch (err) {
    throw new HttpError(400, `Webhook signature verification failed: ${err.message}`, 'BAD_SIGNATURE');
  }
}

async function handleWebhookEvent(event) {
  switch (event.type) {
    case 'checkout.session.completed':
    case 'checkout.session.async_payment_succeeded':
      return fulfilTopUp(event.data.object);
    default:
      return { ignored: true };
  }
}

// Lets the success page confirm a payment directly with Stripe, so the wallet
// updates even when the webhook is late or not forwarded in local development.
async function confirmSession(sessionId, user) {
  const session = await requireStripe().checkout.sessions.retrieve(sessionId);
  if (session.client_reference_id !== user.id) {
    throw new HttpError(403, 'This checkout session belongs to another account', 'FORBIDDEN');
  }
  const result = await fulfilTopUp(session);
  return { status: session.payment_status, ...result };
}

module.exports = { createTopUpSession, constructWebhookEvent, handleWebhookEvent, confirmSession };
